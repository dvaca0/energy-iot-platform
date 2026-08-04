# University Energy Intelligence Platform — architecture

The definitive technical reference. If this document and the code disagree, the
code is a bug or this document is stale; either way, one of them gets fixed.

Decisions and their reasoning live in [`adr/`](adr/README.md). This document
describes the resulting system.

---

## 1. Overall architecture

Raspberry Pi edge nodes measure electrical load at building panels, buffer
locally, and synchronise to a central FastAPI backend over HTTP. The backend
stores readings in SQLite, attributes them to installation campaigns, and serves
analytics, reports and monitoring.

```
  Raspberry Pi node                  Backend (gunicorn, :8010)         Consumers
  ┌────────────────┐                 ┌──────────────────────┐          ┌────────┐
  │ collector      │  POST /api/v1/  │ ingest               │          │ React  │
  │  poll  15 s    │─ measurements/ ─▶  authenticate        │          │ front- │
  │  buffer (sqlite)│    batch        │  authorize          │          │ end    │
  │  sync   60 s   │                 │  classify            │          │ :5174  │
  │                │  POST /api/edge/│  attribute           │          └────────┘
  │ heartbeat      │─ heartbeat ─────▶                      │          ┌────────┐
  └────────────────┘                 │ energy_readings      │◀─────────│ reports│
                                     │ (SQLite, WAL)        │          │ AI     │
  ┌────────────────┐                 │                      │          │ mining │
  │ Shelly plugs   │─ accessory ─────▶ smart_plug_readings  │          └────────┘
  └────────────────┘                 └──────────┬───────────┘
                                                │
                                     ┌──────────▼───────────┐
                                     │ monitoring scheduler │  separate process
                                     │ heartbeat / rules    │  Telegram alerts
                                     └──────────────────────┘
```

Deliberate structural choices:

- **The monitoring scheduler is a separate process.** An in-process scheduler
  would multiply alerts if gunicorn ever moved off `-w 1`, and could not report
  a backend crash. A backend reload does not restart it.
- **The edge buffers and retries.** A backend outage delays data, it does not
  lose it. This is why ingestion may block briefly during a migration without
  consequence.
- **SQLite in WAL mode**, single writer, many readers. Backups must use the
  online backup API, never `cp`.

---

## 2. The five concepts

The redesign of 2026-07-26 exists because four questions had collapsed into two
columns. Each now has exactly one owner, and no owner reads another's state to
answer its own question.

| Question | Owner | Source of truth |
|---|---|---|
| Does this node exist? Is it authorized? | `Node` | `nodes`, `node_commission_states` |
| Is it online? Is sync healthy? | derived | `monitor_node_heartbeat_latest` |
| What stage is the campaign at? | `Deployment` | `deployments`, `deployment_statuses` |
| What kind of measurement is this? | `EnergyReading.context` | `measurement_contexts` |
| Where does this reading count? | `EnergyReading` | `deployment_id`, `building_id`, `panel_id` |

A node going offline changes no deployment. Completing a deployment changes no
node state and stops no ingestion. Classification does not depend on
attribution, and attribution does not depend on classification.

---

## 3. Data flow

### Ingest

```
payload ─▶ authenticate ─▶ authorize ─▶ classify ─▶ attribute ─▶ store
           token vs        commission   node's      resolver     always
           auth_token_hash  state may_   declared    over         (never
                            upload       context     captured_at   reject)
```

Once authenticated and authorized, **data is always stored and never rejected.**
A reading that cannot be attributed is stored unattributed. Rejection destroys
evidence; classification preserves it.

### Read

Analytics never re-derive attribution. A reading's stored `building_id` is the
answer, permanently. Every analytics path goes through `app/db/scope.py`, which
filters by `measurement_contexts.counts_in_analytics`.

---

## 4. Node lifecycle

States live in `node_commission_states`; semantics are columns, so a new state
is one `INSERT`.

```
  registered ──▶ commissioned ──▶ decommissioned
                    ▲    │
                    │    ▼
                 suspended ──────▶ decommissioned
```

