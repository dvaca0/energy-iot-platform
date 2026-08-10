"""Layers 3 & 4 — collector self-heal and reboot escalation. DISABLED.

RECOVERS (layer 3):  a collector that is alive but not producing measurements.
    This is exactly the condition the 2026-08-01 alert claimed was happening
    ("Node N001 is alive but not measuring"). It had no automatic remedy.
    systemd's Restart=always cannot help here: a SIGSTOP'd or wedged process
    is still "active" as far as systemd is concerned - demonstrated by the
    collector-freeze test, where systemctl is-active reported active while the
    process was in state T.

RECOVERS (layer 4):  wedged userspace that a unit restart cannot clear,
    by escalating to a reboot after N consecutive failed restarts.

CANNOT RECOVER: a node that is fully down. Nothing here runs then. And it
    cannot recover the Aug 1 brownout latch, where no code was executing.
"""

from __future__ import annotations

import datetime
import os
import sqlite3
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import enconfig  # noqa: E402

RECOVERS = "stalled collector (alive but not measuring); escalates to reboot"
CANNOT = "a node that is fully down, or an unpowered SoC"
FLAG = "RECOVERY_SELF_HEAL"
COLLECTOR_UNIT = "energy-node-collector.service"


def enabled() -> bool:
    return enconfig.get_bool(FLAG, False)


def _counter_path() -> str:
    return os.path.join(enconfig.get("EN_STATE_DIR", "/opt/energy-node/state"),
                        "selfheal_failures")


def failures(delta: int = 0) -> int:
    path = _counter_path()
    try:
        n = int(open(path).read().strip()) if os.path.exists(path) else 0
    except (OSError, ValueError):
        n = 0
    if delta:
        n = max(0, n + delta) if delta > 0 else 0
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fh:
                fh.write(str(n))
        except OSError:
            pass
    return n


def measurement_age():
    """Seconds since the newest measurement, or None if unknown."""
    db = enconfig.get("DB_PATH", "/opt/energy-node/database/edge_buffer.db")
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        row = conn.execute("SELECT MAX(captured_at) FROM measurements").fetchone()
        conn.close()
        if not row or not row[0]:
            return None
        t = datetime.datetime.fromisoformat(row[0].replace("Z", "+00:00"))
        return (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds()
    except Exception:
        return None


def status() -> dict:
    age = measurement_age()
    return {"enabled": enabled(), "experimental": False,
            "recovers": RECOVERS, "cannot_recover": CANNOT,
            "detail": {"flag": FLAG,
                       "measurement_age_s": round(age, 1) if age else age,
                       "stale_after_s": enconfig.get_int("RECOVERY_STALE_SECONDS", 600),
                       "consecutive_failures": failures(),
                       "auto_reboot": enconfig.get_bool("RECOVERY_AUTO_REBOOT", False),
                       "reboot_after": enconfig.get_int(
                           "RECOVERY_AUTO_REBOOT_AFTER_FAILURES", 3)}}


def run() -> int:
    if not enabled():
        print(f"[recovery.selfheal] DISABLED ({FLAG}=0) - no action")
        return 0

    age = measurement_age()
    limit = enconfig.get_int("RECOVERY_STALE_SECONDS", 600)
    if age is None:
        print("[recovery.selfheal] measurement age unknown - taking no action")
        return 0
    if age <= limit:
        failures(-1)
        print(f"[recovery.selfheal] healthy (age {age:.0f}s <= {limit}s)")
        return 0

    n = failures(+1)
    print(f"[recovery.selfheal] STALE {age:.0f}s > {limit}s "
          f"(consecutive={n}) -> restarting collector")
    subprocess.run(["systemctl", "restart", COLLECTOR_UNIT], timeout=60)

    threshold = enconfig.get_int("RECOVERY_AUTO_REBOOT_AFTER_FAILURES", 3)
    if enconfig.get_bool("RECOVERY_AUTO_REBOOT", False) and n >= threshold:
        # The reboot budget is shared with the Recovery Manager and lives in
        # the persistent ledger, NOT in this counter.
        #
        # This previously called failures(-1) here, which zeroes the counter.
        # After the reboot the node therefore had no memory of having tried:
        # three more restarts, another reboot, forever. That is the infinite
        # reboot loop the ledger exists to make impossible. The counter is
        # deliberately NOT reset - the reboot is recorded in the ledger and
        # the budget decides whether another one is allowed.
        import time

        from recovery import ledger as ledger_mod

        now = time.time()
        led = ledger_mod.load()
        budget = enconfig.get_int("RECOVERY_REBOOT_MAX", 3)
        window = enconfig.get_int("RECOVERY_REBOOT_WINDOW_S", 1800)
        used = led.reboots_in_window(now, window)
        if used >= budget:
            print(f"[recovery.selfheal] reboot budget exhausted "
                  f"({used}/{budget} in {window}s) - NOT rebooting. "
                  f"Recovery Manager owns SAFE MODE from here.")
            return 0
        print(f"[recovery.selfheal] escalation: {n} >= {threshold} -> REBOOT "
              f"({used + 1}/{budget} in {window}s)")
        led.reboots.append(now)
        ledger_mod.prune(led, now)
        ledger_mod.save(led)     # persist BEFORE rebooting, or it never happens
        from recovery import ups_wake
        ups_wake.arm()          # no-op unless its own flag is set
        subprocess.run(["systemctl", "reboot"], timeout=30)
    return 0
