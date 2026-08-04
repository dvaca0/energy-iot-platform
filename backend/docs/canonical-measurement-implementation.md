# Canonical measurement model — implementation report

**Date:** 2026-07-31 · **Migration:** 012 · **ADR:** 0007 · **Status:** deployed and verified

The platform now has one definition of energy. Every KPI, forecast, cluster and
export derives from it. No historical reading was modified.

---

## 1. Architecture decisions

### The canonical quantities

| Field | Meaning — fixed forever | Required |
|---|---|---|
| `power_kw` | instantaneous active power at the sample instant | yes |
| `interval_energy_kwh` | energy attributable to this sample's interval | yes |
| `interval_seconds` | length of that interval | yes |
| `meter_energy_kwh` | the device's own cumulative register | no |
| `energy_source` | `measured` / `counter_delta` / `power_integral` | yes |

`interval_energy_kwh` is the analytics quantity. `meter_energy_kwh` exists for
reconciliation against a utility bill and is never differenced by an analytic.

### Why interval energy rather than cumulative

Cumulative was the old implicit contract and is the weaker one: it needs reset
detection, needs ordered adjacency (which produced the midnight-boundary bug),
drops the first reading of every window, and turns a data gap into one enormous
false delta. Interval energy is **additive** — `SUM()` is the answer — and it is
immune to resets and gaps. It also matches ADR-0004, where each reading is
attributed independently: a per-reading quantity belongs with per-reading
attribution.

### Historical eras, not historical edits

Historical readings are immutable, so an era cannot be stamped onto them. It is
recorded *beside* them, in `measurement_eras`. Four rows describe the platform's
entire history:

| Node | Range | Semantics |
|---|---|---|
| N001 | → 2026-07-03 15:32:39 | `cumulative_counter` |
| N001 | 2026-07-25 00:01:01 → | `interval_energy` |
| N002 | all | `absent` |
| N003 | all | `absent` |

Closing an era is one `UPDATE ... SET ends_at`; opening one is one `INSERT`.
When a collector starts emitting canonical fields, that is the entire backend
integration — no code change.

### One interpretation point

`app/services/energy_aggregate.py` is the only code permitted to read
`energy_readings.energy_kwh`. It exposes three entry points over one shared SQL
CTE:

- `hourly_energy()` — hourly buckets with tariff applied (the fast path)
- `reading_energy()` — per-reading interval energy, for row-level consumers
- `energy_by_reading_id()` — `{id: kWh}`, for callers holding ORM rows

### Discovered mid-implementation, and corrected

The audit that the task required turned up something the earlier work had
asserted but not verified: **seven consumers were still interpreting
`energy_kwh` themselves.** Reports, the data explorer, mining, the ML feature
builder, two `metrics` endpoints and the dashboard's night-consumption estimator
each re-derived energy with their own rule — some with the 100 kWh reset guard,
`ml_engine` without it, `metrics` with a last-minus-first-of-day rule. The
"single canonical service" was true of the headline KPIs and false everywhere
else. All seven now go through the canonical service; proofs 5–7 below verify it
numerically rather than by inspection.

---

## 2. Schema changes

Migration `012_canonical_measurement_model`, applied 2026-07-31 19:11:13.

**New table `energy_semantics`** — the vocabulary, as data:

| code | reads_legacy | requires_delta |
|---|---|---|
| `cumulative_counter` | yes | yes |
| `interval_energy` | yes | no |
| `canonical` | no | no |
| `absent` | no | no |

**New table `measurement_eras`** — `(node_id, starts_at, ends_at,
energy_semantics, nominal_interval_seconds, discovered_by, notes)`, plus index
`idx_measurement_eras_node`.

**Four nullable columns on `energy_readings`**: `interval_energy_kwh`,
`interval_seconds`, `meter_energy_kwh`, `energy_source`.

`ALTER TABLE ADD COLUMN` in SQLite is metadata-only. Existing rows return NULL
without being rewritten — which is why proof 8 can show a byte-identical hash of
all 247,633 pre-existing rows.

---

## 3. Collector changes

None required, and none made. Existing collectors keep posting `energy_kwh` and
keep working: their era declares how to read it.

`POST /api/readings` now also accepts `interval_energy_kwh`, `interval_seconds`,
`meter_energy_kwh` and `energy_source`, all persisted. The full mapping for
Shelly, ADS1256, ESP32 and Modbus hardware is in
[`collector-contract.md`](collector-contract.md).

Cutover for a node, when its collector is updated: insert an era with semantics
`canonical` from the cutover instant. `energy_kwh` is then never consulted for
that node again.

---

## 4. Backend changes

