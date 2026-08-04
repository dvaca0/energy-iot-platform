# Deployment integrity — root cause and design

**Design document. No implementation. No production data modified.**

Goal: make overlapping attribution windows structurally impossible, and
understand exactly how the current invalid state entered the system.

---

## 1. Root cause analysis of Deployment 4

### The evidence

`deployments_pre_m3` is the untouched pre-M3 snapshot retained by the M3
rollback path:

```
pre-M3 : (4, node 1, bld 8, '2026-06-14', '2026-06-21', 'completed')
now    : (4, node 1, bld 8, '2026-06-14',  NULL,        'completed')
```

`migrations/versions/003_deployment_lifecycle.up.sql`, line 113:

```sql
UPDATE deployments SET end_date = NULL WHERE id = 4;
```

### The answer, precisely

| Question | Answer |
|---|---|
| Why `completed` with NULL `end_date`? | Two separate events, months apart in cause |
| Was it created that way by the application? | **No.** Created `active` with `end_date='2026-06-21'` |
| Was it manually edited? | **No.** No raw-SQL edit; the change is in a versioned migration |
| Which migration? | **M3 `003_deployment_lifecycle`, applied 2026-07-26T22:06:55** |
| Who authored it? | **I did.** It implements decision D1, which the platform owner approved |
| Incomplete transition? | **No.** Both halves completed normally |
| Expected under current rules? | **No.** It is incoherent, and nothing forbids it |

### Full history

1. **Created** by `POST /api/deployments` (`deployments.py:174`) with
   `status="active"` hard-coded and `end_date='2026-06-21'` from the technician
   form.
2. **Completed** by `POST /api/deployments/{id}/finish` (`deployments.py:263`),
   which sets `status = "completed"` and **does not touch `end_date`**. State
   after: `completed`, `2026-06-14 → 2026-06-21`. Coherent.
3. **Opened** by M3, D1: `end_date` set to NULL because 75 % of N001's readings
   fell outside their own declared campaign window, and the resolver would
   otherwise have stranded every future reading. State after: `completed` with
   an unbounded window. **Incoherent, and undetected.**
4. **Made harmful** on 2026-07-30 by the creation of deployment 6, which opened
   a second attributing window inside deployment 4's now-unbounded one.

Migration 008 (`physical_ratings_and_node_transitions`, not authored by me) only
`ADD COLUMN`s ratings to `deployments`. It did not touch dates or status.

### Why the framework allowed it

D1 was correct **under the assumption of one deployment per node**, which held
when it was applied. It was not guarded, because none of the following existed:

| Layer | What it checked | What it missed |
|---|---|---|
| CHECK constraints (M3) | date format; `end_date >= start_date` | status/window coherence |
| `INV-06` | status is a legal value | whether the window matches the status |
| Any invariant | — | overlap between deployments |
| Application | — | overlap; status/window coherence |

**The real defect is not the NULL.** It is that "a terminal status implies a
bounded window" and "one attributing window per node per instant" were never
expressed anywhere — not as a constraint, not as an invariant, not as a
validation. D1 was a legitimate operation that a missing rule allowed to become
invalid later.

I should have added the coherence rule when I made `end_date` nullable in M3.
Making a column nullable creates a new state space; M3 did not enumerate it.

---

## 2. Every path that can introduce an overlap

| # | Path | Location | Guard today |
|---|---|---|---|
| 1 | `POST /api/deployments` | `deployments.py:174` | **None.** No overlap check, no date validation beyond CHECKs. Hard-codes `status="active"`, so a new campaign is immediately attributing |
| 2 | `POST /api/deployments/{id}/finish` | `deployments.py:263` | Validates the transition; **never sets `end_date`** |
| 3 | `PUT /api/deployments/{id}/ratings` | migration 008 | Ratings only; safe |
| 4 | `app/db/seed.py:241,250` | seed | Not in the live path |
| 5 | Migrations / raw SQL | — | Invariants only; none covers overlap |

**No DELETE path exists** and there is **no date-editing endpoint** — deployment
dates cannot currently be changed through the API at all.

### The latent second defect

Path 2 sets `completed` without setting `end_date`. Today the create payload
requires `end_date` (`DeploymentCreate.end_date: str`), so a NULL cannot arrive
that way. But the column is now nullable, and the open-ended feature invites
making the field optional. **The moment it becomes optional, create → finish
reproduces deployment 4's exact invalid state through the normal application
path.** This is a trap waiting to be stepped in.

---

## 3. The decisive finding: day granularity cannot express the handover

