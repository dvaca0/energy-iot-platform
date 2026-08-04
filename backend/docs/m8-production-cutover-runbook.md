# M8 production cutover — operational runbook

**Status: NOT AUTHORIZED. `ATTRIBUTION_RESOLVER_ENABLED` remains OFF.**

This is the operational procedure for making the attribution resolver
authoritative. It supersedes the preparatory `m8-cutover-package.md`.

M8 is the only change in this programme that alters what happens to data
arriving in real time. Every earlier migration could be undone from a backup; a
defect here corrupts readings as they arrive, and a backup taken beforehand does
not contain them. It is therefore run as a rehearsed operational cutover with a
named operator, defined stop conditions, and a rollback that is a flag flip
rather than a restore.

Read sections 1–3 before touching anything. Sections 4–11 are executed in order.
Sections 12–18 govern what happens afterwards.

---

## 1. Pre-cutover checklist

Every line must be ticked, by name, before the operator proceeds.

- [ ] Shadow report regenerated within the last 24 hours
- [ ] `MULTIPLE_MATCHES` count is **zero**
- [ ] `ATTRIBUTION_DIFFERS` contains only the known N003 contamination window
- [ ] No unexplained disagreement for N001
- [ ] All 16 invariants clean (`python3 -m migrations.runner verify`)
- [ ] Restore drill passed (`python3 -m migrations.runner restore-drill`)
- [ ] `energy_readings_pre_m4` present
- [ ] `m5_attribution_backup` present
- [ ] `migration_markers` contains `m5_n003_boundary`
- [ ] All three nodes online and heartbeating
- [ ] All node buffers at zero (`nodes.buffer_pending`)
- [ ] **N003's declared `measurement_context` confirmed against physical reality**
- [ ] Isolated full-stack replay validation completed and passed (appendix A)
- [ ] Disk free ≥ 5 GB
- [ ] Operator named, and a second person available to confirm abort decisions

---

## 2. Preconditions

Structural prerequisites, all satisfied as of M7:

| Requirement | Delivered by |
|---|---|
| `deployment_id` / `building_id` / `electrical_panel_id` nullable | M4 |
| `context` FK to `measurement_contexts` | M4 |
| `ingested_at` column present | M4 |
| `deployment_statuses.allows_attribution` | M3 |
| `deployments.end_date` nullable; deployment 4 open-ended | M3 (D1) |
| `node_commission_states.may_upload` | M7 |
| `migration_markers`, `v_m5_contamination_window` | M6 |
| Pure, benchmarked resolver | M8 shadow |

Operational preconditions:

- The cutover happens in a quiet window, with the operator able to watch for at
  least 30 minutes afterwards.
- No other migration is in flight.
- The monitoring scheduler is running (it is a separate process; a backend
  reload does not restart it).

---

## 3. Operator checklist

The person executing the cutover confirms, in writing:

1. I have read this runbook end to end.
2. I know the abort criteria (§15) and will abort rather than improvise.
3. I know the rollback is `ATTRIBUTION_RESOLVER_ENABLED=false` plus `kill -HUP`,
   and that it takes seconds.
4. I will not run cleanup (§18) during this session.
5. I will not run the resolver as a backfill over historical rows, ever.
6. I have a terminal open on the backend host with the backup directory visible.

---

## 4. Backup procedure

```bash
cd /home/manager/energy-platform/backend
python3 -m migrations.runner backup
```

Uses SQLite's online backup API. **Never `cp`** — the database is WAL with a
live multi-megabyte `-wal` file and a plain copy can capture a torn state.

Record the resulting filename in the cutover log. It is the last-resort
recovery point for §14.

---

## 5. Restore drill

```bash
python3 -m migrations.runner restore-drill
```

Restores the backup to a scratch path and compares row counts, measured totals
and all 16 invariants against the live database. **The drill must pass.** A
failure here is an abort, not a warning: it means the recovery path is not
actually available.

---

## 6. Feature flag activation