| File | Change |
|---|---|
| `services/energy_aggregate.py` | era-aware resolution; shared CTE; added `reading_energy()`, `energy_by_reading_id()` |
| `routers/readings.py` | accepts and persists the four canonical fields |
| `db/models.py` | canonical columns declared; `energy_kwh` marked LEGACY |
| `routers/reports.py` | 4 sites → canonical service; exports now label the register `meter_energy_kwh` |
| `routers/mining.py` | energy → canonical service; power/PF statistics → one grouped SQL aggregate |
| `routers/metrics.py` | `/live` and `/campuses` → canonical service |
| `routers/dashboard.py` | night-consumption estimator → canonical service, window narrowed to the night band |
| `routers/data_explorer.py` | → canonical service |
| `services/ml_engine.py` | feature builder → canonical service |
| `tests/test_energy_aggregate.py` | reference oracle made era-aware; both paths bounded against ingestion races |

`grep` for a second interpretation of `energy_kwh` outside `energy_aggregate.py`
now returns only raw-column echoes: CSV dumps of the stored value and the
ingest endpoint returning what was posted.

---

## 5. Compatibility strategy

| Concern | Outcome |
|---|---|
| Existing collectors | unchanged, still supported |
| Historical readings | untouched; interpreted through their era |
| June's published figures | unchanged — the counter era is still read as a counter |
| Dashboards | correct immediately, no frontend change |
| `energy_kwh` | legacy: never written by new collectors, read only via the era table, retained as evidence |

---

## 6. Migration plan (executed)

1. Investigate and record eras — evidence in ADR-0007.
2. Dry run 012 up → down → up on a database copy. Clean.
3. Verified backup + restore drill. Passed.
4. Apply through the migration runner: backup → invariant snapshot → apply in
   transaction → re-check invariants. **18 invariants, 0 violations.**
5. Make `energy_aggregate` era-aware; verify KPIs.
6. Audit every consumer; route the seven stragglers through the canonical service.
7. Run the ten proofs.

## 7. Rollback plan

```bash
venv/bin/python -m migrations.runner down 012
```

`012_canonical_measurement_model.down.sql` drops only additions — the two tables
and the four columns. No reading is touched on the way down; the invariant gate
verifies that, and auto-rolls-back if it does not hold.

The code layer must be reverted alongside it, or `energy_aggregate` will query
tables that no longer exist. Pre-change copies:

```
backups/energy_aggregate.py-before-canonical-20260731_191102
backups/models.py-before-canonical-20260731_191102
backups/readings.py-before-canonical-20260731_191102
```

Database backups: `backups/db/energy_platform-20260731_191106-pre-012-up.db`
(restore drill passed 2026-07-31 20:16).

After rollback the platform returns to reading every era as a counter — i.e. the
~400x-low KPIs. That is the state being rolled back *to*, and it is expected.

---

## 8. Benchmark, before and after

Serial, warm, single request:

| Endpoint | Before | After |
|---|---:|---:|
| `/api/dashboard/summary` | 0.609 s | 0.550 s |
| `/api/cost/summary` | 0.842 s | 0.482 s |
| `/api/ai/insights` | 0.606 s | 0.469 s |
| `/api/mining` | 2.077 s | **0.516 s** |
| `/api/ai-center` | 6.530 s | 6.654 s |
| `/api/metrics/daily` | 0.495 s | 0.412 s |

Concurrent — the real `PageDashboard` fan-out, 11 endpoints at once, 1 gunicorn
worker, 9 page loads:

| | Before | After |
|---|---:|---:|
| median whole-page wall clock | 20.5 s | **12.0 s** |
| worst whole-page wall clock | 22.7 s | **12.2 s** |
| requests over the 30 s Axios limit | 0 | **0** |
| failures | 0 | **0** |

Faster than the baseline, not merely no worse. Two changes account for it:
mining no longer materialises 33,000 ORM rows per request to compute averages
(one grouped SQL aggregate instead), and the dashboard's night estimator scans
the six-hour night band rather than the whole day.

The remaining bottleneck is unchanged and pre-existing: one gunicorn worker
serialises the whole page. The measured remedy (4 workers, worst case 5.89 s,
1.6 GB) still requires root on
`/etc/systemd/system/energy-platform-backend.service`.

---

## 9. Mathematical proof that the new values are correct

For a node in era *E* at time *t*, interval energy is

```
                 ⎧ interval_energy_kwh                      E = canonical
                 ⎪ energy_kwh                               E = interval_energy
  e(r)      =    ⎨ 0                                        E = absent
                 ⎪ Δ   if 0 < Δ ≤ 100,  Δ = kwh(r) − kwh(prev)   E = cumulative_counter
                 ⎩ 0   otherwise
```

and every reported figure is a sum of `e(r)` over a set of readings, priced at
the tariff of the local hour containing *r*.

**Correctness of the era assignment** rests on measured evidence, not choice:

