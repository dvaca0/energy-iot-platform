"""Persistent boot progression — "how far did this boot actually get?"

WHY
    The runtime state machine knows where boot failed, but only while it is
    running. After a reboot, a watchdog reset or a power cut that knowledge is
    gone, and journald may be gone with it. This makes the answer durable, so
    that after any restart the question

        "what was the last stage the node successfully reached?"

    has a reliable answer without reproducing the fault.

OWNERSHIP - three stores, three jobs, no overlap
    blackbox.boots        historical event ledger: one row per boot, WHY the
                          previous boot ended. Already existed; untouched.
    recovery-ledger.json  mutable recovery state: the reboot budget and
                          escalation memory. Small, rewritten constantly.
    boot_state (here)     structured record of how far each boot got, keyed by
                          the SAME boot_id blackbox uses, in the SAME database.

    A second boot-history database would be a competing source of truth, so
    there isn't one.

STAGES ARE NOT REDEFINED HERE
    The canonical order is pipeline.STAGE_ORDER. These names are derived from
    it, so a stage added there appears here automatically and the two can never
    disagree.

DURABILITY
    Inherits blackbox's connection policy: SQLite WAL with synchronous=FULL.
    Boot records are rare and irreplaceable, so we pay for the fsync. Each
    update is a single committed transaction, so a power cut mid-write leaves
    the previous consistent row rather than a torn one.

APPEND, NEVER ERASE
    A boot that failed at TAILSCALE_READY and later recovered keeps both facts:
    the row carries the current view, and boot_events keeps the history. A
    recovery that succeeds must never make the failure invisible.

STDLIB ONLY.
"""

from __future__ import annotations

__version__ = "1.0.0"

import json
import os
import sqlite3
import sys
import time
from typing import List, Optional

_LIB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

import blackbox  # noqa: E402
import enconfig  # noqa: E402

from recovery import pipeline as P  # noqa: E402

#: A record created more than this long after kernel boot was not watching
#: the boot, so it must not claim to have timed it.
OBSERVE_GRACE_S = 300.0

BOOT_STARTED = "BOOT_STARTED"
HEALTHY = "HEALTHY"

#: observed_from records when the RECORD began, which is not when the node
#: booted. A daemon installed or started long after boot would otherwise
#: measure time_to_healthy from a kernel boot nobody was watching.
#:
#: Deliberately no SQL comments inside the CREATE TABLE: SQLite stores the
#: original DDL text verbatim and replays it on ALTER TABLE, where an embedded
#: comment breaks the rewrite with "incomplete input".
SCHEMA = """
CREATE TABLE IF NOT EXISTS boot_state (
    boot_id               TEXT PRIMARY KEY,
    node_id               TEXT,
    boot_started_at       REAL,
    boot_started_iso      TEXT,
    prev_boot_reason      TEXT,
    current_stage         TEXT,
    last_successful_stage TEXT,
    first_failed_stage    TEXT,
    failure_reason        TEXT,
    failure_owner         TEXT,
    service_restarts      INTEGER NOT NULL DEFAULT 0,
    reboot_attempts       INTEGER NOT NULL DEFAULT 0,
    safe_mode_entered     INTEGER NOT NULL DEFAULT 0,
    safe_mode_at          REAL,
    network_used          TEXT,
    tailscale_state       TEXT,
    backend_state         TEXT,
    sensor_state          TEXT,
    collector_state       TEXT,
    heartbeat_state       TEXT,
    measurements_state    TEXT,
    time_sync_state       TEXT,
    boot_complete         INTEGER NOT NULL DEFAULT 0,
    healthy_at            REAL,
    time_to_healthy_s     REAL,
    final_outcome         TEXT,
    updated_at            REAL,
    observed_from         REAL
);
CREATE INDEX IF NOT EXISTS idx_boot_state_at ON boot_state(boot_started_at);

CREATE TABLE IF NOT EXISTS boot_events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    boot_id   TEXT NOT NULL,
    at        REAL NOT NULL,
    at_iso    TEXT,
    kind      TEXT NOT NULL,
    stage     TEXT,
    detail    TEXT
);
CREATE INDEX IF NOT EXISTS idx_boot_events_boot ON boot_events(boot_id, id);
"""

# Event kinds
E_BOOT = "boot_started"
E_STAGE_OK = "stage_reached"
E_STAGE_FAIL = "stage_failed"
E_REMEDY = "remedy"
E_REBOOT = "reboot"
E_SAFE_MODE = "safe_mode_entered"
E_SAFE_MODE_EXIT = "safe_mode_left"
E_HEALTHY = "healthy"


def stage_names() -> List[str]:
    """The canonical boot states, derived from pipeline.STAGE_ORDER.

    Never hardcoded: a stage added to the pipeline appears here for free, so
    the two definitions cannot drift apart.
    """
    return [BOOT_STARTED] + [f"{s.upper()}_READY" for s in P.STAGE_ORDER] + [HEALTHY]


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


