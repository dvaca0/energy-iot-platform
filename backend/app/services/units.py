"""Unit conversion at the ingestion boundary, in one place.

The Shelly Pro 3EM reports power in **watts**, apparent power in **volt-amperes**
and its energy registers in **watt-hours**. The platform's stored vocabulary is
kW, kVA and kWh — set by ``energy_readings.power_kw``, which predates all of
this and cannot be redefined (CONTRIBUTING.md).

Something has to divide by a thousand. The danger is that *two* things do.

The rule this module exists to enforce
--------------------------------------

**Conversion happens exactly once, at the boundary where a payload enters the
platform, and only for payloads whose fields are documented as device units.**

The two ingest routes are deliberately asymmetric, and it is worth being blunt
about why, because the asymmetry is what makes double conversion possible:

``/api/v1/measurements/batch``
    Fields are named for the *device*: ``active_power_a``, ``total_apparent_power``.
    They arrive in **watts and volt-amperes**. This module converts them.

``/api/readings``
    Fields are named for the *platform*: ``power_kw``, ``phase_a_apparent_kva``.
    They arrive **already converted**. This module must not be applied to them.

That is why every field on ``ReadingCreate`` carries its unit in its name. A
field called ``phase_a_power_kw`` cannot be mistaken for watts by a reader or by
a future maintainer, and a field called ``active_power_a`` cannot be mistaken
for kilowatts. The naming is the safety mechanism; these functions are just the
arithmetic.

``None`` propagates through every function untouched. A quantity the meter did
not report must stay unreported — converting it to ``0.0`` would turn "no
neutral CT installed" into "zero amps flowing", which is a measurement claim the
platform has no right to make.
"""

from __future__ import annotations

#: Watts per kilowatt, volt-amperes per kilovolt-ampere, watt-hours per
#: kilowatt-hour. One constant, so the three conversions cannot drift apart.
PER_KILO = 1000.0


def w_to_kw(watts: float | None) -> float | None:
    """Watts to kilowatts. ``None`` in, ``None`` out."""
    return None if watts is None else watts / PER_KILO


def va_to_kva(volt_amperes: float | None) -> float | None:
    """Volt-amperes to kilovolt-amperes. ``None`` in, ``None`` out."""
    return None if volt_amperes is None else volt_amperes / PER_KILO


def wh_to_kwh(watt_hours: float | None) -> float | None:
    """Watt-hours to kilowatt-hours. ``None`` in, ``None`` out.

    Used for the meter's cumulative registers. They are large — N001's
    ``total_act`` read 5,310,919.91 Wh in the 2026-08-18 capture — so the result
    is deliberately not rounded here: rounding a lifetime register at ingest
    would make it disagree with the utility bill it exists to reconcile against.
    """
    return None if watt_hours is None else watt_hours / PER_KILO


def passthrough(value: float | None) -> float | None:
    """Amperes, volts, hertz and power factor: no conversion, ever.

    Exists so a mapping table can name a converter for *every* field. A field
    with no entry is a field somebody forgot to think about; a field mapped to
    ``passthrough`` is a field somebody decided needs nothing.
    """
    return value
