# The collector contract

How any hardware becomes a measurement this platform understands.

The rule this document exists to enforce: **the backend contains no
hardware-specific logic, now or ever.** A collector translates its device into
the canonical model; the platform stores and interprets that model and nothing
else. Adding a meter type is a collector change and, at most, one row in
`measurement_eras`. It is never a change to the analytics layer.

## The payload

`POST /api/readings`

```json
{
  "node_id": "N001",
  "timestamp": "2026-07-31T20:15:00Z",

  "power_kw": 12.4,
  "interval_energy_kwh": 0.0517,
  "interval_seconds": 15.0,
  "energy_source": "measured",

  "meter_energy_kwh": 26411.882,
  "voltage": 127.3,
  "current": 97.4,
  "power_factor": 0.95,
  "frequency_hz": 60.0
}
```

### Mandatory

| Field | Meaning — fixed forever |
|---|---|
| `node_id` | the node's code, as registered |
| `timestamp` | UTC instant the sample was taken (not when it was sent) |
| `power_kw` | instantaneous active power at that instant |
| `interval_energy_kwh` | energy attributable to the interval this sample represents |
| `interval_seconds` | length of that interval |
| `energy_source` | how `interval_energy_kwh` was obtained |

### Optional

| Field | Meaning |
|---|---|
| `meter_energy_kwh` | the device's own cumulative register — **reconciliation only** |
| `voltage`, `current`, `power_factor`, `frequency_hz` | electrical quality |
| `phase_*_voltage`, `phase_*_current` | three-phase detail |

`energy_kwh` is still accepted so existing collectors keep working unchanged.
**New collectors must not send it.** It is legacy and its meaning is resolved
per era (ADR-0007).

## `energy_source` — the three legal values

| Value | Use when |
|---|---|
| `measured` | the device reported interval energy directly |
| `counter_delta` | the collector differenced a cumulative register |
| `power_integral` | the collector integrated power over the interval |

This is not decoration. `interval_energy_kwh: 0.0517` is unfalsifiable without
it; with it, a reader knows whether the number came from a meter or from
arithmetic. The absence of exactly this information is what caused the incident
that produced this contract.

## Mapping each hardware family

### Shelly Pro 3EM (and any device with a lifetime register)

The device exposes `total_act_energy`, a monotonic lifetime counter. The
collector keeps the previous sample and differences it:

```python
delta = total_act_energy - previous_total_act_energy
if 0 < delta <= MAX_REASONABLE_DELTA_KWH:
    interval_energy_kwh = delta
    energy_source = "counter_delta"
else:
    # counter reset, first sample after restart, or a gap — integrate instead
    interval_energy_kwh = power_kw * interval_seconds / 3600
    energy_source = "power_integral"

meter_energy_kwh = total_act_energy   # always send it: it enables reconciliation
```

The reset detection lives in the collector, which is the only component that
knows the device restarted. The backend never sees a counter.

### ADS1256 (raw ADC, no energy register)

The board reports voltage and current samples. It has no notion of energy, so
the collector integrates:

```python
power_kw = v_rms * i_rms * power_factor / 1000
interval_energy_kwh = power_kw * interval_seconds / 3600
energy_source = "power_integral"
# meter_energy_kwh omitted — this device has no register
```

`interval_seconds` must be the true accumulation window, not the nominal one.
If the sampler ran 14.2 s because of scheduling jitter, send 14.2.

### ESP32 with a pulse-output meter

Each pulse is a fixed energy quantum (`Wh_per_pulse` from the meter's
nameplate). Counting pulses over the interval is a direct measurement:

```python
interval_energy_kwh = pulses_this_interval * wh_per_pulse / 1000
energy_source = "measured"
```

### Modbus meters (Schneider, Siemens, generic RTU)

Most expose both an instantaneous power register and a cumulative energy
register. Prefer the register the vendor documents as *interval* or *demand*
energy if one exists (`measured`); otherwise difference the cumulative register
exactly as for the Shelly (`counter_delta`), and always send it as
`meter_energy_kwh` as well.

## Rules a collector must obey

1. **`interval_energy_kwh` is energy for one interval, never a running total.**
   It is summed, never differenced. Sending a cumulative value here corrupts
   every aggregate silently.

2. **`interval_seconds` is the real elapsed interval.** It is what makes energy
   interpretable and gaps detectable: 0.05 kWh is 12 kW over 15 s or 0.6 kW over
   5 minutes, and only this field distinguishes them.

3. **Timestamps are UTC and are the sample instant.** Buffered readings keep
   their original timestamp; do not restamp on upload.

4. **A gap is a gap.** After an outage, do not emit one huge catch-up sample.
   Either replay the buffered samples with their own timestamps, or emit nothing
   for the gap. `interval_seconds` then makes the gap visible.

5. **Never send a value the device did not produce.** Omit the field instead.
   `null` means "not measured", which is information; a zero is a measurement.

## What the backend does with it

One place, `app/services/energy_aggregate.py`, resolves every reading to
interval energy and hands it to every consumer — dashboard, cost, AI, mining,
reports, exports. It is the only code permitted to read
`energy_readings.energy_kwh`.

A collector emitting the canonical fields needs one row in `measurement_eras`
declaring semantics `canonical` from its cutover instant, at which point
`energy_kwh` stops being consulted for that node. That row is the entire
integration on the backend side.

## Adding hardware that fits none of the above

If a device reports a physical quantity the canonical model cannot express,
**do not overload an existing field.** Add a column, add an `energy_semantics`
row describing how to read it, and open an era. That is the mechanism the model
is built on, and it costs one migration. Overloading a field is what cost this
platform a 400x KPI error.