| State | `may_upload` | `is_monitored` | Meaning |
|---|:--:|:--:|---|
| `registered` | no | no | Known, not yet verified in the field. Silence expected. |
| `commissioned` | **yes** | **yes** | In service. The only uploading state. Silence is an alarm. |
| `suspended` | no | yes | Uploads revoked (fault, security, theft). Still installed, still watched. |
| `decommissioned` | no | no | Retired. History retained, silence expected. |

`may_upload` answers authorization. `is_monitored` answers whether silence is an
alarm — this is what reconnected alerting to reality, and no deployment
transition can reach it.

---

## 5. Deployment lifecycle

States live in `deployment_statuses`; transitions in
`deployment_status_transitions`. Both are data.

```
  planned ──▶ installing ──▶ active ──▶ completed
     │            │             │
     └────────────┴─────────────┴──────▶ cancelled
```

| Status | `allows_attribution` | `is_operational` | `is_terminal` |
|---|:--:|:--:|:--:|
| `planned` | no | no | no |
| `installing` | no | yes | no |
| `active` | **yes** | yes | no |
| `completed` | **yes** | no | yes |
| `cancelled` | no | no | yes |

`completed` still attributes its own historical readings — a campaign that ended
does not stop owning what it measured. There is no transition out of `completed`
or `cancelled`: reopening would retroactively change attribution, so a new
deployment is created instead.

`end_date IS NULL` means open-ended, not missing.

---

## 6. Measurement lifecycle

```
  captured at the edge  ──▶  buffered locally  ──▶  synchronised  ──▶  stored
  (timestamp)                (sync_status=0)        (ingested_at)      immutable
```

`timestamp` is when the measurement was taken. `ingested_at` is when the server
received it. They are separate because a replayed buffer can deliver a week-old
measurement seconds ago — and attribution depends on the former.

Stored readings are immutable. A `BEFORE UPDATE` trigger (M9, pending) aborts
any change to `node_id`, `deployment_id`, `building_id`, `electrical_panel_id`
or `context`. Corrections happen only through supervised migrations that drop
the trigger, act within a backed-up reversible step, and reinstate it.

Measured values are immutable under **all** circumstances, with no waiver.

---

## 7. Attribution lifecycle

Implemented in `app/services/attribution.py`. Pure, stateless, deterministic,
idempotent. No I/O, no clock, no globals, no mutable cache.

```
resolve(state, node_id, captured_at) ─▶ Decision(deployment, building, panel,
                                                 context, reason, flags)
```

For each measurement **independently**, find the deployment where `node_id`
matches, `start_date <= captured_at <= COALESCE(end_date, ∞)`, and the status
allows attribution.

| Outcome | Reason code |
|---|---|
| Exactly one match | `ATTRIBUTED_IN_WINDOW` |
| Node has no deployments | `NO_MATCHING_DEPLOYMENT` |
| Deployments exist, none covers the timestamp | `OUTSIDE_DEPLOYMENT_WINDOW` |
| Covering deployment cannot attribute | `DEPLOYMENT_NOT_ATTRIBUTING` |
| More than one covers it | `MULTIPLE_MATCHES` — attributes nothing |
| Node declares a non-attributable context | `BENCH_NODE`, `LABORATORY_NODE`, … |
| Node may not upload | `NODE_MAY_NOT_UPLOAD` |

Flags are additive and never change attribution: `PLACEHOLDER_BUILDING`,
`MISSING_BUILDING`, `MISSING_PANEL`, `OPEN_ENDED_DEPLOYMENT`.

Three invariants of the design:

- **Attribution follows `captured_at`, never upload time.** The resolver is
  never given the ingestion instant, so it cannot depend on it even by accident.
- **Ambiguity is a result, not a tiebreak.** Overlapping windows produce
  `MULTIPLE_MATCHES` and no attribution. The resolver never silently chooses.
- **The resolver is an ingest-time function.** It reads the node's *current*
  declared context, which is right for new readings and wrong for history.
  **It must never be run as a backfill over stored rows.**

---

## 8. Measurement contexts

Declared, never inferred from the presence of a deployment. Values live in
`measurement_contexts`.

