"""Waveshare UPS HAT (D) driver.

VERIFIED ON N001 (2026-08-03) against vendor documentation:
    "0x43 is the address of INA219 and 0x2D is the i2c address of the MCU chip.
     The 0x00,0x01,0x02 registers are 0x0a, 0x0b, 0x0c respectively."
    21700 Li-ion cell, "4.2V after fully charged".

    N001 reads: 0x2d -> 0x0a,0x0b,0x0c · 0x43 config 0x399F · cell 4.192 V.

Current is derived from the raw INA219 shunt register so this driver NEVER
writes to the chip during a read:
    shunt LSB = 10 uV over a 0.01 ohm shunt  =>  1 mA per count
(0.01 ohm confirmed by the vendor's own INA219.py, set_calibration_16V_5A.)

DISCRIMINATOR vs HAT (E): this driver requires BOTH the 0x0a/0x0b/0x0c MCU
signature AND a responding INA219 at 0x43. HAT (E) reports battery state from
its own MCU registers (0x20+) and does not present an INA219 here. Requiring
the INA219 keeps the two models from being confused.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from i2cbus import signed16  # noqa: E402
from ups.base import UPSDriver, UpsState  # noqa: E402

MCU_ADDR = 0x2D
INA_ADDR = 0x43

MCU_ID_REGS = {0x00: 0x0A, 0x01: 0x0B, 0x02: 0x0C}

REG_ARM = 0x01
ARM_DEFAULT = 0x0B
ARM_ENABLED = 0x55

INA_REG_CONFIG = 0x00
INA_REG_SHUNT = 0x01
INA_REG_BUS = 0x02

SHUNT_OHMS = 0.01
# Vendor percentage curve: p = (V - 3.0) / 1.2 * 100
BATT_EMPTY_V = 3.0
BATT_SPAN_V = 1.2


class WaveshareHatD(UPSDriver):
    name = "waveshare_hat_d"
    model = "Waveshare UPS HAT (D)"
    addresses = (MCU_ADDR, INA_ADDR)

    def probe(self, bus) -> bool:
        try:
            for reg, want in MCU_ID_REGS.items():
                if bus.read_byte_data(MCU_ADDR, reg) != want:
                    return False
        except OSError:
            return False
        try:
            # INA219 must answer. Its config register is readable on any
            # INA219; we do not require the POR value because software may
            # legitimately have reconfigured it.
            bus.read_word_be(INA_ADDR, INA_REG_CONFIG)
        except OSError:
            return False
        return True

    def read(self, bus) -> UpsState:
        st = UpsState(present=True, identified=True, model=self.model,
                      driver=self.name, confidence="positive")
        try:
            arm = bus.read_byte_data(MCU_ADDR, REG_ARM)
            st.arm_register = arm
            st.auto_reboot_armed = (arm == ARM_ENABLED)

            bus_raw = bus.read_word_be(INA_ADDR, INA_REG_BUS)
            shunt_raw = signed16(bus.read_word_be(INA_ADDR, INA_REG_SHUNT))

            voltage = (bus_raw >> 3) * 0.004
            current_ma = shunt_raw * (0.00001 / SHUNT_OHMS) * 1000.0
            pct = max(0.0, min(100.0,
                               (voltage - BATT_EMPTY_V) / BATT_SPAN_V * 100.0))

            st.battery_voltage_v = round(voltage, 3)
            st.battery_current_ma = round(current_ma, 1)
            st.battery_percent = round(pct, 1)
            st.fingerprint = {"mcu": hex(MCU_ADDR), "ina219": hex(INA_ADDR),
                              "ids": "0x0a,0x0b,0x0c"}
        except OSError as exc:
            st.error = f"read failed: {exc}"
        return st

    def supports_wake(self) -> bool:
        return True

    def arm_wake(self, bus) -> tuple:
        """Write 0x55 to reg 0x01 — 'Boot When Power Applied'.

        DANGER: the vendor requires the Pi to power off IMMEDIATELY after this
        write. Only ever call this as the final step of a shutdown sequence.

        RECOVERS: mains outage -> battery flat -> shutdown -> mains returns ->
                  MCU pulls GPIO3 low -> node boots.
        DOES NOT   the 2026-08-01 failure. That had no power transition for the
        RECOVER:   MCU to detect; the rail stayed up for all 43h37m.
        """
        try:
            bus.write_byte_data(MCU_ADDR, REG_ARM, ARM_ENABLED)
            check = bus.read_byte_data(MCU_ADDR, REG_ARM)
            return check == ARM_ENABLED, f"arm register now 0x{check:02x}"
        except OSError as exc:
            return False, str(exc)
