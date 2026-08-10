"""Layer 7 — external relay power-cycle. EXPERIMENTAL, DISABLED, NOT WIRED.

WHY THIS MATTERS MORE THAN ANYTHING ELSE HERE
    This is one of only two mechanisms that can recover the 2026-08-01 failure
    (brownout latches the PMIC; 5V rail stays alive; SoC held off; RTC keeps
    running). Every software layer failed there because no code was executing.
    A relay that physically interrupts and restores the HAT's input creates
    the power-on-reset the board never got.

    We PROVED a true power cycle recovers this node: on 2026-07-27 the RTC
    came back at epoch (full power loss) and the node booted by itself.

PREREQUISITES (none of which exist on N001 today)
    1. A relay or smart plug in series with the UPS HAT's Type-C input.
       It must cut the INPUT, not the Pi's 5V rail - cutting downstream of
       the UPS achieves nothing because the battery keeps the Pi alive.
    2. The relay must be commandable by something that is NOT this node.
       A Pi that is latched off cannot command its own power cycle. This
       module is therefore only the node-side half: it reports capability and
       exposes a local test path. The DECISION to cycle must come from the
       backend or a peer node observing missed heartbeats.
    3. Cycle timing: the UPS HAT (D) holds the Pi up from battery, so the
       input must stay off long enough for the battery to sag below the
       PMIC's hold-up, or the battery must be disconnected. UNVERIFIED - this
       is the main open question for this approach and must be measured
       before anyone relies on it.

RECOVERS:       potentially the brownout latch, if prerequisites 1-3 hold.
CANNOT RECOVER: anything while disabled and unwired. Also cannot be triggered
                by the node itself when the node is the thing that is down -
                that is the whole point of prerequisite 2.
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import enconfig  # noqa: E402

RECOVERS = "brownout latch, IF an external relay cuts the UPS INPUT (unwired)"
CANNOT = "anything today; a latched node cannot command its own power cycle"
FLAG = "RECOVERY_RELAY"

def enabled() -> bool:
    return enconfig.get_bool(FLAG, False)

def backend() -> str:
    return enconfig.get("RECOVERY_RELAY_BACKEND", "none")

def status() -> dict:
    return {"enabled": enabled(), "experimental": True,
            "recovers": RECOVERS, "cannot_recover": CANNOT,
            "detail": {"flag": FLAG, "backend": backend(),
                       "implemented": False,
                       "wired": False,
                       "prerequisites": [
                           "relay in series with the UPS HAT Type-C INPUT",
                           "commandable by a peer/backend, not by this node",
                           "off-time long enough to drain UPS hold-up "
                           "(UNVERIFIED - must be measured)"],
                       "note": "node-side half only; the cycle decision must "
                               "come from something that is still running"}}

def cycle(dry_run: bool = True) -> int:
    """Placeholder. Refuses to act: no relay backend is implemented."""
    if not enabled():
        print(f"[recovery.relay] DISABLED ({FLAG}=0) - no action")
        return 0
    print(f"[recovery.relay] backend={backend()} is not implemented; "
          f"refusing to pretend a power cycle occurred")
    return 1