| Context | `counts_in_analytics` | `may_attribute` | Meaning |
|---|:--:|:--:|---|
| `production` | **yes** | yes | Real load, real panel, real campaign |
| `commissioning` | no | yes | On-site verification before a campaign goes active |
| `bench` | no | no | Hardware bring-up; the instrument is under test |
| `laboratory` | no | no | Controlled acquisition on a real load, outside any campaign |
| `calibration` | no | no | Measured against a reference |
| `simulation` | no | no | Synthetic or replayed; no physical sensor |

Context is taken from `nodes.measurement_context`, which is operator-set and
authoritative. A payload may **narrow** it but never widen it to `production`,
so a misconfigured collector cannot promote its own data into the KPIs.

The important combination:

| Context | Attribution | Meaning | Response |
|---|---|---|---|
| `production` | resolved | Normal | Counts everywhere |
| `production` | **NULL** | **Deployment missing or mis-dated** | Stored **and alerted** |
| non-production | NULL | Expected | Stored silently, excluded |

Row 2 is why context is explicit rather than inferred. Under an inference model,
a genuine production node whose deployment was never created would be silently
relabelled bench and vanish from every KPI. Here it is an alarm.

---

## 9. Analytics scope

`app/db/scope.py` is the single enforcement point. Every analytics call site
uses it; `db.query(EnergyReading)` appears in zero analytics paths.

Two independent exclusions:

- **Context** — `measurement_contexts.counts_in_analytics`.
- **Building metadata** — `buildings.is_placeholder`. A placeholder building
  excludes the *building* from building-level breakdowns without discarding the
  measurements, which may be perfectly real.

Bench and laboratory data remains queryable and exportable through the explicit
`?context=` parameter on `/api/data-explorer`, `/api/reports/dataset.csv` and
`/api/reports/raw-readings.csv`. Exports carry a `context` column so a file is
self-describing.

Deliberately **not** scoped: `/api/infra` and node-inventory counts in reports.
Those report hardware liveness and data volume — a node on the bench is still a
node that is alive, and the platform genuinely holds that many readings.

---

## 10. Monitoring scope

Monitoring follows **nodes**, not campaigns. `monitoring/heartbeat.py` iterates
every node unconditionally; the legacy `/api/alerts/status` iterates nodes whose
commission state has `is_monitored`.

Two rule classes:

- **Liveness** — heartbeat age, buffer growth, reading staleness. Applies to
  every monitored node, whatever it is measuring.
- **Electrical quality** — power factor, frequency, imbalance. Applies **only**
  to nodes declaring `production`. A bench rig reads ~1e-5 A and PF 0.00 by
  design; judging it against production thresholds produces a permanent false
  alarm and trains the operator to ignore the panel.

Guard every threshold rule against the noise floor. Idle meters report ~1e-5 A
and ~-1e-9 kW; naive comparisons produced a permanent CRITICAL imbalance and a
phantom reverse power flow.

---

## 11. Invariants

Sixteen, checked before and after every migration
(`migrations/invariants.py`, `runner invariants`).

| # | Guarantee |
|---|---|
| 01 | No reading that existed before a step is missing after it |
| 02 | **No measured value ever changes — never waivable** |
| 03 | Attribution changes only in a step that declares it |
| 04 | Every reading names a node that exists |
| 05 | Node codes are unique |
| 06 | Deployment status is a legal value |
| 07 | Context is a legal value |
| 08 | A reading with a deployment also names a building |
| 09 | Non-production data is never attributed |
| 10 | Attribution never points at a deleted row |
| 11 | No reading dated more than a day ahead |
| 12 | Reference tables never shrink unexpectedly |
| 13 | The rebuild rollback table survives until cleanup |
| 14 | Every foreign key resolves (`PRAGMA foreign_key_check`) |
| 15 | `captured_at` never changes without an explicit waiver |
| 16 | `(id, node_id, captured_at)` identical: no duplicate, reordered or reassigned id |

Waivable: `allow_attribution_change`, `allow_timestamp_change`,
`allow_node_change`, `allow_building_change`, `allow_deployment_change`. An
unrecognised waiver aborts the run before the backup is taken.

