"""Recovery framework — independently switchable modules.

Every module is enabled by its own flag in hardening.conf. Every module
declares what it RECOVERS and what it CANNOT RECOVER, and reports honestly
when it is disabled.

    module        flag                            recovers
    ------------- ------------------------------- ---------------------------
    watchdog      WATCHDOG_VERIFY                 kernel freeze (verify only)
    selfheal      RECOVERY_SELF_HEAL              stalled collector
                  RECOVERY_AUTO_REBOOT            wedged userspace (escalation)
    ups_wake      RECOVERY_UPS_ARM_ON_SHUTDOWN    mains outage -> mains return
    rtc_wake      RECOVERY_RTC_WAKE               UNTESTED: brownout latch?
    gpio_wake     RECOVERY_GPIO_WAKE              UNTESTED: framework only
    relay         RECOVERY_RELAY                  UNWIRED: external power cycle
    external_watchdog
                  RECOVERY_EXTERNAL_WATCHDOG      UNWIRED: the only layer that
                                                  can recover an unpowered SoC

NONE of the experimental mechanisms may be enabled until validated in a
maintenance window. An untested recovery path creates false confidence and can
itself take a node down.

THE UNSOLVED CASE
    2026-08-01: a brownout stopped the SoC while the 5V rail stayed alive. The
    hardware watchdog was already active and could not help - the watchdog
    counter lives inside the SoC and the SoC had no power. The UPS wake
    triggers on power RETURNING, and power never left. Only rtc_wake might
    close this, and it is unproven.
"""

from __future__ import annotations

import os
import sys

_LIB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from recovery import (external_watchdog, gpio_wake, relay, rtc_wake,  # noqa: E402
                      selfheal, ups_wake, watchdog)

MODULES = {
    "watchdog": watchdog,
    "selfheal": selfheal,
    "ups_wake": ups_wake,
    "rtc_wake": rtc_wake,
    "gpio_wake": gpio_wake,
    "relay": relay,
    "external_watchdog": external_watchdog,
}


def status() -> dict:
    return {name: mod.status() for name, mod in MODULES.items()}


def print_status() -> int:
    print("=== recovery modules ===")
    for name, mod in MODULES.items():
        st = mod.status()
        flag = "ENABLED " if st["enabled"] else "disabled"
        exp = " [EXPERIMENTAL/UNTESTED]" if st.get("experimental") else ""
        print(f"\n  {name:10} {flag}{exp}")
        print(f"     recovers   : {st['recovers']}")
        print(f"     cannot     : {st['cannot_recover']}")
        for k, v in st.get("detail", {}).items():
            print(f"     {k:10} : {v}")
    return 0
