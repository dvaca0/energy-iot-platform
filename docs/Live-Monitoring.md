# Live Monitoring — the technical view

The *Monitoreo en Vivo* screen, and the measurement inventory it is built on.

Its audience is a technician standing next to a panel. It answers, in the order
the questions get asked: is this node measuring, what is it measuring right now,
how has each quantity moved, do the phases agree, do the nodes agree, and is the
node underneath it healthy.

---

## The rule this page is built on

**Everything drawn is a stored measurement.** No quantity is derived to fill a
hole, and no absent value is rendered as zero. A magnitude the platform does not
hold for a node is labelled *no disponible* wherever it would otherwise appear —
in the summary card, in the chart, and in the table.

That rule is what the inventory below exists to make enforceable. It is not a
style preference: a dead sensor and a de-energised panel both read zero amps, and
a page that cannot tell them apart is worse than no page.

---

## Field inventory — Shelly → collector → backend → API → screen

The measuring instrument on N001 and N002 is a **Shelly Pro 3EM**, read over
Gen2 HTTP RPC (`GET /rpc/EM.GetStatus?id=0`) on the private `192.168.50.0/24`
segment. N003 is a different architecture entirely — see below.

### The device contract — verified, not assumed

Read-only capture from N001's production meter, 2026-08-18:
`SPEM-003CEBEU`, app `Pro3EM`, generation 2, firmware **1.4.2**, profile
`triphase`, CT 120 A. Every classification below is against that response, not
against vendor documentation.

| Shelly field | Meaning | Unit | Parsed | Sent | DB column | API key | UI | Class |
|---|---|---|---|---|---|---|---|---|
| `a_voltage` `b_` `c_` | Phase voltage | V | yes | yes | `phase_*_voltage` | `va` `vb` `vc` | Tensión por fase | **ALREADY STORED** |
| `a_current` `b_` `c_` | Phase current | A | yes | yes | `phase_*_current` | `ia` `ib` `ic` | Corriente por fase | **ALREADY STORED** |
| `total_current` | Sum of phases | A | yes | yes | `current` | `i` | Corriente total | **ALREADY STORED** |
| `total_act_power` | Total active power | W | yes | yes | `power_kw` | `kw` | Potencia activa total | **ALREADY STORED** |
| `a_act_power` `b_` `c_` | Active power per phase | W | yes | **now** | `phase_*_power_kw` | `pa` `pb` `pc` | Potencia activa por fase | **KEEP** |
| `a_aprt_power` `b_` `c_` | Apparent power per phase | VA | yes | **now** | `phase_*_apparent_kva` | `sa` `sb` `sc` | Potencia aparente por fase | **KEEP** |
| `total_aprt_power` | Total apparent power | VA | yes — see below | **now** | `apparent_kva` | `kva` | Potencia aparente total | **KEEP** |
| `a_pf` `b_` `c_` | Power factor per phase | — | yes | **now** | `phase_*_power_factor` | `pfa` `pfb` `pfc` | FP por fase | **KEEP** |
| `a_freq` `b_` `c_` | Frequency per phase | Hz | yes | **now** | `phase_*_frequency_hz` | `fa` `fb` `fc` | Frecuencia por fase | **KEEP** |
| `n_current` | Neutral current | A | yes | **now** | `neutral_current` | `nc` | Corriente de neutro | **KEEP** — null here |
| `a_total_act_energy` `b_` `c_` | Imported energy per phase | Wh | no | **now** | `phase_*_energy_imported_kwh` | `imp_a/b/c` | Energía importada | **KEEP** |
| `a_total_act_ret_energy` `b_` `c_` | Returned energy per phase | Wh | no | **now** | `phase_*_energy_returned_kwh` | `ret_a/b/c` | Energía devuelta | **KEEP** |
| `total_act` | Total imported energy | Wh | no | **now** | `meter_energy_kwh` | `imp_t` | Energía importada | **KEEP** |
| `total_act_ret` | Total returned energy | Wh | no | **now** | `meter_energy_returned_kwh` | `ret_t` | Energía devuelta | **KEEP** |
| `temperature:0.tC` | **Meter** temperature | °C | — | heartbeat | `monitor_node_heartbeats.meter_temperature_c` | `health.meter_temperature_c` | Estado del nodo | **KEEP** — health, not electrical |
| — | Reactive power | kvar | n/a | n/a | **never** | computed in the page | Potencia reactiva calculada | **DERIVE** |
| `user_calibrated_phase` | Calibration state | — | — | no | no | no | — | **IGNORE** |
| `id` | RPC channel index | — | — | no | no | no | — | **IGNORE** |

