# Investigation — where every displayed building name comes from

**Investigation only. Nothing was modified: no code, no SQL, no migration, no
data, no flag. Deployment 6 was not touched.**

Trigger: after creating deployment 6 ("Edificio Principal Prueba", N001, active,
2026-07-30 → 2026-08-07), the UI shows building information that looks
inconsistent with deployment state.

Conclusion up front: the observation is real, and it has **two independent
causes**. One is benign presentation. The other is a **cutover blocker** that was
not visible before deployment 6 existed.

---

## 0. Current state

| Deployment | Node | Building | Panel | Window | Status |
|---:|---|---|---|---|---|
| 4 | N001 | 8 `Edificio de prueba` (placeholder) | 8 | 2026-06-14 → **NULL** | `completed` |
| 5 | N003 | 8 `Edificio de prueba` (placeholder) | 8 | 2026-06-14 → 2026-06-21 | `completed` |
| 6 | N001 | 9 `Edificio Principal Prueba` | 9 | 2026-07-30 → 2026-08-07 | **`active`** |

| Node | commission_state | context | last_sync |
|---|---|---|---|
| N001 | commissioned | production | current |
| N002 | **registered** | production | 2026-07-29 |
| N003 | **registered** | bench | 2026-07-26 |

Readings: N001 118,620 on (dep 4 / bld 8) and 28 on (dep 6 / bld 9); N003
123,696 all de-attributed except 32 contamination-window rows.

---

## 1. Where building information is **stored**

Exactly two places. Both are correct.

| Location | Meaning |
|---|---|
| `buildings.id/name/is_placeholder` | The building catalogue |
| `deployments.building_id` | Which building a campaign measures |
| `energy_readings.building_id` | Which building a reading counts toward, stamped at ingest, immutable |

**`nodes` has no building column.** Correct — under the architecture a node does
not own a building.

---

## 2. Where building information is **computed**

This is the problem. There are **three independent derivations** of "the building
for node X", each answering a different question, none named as such.

### Derivation A — newest deployment by id

`backend/app/routers/nodes.py:21` `_node_payload()`

```python
deployment = (db.query(Deployment)
              .filter(Deployment.node_id == node.id)
              .order_by(Deployment.id.desc())    # line 32
              .first())
...
"building": deployment.building.name if deployment else None
```

**No status filter, no date filter.** Whichever deployment row has the highest
id wins — `planned`, `cancelled`, `completed`, anything.

Feeds: `GET /api/nodes`, `GET /api/nodes/online`.

### Derivation B — building on the latest production reading

- `backend/app/routers/metrics.py:91` — `latest.building.name`
- `backend/app/routers/infra.py:54` — `latest.building.name`

where `latest` is the most recent **production-context reading** for that node.
This asks "where did this node's last measurement count?", which is a different
question from A.

Feeds: `GET /api/metrics/live`, `GET /api/infra`.

### Derivation C — aggregate over readings

`backend/app/routers/dashboard.py:79` and `:131` — readings grouped by
`r.building.name` over a time window, producing `most_expensive_building`.

Feeds: `GET /api/dashboard/summary`.

### Derivation D — the deployment's own building

`backend/app/routers/deployments.py:60` — `deployment.building.name`, and
`:254` in the finish endpoint. This one is unambiguous and correct: a
deployment's building is a stored fact about that deployment.

Feeds: `GET /api/deployments`, `POST /api/deployments/{id}/finish`.

### What each currently returns

| Source | N001 | N003 |
|---|---|---|
| A `/api/nodes` | `Edificio Principal Prueba` (dep 6) | `Edificio de prueba` (dep 5) |
| B `/api/metrics/live`, `/api/infra` | `Edificio Principal Prueba` | `Edificio de prueba` |
| C `/api/dashboard/summary` | `most_expensive_building = Edificio de prueba` | — |
| D `/api/deployments` | per row: 6→Principal, 4→prueba | 5→prueba |

A and B agree for N001 **by coincidence** — the newest deployment happens also to
be where the newest readings landed. They will diverge the moment a deployment is
created before any reading is taken under it, or a node is reassigned.

---

## 3. Where building information is **cached**

**Nowhere.** This is not a caching problem.

- `localStorage` holds only `energy_auth`, `energy_role`, `energy_user`
  (`App.tsx:338–349, 2282, 2362`).
- `PageDeployments` polls every 15 s (`App.tsx:878–882`) and replaces state
  wholesale. No memoisation, no SWR, no react-query.
- Backend module caches (`lifecycle`, `commissioning`, `scope`) hold lifecycle
  vocabularies, not building names.
- The served bundle `frontend/dist/assets/index-5ZjZHWUE.js` contains the same
  `"Sin despliegue"` / `"Sin edificio"` strings as source, so dev and prod agree.

---

## 4. Where building information is **displayed**