Every reading-level invariant is bounded by `id <= max_reading_id` captured at
snapshot time, so concurrent ingestion cannot cause a false failure or mask a
real loss.

---

## 12. Migration philosophy

There is no Alembic and no git repository here. `migrations/runner.py` provides
what would otherwise be missing.

Every run: **online backup → invariant snapshot → apply in one transaction →
re-check invariants → record, or roll back automatically.**

Principles the programme established:

1. **Rollback ships with the change.** The runner refuses a step with no
   `.down.sql`. Rollback is written at the same time, not reconstructed under
   pressure.
2. **Prove the rollback, don't assume it.** Every step was rehearsed up → down →
   up on a throwaway copy before touching production.
3. **Prove the restore, don't assume it.** `restore-drill` restores a backup and
   compares counts, totals and invariants against live. It gates the high-risk
   steps.
4. **Rename, never drop.** High-risk rebuilds keep the original table
   (`energy_readings_pre_m4`); rollback is two renames with no data movement.
5. **Additive first.** Six of eight migrations added structure without changing
   meaning. Reclassification came only after the structure was proven.
6. **Semantics as data.** Lifecycle states, commission states and contexts live
   in lookup tables with behaviour-bearing columns, so a new state is one
   `INSERT` rather than a constraint rewrite and a refactor.
7. **Invariants catch what review cannot.** A migration that drops rows or
   rewrites a measurement completes successfully and reports nothing. Automatic
   rollback on violation means it does not survive to be discovered later.

Two SQLite specifics that cost real debugging:

- `ALTER TABLE RENAME` rewrites foreign keys in *other* tables to follow the
  renamed table. Set `PRAGMA legacy_alter_table=ON` during a rebuild, or the
  rollback table silently becomes the live parent.
- A renamed table keeps its indexes under their original names. Drop them before
  creating the new ones or the `CREATE INDEX` collides.

---

## 13. Recovery philosophy

Layered, cheapest first. Prefer a flag flip to a restore; prefer a bounded
correction to a whole-database rollback.

| Layer | Scope | Cost |
|---|---|---|
| Feature flag | Behaviour | seconds |
| Backup table restore by primary key | Bounded rows | seconds |
| Table rename swap | One table | seconds |
| Code restore + `kill -HUP` | Behaviour | seconds |
| Whole-database restore | Everything | minutes, **loses data since** |

Rules:

- **Never delete historical data.** Reclassify, flag, exclude — never delete.
- **Bound every correction by a stored marker**, so "which rows did this touch"
  has an exact answer forever.
- **Two independent identifications** where possible. Resolver-written rows are
  identifiable by `id > m8_freeze_point` *and* by `ingested_at IS NOT NULL`.
- **A refusal is a feature.** The M4 rollback aborts rather than discard
  post-rebuild readings. The resolver refuses to attribute ambiguity. Both stop
  rather than guess.
- **The edge buffer is part of recovery.** A backend outage or a rejected batch
  is not data loss; the Pi retains and retries. This is why brief write-lock
  contention during a migration is acceptable.

---

## Reference

| Path | Purpose |
|---|---|
| `app/db/lifecycle.py` | Deployment lifecycle accessor — the only reader of `deployment_statuses` |
| `app/db/commissioning.py` | Node commission accessor |
| `app/db/scope.py` | Analytics scoping — the single enforcement point |
| `app/services/attribution.py` | The resolver. Pure. |
| `migrations/runner.py` | Migration engine |
| `migrations/invariants.py` | The 16 invariants |
| `migrations/baseline.py` | Immutable baseline reports |
| `migrations/shadow.py` | Read-only shadow execution |
| `docs/adr/` | Decisions and reasoning |
| `docs/m8-production-cutover-runbook.md` | The cutover procedure |

Operational facts that are easy to get wrong: the backend reloads with
`kill -HUP` on the gunicorn master (no root needed); the monitoring scheduler is
a **separate** process and does not restart with it; never
`pgrep -f "app.monitoring.scheduler"` from a shell, because the pattern matches
the invoking shell's own command line.