#: Columns added after the table first shipped. CREATE TABLE IF NOT EXISTS
#: cannot add them to an existing database, so they are applied additively.
#: Additive only - nothing here ever drops or rewrites a column, so an older
#: package reading a newer database still works.
_ADDED_COLUMNS = (("boot_state", "observed_from", "REAL"),)


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, decl in _ADDED_COLUMNS:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
    conn.commit()


def connect() -> sqlite3.Connection:
    """Reuse blackbox's connection policy (WAL + synchronous=FULL)."""
    conn = blackbox.connect()
    conn.executescript(SCHEMA)
    conn.commit()
    _migrate(conn)
    return conn


def boot_id() -> str:
    return blackbox.current_boot_id() or "unknown"


# ------------------------------------------------------------------ analysis


def last_successful_stage(results: List[P.StageResult]) -> str:
    """The furthest point boot actually reached.

    A stage counts as reached only if it and everything before it are not
    FAILED. UNKNOWN does not block progress - a node with no Tailscale has not
    failed to boot, it simply cannot assert that stage.
    """
    by = {r.stage: r for r in results}
    reached = BOOT_STARTED
    for stage in P.STAGE_ORDER:
        r = by.get(stage)
        if r is not None and r.status == P.FAILED:
            break
        reached = f"{stage.upper()}_READY"
    return reached


def failure_owner(stage: Optional[str], results: List[P.StageResult],
                  policy: P.Policy) -> str:
    if stage is None:
        return "NONE"
    by = {r.stage: r for r in results}
    r = by.get(stage)
    if r is None or r.status == P.UNKNOWN:
        return "UNKNOWN"
    return policy.classify(stage).upper()


def _status_of(results: List[P.StageResult], stage: str) -> str:
    for r in results:
        if r.stage == stage:
            return r.status
    return P.UNKNOWN


def _detail_of(results: List[P.StageResult], stage: str) -> str:
    for r in results:
        if r.stage == stage:
            return r.detail
    return ""


# ------------------------------------------------------------------- writing


def begin(conn: sqlite3.Connection, now: Optional[float] = None) -> str:
    """Create this boot's record if it does not exist. Idempotent.

    Called on the daemon's first tick rather than at boot, because the daemon
    is the thing that knows about stages. The boot_id is the kernel's, so a
    daemon restart within one boot updates the same record instead of
    inventing a new boot.
    """
    now = now if now is not None else time.time()
    bid = boot_id()
    row = conn.execute("SELECT boot_id FROM boot_state WHERE boot_id=?",
                       (bid,)).fetchone()
    if row:
        return bid

    prev_reason = None
    try:
        b = conn.execute(
            "SELECT reboot_reason FROM boots WHERE boot_id=?", (bid,)).fetchone()
        if b:
            prev_reason = b[0]
    except sqlite3.DatabaseError:
        pass

    started = now
    try:
        started = blackbox.sysinfo.boot_time()
    except Exception:
        pass

    conn.execute(
        "INSERT INTO boot_state (boot_id, node_id, boot_started_at, "
        "boot_started_iso, prev_boot_reason, current_stage, "
        "last_successful_stage, updated_at, observed_from) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (bid, enconfig.node_id(), started, _iso(started), prev_reason,
         BOOT_STARTED, BOOT_STARTED, now, now))
    conn.execute(
        "INSERT INTO boot_events (boot_id, at, at_iso, kind, stage, detail) "
        "VALUES (?,?,?,?,?,?)",
        (bid, now, _iso(now), E_BOOT, BOOT_STARTED,
         f"previous boot ended: {prev_reason or 'unknown'}"))
    conn.commit()
    return bid


def event(conn: sqlite3.Connection, kind: str, stage: Optional[str],
          detail: str, now: Optional[float] = None) -> None:
    """Append an event. Never overwrites; a later success does not erase an
    earlier failure."""
    now = now if now is not None else time.time()
    conn.execute(
        "INSERT INTO boot_events (boot_id, at, at_iso, kind, stage, detail) "
        "VALUES (?,?,?,?,?,?)", (boot_id(), now, _iso(now), kind, stage, detail))
    if kind == E_REMEDY:
        conn.execute("UPDATE boot_state SET service_restarts=service_restarts+1 "
                     "WHERE boot_id=?", (boot_id(),))
    elif kind == E_REBOOT:
        conn.execute("UPDATE boot_state SET reboot_attempts=reboot_attempts+1 "
                     "WHERE boot_id=?", (boot_id(),))
    elif kind == E_SAFE_MODE:
        conn.execute("UPDATE boot_state SET safe_mode_entered=1, safe_mode_at=? "
                     "WHERE boot_id=?", (now, boot_id()))
    conn.commit()


