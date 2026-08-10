"""Black-box recorder — boot correlation and reboot-reason forensics.

WHY THIS EXISTS
    Two outages (2026-08-01, 2026-08-03) left almost no forensic trail. Both
    were only diagnosable because the RTC happened to preserve one bit of
    information. This module makes that reconstruction automatic and
    permanent, so the NEXT incident leaves a proper record instead of
    requiring an archaeology session.

WHAT IT RECORDS
    A durable boot record at every start, correlated against the previous
    boot, plus the classification that actually mattered during the
    investigation.

THE DISCRIMINATOR (derived from both real incidents)
    The RTC has no backup battery on this hardware, so at boot it is the
    single cheapest signal for telling the two failure modes apart:

      RTC == epoch            -> the board genuinely lost power
      RTC valid + time gap    -> the board stayed POWERED with the SoC not
      + no clean shutdown        running.  THIS is the unsolved latch, and it
                                 is what happened on both 2026-08-01 (43h37m)
                                 and 2026-08-03 (89m).
      bootstatus != 0         -> the hardware watchdog reset us
      clean shutdown markers  -> planned reboot

    Classifying this automatically at boot means the next incident is
    triaged before anyone logs in.

DURABILITY
    SQLite WAL, synchronous=FULL for boot records (they are rare and
    precious), and the record is written as early as the service can run.
    The 1 Hz sample ring lives in powerlog.py and is already WAL; this module
    links the two so a boot record points at the samples that preceded it.

STDLIB ONLY.
"""

from __future__ import annotations

__version__ = "1.0.0"

import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from typing import Optional

_LIB = os.path.dirname(os.path.abspath(__file__))
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

import enconfig  # noqa: E402
import sysinfo  # noqa: E402

SCHEMA = """
CREATE TABLE IF NOT EXISTS boots (
    boot_id            TEXT PRIMARY KEY,
    booted_at          REAL,
    booted_at_iso      TEXT,
    node_id            TEXT,
    -- what the previous boot looked like when it ended
    prev_boot_id       TEXT,
    prev_last_seen     REAL,
    prev_last_seen_iso TEXT,
    gap_seconds        REAL,
    -- the discriminator
    rtc_at_boot        TEXT,
    rtc_valid          INTEGER,
    clean_shutdown     INTEGER,
    watchdog_bootstatus INTEGER,
    reboot_reason      TEXT,
    reason_detail      TEXT,
    -- state at boot
    throttled_at_boot  INTEGER,
    model              TEXT,
    kernel             TEXT,
    bootloader         TEXT,
    hardening_version  TEXT,
    boot_counter       INTEGER,
    recovery_attempts  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_boots_at ON boots(booted_at);

CREATE TABLE IF NOT EXISTS counters (
    name    TEXT PRIMARY KEY,
    value   INTEGER,
    updated REAL
);
"""

# Reboot reason classification
CLEAN = "clean_shutdown"
WATCHDOG = "watchdog_reset"
POWER_LOSS = "power_loss"
LATCH = "latch_or_hang"
FIRST = "first_record"
UNKNOWN = "unknown"


def db_path() -> str:
    return enconfig.get("EN_BLACKBOX_DB",
                        "/opt/energy-node/database/blackbox.db")


