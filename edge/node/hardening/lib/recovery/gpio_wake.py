"""Layer 6b — GPIO wake. EXPERIMENTAL, DISABLED, FRAMEWORK ONLY.

The UPS HAT (D) MCU wakes the Pi by pulling GPIO3 (SCL) low, which is the
documented Raspberry Pi wake-from-halt input. This module prepares the
framework so an external agent - or a future HAT with a watchdog register -
can drive that path without a code change.

NOTHING HERE DRIVES THE PIN. Deliberately.

RECOVERS:       nothing today.
CANNOT RECOVER: anything. On this node the only device wired to GPIO3 is the
                UPS MCU itself, and it only pulls the pin after its own arm
                sequence (see ups_wake). A Pi cannot pull its own wake pin
                while it is halted, so closing the Aug 1 gap this way needs an
                EXTERNAL device. Documented, not implemented.
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import enconfig  # noqa: E402

RECOVERS = "nothing today - framework only, requires external hardware"
CANNOT = "the Aug 1 latch; a halted Pi cannot pull its own wake pin"
FLAG = "RECOVERY_GPIO_WAKE"

def enabled() -> bool:
    return enconfig.get_bool(FLAG, False)

def status() -> dict:
    pin = enconfig.get_int("RECOVERY_GPIO_WAKE_PIN", 3)
    return {"enabled": enabled(), "experimental": True,
            "recovers": RECOVERS, "cannot_recover": CANNOT,
            "detail": {"flag": FLAG, "pin": f"GPIO{pin}",
                       "implemented": False,
                       "note": "requires an external wake source; a halted Pi "
                               "cannot drive its own wake pin"}}
