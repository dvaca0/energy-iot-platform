# M13 — deployment API review, before implementation

The API's job is to let an operator *perform actions*. Its job is not to let
them edit rows. Today it does the second.

Reviewed against the state machine settled in the final architecture review.

---

## 1. Every endpoint, as it is and as it should be

### `POST /api/deployments` — create

| | |
|---|---|
| **Current** | Raw `INSERT` with `status="active"` hard-coded (`deployments.py:184`). No lifecycle. No exclusivity check. No backdating check. This is the endpoint that created deployment 6 directly into `active`, overlapping deployment 4, with nothing to stop it |
| **Desired** | Creates in `planned`. If the caller wants a working deployment immediately — which the technician form does — it walks `planned → installing → active` **inside one transaction**, applying every guard |
| **Transition** | none, or `planned → installing → active` |
| **Auto-written** | `activated_at = now()` only if activated |
| **Validation** | node exists and is `commissioned`; no other live deployment on that node; no backdating |
| **Failures** | `404` node unknown · `409` node not commissioned · `409` another deployment live · `409` backdating |

### `POST /api/deployments/{id}/finish` — complete

| | |
|---|---|
| **Current** | Sets `status="completed"`, `node.status="available"`, zeroes `buffer_pending`. **Never sets an end time.** This is the latent trap: the moment the create payload allows a null end, create→finish reproduces deployment 4's exact invalid state |
| **Desired** | Kept as a compatibility alias for `POST /{id}/complete`. Writes `closed_at` |
| **Transition** | `active → completed` |
| **Auto-written** | `closed_at = now()` |
| **Validation** | transition legal; deployment was activated; warn on pending buffer (`dry_run`) |
| **Failures** | `404` · `409` never activated · `409` illegal transition |

### `GET /api/deployments` — list

| | |
|---|---|
| **Current** | Leaks storage concepts: `allows_attribution`, `is_terminal`, `legal_transitions` (raw state names), `is_open_ended` (derived from `end_date`, which is now planning metadata and so misleading) |
| **Desired** | Business concepts only. `available_actions` replaces `legal_transitions`. `measuring_since` / `measuring_until` express the operational window without naming columns. Legacy flat keys retained |
| **Failures** | — |

### `GET /api/deployments/lifecycle` — vocabulary

Correct as-is. Publishes the canonical states so no client restates them.
Gains `actions` so a UI can render buttons without knowing state names.

### `GET|PUT /api/deployments/{id}/ratings` — physical ratings

Out of scope. Touches no lifecycle field.

### Missing entirely

`PATCH /{id}` (edit planning info) · `POST /{id}/begin-installation` ·
`POST /{id}/activate` · `POST /{id}/complete` · `POST /{id}/cancel` ·
`GET /{id}`. **There is currently no way to move a deployment through its
lifecycle except by creating it already active and later finishing it.** The
five-state machine exists in the database and is unreachable from the API.

---

## 2. Operations the API will expose

Named after what the operator is doing, not what the row does.

| Action | Endpoint | Transition | Written automatically |
|---|---|---|---|
| Plan a campaign | `POST /api/deployments` | → `planned` | — |
| Correct the plan | `PATCH /api/deployments/{id}` | none | — |
| Begin installation | `POST /{id}/begin-installation` | `planned → installing` | — |
| Start measuring | `POST /{id}/activate` | `installing → active` | `activated_at` |
| Finish measuring | `POST /{id}/complete` | `active → completed` | `closed_at` |
| Call it off | `POST /{id}/cancel` | `* → cancelled` | `closed_at` |

The operator never types, sees, or reasons about `activated_at`, `closed_at`,
`is_exclusive`, or window coherence.

---

## 3. Atomicity — transaction boundaries

Every transition is one transaction. Validation happens **before** commit;
nothing partial can survive.

| Operation | Boundary |
|---|---|
| Create (plan only) | single `INSERT` |
| Create + activate | **one transaction** spanning building/panel resolution, `INSERT`, and both transitions. A failure at any point leaves no deployment |
| Begin installation | one `UPDATE`, guarded by the exclusivity index |
| Activate | one `UPDATE` setting `status` and `activated_at` together — they must be simultaneous or R2 aborts |
| Activate **with supersede** | **one transaction**: close the previous deployment *and* activate the new one. Both or neither |
| Complete / cancel | one `UPDATE` setting `status` and `closed_at` together |

FastAPI's `get_db` yields one session per request, so a raised `HTTPException`
before `commit()` discards everything.

---

## 4. Errors state the business rule

| Situation | Response |
|---|---|
| Another deployment live | `409` — "Cannot start measuring: deployment 6 is already active on node N001 since 2026-07-30 21:09. Complete it first, or supersede it explicitly." |
| Never activated | `409` — "Cannot complete: this deployment has never been activated." |
| Readings attributed | `409` — "Cannot cancel: 118,620 readings are attributed to this deployment. Complete it instead." |
| Backdating | `409` — "Cannot start measuring at X: node N001 already has readings up to Y." |
| Editing an activated field | `409` — "Cannot change the building: this deployment started measuring on X. Create a new deployment." |
| Node not commissioned | `409` — "Cannot start measuring: node N002 is registered, which is not permitted to upload." |
| Illegal transition | `409` — "Cannot X a deployment that is Y. From Y you may: …" |

Database constraint text is never returned. The triggers stay as the last line
of defence; the application is expected to catch every case first.

---

## 5. Internal leaks removed

| Field | Action |
|---|---|
| `allows_attribution` | removed — folded into `available_actions` |
| `is_terminal` | removed — folded into `available_actions` |
| `legal_transitions` | replaced by `available_actions` (verbs, not state names) |
| `is_open_ended` | removed — derived from `end_date`, which is no longer authoritative |
| `activated_at` / `closed_at` | never exposed under those names; surfaced as `measuring_since` / `measuring_until` |
| `is_exclusive` | never exposed |

Verified against the frontend: it consumes `id`, `node_id`, `building_name`,
`campus`, `organizational_unit`, `electrical_panel`, `start_date`, `end_date`,
`status`, `notes`. **None of the removed fields is consumed** — they were added
in M7 and never used.

---

## 6. Compatibility

| Endpoint | Old | New | Strategy |
|---|---|---|---|
| `POST /api/deployments` | Creates `active` | Creates `planned`, activates when asked | Defaults to activating, so the existing form behaves identically — but now through validated transitions. Pass `"activate": false` to plan only |
| `POST /{id}/finish` | Completes without an end time | Alias for `/complete`, writes `closed_at` | Same path, same `dry_run`, same response keys |
| `GET /api/deployments` | Flat keys + M7 internals | Flat keys + business concepts | All flat keys retained; only unused internals removed |
| `reports.deployments` | `real_start`/`real_end` computed from readings | Same keys, now backed by `activated_at`/`closed_at` where present | Key names unchanged |

No frontend change required. No collector change. No write-path change.

---

## 7. Verdict

The current API exposes row mutation, not lifecycle. `POST /api/deployments`
writing `status="active"` directly is the same class of defect as the original
integrity failure: a valid-looking operation with no rule behind it.

The design above is the API expressing the state machine. Proceeding to
implementation.