def update(conn: sqlite3.Connection, results: List[P.StageResult],
           decision: P.Decision, policy: P.Policy,
           now: Optional[float] = None) -> None:
    """Write the current view of this boot. One committed transaction."""
    now = now if now is not None else time.time()
    bid = begin(conn, now)

    failure = P.first_failure(results)
    first_failed = f"{failure.stage.upper()}_READY" if failure else None
    reached = last_successful_stage(results)
    owner = failure_owner(failure.stage if failure else None, results, policy)

    healthy = failure is None and decision.state in (P.HEALTHY,)
    current = HEALTHY if healthy else reached

    prev = conn.execute(
        "SELECT last_successful_stage, boot_complete, boot_started_at, "
        "observed_from FROM boot_state WHERE boot_id=?", (bid,)).fetchone()
    prev_reached = prev[0] if prev else BOOT_STARTED
    was_complete = bool(prev[1]) if prev else False
    started_at = prev[2] if prev else now
    observed_from = (prev[3] if prev and prev[3] is not None else now)

    net_detail = _detail_of(results, P.NETWORK)

    conn.execute(
        "UPDATE boot_state SET current_stage=?, last_successful_stage=?, "
        "first_failed_stage=?, failure_reason=?, failure_owner=?, "
        "network_used=?, tailscale_state=?, backend_state=?, sensor_state=?, "
        "collector_state=?, heartbeat_state=?, measurements_state=?, "
        "time_sync_state=?, final_outcome=?, updated_at=? WHERE boot_id=?",
        (current, reached, first_failed,
         failure.detail if failure else None, owner,
         net_detail,
         _status_of(results, P.TAILSCALE), _status_of(results, P.BACKEND),
         _status_of(results, P.SENSOR), _status_of(results, P.COLLECTOR),
         _status_of(results, P.HEARTBEAT), _status_of(results, P.MEASUREMENTS),
         _status_of(results, P.CLOCK), decision.state, now, bid))

    # Progress is worth an event; so is a regression.
    if reached != prev_reached:
        kind = E_STAGE_OK
        conn.execute(
            "INSERT INTO boot_events (boot_id, at, at_iso, kind, stage, detail) "
            "VALUES (?,?,?,?,?,?)",
            (bid, now, _iso(now), kind, reached,
             f"progressed from {prev_reached}"))

    if failure is not None:
        last_fail = conn.execute(
            "SELECT stage, detail FROM boot_events WHERE boot_id=? AND kind=? "
            "ORDER BY id DESC LIMIT 1", (bid, E_STAGE_FAIL)).fetchone()
        sig = (first_failed, failure.detail)
        if not last_fail or (last_fail[0], last_fail[1]) != sig:
            conn.execute(
                "INSERT INTO boot_events (boot_id, at, at_iso, kind, stage, "
                "detail) VALUES (?,?,?,?,?,?)",
                (bid, now, _iso(now), E_STAGE_FAIL, first_failed,
                 f"[{owner}] {failure.detail}"))

    # A boot is COMPLETE only when the whole contract passes. Linux being up is
    # not a successful boot.
    if healthy and not was_complete:
        # Only claim a time-to-healthy if we were watching from near the start.
        # A record created hours into a boot (fresh install, daemon enabled
        # late) would otherwise report those hours as boot time.
        watched = (observed_from - (started_at or observed_from)) <= OBSERVE_GRACE_S
        tth = max(0.0, now - (started_at or now)) if watched else None
        conn.execute(
            "UPDATE boot_state SET boot_complete=1, healthy_at=?, "
            "time_to_healthy_s=? WHERE boot_id=?", (now, tth, bid))
        detail = (f"boot complete after {tth:.0f}s" if tth is not None
                  else "boot complete (record started mid-boot; "
                       "time-to-healthy not measurable)")
        conn.execute(
            "INSERT INTO boot_events (boot_id, at, at_iso, kind, stage, detail) "
            "VALUES (?,?,?,?,?,?)",
            (bid, now, _iso(now), E_HEALTHY, HEALTHY, detail))

    conn.commit()


# ------------------------------------------------------------------- reading


def _row_to_dict(conn, row) -> dict:
    cols = [d[0] for d in conn.execute("SELECT * FROM boot_state LIMIT 0").description]
    return dict(zip(cols, row))


def status(conn: Optional[sqlite3.Connection] = None) -> Optional[dict]:
    own = conn is None
    conn = conn or connect()
    try:
        row = conn.execute("SELECT * FROM boot_state WHERE boot_id=?",
                           (boot_id(),)).fetchone()
        if row is None:
            row = conn.execute(
                "SELECT * FROM boot_state ORDER BY boot_started_at DESC "
                "LIMIT 1").fetchone()
        return _row_to_dict(conn, row) if row else None
    finally:
        if own:
            conn.close()


def history(limit: int = 20, conn: Optional[sqlite3.Connection] = None) -> list:
    own = conn is None
    conn = conn or connect()
    try:
        rows = conn.execute(
            "SELECT * FROM boot_state ORDER BY boot_started_at DESC LIMIT ?",
            (limit,)).fetchall()
        return [_row_to_dict(conn, r) for r in rows]
    finally:
        if own:
            conn.close()


def events(bid: Optional[str] = None, limit: int = 100,
           conn: Optional[sqlite3.Connection] = None) -> list:
    own = conn is None
    conn = conn or connect()
    try:
        rows = conn.execute(
            "SELECT at_iso, kind, stage, detail FROM boot_events "
            "WHERE boot_id=? ORDER BY id DESC LIMIT ?",
            (bid or boot_id(), limit)).fetchall()
        return [{"at": r[0], "kind": r[1], "stage": r[2], "detail": r[3]}
                for r in rows]
    finally:
        if own:
            conn.close()
