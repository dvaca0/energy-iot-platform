"""Persistence for the recovery ledger. Thin I/O around pipeline.Ledger.

The ledger MUST survive a reboot. That is the whole boot-loop guard: the old
selfheal kept its counter in a file but reset it to zero immediately before
rebooting, so every boot started fresh and the node could reboot forever.

Stored under EN_STATE_DIR (a real disk path, never /run) as JSON, written
atomically. A corrupt or unreadable ledger degrades to an empty one rather
than preventing recovery from running - but it says so loudly, because a
ledger that silently resets is indistinguishable from the bug this replaces.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from typing import Optional

_LIB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

import enconfig  # noqa: E402

from recovery.pipeline import Ledger  # noqa: E402

FILENAME = "recovery-ledger.json"


def path() -> str:
    return os.path.join(
        enconfig.get("EN_STATE_DIR", "/opt/energy-node/state"), FILENAME
    )


def load(p: Optional[str] = None) -> Ledger:
    p = p or path()
    try:
        with open(p, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        return Ledger()
    except (OSError, ValueError) as exc:
        print(f"[recovery.ledger] UNREADABLE ({exc}) - starting from empty. "
              f"Reboot history for the guard is lost.", file=sys.stderr)
        return Ledger()

    if not isinstance(raw, dict):
        return Ledger()

    return Ledger(
        reboots=[float(t) for t in raw.get("reboots", []) if isinstance(t, (int, float))],
        attempts={str(k): int(v) for k, v in (raw.get("attempts") or {}).items()},
        last_attempt={
            str(k): float(v) for k, v in (raw.get("last_attempt") or {}).items()
        },
        safe_mode_since=raw.get("safe_mode_since"),
        safe_mode_last_retry=raw.get("safe_mode_last_retry"),
        safe_mode_last_reboot=raw.get("safe_mode_last_reboot"),
    )


def save(ledger: Ledger, p: Optional[str] = None) -> None:
    """Atomic write. A half-written ledger after a power cut would be worse
    than none: it is the only thing standing between a fault and a reboot loop.
    """
    p = p or path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    payload = {
        "reboots": ledger.reboots,
        "attempts": ledger.attempts,
        "last_attempt": ledger.last_attempt,
        "safe_mode_since": ledger.safe_mode_since,
        "safe_mode_last_retry": ledger.safe_mode_last_retry,
        "safe_mode_last_reboot": ledger.safe_mode_last_reboot,
    }
    d = os.path.dirname(p)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".recovery-ledger.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def prune(ledger: Ledger, now: float, keep_s: float = 604800.0) -> Ledger:
    """Drop reboot records older than a week so the file cannot grow forever."""
    ledger.reboots = [t for t in ledger.reboots if now - t <= keep_s]
    return ledger