The resolver ships behind `ATTRIBUTION_RESOLVER_ENABLED`, read from
`backend/.env` (mode 600). It defaults to **false**, and the ingest path uses the
legacy attribution logic while it is false.

```bash
# backend/.env
ATTRIBUTION_RESOLVER_ENABLED=true
```

The flag is read once per worker at import time, so it takes effect on reload,
not mid-request. That is deliberate: no request should see a régime change
half-way through.

**Do not reload yet.** §7 must happen in the same transaction as enablement.

---

## 7. Freeze-point recording

The boundary between "written by the legacy path" and "written by the resolver"
must be exact. It is recorded by a numbered migration, not by hand:

```sql
INSERT INTO migration_markers (name, reading_id, recorded_at, notes)
VALUES ('m8_freeze_point',
        (SELECT COALESCE(MAX(id), 0) FROM energy_readings),
        datetime('now'),
        'Highest reading id written by the legacy attribution path.');
```

Run it **immediately before** the reload that activates the resolver, in the
same operator action. A gap in either direction produces rows belonging to
neither régime and makes the reconciliation window wrong.

Three markers then bound everything:

| Marker | Meaning |
|---|---|
| `m5_n003_boundary` | Last N003 row classified by M5 |
| `m6_analytics_scope` | Analytics switched to production scope |
| `m8_freeze_point` | Last row written by the legacy path |

Reconciliation window: `m5_n003_boundary < id <= m8_freeze_point`.

---

## 8. Resolver enablement

```bash
kill -HUP $(systemctl show -p MainPID --value energy-platform-backend.service)
```

Gunicorn starts new workers that re-import the app and read the flag, then
retires the old ones. No connection is dropped. Collectors that hit the moment
of transition retry from their buffer.

Start the clock. The next 30 minutes are the observation window.

---

## 9. Verification

Immediately, and then again after one full sync cycle on every node:

- [ ] `/health` returns 200
- [ ] Reading count rising
- [ ] **No 400/500 in any collector log** — the resolver must never reject
- [ ] New rows have `ingested_at` populated (the legacy path never set it)
- [ ] N001's new rows → deployment 4, building 8
- [ ] N003's new rows → `NULL` attribution, context per its declared state
- [ ] `v_m5_contamination_window` has stopped growing
- [ ] All 16 invariants clean
- [ ] `/api/alerts/status` shows no new findings beyond the known ones

```sql
-- rows written by the resolver, two independent identifications
SELECT COUNT(*) FROM energy_readings
 WHERE id > (SELECT reading_id FROM migration_markers WHERE name='m8_freeze_point');
SELECT COUNT(*) FROM energy_readings WHERE ingested_at IS NOT NULL;
-- these must agree
```

---

## 10. Window reconciliation

Only after §9 passes. A numbered migration declaring
`allow_attribution_change`, run through the standard runner so it gets a backup,
a snapshot and the invariant gate.

```sql
CREATE TABLE m8_reconciliation_backup AS
SELECT id, deployment_id, building_id, electrical_panel_id, context
  FROM energy_readings
 WHERE id >  (SELECT reading_id FROM migration_markers WHERE name='m5_n003_boundary')
   AND id <= (SELECT reading_id FROM migration_markers WHERE name='m8_freeze_point')
   AND node_id = (SELECT id FROM nodes WHERE code='N003')
   AND context = 'production';
-- then apply the resolver's decision to exactly those ids
```

Properties, all required and all structural:

- **Deterministic** — bounded by stored markers and a fixed predicate.
- **Idempotent** — the predicate requires `context='production'`; after one run
  nothing matches, so re-running is a no-op. Safe after a partial failure.
- **Auditable** — `v_m5_contamination_window` lists candidates beforehand; the
  backup table records every prior value; the run reports counts.
- **Reversible** — restore by primary key from `m8_reconciliation_backup`.

**Rows at or below `m5_n003_boundary` are never touched.** The shadow report
proved 0 of the 120,361 `laboratory` rows sit above that boundary, so M5's
classification is outside the window by construction.