```
last reading stamped deployment 4 : 2026-07-30 21:09:15.426
first reading stamped deployment 6: 2026-07-30 21:09:30.425
readings stamped dep 4 on 2026-07-30: 4,907
dep-4-stamped readings after dep 6 began: 0   → boundary is CLEAN
```

The nodes were switched over **mid-afternoon**, one 15-second sample apart, with
no interleaving. `start_date` / `end_date` are `YYYY-MM-DD`, so the window model
cannot represent this. Any day-granular repair is wrong:

| Repair | Result |
|---|---|
| dep 4 ends `2026-07-29` | 4,907 readings stamped dep 4 would resolve to dep 6 — mass mismatch |
| dep 4 ends `2026-07-30` | Still overlaps dep 6 on the 30th — `MULTIPLE_MATCHES` persists |

**With timestamp granularity, dep 4 ends `2026-07-30 21:09:15.426` and dep 6
starts `21:09:30.425`. Stored attribution and resolver attribution then agree on
every single reading, and not one historical row changes.**

This is the strongest argument in the document: the correct model is also the
only one that repairs the current state without touching data.

---

## 4. Proposed integrity model

### The invariant

> For any node, at most one deployment whose status occupies a window may cover
> any instant in time.

`MULTIPLE_MATCHES` becomes an integrity violation rather than a runtime outcome.
The resolver keeps the branch — defence in depth — but it becomes unreachable.

### Lifecycle rules, stated explicitly

| Question | Rule |
|---|---|
| When does `start_at` become authoritative? | At creation. It is the scheduled start and is required for every status |
| When does `end_at` become authoritative? | On transition to a terminal status. Before that, NULL means "no scheduled end" |
| When does attribution begin? | At `start_at`, inclusive, but only once the status has `allows_attribution` |
| When does attribution end? | At `end_at`, inclusive. NULL = unbounded |
| Which statuses occupy a window? | Everything except `cancelled` (new column `occupies_window`) |
| Which statuses attribute? | `active`, `completed` (existing `allows_attribution`) |

Two derived rules:

- **R1 — terminal implies bounded.** A status that is `is_terminal` and
  `allows_attribution` must have `end_at IS NOT NULL`. This is exactly what
  deployment 4 violates.
- **R2 — no overlap.** Two deployments of the same node, both
  `occupies_window`, must not have intersecting `[start_at, end_at]` ranges,
  where NULL end is +∞.

`planned` and `installing` occupy a window without attributing. They are
included in R2 so a scheduling conflict is caught when it is scheduled, not when
it activates. `cancelled` is a tombstone and blocks nothing.

### The transition question

> If an ACTIVE deployment exists and another is activated, should the previous
> one auto-close, require confirmation, or be rejected?

**Recommendation: reject (C), plus an explicit atomic supersede operation.**

| Option | Verdict |
|---|---|
| A — auto-close | **Rejected.** Silently writes an `end_at` the operator never chose, changing the meaning of readings in the overlap. That is precisely the class of silent semantic change this whole programme has been removing |
| B — operator confirmation | **Rejected.** A two-phase API flow that cannot be transactional from the client's side; a crash between phases leaves the invalid state |
| C — reject | **Correct default.** The system never changes what the operator did not name |

C alone is inconvenient — the operator must close deployment 4 before activating
6, and between the two calls the node has no active deployment. So C is paired
with one explicit operation that does both **in a single transaction**:

```
POST /api/deployments/{new_id}/activate
     { "supersede": {"deployment_id": 4, "end_at": "2026-07-30T21:09:15.426"} }
```

Both deployments are named, the boundary is named, and it either all commits or
none of it does. Nothing is inferred.

---

## 5. Database protections

SQLite has no `EXCLUDE` constraint (that is PostgreSQL). Ranked by strength:

| Mechanism | Viable | Verdict |
|---|---|---|
| `EXCLUDE USING gist` | No | Not available in SQLite |
| **`BEFORE INSERT/UPDATE` triggers with `RAISE(ABORT)`** | **Yes** | **Strongest available.** Enforces regardless of how the write arrives — app, raw SQL, or migration |
| Partial unique index | Partly | Cannot express range overlap |
| `CHECK` constraint | Partly | Can express R1 only by hard-coding `'completed'`, which breaks the lookup-table principle |
| Application validation | Yes | Necessary, not sufficient — bypassed by raw SQL |

**Recommendation: triggers as the primary guarantee.** Sketch:

