"""Waveshare UPS HAT (E) driver.

NOT VERIFIED AGAINST PHYSICAL HARDWARE. Written from the vendor register map
(https://www.waveshare.com/wiki/UPS_HAT_(E)_Register), which documents MCU
slave address 0x2D with:

    0x00        ID register, fixed 0x0a
    0x01        "Automatically Rebooting" register, fixed 0x0b;
                write 0x55 to power off and enable the incoming power function
    0x02        charging register (bitfield, NOT a fixed 0x0c)
    0x03        communication register (BQ4050 / IP2368 status)
    0x10/0x11   Type-C VBUS voltage, mV, low byte first
    0x12/0x13   Type-C VBUS current, mA
    0x20/0x21   battery total voltage, mV
    0x22/0x23   battery current, mA, signed (positive = charging)
    0x24/0x25   battery percent

This driver exists so that an N002/N003 carrying a HAT (E) identifies itself
correctly on first boot rather than being misread as a HAT (D). Its probe is
deliberately strict: it requires the ID register AND a battery voltage and
percentage in physically plausible ranges. If a real HAT (E) is ever attached
and this probe fails, the node will report UNIDENTIFIED with a raw fingerprint
rather than inventing values — which is the correct failure mode.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ups.base import UPSDriver, UpsState  # noqa: E402

MCU_ADDR = 0x2D

REG_ID = 0x00
ID_VALUE = 0x0A
REG_ARM = 0x01
ARM_ENABLED = 0x55
REG_CHARGING = 0x02

REG_VBUS_V = 0x10
REG_BATT_V = 0x20
REG_BATT_I = 0x22
REG_BATT_PCT = 0x24

# Plausibility gates. A 4S pack tops out near 16.8 V; a 1S pack near 4.2 V.
BATT_MIN_MV = 2500
BATT_MAX_MV = 17500
BATT_LOW_V = 9.0   # only meaningful for multi-cell packs; see note in read()


def _le16(bus, addr, reg) -> int:
    """HAT (E) publishes low byte first, unlike the big-endian INA219."""
    lo = bus.read_byte_data(addr, reg)
    hi = bus.read_byte_data(addr, reg + 1)
    return (hi << 8) | lo


def _signed(v: int) -> int:
    return v - 0x10000 if v > 0x7FFF else v


class WaveshareHatE(UPSDriver):
    name = "waveshare_hat_e"
    model = "Waveshare UPS HAT (E)"
    addresses = (MCU_ADDR,)

    def probe(self, bus) -> bool:
        try:
            if bus.read_byte_data(MCU_ADDR, REG_ID) != ID_VALUE:
                return False
            # Reject a HAT (D), whose 0x02 is a fixed 0x0c rather than a
            # charging bitfield, and which pairs with an INA219 at 0x43.
            if bus.read_byte_data(MCU_ADDR, 0x02) == 0x0C:
                try:
                    bus.read_word_be(0x43, 0x00)
                    return False          # INA219 present => HAT (D)
                except OSError:
                    pass
            mv = _le16(bus, MCU_ADDR, REG_BATT_V)
            pct = _le16(bus, MCU_ADDR, REG_BATT_PCT)
            return BATT_MIN_MV <= mv <= BATT_MAX_MV and 0 <= pct <= 100
        except OSError:
            return False

    def read(self, bus) -> UpsState:
        st = UpsState(present=True, identified=True, model=self.model,
                      driver=self.name, confidence="positive")
        try:
            arm = bus.read_byte_data(MCU_ADDR, REG_ARM)
            st.arm_register = arm
            st.auto_reboot_armed = (arm == ARM_ENABLED)

            st.battery_voltage_v = round(_le16(bus, MCU_ADDR, REG_BATT_V) / 1000.0, 3)
            st.battery_current_ma = float(_signed(_le16(bus, MCU_ADDR, REG_BATT_I)))
            st.battery_percent = float(_le16(bus, MCU_ADDR, REG_BATT_PCT))
            st.vbus_voltage_v = round(_le16(bus, MCU_ADDR, REG_VBUS_V) / 1000.0, 3)

            ch = bus.read_byte_data(MCU_ADDR, REG_CHARGING)
            st.charging = bool(ch & 0x80)
            # VBUS present bit; when absent the pack is carrying the load.
            st.on_battery = not bool(ch & 0x20)
            st.fingerprint = {"mcu": hex(MCU_ADDR), "charging_reg": hex(ch)}
        except OSError as exc:
            st.error = f"read failed: {exc}"
        return st

    def supports_wake(self) -> bool:
        return True

    def arm_wake(self, bus) -> tuple:
        """Write 0x55 to reg 0x01. Vendor: 'power off and enable the incoming
        power function'. Only safe immediately before poweroff."""
        try:
            bus.write_byte_data(MCU_ADDR, REG_ARM, ARM_ENABLED)
            check = bus.read_byte_data(MCU_ADDR, REG_ARM)
            return check == ARM_ENABLED, f"arm register now 0x{check:02x}"
        except OSError as exc:
            return False, str(exc)