Report afterwards: rows corrected, rows unchanged, rows still unattributed, rows
needing manual review.

---

## 11. Post-cutover validation

- [ ] Reconciliation report reviewed
- [ ] `v_m5_contamination_window` returns **0 rows**
- [ ] N003's `laboratory` count still exactly 120,361
- [ ] N001's production count unchanged apart from new arrivals
- [ ] Cost endpoints moved only by live drift — verified with a control snapshot
      taken two minutes apart, as in M6
- [ ] Restore drill passes again
- [ ] All 16 invariants clean

---

## 12. Monitoring

For the soak period (§17), watch:

| Signal | Where | Alarm condition |
|---|---|---|
| Ingest rejections | collector logs | any 400/500 |
| Buffer growth | `nodes.buffer_pending` | > 0 for more than two cycles |
| Unattributed production | `context='production' AND deployment_id IS NULL` | any row |
| Heartbeat | `/api/alerts/status` | any new finding |
| Invariants | `runner verify` | any violation |
| Contamination window | `v_m5_contamination_window` | any growth |

A `production` reading with NULL attribution is the signal that matters most: it
means a node is measuring for real and no deployment covers it. That is a
commissioning error, and under this architecture it is loud rather than silent.

---

## 13. Rollback procedure

Three independent layers, cheapest first. Prefer the top of the table.

| Layer | Action | Cost | Data impact |
|---|---|---|---|
| Resolver | `ATTRIBUTION_RESOLVER_ENABLED=false`, `kill -HUP` | seconds | none; ingestion returns to the legacy path |
| Reconciliation | restore from `m8_reconciliation_backup` by id | seconds | bounded to the window |
| Code | restore `backups/*-before-m8-*`, `kill -HUP` | seconds | none |
| Database | restore the §4 backup | minutes | **loses every reading ingested since** |

Note the M4 interaction: once the resolver has written unattributed rows,
`004_rebuild_energy_readings.down.sql` refuses to run rather than discard them.
That is intended behaviour, not an obstacle to work around.

---

## 14. Failure scenarios

| Scenario | Detection | Response |
|---|---|---|
| Resolver rejects readings | 400s in collector logs; buffers growing | Disable flag immediately. Buffers replay; nothing lost. |
| Attribution wrong for N001 | N001 rows unattributed or on the wrong building | Disable flag. Assess against shadow predictions before repairing. |
| Reconciliation touched rows below the M5 boundary | `laboratory` count ≠ 120,361 | Restore from `m8_reconciliation_backup`. Investigate the predicate. |
| Invariant violation | `runner verify` | Runner rolls the migration back automatically; do not re-run until understood. |
| `ingested_at` not populated | Verification query in §9 | Disable flag; the recovery procedure depends on this field. |
| Node offline during cutover | `/api/alerts/status` | Not a failure. Its buffer replays on return — and that replay is the strongest live proof the fix works. |
| Ambiguous attribution appears | `MULTIPLE_MATCHES` in a later shadow run | Disable flag. Overlapping deployments must be resolved administratively first. |

---

## 15. Abort criteria

Stop **before** §8. Aborting costs nothing.

1. Any `MULTIPLE_MATCHES` in the shadow report.
2. An unexplained disagreement for N001.
3. The isolated replay validation (appendix A) not performed, or its result not
   matching the shadow prediction.
4. Restore drill fails.
5. Any invariant failing beforehand.
6. `energy_readings_pre_m4` or `m5_attribution_backup` missing.
7. **A node's declared `measurement_context` not confirmed against physical
   reality** — in particular N003.
8. Any node offline or holding a non-empty buffer.
9. The operator is not able to watch for 30 minutes afterwards.

---

## 16. Success criteria

All must hold before the cutover is declared successful:

1. Zero readings rejected during or after cutover.
2. Zero invariant violations.
3. Every new reading has `node_id` set and `ingested_at` populated.
4. N001 attribution unchanged (deployment 4 covers it, open-ended).
5. N003's new readings unattributed, context matching its declared state.
6. `v_m5_contamination_window` returns 0 rows after reconciliation.
7. `laboratory` count still exactly 120,361 — M5's work untouched.
8. Cost figures move only by live drift, proven against a control snapshot.
9. Reconciliation touched only the window.
10. A buffered replay observed in production attributes by `captured_at`.