def connect() -> sqlite3.Connection:
    path = db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    # Boot records are rare and irreplaceable - pay for durability here.
    conn.execute("PRAGMA synchronous=FULL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


# ------------------------------------------------------------- collectors
def current_boot_id() -> Optional[str]:
    try:
        with open("/proc/sys/kernel/random/boot_id") as fh:
            return fh.read().strip()
    except OSError:
        return None


def rtc_at_boot() -> tuple:
    """Read what the kernel logged when it set the clock from the RTC.

    Returns (iso_string, valid_bool). An epoch value means the RTC lost
    power, which means the BOARD lost power.
    """
    try:
        out = subprocess.run(
            ["journalctl", "-b", "0", "-k", "--no-pager", "-o", "cat"],
            capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return None, None
    m = re.search(r"setting system clock to (\S+)", out)
    if not m:
        return None, None
    val = m.group(1)
    valid = not val.startswith("1970")
    return val, valid


def previous_boot_end() -> tuple:
    """(boot_id, last_entry_epoch) of the previous boot, from the journal."""
    try:
        out = subprocess.run(["journalctl", "--list-boots", "--no-pager"],
                             capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return None, None
    prev = None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].lstrip("-").isdigit():
            if parts[0] == "-1":
                prev = line
    if not prev:
        return None, None
    bid = prev.split()[1]
    # last entry timestamp is the tail of the line
    try:
        ts = subprocess.run(
            ["journalctl", "-b", "-1", "--no-pager", "-o",
             "short-unix", "-n", "1"],
            capture_output=True, text=True, timeout=30).stdout.strip()
        epoch = float(ts.split()[0]) if ts else None
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        epoch = None
    return bid, epoch


def previous_clean_shutdown() -> Optional[bool]:
    try:
        out = subprocess.run(
            ["journalctl", "-b", "-1", "--no-pager", "-o", "cat"],
            capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    if not out:
        return None
    return bool(re.search(
        r"(Reached target.*(Power-Off|Reboot|Halt)|systemd-shutdown|"
        r"Unmounting /|Deactivating swap)", out))


def bootloader_version() -> Optional[str]:
    out = sysinfo.vcgencmd("bootloader_version")
    return out.splitlines()[0] if out else None


def classify(rtc_valid, clean, bootstatus, gap) -> tuple:
    """Return (reason, detail). This is the triage that took a whole
    investigation to work out the first time."""
    if clean:
        return CLEAN, "previous boot logged an ordered shutdown"
    if bootstatus:
        return WATCHDOG, f"watchdog bootstatus={bootstatus}"
    if rtc_valid is False:
        return POWER_LOSS, ("RTC returned epoch: the board genuinely lost "
                            "power and re-powered")
    if rtc_valid is True:
        g = f"{gap:.0f}s" if gap else "unknown"
        return LATCH, (
            f"RTC retained correct time across a {g} outage with no clean "
            f"shutdown: the board stayed POWERED while the SoC was not "
            f"running. This is the unsolved latch (2026-08-01, 2026-08-03).")
    return UNKNOWN, "insufficient evidence to classify"


def bump(conn, name: str, delta: int = 1) -> int:
    row = conn.execute("SELECT value FROM counters WHERE name=?",
                       (name,)).fetchone()
    val = (row[0] if row else 0) + delta
    conn.execute("INSERT OR REPLACE INTO counters (name,value,updated) "
                 "VALUES (?,?,?)", (name, val, time.time()))
    conn.commit()
    return val


def counter(conn, name: str) -> int:
    row = conn.execute("SELECT value FROM counters WHERE name=?",
                       (name,)).fetchone()
    return row[0] if row else 0


# ------------------------------------------------------------- record
def record_boot(force: bool = False) -> dict:
    """Write this boot's record. Idempotent per boot_id."""
    conn = connect()
    bid = current_boot_id()
    if not bid:
        return {"error": "cannot read boot_id"}

    existing = conn.execute("SELECT boot_id FROM boots WHERE boot_id=?",
                            (bid,)).fetchone()
    if existing and not force:
        return dict(read_boot(conn, bid), already_recorded=True)

    rtc, rtc_valid = rtc_at_boot()
    prev_id, prev_end = previous_boot_end()
    clean = previous_clean_shutdown()
    wd = sysinfo.watchdog_state()
    try:
        bootstatus = int(wd.get("bootstatus") or 0)
    except (TypeError, ValueError):
        bootstatus = 0

    booted = time.time() - (sysinfo.uptime_seconds() or 0)
    gap = (booted - prev_end) if prev_end else None

    first = conn.execute("SELECT COUNT(*) FROM boots").fetchone()[0] == 0
    if first:
        reason, detail = FIRST, "first record written by this recorder"
    else:
        reason, detail = classify(rtc_valid, clean, bootstatus, gap)

    try:
        import version as version_mod
        hv = version_mod.installed_version()
    except Exception:
        hv = None

    n = bump(conn, "boots")
    if reason in (LATCH, POWER_LOSS, WATCHDOG):
        bump(conn, f"unplanned_{reason}")
        bump(conn, "unplanned_total")

    rec = {
        "boot_id": bid, "booted_at": booted,
        "booted_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                       time.gmtime(booted)),
        "node_id": enconfig.node_id(),
        "prev_boot_id": prev_id, "prev_last_seen": prev_end,
        "prev_last_seen_iso": (time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                             time.gmtime(prev_end))
                               if prev_end else None),
        "gap_seconds": gap,
        "rtc_at_boot": rtc,
        "rtc_valid": int(rtc_valid) if rtc_valid is not None else None,
        "clean_shutdown": int(clean) if clean is not None else None,
        "watchdog_bootstatus": bootstatus,
        "reboot_reason": reason, "reason_detail": detail,
        "throttled_at_boot": sysinfo.throttled_mask(),
        "model": sysinfo.capabilities().get("model"),
        "kernel": os.uname().release,
        "bootloader": bootloader_version(),
        "hardening_version": hv,
        "boot_counter": n,
        "recovery_attempts": counter(conn, "recovery_attempts"),
    }
    cols = ",".join(rec)
    conn.execute(f"INSERT OR REPLACE INTO boots ({cols}) "
                 f"VALUES ({','.join('?' * len(rec))})", tuple(rec.values()))
    conn.commit()
    conn.close()
    return rec


def read_boot(conn, bid) -> dict:
    cur = conn.execute("SELECT * FROM boots WHERE boot_id=?", (bid,))
    row = cur.fetchone()
    if not row:
        return {}
    return dict(zip([d[0] for d in cur.description], row))


def history(limit: int = 20) -> list:
    conn = connect()
    cur = conn.execute("SELECT * FROM boots ORDER BY booted_at DESC LIMIT ?",
                       (limit,))
    cols = [d[0] for d in cur.description]
    out = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    return out


def summary() -> dict:
    conn = connect()
    boots = conn.execute("SELECT COUNT(*) FROM boots").fetchone()[0]
    by_reason = dict(conn.execute(
        "SELECT reboot_reason, COUNT(*) FROM boots GROUP BY reboot_reason"
    ).fetchall())
    counters = dict(conn.execute(
        "SELECT name, value FROM counters").fetchall())
    last = conn.execute(
        "SELECT booted_at_iso, reboot_reason, gap_seconds, reason_detail "
        "FROM boots ORDER BY booted_at DESC LIMIT 1").fetchone()
    conn.close()
    return {"recorded_boots": boots, "by_reason": by_reason,
            "counters": counters,
            "last_boot": {"at": last[0], "reason": last[1],
                          "gap_seconds": last[2], "detail": last[3]}
            if last else None}
