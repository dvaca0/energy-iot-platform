# M8 cutover package

**Status: PREPARED, NOT EXECUTED. Shadow mode only until explicitly approved.**

M8 is the only migration that changes what happens to data arriving in real time.
Everything before it could be undone from a backup; a defect here corrupts
readings as they arrive, and no backup taken beforehand contains them. It is
therefore run as an operational cutover with a rehearsed procedure, defined
success and failure criteria, and an abort path — not as a development
migration.

Prerequisites, all satisfied as of M7:

- `energy_readings.deployment_id` / `building_id` / `electrical_panel_id` nullable (M4)
- `energy_readings.context` and `ingested_at` present (M4)
- `deployment_statuses` with `allows_attribution` (M3)
- `deployments.end_date` nullable, deployment 4 open-ended (M3, D1)
- `node_commission_states` with `may_upload` (M7)
- `migration_markers` and `v_m5_contamination_window` (M6)
- `energy_readings_pre_m4`, `m5_attribution_backup` retained

---

## 1. Freeze-point procedure

Record the boundary before the resolver becomes authoritative, so "rows written
by the old path" and "rows written by the resolver" are separable forever.

```sql
INSERT INTO migration_markers (name, reading_id, recorded_at, notes)
VALUES ('m8_freeze_point',
        (SELECT COALESCE(MAX(id), 0) FROM energy_readings),
        datetime('now'),
        'Highest reading id written by the legacy attribution path. Rows above this were written by the resolver.');
```

Taken inside the same transaction that enables the resolver. Not before, not
after — a gap in either direction produces rows that belong to neither régime.

Three markers then bound the reconciliation window exactly:

| Marker | Meaning |
|---|---|
| `m5_n003_boundary` | Last N003 row classified by M5 |
| `m6_analytics_scope` | Analytics switched to production scope |
| `m8_freeze_point` | Last row written by the legacy path |

The reconciliation window is `m5_n003_boundary < id <= m8_freeze_point`.

---

## 2. Shadow resolver execution procedure

The resolver runs **read-only** alongside the existing write path. It computes
what it *would* attribute and records that; it writes nothing to
`energy_readings`.

1. Deploy `app/services/attribution.py` with `resolve(db, node_id, captured_at)`
   returning `(deployment_id, building_id, panel_id, reason)`. Pure function of
   stored data — no side effects, no writes.
2. Deploy `shadow_attributions` table:
   `(reading_id PK, resolved_deployment_id, resolved_building_id,
     resolved_panel_id, reason, computed_at)`.
3. Run `python3 -m migrations.shadow --since <marker>` as a **separate process**,
   never inside a request. It reads readings, calls the resolver, writes only to
   `shadow_attributions`.
4. Let it run across at least: one full N001 sync cycle, one N003 cycle, one
   N002 heartbeat-only period, and **one deliberate buffered-replay test on
   N002** — the case that proves the per-measurement fix for defect B1.

The shadow phase ends only when the report in §3 is reviewed and approved.

### Deliberate replay test

N002 is the safe subject: it has zero readings, so a replay cannot disturb real
data.

1. Stop `energy-node-collector` on N002; let its buffer accumulate across a
   deployment boundary.
2. Create a deployment for N002 with a `start_date` after the buffered
   measurements begin.
3. Restart the collector and let the buffer drain.
4. Confirm in `shadow_attributions` that measurements before `start_date`
   resolve to `NULL` and those after resolve to the new deployment.

Under the current code the whole batch would take the newest deployment. That
divergence appearing in the report is the proof the fix works.

---

## 3. Shadow attribution report format

One row per disagreement between stored and resolved attribution.

| Column | Source |
|---|---|
| `reading_id` | `energy_readings.id` |
| `node` | `nodes.code` |
| `captured_at` | `energy_readings.timestamp` |
| `current_deployment` | stored `deployment_id` |
| `resolved_deployment` | `shadow_attributions.resolved_deployment_id` |
| `current_building` | stored `building_id` |
| `resolved_building` | `shadow_attributions.resolved_building_id` |
| `current_context` | stored `context` |
| `resolved_context` | node's declared `measurement_context` |
| `reason` | why the resolver chose what it chose |

`reason` is a closed vocabulary, so disagreements can be counted by cause:

| Reason | Meaning |
|---|---|
| `in_window` | Exactly one deployment covers `captured_at` |
| `no_deployment` | Node has none at all |
| `outside_all_windows` | Deployments exist, none covers this timestamp |
| `status_not_attributing` | Covering deployment is `planned`/`cancelled` |
| `ambiguous_overlap` | More than one covers it — **requires manual review** |
| `context_not_attributable` | Node declares a non-attributable context |

The report is generated to `docs/migration-baselines/` with the same immutable
treatment as the M5 baseline: SHA-256 embedded, `chmod 444`.

**Expected disagreements before cutover** (predicted from current data):

- N003's ~30+ contamination-window rows: currently `(5, 8, production)`,
  resolver gives `(NULL, NULL, bench)` — the node declares `bench`.
- N001: no disagreement expected. Deployment 4 is open-ended and covers
  everything from 2026-06-14 onward.
- Any `ambiguous_overlap` row is a **stop condition**, not a finding.

---

## 4. Window reconciliation procedure

Runs immediately after cutover, as a numbered migration declaring
`allow_attribution_change`. Reclassifies **only** rows created after M5 and at
or before the freeze point.

