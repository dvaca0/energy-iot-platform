"""UPS driver base class and state model.

DESIGN RULE — NEVER MISIDENTIFY HARDWARE
    N001 is the only node whose UPS has been physically characterised. N002
    and N003 are assumed to have *a* UPS HAT, not necessarily the same model.
    A driver may only claim hardware when its fingerprint matches exactly.
    Unknown hardware is reported as present-but-unidentified, with its raw
    I2C fingerprint exposed so the model can be added — never guessed at.

    A wrong battery reading is worse than no battery reading: it would let the
    platform believe a node has power headroom it does not have.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Optional


@dataclass
class UpsState:
    """One observation of UPS state.

    `present` means "some UPS hardware answered". `identified` means "a driver
    positively matched it". Battery values are populated ONLY when identified.
    """

    present: bool = False
    identified: bool = False
    model: Optional[str] = None
    driver: Optional[str] = None
    confidence: str = "absent"
    battery_voltage_v: Optional[float] = None
    battery_current_ma: Optional[float] = None
    battery_percent: Optional[float] = None
    battery_low: Optional[bool] = None
    on_battery: Optional[bool] = None
    charging: Optional[bool] = None
    vbus_voltage_v: Optional[float] = None
    auto_reboot_armed: Optional[bool] = None
    arm_register: Optional[int] = None
    fingerprint: dict = field(default_factory=dict)
    error: Optional[str] = None

    def as_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        if not self.present:
            return f"no UPS detected ({self.confidence})"
        if not self.identified:
            return (f"UPS present but UNIDENTIFIED at "
                    f"{self.fingerprint.get('addresses')} — model not in registry")
        return (f"{self.model} batt={self.battery_voltage_v}V "
                f"{self.battery_percent}% {self.battery_current_ma}mA "
                f"armed={self.auto_reboot_armed}")


class UPSDriver:
    """Base class. Subclass per supported HAT model.

    Contract:
      name         short stable driver id, used in config UPS_DRIVER_ORDER
      model        human-readable hardware name
      probe(bus)   -> bool. MUST be read-only and MUST be strict.
      read(bus)    -> UpsState. Only called after probe() returned True.
      arm_wake(bus)-> (ok, detail). Optional; default is unsupported.
    """

    name = "base"
    model = "unknown"
    #: addresses this driver expects to find; used for reporting only
    addresses: tuple = ()

    def probe(self, bus) -> bool:
        raise NotImplementedError

    def read(self, bus) -> UpsState:
        raise NotImplementedError

    def arm_wake(self, bus) -> tuple:
        """Arm a 'boot when power returns' feature, if the hardware has one."""
        return False, f"{self.model} exposes no wake-arm register"

    def supports_wake(self) -> bool:
        return False
