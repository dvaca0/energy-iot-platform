"""Continuous power / UPS telemetry recorder.

WHY: 180 undervoltage events were logged on N001 with nothing recording input
voltage, battery state or board power at the moment of each, so the cause
could not be identified. This records continuously and dumps a
high-resolution window whenever the firmware's throttle flags change.

WHAT IT PROTECTS AGAINST: nothing. This is instrumentation. Its job is to make
the next failure explainable rather than a mystery.

FIRST RESULT (N001, 2026-08-03 08:27:40): captured an undervoltage with
batt_ma at +-1..3 mA and on_battery=0 throughout - the battery never
discharged and the input never dropped out, while ext5v_min_60s reached
4.942 V. That rules out charger contention and input dropout, and points at
the HAT's 5 V regulator transient response.

PORTABILITY: per-rail board power needs `vcgencmd pmic_read_adc`, which is
Pi 5 only. On a Pi 4 that column is simply absent - recorded as NULL and
reported honestly by the capability probe, never fabricated.
"""

from __future__ import annotations

__version__ = "1.0.0"

import collections
import json
import os
import sqlite3
import sys
import time
from typing import Optional

_LIB = os.path.dirname(os.path.abspath(__file__))
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

import enconfig  # noqa: E402
import sysinfo  # noqa: E402
import ups as ups_pkg  # noqa: E402

SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
    ts REAL PRIMARY KEY, ext5v_v REAL, vdd_core_v REAL, throttled INTEGER,
    undervolt_now INTEGER, temp_c REAL, board_power_w REAL, batt_v REAL,
    batt_ma REAL, batt_pct REAL, on_battery INTEGER, load1 REAL,
    burst INTEGER DEFAULT 0);
CREATE INDEX IF NOT EXISTS idx_samples_ts ON samples(ts);
CREATE TABLE IF NOT EXISTS events (
    ts REAL PRIMARY KEY, kind TEXT, throttled_from INTEGER, throttled_to INTEGER,
    flags_set TEXT, ext5v_v REAL, ext5v_min_60s REAL, board_power_w REAL,
    batt_v REAL, batt_ma REAL, on_battery INTEGER, detail TEXT);