```sql
CREATE TRIGGER trg_deployments_no_overlap_insert
BEFORE INSERT ON deployments
BEGIN
  SELECT RAISE(ABORT, 'deployment window overlaps an existing deployment for this node')
  WHERE (SELECT occupies_window FROM deployment_statuses WHERE code = NEW.status) = 1
    AND EXISTS (
      SELECT 1 FROM deployments d
        JOIN deployment_statuses s ON s.code = d.status
       WHERE d.node_id = NEW.node_id
         AND s.occupies_window = 1
         AND d.start_at <= COALESCE(NEW.end_at, '9999-12-31 23:59:59')
         AND NEW.start_at <= COALESCE(d.end_at, '9999-12-31 23:59:59')
    );
END;
```

Plus the mirrored `BEFORE UPDATE` trigger (excluding `OLD.id`), and a coherence
trigger for R1. Both read `deployment_statuses`, so semantics stay data.

Overlap test: `[a1,a2]` and `[b1,b2]` intersect iff `a1 <= b2 AND b1 <= a2`,
with NULL end coalesced to a sentinel far future.

**Defence in depth, three layers:**

1. **Database triggers** — cannot be bypassed, not even by a migration.
2. **Application validation** — returns a useful 409 before commit instead of a
   raw `SQLITE_CONSTRAINT`.
3. **Migration invariants** — `INV-17` (no overlap) and `INV-18` (terminal
   implies bounded), so the condition can never be introduced by a migration and
   can never survive one undetected.

---

## 6. Application protections

- `POST /api/deployments` — validate the window against existing deployments
  before commit; return **409** naming the conflicting deployment and its
  window. Stop hard-coding `status="active"`; create in the first non-terminal
  state.
- `POST /{id}/activate` — new. Validates node commissioning and window
  exclusivity; supports the atomic `supersede` payload above.
- `POST /{id}/finish` — require `end_at`, defaulting to the transition instant.
  Never leave a terminal deployment unbounded.
- `PATCH /{id}/window` — new, and the only way to change dates. Re-validates
  overlap. Refuses if the change would orphan or re-attribute existing readings
  without an explicit acknowledgement.
- All of the above inside one transaction with validation **before** commit.

---

## 7. Frontend — where validation is missing

Identification only; no UI redesign proposed.

| Location | Problem |
|---|---|
| `App.tsx:923` | Client-side check requires only that fields are non-empty. No overlap awareness |
| `App.tsx:939` | `createDeployment` assumes success; a 409 would surface as an unhandled error |
| `App.tsx:995-996` | Filters on the literal `"active"`; ignores `is_terminal` / `is_operational` already in the payload |
| `App.tsx:1175` | Free-text building field creates a new building on every spelling variant — how building 9 was created |
| `App.tsx:1025` | Shows `node.building` from the newest deployment by id, hiding the ambiguity |
| Form | No end-date-optional support, and no way to express "supersede deployment N" |

The frontend cannot currently *see* an overlap, let alone prevent one.

---

## 8. Migration plan

Same discipline as M0–M8: backup, restore drill, dry run on a copy, live, invariants, rollback verification.

| # | Migration | Risk | Notes |
|---|---|---|---|
| **M10** | `deployment_statuses.occupies_window` + backfill | Low | Additive; `cancelled = 0`, rest `1` |
| **M11** | Add `start_at` / `end_at` DATETIME; backfill from existing dates | Medium | Rebuild. `start_at = start_date 00:00:00`, `end_at = end_date 23:59:59.999`. Keeps `start_date`/`end_date` for API compatibility |
| **M12** | Integrity triggers + `INV-17` / `INV-18` | Medium | Must run **after** the overlap is repaired, or it aborts |
| **M13** | Application validation + new endpoints | Medium | Code only |

**M11 backfill and the repair are deliberately separate.** M11 preserves current
semantics exactly (deployment 4 stays unbounded); the repair is its own operator
decision, in §9.

---

## 9. The current overlap — correction options

**Which invariant failed?** None — none existed. Both R1 and R2 were absent.
Deployment 4 violates R1 (`completed`, unbounded); 4 and 6 together violate R2.

**This requires an operator decision. I will not set a date silently.**

| Option | Action | Consequence |
|---|---|---|
| **A (recommended)** | After M11, close deployment 4 at `2026-07-30 21:09:15.426` — its own last reading | Stored attribution and resolver attribution agree on **every reading**. **Zero historical rows change.** Both R1 and R2 satisfied |
| B | Close deployment 4 at `2026-07-29 23:59:59` | 4,907 readings stamped dep 4 on 07-30 would resolve to dep 6. Requires reconciliation of real production data |
| C | Cancel deployment 6 | Discards a real, intentional campaign. Rejected |