"Parsed" means the collector already reads the key out of the response.
"Sent"/"now" means the payload contract carries it as of M15 — the on-node
collector change that populates it is a separate step, so these columns are NULL
until it lands, and the interface says *no disponible* meanwhile.

**`total_aprt_power` was already being parsed and thrown away.** The proof is in
the stored data: `energy_readings.power_factor` on N001 carries 13–16 decimal
places (`0.9500164388225734`). The meter publishes `a_pf`/`b_pf`/`c_pf` at two
decimals, so no mean of them can produce that — it is a division,
`total_act_power / total_aprt_power`. The collector read the apparent power, used
it once to compute a ratio, and discarded it.

**Two aggregates keep their historical meaning and are not redefined**
(CONTRIBUTING.md forbids it): `voltage` is the *mean* of the energised phases
(124.7 + 126.1 + 126.0 → 125.600000), and `current` is the *sum*
(37.470 + 35.133 + 33.257 = 105.860, matching `total_current` exactly). The
screen labels them accordingly.

**Reactive power is derived, never stored.** The firmware exposes no Q. The page
computes `Q = √(max(S² − P², 0))` from the two measured inputs, draws it under a
**CALCULADO** badge, and returns null unless both inputs are present at that
instant. The `max(…, 0)` matters: at a near-unity power factor, independently
rounded P and S can put `S² − P²` just below zero.

**Nothing absent from the capture was added.** An earlier draft plumbed
`errors` / `a_errors` meter-fault flags through the schema. This firmware does
not return them, so no column exists for them.

### Why the per-phase power factor was worth a migration

The capture is its own argument:

```
a_pf 0.99    b_pf 0.99    c_pf 0.87    aggregate P/S = 0.9505
```

Phase C is running more than a tenth below its siblings, and the single stored
aggregate — 0.95, comfortably above the 0.85 warning threshold — cannot show it.
The prototype CSV on N003 recorded the same pattern in May. Until M15 the
platform had no column that could hold the finding.

### Node health — stored, and shown

From `monitor_node_heartbeats`, written every ~45 s by the canonical
authenticated heartbeat. All of these appear in the card's status strip.

| Column | Shown as |
|---|---|
| `collector_status`, `collector_restarts` | Colector |
| `buffered_readings`, `pending_sync` | Buffer pendiente |
| `received_at` | Heartbeat (age) |
| `cpu_percent`, `cpu_temperature_c`, `memory_percent`, `disk_percent` | CPU · Temperatura · Disco |
| `clock_drift_seconds` | Desfase de reloj |
| `undervoltage`, `throttled`, `filesystem_readonly` | Sticky chips |
| `software_version` | Software |
| `ads_ok` | Condition *ADC sin responder* when explicitly false |
| `local_alerts` | Decoded, available for display |
| `nodes.last_sync` | RPi status |
| newest reading timestamp | Medidor status, reading age |

`ads_ok`, `shelly_reachable`, `internet_ok` and `latency_ms` are **null on the
Pi 5 nodes** — their collector does not probe them. Null renders as `—`, never
as a failure.

---

## Honest degradation across hardware

