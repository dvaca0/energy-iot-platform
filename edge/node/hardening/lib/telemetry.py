"""The canonical heartbeat payload.

ONE producer, ONE payload, MANY consumers.

The 2026-08-01 outage cost 43h37m because the platform had two heartbeat
concepts: the collector posted to /api/edge/heartbeat (which updated last_sync
only) while the monitoring subsystem read /api/monitoring/heartbeat (which
nobody posted to). N001 therefore sat at ever_seen=false / heartbeat_age=null
forever, and node.heartbeat_lost — the rule that correctly caught N002 at
EMERGENCY — could never fire for it.

This module builds the single payload. The collector is the sole producer; it
calls build() once per interval. Nothing else on the node produces heartbeats.

STDLIB ONLY — imported by the collector, whose venv has only `requests`.
"""

from __future__ import annotations

__version__ = "1.0.0"

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

AGENT_VERSION = "2.0.0"
COLLECTOR_UNIT = "energy-node-collector.service"


def _sqlite_ro(path: str):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)


def recent_undervoltage() -> bool:
    """Edge-triggered undervoltage from the power logger's event table.

    NOT the firmware's sticky bits. Bits 16/18 only clear on reboot, so
    reporting them would pin node.undervoltage at ERROR permanently and add to
    the alert fatigue that already buried the real signal (968 of 1375
    notifications came from one noisy rule). The firmware sag lasts 2-4s, far
    shorter than the heartbeat interval, so we ask the 1 Hz logger instead.
    """
    db = enconfig.get("EN_POWER_DB", "/opt/energy-node/database/power_telemetry.db")
    window = enconfig.get_int("UNDERVOLT_WINDOW_SECONDS", 600)
    try:
        conn = _sqlite_ro(db)
        row = conn.execute(
            "SELECT COUNT(*) FROM events WHERE kind='undervoltage' AND ts > ?",
            (time.time() - window,)).fetchone()
        conn.close()
        return bool(row and row[0])
    except sqlite3.Error:
        return False


def collector_state() -> dict:
    out = {"collector_status": sysinfo.systemd_is_active(COLLECTOR_UNIT),
           "collector_pid": sysinfo.systemd_main_pid(COLLECTOR_UNIT),
           "buffered_readings": None, "pending_sync": None,
           "last_measurement_at": None, "sqlite_size_mb": None,
           "sqlite_wal_mb": None, "_local_rows_total": None}

    db = enconfig.get("DB_PATH", "/opt/energy-node/database/edge_buffer.db")
    try:
        out["sqlite_size_mb"] = round(os.path.getsize(db) / 1e6, 2)
        wal = db + "-wal"
        if os.path.exists(wal):
            out["sqlite_wal_mb"] = round(os.path.getsize(wal) / 1e6, 2)
    except OSError:
        pass

    try:
        conn = _sqlite_ro(db)
        # `buffered_readings` means UNSENT BACKLOG (node.buffer alerts above
        # 500/5000). This node retains synced rows as local history, so total
        # row count is ~64k and would pin that alert CRITICAL forever.
        pending = conn.execute(
            "SELECT COUNT(*) FROM measurements WHERE sync_status=0").fetchone()[0]
        out["buffered_readings"] = pending
        out["pending_sync"] = pending
        out["_local_rows_total"] = conn.execute(
            "SELECT COUNT(*) FROM measurements").fetchone()[0]
        out["last_measurement_at"] = conn.execute(
            "SELECT MAX(captured_at) FROM measurements").fetchone()[0]
        conn.close()
    except sqlite3.Error:
        pass
    return out


def build(node_id: Optional[str] = None) -> dict:
    """Assemble the canonical heartbeat. Never raises."""
    caps = sysinfo.capabilities()
    mask = sysinfo.throttled_mask()
    flags = sysinfo.decode_throttle(mask) if mask is not None else []
    ups_state = ups_pkg.read()
    mem = sysinfo.memory()
    dsk = sysinfo.disk("/")
    la = sysinfo.loadavg()

    undervolt = bool(mask & 0x1) if mask is not None else None
    if recent_undervoltage():
        undervolt = True
    throttled = bool(mask & 0x6) if mask is not None else None

    local_alerts = []
    if ups_state.present and ups_state.identified:
        if ups_state.battery_low:
            local_alerts.append(
                f"UPS battery low: {ups_state.battery_voltage_v}V "
                f"({ups_state.battery_percent}%)")
        if ups_state.on_battery:
            local_alerts.append(
                f"RUNNING ON UPS BATTERY: {ups_state.battery_current_ma}mA, "
                f"{ups_state.battery_percent}% remaining")
        local_alerts.append(f"ups={ups_state.summary()}")
    elif ups_state.present:
        local_alerts.append(
            f"UPS UNIDENTIFIED at {ups_state.fingerprint.get('addresses')} — "
            f"battery state not reported (never guessed)")
    else:
        local_alerts.append(f"UPS not detected ({ups_state.confidence})")

    if flags:
        local_alerts.append(f"throttle flags: 0x{mask:x} {','.join(flags)}")
    if not caps["pmic_adc"]:
        local_alerts.append(
            f"per-rail power unavailable on this board ({caps['model']})")

    coll = collector_state()
    total = coll.pop("_local_rows_total", None)
    if total is not None:
        local_alerts.append(f"local history rows retained: {total}")

    payload = {
        "node_id": node_id or enconfig.node_id(),
        # MUST be UTC. The backend derives clock drift from this; sending
        # local time produced a bogus -21602s (-6h CST) CRITICAL alert.
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "hostname": sysinfo.hostname(),
        "software_version": AGENT_VERSION,
        "uptime_seconds": sysinfo.uptime_seconds(),
        "boot_time": time.strftime("%Y-%m-%dT%H:%M:%S",
                                   time.localtime(sysinfo.boot_time())),
        "cpu_percent": sysinfo.cpu_percent(),
        "cpu_temperature_c": sysinfo.cpu_temperature_c(),
        "memory_percent": mem["memory_percent"],
        "swap_percent": mem["swap_percent"],
        "disk_percent": dsk["disk_percent"],
        "disk_free_mb": dsk["disk_free_mb"],
        "load_1": la[0], "load_5": la[1], "load_15": la[2],
        "filesystem_readonly": sysinfo.filesystem_readonly("/"),
        "undervoltage": undervolt,
        "throttled": throttled,
        "throttle_flags": (f"0x{mask:x} {','.join(flags)}" if mask is not None
                           else None),
        "local_alerts": local_alerts,
    }
    payload.update(sysinfo.network())
    payload.update(coll)
    return payload


if __name__ == "__main__":
    import json
    print(json.dumps(build(), indent=2, default=str))