**Recommendation: A**, and only after M11 provides timestamp granularity.
It is the only option that satisfies the integrity rules without modifying a
single historical reading, and it records what physically happened: the node was
moved at 21:09 on 2026-07-30.

The value `21:09:15.426` is not invented — it is deployment 4's own last
reading, with the next sample already on deployment 6. Any instant in that
15-second gap works; the last reading is the most defensible.

**Awaiting explicit approval before applying.**

---

## 10. Automated tests

`backend/tests/test_deployment_integrity.py`, plain Python (pytest is not
installed), matching `test_monitoring.py`. All against a throwaway copy.

| Case | Expectation |
|---|---|
| Overlapping active deployments | Rejected at DB and API |
| Overlapping planned deployments | Rejected (`occupies_window = 1`) |
| Overlap with a cancelled deployment | **Allowed** — tombstones block nothing |
| Adjacent windows (`end_at` = next `start_at` − 1 µs) | Allowed |
| Touching windows (`end_at` == next `start_at`) | Rejected — inclusive bounds |
| Same-day handover at a timestamp | Allowed |
| Activating a second deployment without supersede | Rejected, 409 naming the conflict |
| Activating with atomic supersede | Both committed, or neither |
| Completing without `end_at` | Rejected (R1) |
| Completing sets `end_at` | Window becomes bounded |
| Editing dates into an overlap | Rejected |
| Editing dates of a completed deployment to unbounded | Rejected (R1) |
| Cancelling an overlapping deployment | Allowed; frees the window |
| Concurrent activation of two deployments | Exactly one succeeds |
| Race: insert during another transaction | Trigger fires inside the writer's transaction |
| Raw SQL bypassing the API | **Still rejected** by the trigger |
| Migration attempting an overlap | Rejected by `INV-17` |

The raw-SQL and migration cases matter most: they are what distinguish a real
guarantee from a convention.

---

## 11. Risk assessment

| Risk | Severity | Mitigation |
|---|---|---|
| M11 rebuild damages deployments | High | 3 rows; proven rename pattern; `deployments_pre_m11` retained; full up/down/up rehearsal |
| Triggers block legitimate operations | Medium | Tested against every existing row before install; `occupies_window` gives an escape via `cancelled` |
| Triggers block a future migration | Medium | Migrations may drop and reinstate them, exactly as M9's immutability trigger does |
| Timestamp backfill shifts attribution | **High** | `end_at = end_date 23:59:59.999` preserves inclusive day semantics exactly. Verified by re-running the shadow resolver before and after: decisions must be identical |
| Repair changes historical readings | **High** | Option A changes none. Verified by shadow comparison before committing |
| Frontend breaks on 409 | Low | `start_date`/`end_date` retained in the API payload |
| Trigger performance | Low | 3 rows; indexed by `idx_deployments_node_dates` |

**Backwards compatibility:** no historical reading is modified, no stored
attribution changes, and `start_date`/`end_date` remain in every API response.

---

## 12. Rollback strategy

| Layer | Action | Cost |
|---|---|---|
| Triggers | `DROP TRIGGER` | seconds |
| Application validation | restore `backups/*-before-m13-*`, `kill -HUP` | seconds |
| `start_at`/`end_at` | swap back `deployments_pre_m11` | seconds |
| `occupies_window` | `DROP COLUMN` | seconds |
| Repair | restore deployment 4's `end_at` from `deployments_pre_m11` | seconds |

Every step is independently reversible, and none touches `energy_readings`.

---

## 13. Final recommendation

1. **Adopt timestamp-granular windows (M11).** Day granularity cannot express
   the handover that already happened, and no day-granular repair is correct.
2. **Enforce at three layers**: triggers (guarantee), application (usable
   errors), invariants (migration safety).
3. **Reject on conflict; supersede only when explicitly asked**, atomically.
4. **Repair via option A** — close deployment 4 at its own last reading —
   changing zero historical rows. **Operator approval required.**
5. **Order:** M10 → M11 → repair → M12 → M13. Triggers go in *after* the repair,
   or they abort on the existing violation.
6. **Fix the latent trap in `/finish`** (terminal without `end_at`) in the same
   pass. It is the same defect as deployment 4, reachable through the normal
   application path the moment `end_date` becomes optional.

The lesson generalises: **M3 made a column nullable without enumerating the new
state space it created.** Any future migration that widens a domain should be
required to state which combinations are legal and add the constraint in the
same step.

Awaiting review before implementation.