`nodes.hardware_kind` is `shelly` for N001/N002 and `ads1256` for N003, and the
two are not comparable: N003 posts to `/api/v1/measurements/batch`, whose
server-side phase averaging counts a missing phase as zero volts, while the
Shelly path uses the node's own floor-excluding average.

The page does **not** branch on `hardware_kind`. Availability is computed from
each node's own newest reading — which columns are actually non-null — so a node
advertises exactly what it reported, and a meter that stops publishing a field
stops advertising it within one sample. `hardware_kind` is displayed as context,
never used as a promise.

---

## Ranges, resolution and aggregation

The nodes sample at 15 s (`POLL_INTERVAL`) and sync every 60 s, so the backend
receives readings in bursts of about four. The live edge therefore advances in
steps, not smoothly — a 40 s gap with no new point is normal, not a fault.

| Range | Bucket | Points per node | Refetch | Aggregation |
|---|---|---|---|---|
| 5 min | none | ~20 | 3 s, incremental | stored samples |
| 15 min | none | ~60 | 3 s, incremental | stored samples |
| 30 min | none | ~120 | 3 s, incremental | stored samples |
| 1 h | none | ~240 | 3 s, incremental | stored samples |
| 6 h | 60 s | ~360 | 30 s | mean; min/max on current and power; energy summed |
| 24 h | 300 s | ~290 | 75 s | as above |
| 7 d | 900 s | ~670 | 225 s | as above |
| Despliegue | adaptive | ~500–1000 | up to 300 s | as above |

**Refetch is paced to the bucket, not to the clock.** A point averaging five
minutes cannot change meaningfully in three seconds, so a bucketed window
refreshes at a quarter of its bucket width (floor 30 s, ceiling 300 s). The
backend runs a single worker and the widest window costs ~1.9 s; polling that
every 30 s would spend 6 % of the whole backend redrawing an identical line.

**The deployment range is scoped by deployment, not by node and dates.** It
takes a `deployment_id`, filters on `energy_readings.deployment_id`, and bounds
the window with that campaign's own `activated_at` → `closed_at` (or now, while
open). `node_ids` is ignored: the campaign decides which nodes appear, and they
are discovered from the readings rather than assumed from the deployment row.
The bucket is the smallest of 60 / 300 / 900 / 1800 / 3600 s that keeps the
window under ~900 points.

Scoping by node and date instead would pull in readings the *next* campaign owns
the moment a node is redeployed inside the window, and an earlier version that
took the union of every selected node's campaign produced a 65-day axis on which
each node occupied a different sixth. Cross-node comparison belongs on the
chronological ranges, which share one axis by construction.

**A campaign can own readings its own dates do not cover**, and the response says
so rather than rendering an unexplained blank chart. Every deployment carries
`readings_in_window` and `readings_outside_window`. On this platform today:

| Deployment | In window | Outside |
|---|---|---|
| #7 N001 Edificio Principal 2.0 | 25,665 | 0 |
| #6 N001 Edificio Principal Prueba | 11,993 | 10,450 |
| #4 N001 Edificio de prueba | 118,620 | 0 |
| #5 N003 Edificio de prueba | **0** | 4,499 |

Deployment 5 declares 2026-06-14 → 06-21 while every reading carrying its id is
stamped 2026-07-26 → 08-06. Its chart is legitimately empty and the page
explains why. Nothing is corrected on read: attribution is written once at ingest
from each measurement's own `captured_at` (ADR-0004), and widening a window to
make a chart look better is exactly the silent retroactive attribution the
platform forbids. The fix is to correct the deployment's dates, not the view.

Rules that make the aggregation safe to read:

- **Bucketing happens in SQL.** `AVG`, `MIN` and `MAX` skip NULLs natively,
  which is exactly the required semantics. Folding 33 fields over 36,000 Python
  tuples cost 1.2 s per seven-day request before this changed.
- **Nulls are skipped per field, never averaged as zero.** A field nobody
  reported inside a bucket is *omitted from the payload* — absence and null mean
  the same thing to the client, and 22 of the 33 series are empty on every
  reading stored before M15, so serialising those nulls would have tripled a
  one-hour payload to carry nothing.
