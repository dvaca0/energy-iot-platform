"""Layer 8 — external hardware watchdog. EXPERIMENTAL, DISABLED, NOT WIRED.

The second of the only two mechanisms that can recover the 2026-08-01 latch.

CONCEPT
    An independent microcontroller (or watchdog HAT) that this node must "pet"
    on a schedule. If petting stops, the MCU asserts a hardware reset - either
    by pulling RUN/GLOBAL_EN low, by pulling GPIO3 low (the documented
    wake-from-halt input), or by cycling power.

WHY IT SUCCEEDS WHERE THE INTERNAL WATCHDOG FAILED
    The bcm2835 watchdog counter lives INSIDE the SoC. On 2026-08-01 the SoC
    had no power, so it never counted and never fired. An external MCU has its
    own power domain and keeps counting regardless of what the Pi is doing.
    That is the entire difference.

PREREQUISITES (none present on N001)
    1. Physical watchdog device: a HAT, or an MCU on I2C/UART/GPIO.
    2. A pet path: this module writes to it on a timer.
    3. A reset path wired to RUN or to the input power.
    4. Pet interval shorter than the MCU's timeout, with margin for a
       legitimately busy node - too aggressive and it reboots a healthy node
       mid-sync, which is its own outage.

RECOVERS:       kernel freeze AND unpowered/latched SoC - the full failure set,
                including the one nothing else covers.
CANNOT RECOVER: nothing, in principle. In practice: anything while the device
                is absent, which is the situation today.
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import enconfig  # noqa: E402

RECOVERS = "kernel freeze AND unpowered/latched SoC (the Aug 1 case) - if wired"
CANNOT = "anything today; no external watchdog device is present"
FLAG = "RECOVERY_EXTERNAL_WATCHDOG"

def enabled() -> bool:
    return enconfig.get_bool(FLAG, False)

def device() -> str:
    return enconfig.get("RECOVERY_EXTERNAL_WATCHDOG_DEVICE", "none")

def detect() -> dict:
    """Look for a plausible external watchdog. Reports, never assumes."""
    dev = device()
    present = bool(dev and dev != "none" and os.path.exists(dev))
    return {"configured": dev, "present": present}

def status() -> dict:
    d = detect()
    return {"enabled": enabled(), "experimental": True,
            "recovers": RECOVERS, "cannot_recover": CANNOT,
            "detail": {"flag": FLAG, "device": d["configured"],
                       "device_present": d["present"],
                       "implemented": False,
                       "pet_interval_s": enconfig.get_int(
                           "RECOVERY_EXTERNAL_WATCHDOG_PET_SECONDS", 30),
                       "prerequisites": [
                           "external MCU/HAT with its own power domain",
                           "pet path (I2C/UART/GPIO)",
                           "reset path wired to RUN or input power",
                           "pet interval < MCU timeout, with margin"],
                       "note": "the ONLY layer that can recover an unpowered "
                               "SoC, because its counter is outside the SoC"}}

def pet() -> int:
    if not enabled():
        print(f"[recovery.external_watchdog] DISABLED ({FLAG}=0) - no action")
        return 0
    d = detect()
    if not d["present"]:
        print(f"[recovery.external_watchdog] device {d['configured']} absent; "
              f"refusing to report a pet that did not happen")
        return 1
    print("[recovery.external_watchdog] no driver implemented for "
          f"{d['configured']}")
    return 1