```sql
CREATE TABLE m8_reconciliation_backup AS
SELECT id, deployment_id, building_id, electrical_panel_id, context
  FROM energy_readings
 WHERE id >  (SELECT reading_id FROM migration_markers WHERE name = 'm5_n003_boundary')
   AND id <= (SELECT reading_id FROM migration_markers WHERE name = 'm8_freeze_point')
   AND node_id = (SELECT id FROM nodes WHERE code = 'N003')
   AND context = 'production';
-- then UPDATE those ids from the resolver's decision
```

The four properties you required:

- **Deterministic** — bounded by stored markers and a fixed predicate. Same
  input, same output, regardless of when it runs.
- **Idempotent** — the predicate requires `context = 'production'`; after one
  run no row matches, so a second run is a no-op. Safe to re-run after a partial
  failure.
- **Auditable** — `v_m5_contamination_window` lists the candidates before, the
  backup table records every prior value, and the post-run report states counts.
- **Reversible** — restore from `m8_reconciliation_backup` by primary key, the
  same mechanism M5 proved.

**Rows before `m5_n003_boundary` are not touched.** They were classified by M5
and are outside this window by construction.

---

## 5. Rollback procedure

Three independent layers, cheapest first.

| Layer | Action | Cost |
|---|---|---|
| Resolver | Set `ATTRIBUTION_RESOLVER_ENABLED=false`, `kill -HUP` | Seconds; ingestion continues on the legacy path |
| Reconciliation | Restore from `m8_reconciliation_backup` by id | Seconds; bounded to the window |
| Code | Restore `backups/*-before-m8-*`, `kill -HUP` | Seconds |

Full database restore from the pre-M8 backup is the last resort and **loses all
readings ingested since**. Prefer the layered rollback; the resolver flag alone
stops the bleeding without touching data.

The M4-style carry-forward hazard applies: once the resolver has written
unattributed rows, `004_rebuild_energy_readings.down.sql` will refuse to run
rather than discard them. That is intended.

---

## 6. Post-cutover verification checklist

- [ ] `migration_markers` contains `m8_freeze_point`
- [ ] All 16 invariants clean (`runner verify`)
- [ ] Restore drill passes
- [ ] Ingestion continues: reading count rising, all 3 heartbeats current
- [ ] **No reading rejected** — no 400s in the collector logs on any node
- [ ] New rows carry a non-null `ingested_at`
- [ ] N001's new rows resolve to deployment 4 / building 8
- [ ] N003's new rows are `bench` with NULL attribution
- [ ] `v_m5_contamination_window` stops growing
- [ ] Cost endpoints unchanged beyond live drift (control snapshot, as in M6)
- [ ] `/api/alerts/status` still reports only the known N002 finding
- [ ] Reconciliation report generated and reviewed

---

## 7. Success criteria

All must hold:

1. Zero readings rejected during and after cutover.
2. Zero invariant violations.
3. Every new reading has `node_id` set and `ingested_at` populated.
4. Attribution for N001 unchanged (open-ended deployment 4 covers it).
5. N003's new readings unattributed and `bench`, with no further contamination.
6. The buffered-replay test attributes measurements to the deployment covering
   each measurement's own timestamp, not to the newest.
7. Cost figures move only by live drift, proven against a control snapshot.
8. Reconciliation touched exactly the window and nothing earlier.

---

## 8. Failure criteria

Any one means the cutover has failed and must be rolled back:

1. Any reading rejected that the legacy path would have accepted.
2. Any invariant violation, especially INV-02, INV-15 or INV-16.
3. Any reading written with `node_id` NULL.
4. N001 readings becoming unattributed.
5. Reconciliation touching a row at or below `m5_n003_boundary`.
6. Cost figures moving beyond control-snapshot drift.
7. Collector buffers growing on any node.

---

## 9. Abort criteria

Stop **before** enabling the resolver — do not proceed to cutover — if:

1. The shadow report contains any `ambiguous_overlap` row.
2. The shadow report shows a disagreement for N001 that is not understood.
3. The buffered-replay test has not been performed, or its result does not
   match the prediction.
4. The pre-cutover restore drill fails.
5. Any invariant is failing before the cutover begins.
6. `energy_readings_pre_m4` or `m5_attribution_backup` is missing.
7. A node's declared `measurement_context` does not match its actual use —
   in particular **N003 must be confirmed as still on the bench**, or its
   readings will be classified wrongly the moment the resolver goes live.

Aborting is free. The shadow phase writes only to `shadow_attributions`, which
can be dropped with no effect on anything.

---

## 10. Recovery procedure

If the cutover fails after the resolver has written rows:

1. **Stop the bleeding.** Disable the resolver flag, `kill -HUP`. Ingestion
   returns to the legacy path within one sync cycle. Collectors buffer and
   retry, so nothing is lost.
2. **Bound the damage.** Rows written by the resolver are exactly
   `id > m8_freeze_point`, and independently identifiable by
   `ingested_at IS NOT NULL` — the legacy path never sets it. Two independent
   identifications of the same set.
3. **Assess.** Compare those rows against `shadow_attributions`. If the
   resolver's decisions were right and only the write mechanism failed, the data
   may be correct and need no repair.
4. **Repair, if needed.** Restore from `m8_reconciliation_backup` for the
   window; for rows above the freeze point, write a bounded supervised migration
   declaring `allow_attribution_change`, backed up and reversible like M5.
5. **Last resort.** Restore the pre-M8 backup, accepting the loss of readings
   ingested since. Only if steps 1–4 cannot produce a correct database — the
   edge buffers may still hold the affected measurements and can be replayed.

At no point is any historical reading deleted. `energy_readings_pre_m4`,
`m5_attribution_backup` and the reconciliation backup all remain until the soak
period completes and you approve cleanup.