- **Extremes survive on current and power** — total and per-phase — because a
  spike is the finding. Each bucketed point carries `i_min`/`i_max`,
  `ia_min`… and `kw_min`/`kw_max`, `pa_min`… alongside the mean.
- **Every point says how many samples it covers** (`n`), and the tooltip, the
  table and the section header all say when values are means.
- **Energy is never recomputed here.** `energy_aggregate.bucketed_energy`
  resolves the measurement era (ADR-0007). Cross-checked against
  `hourly_energy` over seven days: 1373.3023 kWh both ways.

The SQL and Python aggregations were pinned against each other on six hours of
real data: `n`, `min` and `max` agree exactly, and the means differ by at most
one unit in the last stored decimal (0.01 V, 0.001 A) — a floating-point
rounding tie, an order of magnitude below what the instrument publishes.

## Refresh strategy

| Resource | Cadence | Payload |
|---|---|---|
| `/api/metrics/live/snapshot` | 3 s | ~5 KB |
| `/api/metrics/live/history`, un-bucketed ranges | 3 s, `?since=` | ~0.3 KB per tick |
| `/api/metrics/live/history`, 6 h and 24 h | 30 s, full window | 70–90 KB |

`?since=` is honoured only for un-bucketed ranges. A bucket's mean changes while
the bucket fills, so an incremental slice of one would hand the client
half-finished averages it could never correct; the backend reports which it did
in `incremental`.

Three properties keep a long-lived tab from degrading: one request at a time per
resource (a tick arriving while the previous fetch is open is dropped), a hidden
tab polls nothing and refetches whole on return, and the held window is trimmed
to the range on every merge so memory is bounded by the range rather than by
uptime.

**Pause freezes the view only.** It stops the polling loop in the browser. The
collector, the edge buffer and the node's acquisition are untouched — this page
is a reader.

---

## Thresholds

The page holds **no thresholds of its own**. `/api/metrics/live/snapshot`
publishes a `limits` block read from `app.monitoring.config`, the same source the
alerting rules resolve against, so a badge here and a Telegram alert cannot
disagree.

| Condition | Limit |
|---|---|
| Tensión fuera de rango | ±13 % warning, ±20 % critical of 127 V nominal |
| Fase ausente | < 40 V while another phase is energised |
| Frecuencia fuera de rango | ±0.5 Hz warning, ±1.0 Hz critical of 60 Hz |
| Factor de potencia bajo | < 0.85 warning, < 0.70 critical |
| Corriente elevada | > 400 A warning, > 500 A critical |
| Desbalance de corriente | > 10 % warning, > 25 % critical |
| Desbalance de tensión | > 2 % warning, > 5 % critical |
| Lectura obsoleta | reading age > `nodeOfflineTimeout` (300 s) |
| Buffer pendiente | `pending_sync` > 0 |

Imbalance and power factor are **guarded by the noise floor**
(`imbalance_min_current_a`, 1.0 A). An idle meter reports ~1e-5 A, and the
percentage spread between two noise samples is arbitrarily large — computing it
unguarded produced a permanent false CRITICAL in the alerting system, and the
same guard is applied here.

These are hints for a technician. **Nothing is raised, escalated or notified
from the browser** — this page is not a second alerting surface.

---

## Files

| Layer | Path |
|---|---|
| Service | `backend/app/services/live_view.py` |
| Routes | `backend/app/routers/metrics.py` (`/live/snapshot`, `/live/history`) |
| Page | `frontend-src/src/pages/PageLiveMonitor.tsx` |
| Components | `frontend-src/src/components/livemonitor/` |
| Render checks | `frontend-src/tests/render-live-monitor.tsx` |

Related: [API.md](API.md), [Collector.md](Collector.md),
[Monitoring.md](Monitoring.md), [Frontend.md](Frontend.md).