| # | Location | Field | Source |
|---|---|---|---|
| 1 | `App.tsx:1025` — **Deployments page, node card** | `node.building \|\| "Sin despliegue"` | **A** |
| 2 | `App.tsx:1043` — past deployments list | `deployment.building_name` | D |
| 3 | `App.tsx:1073` — active deployments card | `deployment.building_name` | D |
| 4 | `App.tsx:973` — finish confirmation dialog | `check.building` | D |
| 5 | `App.tsx:1260` — live monitoring list | `n.building \|\| "Sin edificio"` | B |
| 6 | `App.tsx:2039` — infrastructure page | `node.building \|\| "Sin edificio"` | A |
| 7 | `App.tsx:520` — dashboard "Edificio más costoso" | `most_expensive_building.name` | C |
| 8 | `App.tsx:514` — dashboard cost subtitle | `most_expensive_building.name` | C |
| 9 | `App.tsx:491` — building metrics chart | `item.building_name` | metrics/buildings |
| 10 | `App.tsx:1824, 1894` — reports | `deployment.building_name` | D |
| 11 | `App.tsx:2321` — campus map | `node.building` | A |

**The card you observed is #1**, fed by derivation A.

### The complete chain for the node card

```
buildings.name (id 9, 'Edificio Principal Prueba')
  ▲ FK
deployments.building_id            deployment 6, status='active'
  ▲ selected by  ORDER BY id DESC LIMIT 1   ← no status filter, no date filter
backend/app/routers/nodes.py:32   _node_payload()
  ▲
GET /api/nodes  →  field "building"
  ▲
App.tsx:874  getNodes().then(setNodes)     polled every 15 s
  ▲
App.tsx:1025  {node.building || "Sin despliegue"}
```

---

## 5. Classification of the observed behaviour

| Finding | Class |
|---|---|
| F1 — node card shows newest deployment's building regardless of status | **Architectural inconsistency** |
| F2 — N003 shows a building despite being de-attributed and `registered` | **Architectural inconsistency** (same root cause as F1) |
| F3 — three unnamed derivations of "node's building" | **Architectural inconsistency** |
| F4 — node card says "Principal Prueba", dashboard says "de prueba" | **Correct** — different questions, presented without distinction (presentation issue) |
| F5 — deployments 4 and 6 both claim today → `MULTIPLE_MATCHES` | **Architectural inconsistency + CUTOVER BLOCKER** |
| F6 — nothing prevents overlapping attributing windows | **Backend / schema gap** |
| F7 — deployment creation writes `status="active"` directly | **Backend issue** |
| F8 — frontend restates lifecycle values | **Frontend issue** |
| F9 — same field, two fallback strings | **Frontend issue** (cosmetic) |
| F10 — "Despliegues Pasados" = everything not `active` | **Frontend issue** |

---

## 6. Each inconsistency: why, what leaks, what would be correct

### F5 — Overlapping deployments (the blocker)

**Why.** Deployment 4 is `completed` with `end_date = NULL`. `completed` has
`allows_attribution = 1` by design — a finished campaign still owns the readings
it took. But `end_date = NULL` means *unbounded*, so deployment 4 also claims
every future instant. Deployment 6 then opened a window inside that unbounded
one.

Verified with the resolver:

```
dep=4  2026-06-14 -> None          status=completed  allows_attribution=True
dep=6  2026-07-30 -> 2026-08-07    status=active     allows_attribution=True

2026-07-29  → dep=4  ATTRIBUTED_IN_WINDOW
2026-07-30  → None   MULTIPLE_MATCHES  candidates=(4, 6)
2026-08-01  → None   MULTIPLE_MATCHES  candidates=(4, 6)
2026-08-08  → dep=4  ATTRIBUTED_IN_WINDOW      ← reverts to the placeholder
```

**4,947 readings** since 2026-07-30 currently resolve to `MULTIPLE_MATCHES`.

