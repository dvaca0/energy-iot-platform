# ADR-0007 — The canonical measurement model

- **Status:** accepted
- **Date:** 2026-07-31
- **Supersedes:** the implicit contract that `energy_kwh` is a cumulative meter counter

## Context

`energy_kwh` has had two meanings over the platform's life:

| Era | Range | Meaning | Evidence |
|---|---|---|---|
| Counter | → 2026-07-03 15:32:39 | cumulative lifetime register | monotonic 17,283 → 26,259 kWh, 0.0 % negative deltas |
| Interval | 2026-07-25 00:01:01 → | energy in this sample's interval | `= power_kw × 15.000/3600` to zero relative error, 51.6 % negative deltas |

Every consumer computes `current − previous`, which is correct for the first and
meaningless for the second. Dashboard KPIs are ~400× low.

The root cause is not the arithmetic. It is that **one column carried two
meanings**, and nothing in the schema recorded which.

## Decision

### The canonical quantities

| Field | Meaning — fixed forever | Who provides it | Required |
|---|---|---|---|
| `power_kw` | Instantaneous active power at the sample instant | measured by every meter | **yes** |
| `interval_energy_kwh` | Energy attributable to the interval this sample represents | measured, or derived by the collector | **yes** |
| `interval_seconds` | Length of that interval | collector knows its own cadence | **yes** |
| `meter_energy_kwh` | The device's own cumulative register | devices that have one | no |
| `energy_source` | How `interval_energy_kwh` was obtained | collector | **yes** |

**`interval_energy_kwh` is the analytics quantity.** Everything — cost, KPIs,
AI, mining, reports, forecasting — consumes that and nothing else.

**`meter_energy_kwh` is for reconciliation only.** It exists so a campaign can
be checked against the utility bill. No analytic ever differences it.

### Why interval energy, not cumulative

Cumulative is what the old code assumed. It is the weaker contract:

- it needs reset detection (hence the 100 kWh guard),
- it needs ordered adjacency (hence `LAG`, hence the midnight-boundary bug),
- the first reading of any window contributes nothing,
- a data gap produces one enormous false delta.

Interval energy has none of those properties. It is **additive**: `SUM()` is the
answer. It is immune to counter resets and to gaps. And it matches the
attribution model from ADR-0004, where each reading is independently attributed
to a deployment — a per-reading quantity belongs with per-reading attribution.

### `energy_source` — provenance is part of the measurement

Three legal values:

| Value | Meaning |
|---|---|
| `measured` | the device reported interval energy directly |
| `counter_delta` | the collector differenced a cumulative register |
| `power_integral` | the collector integrated power over the interval |

Without this, `interval_energy_kwh = 0.0488` is unfalsifiable. With it, a reader
knows whether that number came from a meter or from arithmetic — which is
exactly the information whose absence caused this incident.

### Two additions beyond the brief

The task suggested `instantaneous_power_kw`, `interval_energy_kwh`,
`lifetime_energy_kwh`. Those three are adopted (under existing/clearer names).
Two more are required and are not cosmetic:

- **`interval_seconds`** — interval energy without its interval is
  uninterpretable, and gaps become undetectable. 0.05 kWh means 12 kW over 15 s
  or 0.6 kW over 5 min.
- **`energy_source`** — see above.

### Historical eras: distinguishable without touching a row

Historical readings are immutable, so their era cannot be stamped onto them.
It is recorded **beside** them instead:

```
measurement_eras(node_id, starts_at, ends_at, energy_semantics, ...)
```

Three rows describe the platform's entire history. No reading is read, written
or migrated. `energy_semantics` is itself a lookup table, following the pattern
established for deployment lifecycle and measurement context.

| Semantics | How the canonical service reads legacy `energy_kwh` |
|---|---|
| `cumulative_counter` | difference consecutive values, with the existing guards |
| `interval_energy` | take the value as-is |
| `canonical` | ignore `energy_kwh`; read `interval_energy_kwh` |
| `absent` | no energy available (N003 — batch endpoint stores NULL) |

An era is closed by setting `ends_at`; a new one opens. When the collector is
updated to emit canonical fields, that is one INSERT — no code change.

### One interpretation point

`app/services/energy_aggregate.py` is the **only** code permitted to read
`energy_readings.energy_kwh`. It resolves era → semantics → interval energy and
hands back hourly buckets. Every other consumer already goes through it after
the M6/performance work.

## Consequences

- Dashboard KPIs become correct immediately: today's energy goes from 0.37 kWh
  (sum of noise) to ~148 kWh (sum of interval energy), matching `power × time`.
- No historical row is modified. `ALTER TABLE ADD COLUMN` in SQLite is a
  metadata-only operation; existing rows return NULL without being rewritten,
  which INV-02, INV-15 and INV-16 verify.
- Analytics reproducibility is preserved: the counter era is still read as a
  counter, so June's figures do not change.
- New hardware integrates by populating four columns. The backend gains no
  hardware-specific branch, now or ever.
- `energy_kwh` becomes legacy: never written again, read only through the era
  table, retained because it is historical evidence.

## Alternatives rejected

**Reinterpret history in place.** Forbidden, and wrong: it would destroy the
counter era's meaning and make June's published figures unreproducible.

**A single `energy_kwh` with a `semantics` column on each row.** Requires
writing to 123,000 existing rows. The era table achieves the same with three.

**Compensate in the backend by detecting the shape at query time** (e.g. "if
deltas are mostly negative, treat as interval"). Heuristic, silent, and would
flip behaviour as data changed. Provenance must be declared, not guessed.

**Make the collector return to a cumulative counter.** Restores the old contract
but keeps its weaknesses, and leaves the platform with no defined model for the
next hardware. It also cannot be done from here — the node is unreachable.
