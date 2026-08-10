"""UPS hardware discovery framework.

    UPSDriver
        |-- Waveshare HAT (D)     verified on N001
        |-- Waveshare HAT (E)     from vendor register map, unverified
        |-- Unknown               safe fallback, exposes raw I2C fingerprint
        `-- (future drivers)      add a module + register it here

At startup the framework:
    1. checks whether an I2C bus exists at all
    2. probes each registered driver in UPS_DRIVER_ORDER
    3. loads the first driver whose fingerprint matches EXACTLY
    4. if nothing matches but devices answered, returns UNIDENTIFIED with the
       raw address list logged, and continues safely

It never guesses. N002 and N003 will identify themselves on first boot, or
declare honestly that their hardware is not in the registry.
"""

from __future__ import annotations

import os
import sys

_LIB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

import enconfig  # noqa: E402
from i2cbus import I2CBus  # noqa: E402
from ups.base import UPSDriver, UpsState  # noqa: E402
from ups.waveshare_hat_d import WaveshareHatD  # noqa: E402
from ups.waveshare_hat_e import WaveshareHatE  # noqa: E402

#: driver registry — add new models here
REGISTRY = {
    WaveshareHatD.name: WaveshareHatD,
    WaveshareHatE.name: WaveshareHatE,
}

# Addresses worth reporting when nothing matches, so an unknown HAT can be
# identified from the field without a site visit.
_SCAN_START, _SCAN_END = 0x03, 0x77


def _ordered_drivers() -> list:
    order = enconfig.get_list("UPS_DRIVER_ORDER", list(REGISTRY))
    drivers = [REGISTRY[n]() for n in order if n in REGISTRY]
    # Anything registered but not listed still gets probed, last.
    drivers += [c() for n, c in REGISTRY.items() if n not in order]
    return drivers


def discover(bus_num: int = None) -> UpsState:
    """Identify the attached UPS. Never raises, never guesses."""
    if not enconfig.get_bool("UPS_ENABLED", True):
        return UpsState(present=False, confidence="disabled",
                        error="UPS_ENABLED=0 in hardening.conf")

    bus_num = bus_num if bus_num is not None else enconfig.get_int("UPS_I2C_BUS", 1)

    if not I2CBus.available(bus_num):
        return UpsState(
            present=False, confidence="no-bus",
            error=f"/dev/i2c-{bus_num} missing — is dtparam=i2c_arm=on set "
                  f"in /boot/firmware/config.txt and has the node rebooted?")

    try:
        with I2CBus(bus_num) as bus:
            for drv in _ordered_drivers():
                try:
                    if drv.probe(bus):
                        st = drv.read(bus)
                        _apply_thresholds(st)
                        return st
                except OSError:
                    continue

            found = bus.scan(_SCAN_START, _SCAN_END)
            if found:
                return UpsState(
                    present=True, identified=False, confidence="unidentified",
                    fingerprint={"bus": bus_num,
                                 "addresses": [hex(a) for a in found],
                                 "registry": list(REGISTRY)},
                    error="I2C devices present but no registered driver "
                          "matched. Battery state deliberately NOT reported. "
                          "Add a driver to lib/ups/ and register it.")
            return UpsState(present=False, confidence="absent",
                            fingerprint={"bus": bus_num, "addresses": []},
                            error="no I2C devices answered")
    except OSError as exc:
        return UpsState(present=False, confidence="error", error=str(exc))


def _apply_thresholds(st: UpsState) -> None:
    """Apply configured thresholds. Drivers report raw values only."""
    if st.battery_voltage_v is not None:
        st.battery_low = st.battery_voltage_v < enconfig.get_float(
            "UPS_BATTERY_LOW_V", 3.15)
    if st.battery_current_ma is not None and st.on_battery is None:
        st.on_battery = st.battery_current_ma < enconfig.get_float(
            "UPS_ON_BATTERY_MA", -50.0)


def arm_wake() -> tuple:
    """Arm the identified HAT's wake feature. Caller MUST power off at once.

    Guarded by RECOVERY_UPS_ARM_ON_SHUTDOWN; see lib/recovery/ups_wake.py.
    """
    bus_num = enconfig.get_int("UPS_I2C_BUS", 1)
    if not I2CBus.available(bus_num):
        return False, f"/dev/i2c-{bus_num} unavailable"
    try:
        with I2CBus(bus_num) as bus:
            for drv in _ordered_drivers():
                if drv.probe(bus):
                    if not drv.supports_wake():
                        return False, f"{drv.model} has no wake register"
                    return drv.arm_wake(bus)
        return False, "no identified UPS — refusing to write to unknown hardware"
    except OSError as exc:
        return False, str(exc)


def read() -> UpsState:
    return discover()


if __name__ == "__main__":
    import json
    s = discover()
    print(json.dumps(s.as_dict(), indent=2))
    print("\n" + s.summary())
