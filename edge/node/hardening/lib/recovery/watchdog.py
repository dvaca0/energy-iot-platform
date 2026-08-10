"""Layer 1 — hardware watchdog. VERIFICATION ONLY.

The bcm2835 watchdog is armed by the OS via
/usr/lib/systemd/system.conf.d/40-rpi-enable-watchdog.conf (RuntimeWatchdogSec).
This package does not arm it; it verifies it, because it was ALREADY ACTIVE
during the 2026-08-01 failure and did not help.

RECOVERS:       kernel freeze / deadlock (~60s then reboot).
CANNOT RECOVER: an unpowered SoC. The watchdog counter is inside the SoC. On
                2026-08-01 the RTC kept perfect time for 43h37m, proving the
                board stayed powered while the SoC was held off. No code on an
                unpowered CPU can restart that CPU.
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import enconfig, sysinfo  # noqa: E402

RECOVERS = "kernel freeze / deadlock"
CANNOT = "unpowered SoC or PMIC latch (was active on 2026-08-01, did not help)"

def enabled() -> bool:
    return enconfig.get_bool("WATCHDOG_VERIFY", True)

def status() -> dict:
    wd = sysinfo.watchdog_state()
    want = enconfig.get_int("WATCHDOG_EXPECT_TIMEOUT", 60)
    ok = bool(wd.get("present")) and wd.get("state") == "active"
    return {"enabled": enabled(), "experimental": False,
            "recovers": RECOVERS, "cannot_recover": CANNOT,
            "healthy": ok,
            "detail": {"present": wd.get("present"), "state": wd.get("state"),
                       "timeout": wd.get("timeout"), "expected": want,
                       "identity": wd.get("identity"),
                       "bootstatus": wd.get("bootstatus")}}