**What leaks.** The idea that "completed" bounds a campaign in time. It does not
— status and window are independent, and nothing enforces their coherence. The
D1 decision (open-ending deployment 4 so N001's data was not stranded) was
correct in a world with one deployment per node, and silently became a
contradiction when a second was added.

**What would be architecturally correct.** `status = 'completed'` should imply a
closed window: a completed campaign has ended, so `end_date` must be non-null.
Additionally, no two deployments for the same node whose statuses allow
attribution should have overlapping date ranges. Neither rule is expressed
anywhere — there is no CHECK, no unique index, and no application validation
(`deployments` has only format and `end_date >= start_date` CHECKs).

**Consequences right now.** The legacy ingest path resolves the ambiguity
silently by taking `ORDER BY id DESC` — which is why the 28 newest readings
landed on deployment 6. The resolver refuses. **Old and new behaviour now
disagree on live data, and the gap grows by ~5 readings/minute.** This is abort
criterion 1 in the cutover runbook: the cutover is blocked until the overlap is
resolved administratively.

### F1 / F2 — the node card

**Why.** `_node_payload` selects `ORDER BY Deployment.id.desc()` with no filter.
"Newest deployment by primary key" is not a concept the architecture defines.

**What leaks.** *Node owns a building* — the pre-redesign model. The field
`/api/nodes.building` is a survival of it: it presents a node as being "in" a
building, when under the current architecture a node is only ever *assigned to a
campaign*, and a **reading** is what belongs to a building.

N003 makes the leak visible: it is `registered` (may not upload), its deployment
is `completed`, and **every one of its 123,696 readings has
`building_id = NULL`** — yet the UI states it is in "Edificio de prueba". No
reading supports that claim.

**What would be architecturally correct.** A node has no building. If the UI
needs to show where a node is *currently assigned*, the defined concept is *the
deployment(s) whose status `is_operational` and whose window covers now* — and
that query can legitimately return zero (unassigned) or, today, more than one
(ambiguous), both of which the UI should be able to say. Silently picking the
highest id is exactly the class of hidden tiebreak the redesign removed from
ingestion.

### F3 — three derivations

**Why.** Each endpoint grew its own answer at a different time. B was corrected
during M5/M6 to read `reading.building` instead of
`reading.deployment.building`; A was never revisited because it starts from a
node, not a reading.

**What leaks.** That "the building of a node" is one well-defined thing. It is
not. There are three distinct questions and the API uses one field name,
`building`, for all of them.

**What would be correct.** Name the question in the field:
assignment-by-deployment, last-measured-building, and highest-consuming-building
are three different values and should not share an identifier.

### F4 — dashboard vs node card (not a bug)

`most_expensive_building` = `Edificio de prueba` because 118,620 of N001's
readings are attributed there against 28 on the new building. The node card says
`Edificio Principal Prueba` because that is the newest deployment. **Both are
accurate answers to different questions.** The inconsistency is presentational:
neither label tells the reader which question it answered.

### F7 — creation bypasses the lifecycle

`deployments.py:184` still writes `status="active"` directly. Flagged during M3
and deliberately deferred to preserve behaviour. Its consequence is now
concrete: deployment 6 was created **immediately active and immediately
overlapping** deployment 4, with no `planned` → `installing` stage at which an
overlap check could have run and no validation that one was needed.

**Correct behaviour:** creation enters the first non-terminal state and reaches
`active` only through a transition that validates node commissioning and window
exclusivity.

### F8 / F9 / F10 — frontend

- `App.tsx:995-996` filters on the literals `"active"` / `!== "active"`. The
  payload already carries `is_terminal`, `is_operational` and `legal_transitions`
  from `/api/deployments`, and `/api/deployments/lifecycle` publishes the
  vocabulary — none is used. A `planned` deployment would be filed under
  "Despliegues Pasados".
- The same field renders as `"Sin despliegue"` at `App.tsx:1025` and
  `"Sin edificio"` at `App.tsx:2039`. Two different claims from one null.
  Under the architecture the accurate statement is "no deployment covers this
  node now", which is not the same as "no building".
- The Deployments page has no representation for `planned`, `installing` or
  `cancelled`, and no way to show that a node's assignment is ambiguous.

---

## 7. Answer to the direct question

> Under the new architecture, does a Node still own a building? Or should
> building ownership exist ONLY through an active deployment?

**A node does not own a building.** Ownership is:

- A **deployment** names a building — that is a stored fact about the campaign.
- A **reading** names a building — stamped at ingest from the deployment
  covering its own `captured_at`, then immutable.
- A **node** names neither. It has identity, commissioning state and declared
  measurement context.

`/api/nodes.building` therefore has no architectural basis. It is the last
substantial remnant of the pre-redesign model, and it is the field feeding the
card you noticed.

One refinement: "only through an **active** deployment" is slightly too strict.
`completed` deployments legitimately retain attribution of their historical
readings (ADR-0004) — that is why a finished campaign's data stays in its
building. The precise rule is *the deployment whose window covers the instant in
question and whose status allows attribution* — which for "where is this node
now?" means an operational deployment covering now, and for "where does this
reading belong?" means whatever covered `captured_at`.

---

## 8. Additional observation, outside the reported scope

`app/db/commissioning.py` has gained transition machinery
(`node_commission_transitions`, `node_commission_events`) via migration 008
`physical_ratings_and_node_transitions`, which I did not author. Both tables
exist and are populated (8 transitions, 2 events), so the code is consistent
with the schema.

Related: N002 and N003 are now `registered` rather than `commissioned`. Under
`node_commission_states`, `registered` has `may_upload = 0`. The ingest path does
not yet consult `may_upload` — that check arrives with the resolver in M8 — so
this has no effect today, but on cutover **N002 and N003 would stop being
authorized to upload**. Worth confirming that is intended before cutover.

---

## 9. Summary

Nothing in the frontend is caching stale data, and nothing in the database is
wrong. What you observed is two things at once:

1. A **benign** difference — the dashboard's most-expensive building and the node
   card's building are different questions with different correct answers.
2. A **serious** one — deployment 6 overlapping open-ended deployment 4 has made
   4,947 readings ambiguous under the resolver, and the node card is reading from
   a derivation that has no architectural definition and silently hides that
   ambiguity by taking the highest id.

The second is a cutover blocker. No changes proposed here; awaiting review.
