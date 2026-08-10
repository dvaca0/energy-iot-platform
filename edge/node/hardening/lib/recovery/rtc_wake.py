"""Layer 6 — RTC wake alarm. EXPERIMENTAL, DISABLED, UNVALIDATED.

THE ONLY REMAINING SOFTWARE HOPE for the 2026-08-01 failure mode.

The RTC provably kept accurate time across the entire 43h37m outage, so its
power domain survives a PMIC brownout latch. If the firmware will honour an
RTC alarm from that state, a rolling "dead-man alarm" recovers the node with
no new hardware. Whether it does is UNDOCUMENTED and must be proven by the
maintenance-window test `halt-rtc-wake` before this is ever enabled.

RECOVERS:       possibly the brownout latch. UNPROVEN.
CANNOT RECOVER: anything, while disabled. Claiming otherwise before the test
                would be exactly the false confidence this package exists to
                prevent.
"""
from __future__ import annotations
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import enconfig  # noqa: E402

RECOVERS = "UNPROVEN - possibly a brownout latch; must be validated first"
CANNOT = "anything while disabled; unknown whether firmware wakes from a latch"
FLAG = "RECOVERY_RTC_WAKE"

def device() -> str:
    return enconfig.get("RECOVERY_RTC_DEVICE", "/sys/class/rtc/rtc0/wakealarm")

def enabled() -> bool:
    return enconfig.get_bool(FLAG, False)

def _read() -> str:
    try:
        with open(device()) as fh:
            return fh.read().strip()
    except OSError:
        return ""

def status() -> dict:
    cur = _read()
    return {"enabled": enabled(), "experimental": True,
            "recovers": RECOVERS, "cannot_recover": CANNOT,
            "detail": {"flag": FLAG, "device": device(),
                       "supported": os.path.exists(device()),
                       "alarm_set": cur or "(none)",
                       "horizon_s": enconfig.get_int("RECOVERY_RTC_WAKE_SECONDS", 1800)}}

def set_alarm(seconds: int = None) -> int:
    if not enabled():
        print(f"[recovery.rtc_wake] DISABLED ({FLAG}=0) - no action")
        return 0
    horizon = seconds or enconfig.get_int("RECOVERY_RTC_WAKE_SECONDS", 1800)
    try:
        with open(device(), "w") as fh:
            fh.write("0\n")
        with open(device(), "w") as fh:
            fh.write(f"{int(time.time()) + horizon}\n")
        print(f"[recovery.rtc_wake] alarm set +{horizon}s")
        return 0
    except OSError as exc:
        print(f"[recovery.rtc_wake] failed: {exc}")
        return 1

def clear() -> int:
    try:
        with open(device(), "w") as fh:
            fh.write("0\n")
        print("[recovery.rtc_wake] alarm cleared")
        return 0
    except OSError as exc:
        print(f"[recovery.rtc_wake] clear failed: {exc}")
        return 1
