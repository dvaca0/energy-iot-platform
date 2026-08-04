# M11 backfill validation — for approval before any value is written

**Nothing written. This is the pre-execution report.**

`activated_at` and `closed_at` do not yet exist as columns. This report states
exactly which rows will receive values, what those values are, where each one
comes from, and what must remain byte-identical.

---

## Current columns

```
id, node_id, building_id, electrical_panel_id, start_date, end_date, status, notes,
panel_main_breaker_a, ct_max_current_a, nominal_voltage_v, phase_count,
warning_current_a, critical_current_a, emergency_current_a, sustained_seconds
```

`activated_at` and `closed_at` are **absent**. M11 adds them.

---

## Rows affected: 3 of 3

### Deployment 4 — N001, completed

| | |
|---|---|
| Current `start_date` / `end_date` | `2026-06-14` / **NULL** (the D1 artifact) |
| Attributed readings | **118,620**, none of them contamination artifacts |
| First attributed reading | `2026-06-14 21:57:34.692460` |
| Last attributed reading | `2026-07-30 21:09:15.426000` |

| New field | Proposed value | Source | Justification |
|---|---|---|---|
| `activated_at` | `2026-06-14 21:57:34.692460` | its own **first** attributed reading | The instant this deployment demonstrably began attributing. Measured, not chosen. |
| `closed_at` | `2026-07-30 21:09:15.426000` | its own **last** attributed reading | The instant it demonstrably stopped. Closes the unbounded window that D1 created, satisfying R1 (terminal + attributing ⇒ bounded). |

### Deployment 5 — N003, completed

| | |
|---|---|
| Current `start_date` / `end_date` | `2026-06-14` / `2026-06-21` |
| Attributed readings | **32 — all 32 are contamination-window artifacts** |
| First / last attributed reading | `2026-07-26 22:40:16` / `2026-07-26 23:06:29` |

| New field | Proposed value | Source | Justification |
|---|---|---|---|
| `activated_at` | `2026-06-14 00:00:00.000` | its `planned_start`, start of day | **Its readings are not usable as a source.** All 32 are known artifacts of the M5→M8 contamination window, dated a month after the campaign, and are scheduled for reconciliation at the M8 cutover. Using them would record a June campaign as having run in July. The planned dates are the only honest evidence available. |
| `closed_at` | `2026-06-21 23:59:59.999` | its `planned_end`, end of day | Same reasoning. Reproduces the current window semantics exactly. |

This is the one row where the backfill is **not** derived from readings, and the
reason is explicit: its readings are the defect, not the evidence.

### Deployment 6 — N001, active

| | |
|---|---|
| Current `start_date` / `end_date` | `2026-07-30` / `2026-08-07` |
| Attributed readings | **260**, none of them contamination artifacts |
| First attributed reading | `2026-07-30 21:09:30.425000` |

| New field | Proposed value | Source | Justification |
|---|---|---|---|
| `activated_at` | `2026-07-30 21:09:30.425000` | its own **first** attributed reading | The instant it demonstrably began attributing. |
| `closed_at` | **NULL** | — | Still `active`. A non-terminal deployment has no close time; NULL means "no scheduled end", which is correct and permitted. |

---

## The handover, measured

```
deployment 4 last reading   2026-07-30 21:09:15.426000
deployment 6 first reading  2026-07-30 21:09:30.425000
gap                         14.999 s   (exactly one 15 s sampling interval)
N001 readings inside gap    0
```

Deployment 4 closes and deployment 6 opens inside a single sampling interval
containing no readings. There is no instant at which both windows are open, and
no reading falls in the gap.

---

## Rule 6 consistency

Rule 6 governs **future activations** through the API. It does not apply to the
initialisation of historical records — but the proposed values are checked
against it anyway, and deployment 6 satisfies it:

| Dep | Proposed `activated_at` | Latest reading on that node attributed elsewhere | Consistent |
|---|---|---|---|
| 6 | `2026-07-30 21:09:30.425` | `2026-07-30 21:09:15.426` (deployment 4's last) | **yes** — later, as required |
| 5 | `2026-06-14 00:00:00` | none | yes (vacuous) |
| 4 | `2026-06-14 21:57:34.692` | n/a — predates deployment 6 entirely | n/a |

---

## What must remain byte-identical

Recorded before execution. These SHA-256 values are re-computed after M11 and
must match exactly:

| Dep | Fields `(id, node_id, building_id, electrical_panel_id, start_date, end_date, status, notes)` | SHA-256 (16) |
|---:|---|---|
| 4 | `(4, 1, 8, 8, '2026-06-14', None, 'completed', '')` | `02ae441ddc9ae2c6` |
| 5 | `(5, 3, 8, 8, '2026-06-14', '2026-06-21', 'completed', '')` | `e287bd8ab0c3d6f3` |
| 6 | `(6, 1, 9, 9, '2026-07-30', '2026-08-07', 'active', '')` | **`5939fa35fb0abe9c`** |

**Deployment 6's identity, node, building, panel, planned dates and status are
not touched.** Only its new `activated_at` column is populated. The checksum is
the proof, and it is an acceptance criterion of the migration — a mismatch
aborts and rolls back.

The eight physical-ratings columns from migration 008 are all NULL on all three
rows and are not touched either.

---

## Acceptance criteria for M11

All must pass or the migration rolls back:

1. The three identity checksums above are unchanged.
2. All 16 invariants clean.
3. Restore drill passes.
4. **Shadow verification**: re-run the resolver against the new windows.
   `ATTRIBUTION_DIFFERS` must be **exactly the 32 contamination rows and nothing
   else**. Any other disagreement means the backfill is wrong.
5. No `energy_readings` row modified — guaranteed by INV-01, INV-02, INV-15,
   INV-16.

Criterion 4 is the strong one: it verifies across all ~226,000 readings that
stored attribution and resolvable attribution agree everywhere except the single
set already known to be wrong and already scheduled for reconciliation.

---

## Summary

| Dep | `activated_at` | `closed_at` | Derived from |
|---:|---|---|---|
| 4 | `2026-06-14 21:57:34.692460` | `2026-07-30 21:09:15.426000` | its own readings |
| 5 | `2026-06-14 00:00:00.000` | `2026-06-21 23:59:59.999` | planned dates (readings are artifacts) |
| 6 | `2026-07-30 21:09:30.425000` | `NULL` | its own first reading |

Awaiting approval before execution.
