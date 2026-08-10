"""Layer 5 — UPS "Boot When Power Applied". EXPERIMENTAL, DISABLED.

Writes 0x55 to the UPS MCU arm register during shutdown ONLY. The vendor
requires the Pi to power off immediately after the write, so this is wired as
a systemd ExecStop and must never run while the node is live.

RECOVERS:       mains outage -> battery flat -> clean shutdown -> mains
                returns -> MCU pulls GPIO3 low -> node boots unattended.
CANNOT RECOVER: the 2026-08-01 failure. The MCU triggers on power RETURNING at
                the charging port; in that incident power never went away (the
                RTC kept time for the whole 43h37m), so there was no
                transition to detect. Arming this would NOT have helped.
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import enconfig  # noqa: E402
import ups as ups_pkg  # noqa: E402

RECOVERS = "mains outage -> battery flat -> shutdown -> mains returns -> boot"
CANNOT = "the Aug 1 brownout latch (no power transition for the MCU to see)"
FLAG = "RECOVERY_UPS_ARM_ON_SHUTDOWN"

def enabled() -> bool:
    return enconfig.get_bool(FLAG, False)

def status() -> dict:
    st = ups_pkg.read()
    return {"enabled": enabled(), "experimental": True,
            "recovers": RECOVERS, "cannot_recover": CANNOT,
            "detail": {"flag": FLAG, "ups": st.summary(),
                       "armed": st.auto_reboot_armed,
                       "arm_register": (hex(st.arm_register)
                                        if st.arm_register is not None else None)}}

def arm() -> int:
    """Called from the shutdown hook. No-op unless explicitly enabled."""
    if not enabled():
        print(f"[recovery.ups_wake] DISABLED ({FLAG}=0) - no action")
        return 0
    ok, detail = ups_pkg.arm_wake()
    print(f"[recovery.ups_wake] arm ok={ok} {detail}")
    return 0 if ok else 1