"""

COLUMNS = ("ts", "ext5v_v", "vdd_core_v", "throttled", "undervolt_now",
           "temp_c", "board_power_w", "batt_v", "batt_ma", "batt_pct",
           "on_battery", "load1", "burst")


def db_path() -> str:
    return enconfig.get("EN_POWER_DB",
                        "/opt/energy-node/database/power_telemetry.db")


def _adc_volt(name: str) -> Optional[float]:
    raw = sysinfo.vcgencmd("pmic_read_adc", name)
    if not raw or "=" not in raw:
        return None
    try:
        return float(raw.rsplit("=", 1)[1].rstrip("VA"))
    except ValueError:
        return None


def board_power_w() -> Optional[float]:
    """Sum V*I across every PMIC rail. Pi 5 only; None elsewhere."""
    if not sysinfo.capabilities()["pmic_adc"]:
        return None
    raw = sysinfo.vcgencmd("pmic_read_adc")
    if not raw:
        return None
    amps, volts = {}, {}
    for line in raw.splitlines():
        line = line.strip()
        if "=" not in line:
            continue
        label, value = line.rsplit("=", 1)
        try:
            num = float(value.rstrip("VA"))
        except ValueError:
            continue
        name = label.split()[0]
        key = name.rsplit("_", 1)[0]
        if name.endswith("_A"):
            amps[key] = num
        elif name.endswith("_V"):
            volts[key] = num
    total = sum(amps[k] * volts[k] for k in amps if k in volts)
    return round(total, 3) if total else None


def sample() -> dict:
    row = {"ts": time.time(), "burst": 0}
    try:
        mask = sysinfo.throttled_mask()
        row["throttled"] = mask
        row["undervolt_now"] = int(bool(mask & 1)) if mask is not None else None
        row["ext5v_v"] = _adc_volt("EXT5V_V")
        row["vdd_core_v"] = _adc_volt("VDD_CORE_V")
        row["temp_c"] = sysinfo.cpu_temperature_c()
        row["load1"] = sysinfo.loadavg()[0]
        u = ups_pkg.read()
        row["batt_v"] = u.battery_voltage_v
        row["batt_ma"] = u.battery_current_ma
        row["batt_pct"] = u.battery_percent
        row["on_battery"] = int(u.on_battery) if u.on_battery is not None else None
    except Exception as exc:
        row["detail"] = f"sample error: {exc}"
    return row


def connect() -> sqlite3.Connection:
    path = db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def persist(conn, rows) -> None:
    conn.executemany(
        f"INSERT OR REPLACE INTO samples ({','.join(COLUMNS)}) "
        f"VALUES ({','.join('?' * len(COLUMNS))})",
        [tuple(r.get(c) for c in COLUMNS) for r in rows])
    conn.commit()


def prune(conn) -> None:
    now = time.time()
    conn.execute("DELETE FROM samples WHERE ts < ?",
                 (now - enconfig.get_int("POWERLOG_RETENTION_DAYS", 14) * 86400,))
    conn.execute("DELETE FROM events WHERE ts < ?",
                 (now - enconfig.get_int("POWERLOG_EVENT_RETENTION_DAYS", 365) * 86400,))
    conn.commit()


def record_event(conn, kind, prev, cur, ring, row) -> None:
    recent = [r["ext5v_v"] for r in ring
              if r.get("ext5v_v") is not None and r["ts"] > row["ts"] - 60]
    newly = sysinfo.decode_throttle(cur & ~prev) if (prev is not None and cur is not None) else []
    conn.execute(
        "INSERT OR REPLACE INTO events (ts,kind,throttled_from,throttled_to,"
        "flags_set,ext5v_v,ext5v_min_60s,board_power_w,batt_v,batt_ma,"
        "on_battery,detail) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (row["ts"], kind, prev, cur, json.dumps(newly), row.get("ext5v_v"),
         min(recent) if recent else None, row.get("board_power_w"),
         row.get("batt_v"), row.get("batt_ma"), row.get("on_battery"), ""))
    persist(conn, [dict(r, burst=1) for r in ring])
    conn.commit()


def main() -> int:
    if not enconfig.get_bool("POWERLOG_ENABLED", True):
        print("[powerlog] POWERLOG_ENABLED=0 - exiting")
        return 0

    hz = enconfig.get_float("POWERLOG_SAMPLE_HZ", 1.0)
    ring_s = enconfig.get_int("POWERLOG_RING_SECONDS", 300)
    persist_every = enconfig.get_int("POWERLOG_PERSIST_EVERY", 5)
    rail_every = enconfig.get_int("POWERLOG_RAIL_EVERY", 30)
    prune_every = enconfig.get_int("POWERLOG_PRUNE_EVERY", 3600)

    caps = sysinfo.capabilities()
    print(f"[powerlog] {caps['model']} | pmic_adc={caps['pmic_adc']} "
          f"| {hz}Hz ring={ring_s}s db={db_path()}", flush=True)
    if not caps["pmic_adc"]:
        print("[powerlog] NOTE: per-rail board power unavailable on this "
              "board; board_power_w will be NULL (not fabricated)", flush=True)

    conn = connect()
    ring = collections.deque(maxlen=max(1, int(ring_s * hz)))
    prev_mask = None
    last_persist = last_rails = last_prune = 0.0
    interval = 1.0 / hz if hz > 0 else 1.0

    while True:
        started = time.time()
        row = sample()
        if started - last_rails >= rail_every:
            row["board_power_w"] = board_power_w()
            last_rails = started
        ring.append(row)
        mask = row.get("throttled")
        try:
            if prev_mask is not None and mask is not None and mask != prev_mask:
                kind = "undervoltage" if (mask & ~prev_mask) & 0x1 else "throttle_change"
                record_event(conn, kind, prev_mask, mask, ring, row)
                last_persist = started
            elif started - last_persist >= persist_every:
                persist(conn, [row])
                last_persist = started
            if started - last_prune >= prune_every:
                prune(conn)
                last_prune = started
        except sqlite3.Error:
            pass
        if mask is not None:
            prev_mask = mask
        time.sleep(max(0.0, interval - (time.time() - started)))


if __name__ == "__main__":
    sys.exit(main())