---

## 17. Soak period

**Minimum 7 days** of normal operation after reconciliation, during which:

- No temporary artifact is removed (§18).
- `runner verify` is run daily.
- The monitoring signals in §12 stay clean.
- At least one real buffered replay is observed and confirmed correct — a node
  outage and recovery. If none occurs naturally within the soak, extend rather
  than force one.

The soak ends when the platform owner says so, not on a timer.

---

## 18. Cleanup criteria

**Nothing here is authorized. This section defines when each artifact may be
proposed for removal, not that it should be.**

Cleanup is a separate numbered migration with its own backup, invariant gate and
rollback, run only on explicit instruction.

### `energy_readings_pre_m4` (~30 MB)

- **Why it exists** — the pre-rebuild copy of all 225k readings; the rollback
  path for the highest-risk migration in the programme. Two renames restore it.
- **Safe to remove when** — soak complete, and the rebuilt table has been the
  only source of truth for analytics, reports and exports throughout.
- **Prerequisites** — §16 all green; a verified backup newer than the cutover;
  `INV-13` explicitly retired in the same migration (it fails if the table
  vanishes while the rebuild is in effect).
- **Rollback implications** — **the M4 rollback ceases to exist.** After this,
  recovering from a rebuild defect means restoring a whole-database backup and
  losing everything ingested since. This is the single most consequential
  cleanup; treat it as last.

### `m5_attribution_backup` (123,696 rows)

- **Why it exists** — every N003 row's attribution and context before M5
  reclassified it, keyed by primary key. Also the derivation source for
  `m5_n003_boundary`.
- **Safe to remove when** — soak complete **and** the marker has been
  materialised elsewhere, because `v_m5_contamination_window` derives its
  boundary from `MAX(id)` on this table.
- **Prerequisites** — the contamination view either dropped or rewritten to read
  the marker directly; N003's classification confirmed correct against physical
  reality.
- **Rollback implications** — M5 becomes irreversible. The `laboratory`/`bench`
  split could only be reconstructed by re-deriving it from timestamps, which
  loses the record of the owner's determination.

### `m8_reconciliation_backup`

- **Why it exists** — prior attribution for the contamination window.
- **Safe to remove when** — soak complete and the reconciliation report reviewed
  and accepted.
- **Prerequisites** — `v_m5_contamination_window` returning 0 rows for the whole
  soak.
- **Rollback implications** — the window reconciliation becomes irreversible.
  Low impact: 32 rows, all reconstructible from the resolver, which is
  deterministic.

### `migration_markers`

- **Why it exists** — the freeze points that make "rows created between X and Y"
  answerable. The audit trail of the whole programme.
- **Safe to remove when** — **never, in practice.** Three rows costing bytes,
  and they are the only durable record of the régime boundaries.
- **Prerequisites** — n/a.
- **Rollback implications** — any future reconciliation loses its ability to
  bound a window precisely. Retain indefinitely.

### `v_m5_contamination_window`

- **Why it exists** — makes rows written during the M5→M8 gap permanently
  identifiable and auditable.
- **Safe to remove when** — reconciliation complete, the view returning 0 rows
  for the full soak, and its final state captured in an immutable report.
- **Prerequisites** — the reconciliation report archived under
  `docs/migration-baselines/`.
- **Rollback implications** — none directly; it owns no data. But dropping it
  removes the standing audit query, so archive its final output first.

### `nodes_pre_m7`, `deployments_pre_m3`

- **Why they exist** — rollback paths for the node and deployment rebuilds.
- **Safe to remove when** — soak complete. Both are tiny (3 and 2 rows) and
  cheap to keep.
- **Prerequisites** — no lifecycle or commissioning change pending.
- **Rollback implications** — M3/M7 rollback would require a full restore.
  Given their size, there is no real reason to remove them.