- Counter era: `energy_kwh` rose monotonically 17,283.8189 → 26,259.2423 kWh
  over 19 days, **0.0 %** negative deltas. Only a counter behaves this way.
- Interval era: `energy_kwh = power_kw × 15.000 / 3600` with relative error
  **exactly 0.000e+00**, and **51.6 %** of deltas negative. Differencing this is
  differencing noise; it is definitionally energy over a 15-second interval.

**Correctness of the aggregation.** The tariff period is constant within a local
hour — every GDMTH boundary (0, 6, 7, 8, 18, 19, 20, 21, 22) is a whole hour,
and America/Mexico_City has been a fixed UTC−6 since 2022, asserted at runtime
by `_assert_whole_hour_offset`. So classifying once per hourly bucket is
identical to classifying per reading; `tests/test_energy_aggregate.py` GATE 2
verifies this across all 144 buckets.

**Magnitude sanity.** Mean power over the week is 16.409 kW across 27,865
samples. `16.409 kW × 168 h ≈ 2,757 kWh`, against 2,166 kWh measured over the
readings actually present — consistent, given gaps. The old figure of 30.9 kWh
per week implies a mean of 0.18 kW against a measured 16.4 kW: wrong by the
~90x that differencing noise instead of summing energy produces.

### KPI change

| KPI | Before | After |
|---|---:|---:|
| energy today | 0.37 kWh | 172.04 kWh |
| cost today | $0.55 | $261.02 |
| energy this week | 30.883 kWh | 1,561.20 kWh |
| cost this week | $51.79 | $2,585.47 |
| projected month | $28.40 | $12,528.98 |

The old numbers were the sum of rounding noise. The new ones are the sum of
measured interval energy.

---

## 10. The ten required proofs

| # | Proof | Result |
|---|---|---|
| 1 | dashboard totals = independent recomputation | **PASS** — 6/6 KPIs match a from-scratch SQL+Python recomputation that imports no app code |
| 2 | cost = Σ(energy) × tariff, per measurement type | **PASS** — to the cent, era-resolved |
| 3 | weekly = sum of daily | **PASS** — 1,556.297 kWh both ways, exact |
| 4 | monthly projection consistent | **PASS** — matches today/hours × 24 × 30 |
| 5 | AI uses the same energy source | **PASS** — `ml_engine` 168 h sum vs aggregate: difference **0.000000000 kWh**, cost identical |
| 6 | mining uses the same source | **PASS** — total and night kWh match per building; power stats match the replaced Python loop |
| 7 | reports use the same source | **PASS** — `cost_between` equals the dashboard week to the cent |
| 8 | no historical reading changed | **PASS** — SHA-256 over all 247,633 pre-existing rows byte-identical; new columns NULL on every one |
| 9 | no deployment attribution changed | **PASS** — attribution totals identical, deployments row-for-row identical |
| 10 | no performance regression | **PASS** — faster than baseline: worst page 22.7 s → 12.2 s, 0 timeouts |

### Regression gates

| Suite | Result |
|---|---|
| `test_energy_aggregate.py` | 8/8 (stable across 3 consecutive runs) |
| `test_deployment_lifecycle.py` | 29/29 |
| `test_collector.py` | 49/49 |
| `test_monitoring.py` | 329/329 |
| `migrations.runner verify` | 18 invariants, 0 violations |
| restore drill | PASSED |

`test_smart_plugs.py` (52/1) and `test_synthetic_deployment.py` (5/6) fail.
Both were **verified pre-existing**: re-run against the pre-canonical code they
produce identical counts and identical failing assertions. Neither imports any
module changed here; they concern deployment-state gating in the alerting rules,
not energy.

---

## 11. Two behaviour changes worth stating plainly

- **`lifetime_energy_kwh` in `/api/metrics/live` and the deployment exports** now
  reports `meter_energy_kwh`, the canonical register field. It is currently
  **null**, because no collector reports a register yet. That is honest: in the
  interval era there is no lifetime count, and the previous value was
  `energy_kwh` mislabelled as one.

- **`peak_power_kw` in `/api/mining`** now includes the first reading of the
  window. The old delta loop walked consecutive pairs and silently skipped it,
  which could hide a peak.

## 12. Still open

- **M8 production cutover** — not authorized; the resolver remains shadow-only
  and `ATTRIBUTION_RESOLVER_ENABLED` does not exist in `.env`.
- **M9** — immutability trigger on `energy_readings`, retire `Node.status`.
- **4 gunicorn workers** — measured and justified; blocked on root.
- **N003 context** — physically in storage; confirm before cutover.
- **Cleanup migration** — `energy_readings_pre_m4`, `m5_attribution_backup`,
  `nodes_pre_m7`, `deployments_pre_m3` all still retained deliberately.