### Legacy compatibility code

- **Why it exists** — the pre-resolver attribution path in `edge.py`,
  `readings.py` and `smart_plugs.py`, still reachable when the flag is false.
- **Safe to remove when** — the resolver has been authoritative for a full soak,
  **and** the platform owner accepts that rollback is no longer a flag flip.
- **Prerequisites** — every collector confirmed working against the resolver
  through at least one buffered replay each.
- **Rollback implications** — **severe.** Removing it converts the cheapest,
  fastest rollback layer (§13, seconds) into a code restore. Strong
  recommendation: keep this until the platform has run a full measurement
  campaign on the resolver. The maintenance cost is one `if`.

### Suggested order

`m8_reconciliation_backup` → `v_m5_contamination_window` →
`nodes_pre_m7` / `deployments_pre_m3` → `m5_attribution_backup` →
`energy_readings_pre_m4` → legacy code (last, and not soon).

`migration_markers` is never removed.

---

## Appendix A — replay validation strategy

The remaining unproven claim is not the resolver's logic — the shadow run
covered 225,832 readings and proved determinism, purity and boundary handling.
It is the **integration**: that the ingest handler passes each measurement's own
`captured_at` to the resolver rather than the current time, and that a buffer
spanning a deployment boundary lands correctly on both sides.

Four ways to obtain that evidence:

| Option | Realism | Safety | Complexity | Confidence |
|---|---|---|---|---|
| **A** — validation endpoint in production | Medium — real HTTP and payload parsing, but the resolver cannot be enabled in production, so the write path stays untested | **Low** — adds an endpoint to the production surface that accepts payloads; must be provably read-only, and proving that is harder than avoiding it | Medium | Medium |
| **B** — replay against a copy of the production database | High — real code, real payloads, real data | High — a copy | Medium | High |
| **C** — isolated test database from the latest verified backup | High | **Highest** — built from an already-drilled backup, no live coupling at all | Medium | High |
| **D** — isolated full stack: C, plus real payloads over real HTTP, with the resolver **enabled** | **Highest** | **Highest** | Medium-high | **Highest** |

### Recommendation: **D**

It is the only option that can answer the actual question. A, B and C all leave
the resolver disabled or bypassed in the environment being tested; only D
exercises the enabled write path end to end. And it does so where enabling it
costs nothing.

Procedure, for approval — **not executed**:

1. Build the isolated database with the existing, already-rehearsed restore
   path: `runner backup`, then restore to `/tmp/.../cutover-rehearsal.db`.
   No new tooling.
2. Capture real edge payloads read-only from N002's `edge_buffer.db`
   (`sync_status=0` rows), or reconstruct them from the documented batch schema.
   N002 is the right subject: it has zero readings, so nothing real is at stake.
3. Start a second gunicorn on an unused port, **bound to 127.0.0.1**, with
   `ENERGY_DB_PATH` pointing at the isolated copy and
   `ATTRIBUTION_RESOLVER_ENABLED=true`. Verify the target path before starting.
4. In the isolated database only, construct deployment windows around the
   captured timestamps — freely, because nothing there is production.
5. Replay the payloads over HTTP, out of chronological order, with the batch
   spanning a boundary.
6. Assert: measurements before the boundary unattributed, after it attributed;
   attribution identical regardless of replay order or delay; `ingested_at`
   populated and distinct from `timestamp`.
7. Compare against the shadow prediction for the same inputs. They must agree
   exactly — the resolver is deterministic, so any divergence is an integration
   defect, which is precisely what this tests.
8. Tear down; the isolated database is disposable.

Why this satisfies the constraint against manipulating production deployments:
every deployment boundary is constructed inside the throwaway copy. Production
deployment rows are never read for modification and never written.

Residual risk: an operator error pointing the second instance at the production
database. Mitigated by binding to localhost, using a distinct port, and echoing
the resolved `ENERGY_DB_PATH` before start — the same discipline the migration
runner already uses.
