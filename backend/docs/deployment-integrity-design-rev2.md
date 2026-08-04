# Deployment integrity — design revision 2

**Architecture review response. No implementation, no schema, no data changes.**

Revision 1 proposed converting `start_date`/`end_date` to timestamps. After the
review challenge I am **withdrawing that proposal** and replacing it with a
different model. What follows is the argument, not a defence of what was already
written.

---

## Q1 — Is timestamp granularity genuinely domain-required?

**The requirement is real. My proposed way of meeting it was wrong.**

### The requirement is not an artifact

Deployment 4 is not a one-off. Relocation is this platform's *core operational
activity*: a small number of expensive nodes rotate around many buildings on
week-long campaigns. Every relocation happens at a specific moment during a
working day — a technician removes a node in the morning and installs it
elsewhere in the afternoon.

At a 15-second cadence that is **5,760 readings per node per day**. Projected at
3 nodes on weekly campaigns over five years: ~780 relocations, and up to
**4.5 million readings** falling on an ambiguous day.

Day granularity does not fail occasionally. It fails on **every same-day
relocation**, which is the normal case. So sub-day precision is genuinely
required by the domain, permanently, independent of deployment 4.

### But my proposal met it the wrong way

Revision 1 said: make `start_date`/`end_date` timestamps. Two objections, and the
second is decisive.

**First**, it forces operators to schedule in timestamps. Nobody plans a campaign
to the millisecond. The technician form would ask for a precision the human
process does not have.

**Second — and this is what changes the design — it destroys information the
domain actually needs.** Deployment 4 was *scheduled* 2026-06-14 → 06-21 and
*actually ran* until 2026-07-30. Those are both facts. The one-field model can
hold only one of them, which is exactly why D1 had to overwrite `end_date` with
NULL: **to express the actual state, it destroyed the planned state.**

D1 was not a mistake in judgement. It was the only move available in a model
that cannot represent a campaign running past its schedule. The model was the
defect.

### The simpler alternative

Do not make the schedule more precise. **Separate the schedule from what
happened**, and derive attribution from the latter:

| Field | Type | Meaning | Authoritative for |
|---|---|---|---|
| `planned_start` | DATE | When we intend to start | scheduling, reporting |
| `planned_end` | DATE NULL | When we intend to finish | scheduling, reporting |
| `activated_at` | DATETIME NULL | When measurement actually began | **attribution start** |
| `closed_at` | DATETIME NULL | When measurement actually ended | **attribution end** |

Attribution window = `[activated_at, COALESCE(closed_at, ∞)]`.

The two timestamps are **never typed by a human**. They are written by the
lifecycle transitions — `activated_at` when the deployment becomes `active`,
`closed_at` when it becomes terminal. Sub-second precision arrives for free,
because the system records when the transition happened.

This is more columns and *less* complexity: no operator learns a new input
format, and the timestamps cannot drift from reality because they are not
independently editable facts — they are transition records.

---

## Q2 — Should `planned` and `installing` reserve time?

**My revision-1 answer was wrong. `planned` must reserve nothing.**

Your example settles it:

```
Monday    planned   Building A
Tuesday   planned   Building B
```

Nothing is installed. Rejecting this would make the system useless as a planning
tool, and planning is most of what a campaign schedule is *for*. Under revision 1
this would have been rejected, because I made `occupies_window` true for
`planned`. That was over-reach: I generalised "prevent overlap" into "prevent
scheduling", which are different things.

### Separating the three concepts

| Concept | Begins at | What it constrains |
|---|---|---|
| **Planning** | row created as `planned` | nothing — a calendar entry |
| **Physical installation** | transition to `installing` | the **node**: it is one object, in one place |
| **Measurement attribution** | transition to `active` | the **attribution window** |

These genuinely do not begin simultaneously, and conflating them is what
produced my error.

**`planned` constrains nothing.** Plan freely, including contradictory plans —
reality resolves them.

**`installing` constrains the node, not the window.** A node cannot be physically
installed in two buildings at once. But `installing` does not attribute
(`allows_attribution = 0` today, correctly): commissioning readings taken during
installation are classified `commissioning` context and excluded from analytics.

**`active` is the authoritative transition for attribution.** That is the moment
someone asserts "this node is now measuring this panel for real".

### The resulting constraint

Not a range constraint. A **current-state** constraint:

> At most one deployment per node may be in an exclusive state
> (`installing` or `active`) at any moment.

Non-overlap of attribution windows then follows *structurally*: deployment B can
only become `active` after A has left the exclusive set, and A's `closed_at` is
written at that moment. Windows cannot overlap because they are created by
mutually exclusive transitions.

This is a much stronger position than checking ranges after the fact.

---

## Q3 — Planned schedule vs actual execution?

**Yes, and deployment 4 is the proof.** I did not reach this by wanting more
fields; I reached it by asking what D1 destroyed.

Deployment 4: planned 06-14 → 06-21 (one week), actual 06-14 → 07-30 (six and a
half weeks). Both true. The current model can hold one.

Three concrete benefits:

1. **D1 becomes unnecessary in hindsight.** Under this model D1 is:
   `planned_end` stays `2026-06-21`, `closed_at` stays NULL. Nothing overwritten,
   no incoherent state, no information lost. **The invalid state could not have
   been created.**
2. **The repair becomes honest.** Setting `closed_at = 2026-07-30 21:09:15.426`
   records *when the node stopped measuring for that campaign* — a fact.
   Revision 1's repair edited the campaign's end date, rewriting a plan to
   describe an outcome.
3. **Schedule adherence becomes reportable.** "Campaigns ran on average N days
   longer than planned" is a legitimate thesis output, currently impossible.

The distinction is not speculative complexity. It is already present in the data
and currently unrecordable.

---

## Q4 — Repair strategies

| Option | Advantages | Disadvantages | Historical correctness | Maintainability |
|---|---|---|---|---|
| **A** Timestamps on start/end *(rev 1)* | Fixes granularity | Destroys planned vs actual; forces timestamp scheduling | Overwrites a real planned date | Poor — repeats D1's flaw |
| **B** Operator picks a day boundary | Human decision | **No valid day exists.** 07-29 mis-resolves 4,907 rows; 07-30 keeps the overlap | Impossible to be correct | n/a |
| **C** Document and tolerate | No change | Resolver must guess; `MULTIPLE_MATCHES` stays a runtime outcome | Preserves the anomaly | Poor — the bug becomes policy |
| **D** Bounded-beats-unbounded tiebreak | No data change | The resolver chooses what no operator stated; fails for two bounded overlaps | Masks rather than fixes | Poor |
| **E** Split deployment 4 into two | Clean windows | Fabricates a campaign that never existed | **False history** | Poor |
| **F** Make `completed` non-attributing | Removes the overlap | **Breaks buffered replay** — a buffer draining after a campaign ends would find no window | Loses real attribution | Rejected on correctness |
| **G (recommended)** Record `closed_at` on deployment 4 | Zero historical rows change; records a fact; `planned_end` preserved | Requires the new field first | **Correct — states what happened** | Good — the mechanism is the normal one |

**G is A done properly.** Same instant, different field, opposite semantics: A
edits the plan, G records the outcome.

The value `2026-07-30 21:09:15.426` is deployment 4's own last reading, with the
next sample already on deployment 6 and **zero interleaving**. Any instant in
that 15-second gap works; the last reading is the most defensible. It remains an
**operator decision** — I will not set it without approval.

Note F deserved the analysis: if `completed` did not attribute, the overlap would
vanish. But the resolver runs at ingest, and a buffer draining days after a
campaign ends must still land in that campaign. `completed` must attribute. The
real rule is that a terminal attributing status must be **bounded** — which is
exactly what deployment 4 violates.

---

## Q5 — What the protection does and does not cover

Primary mechanism is now a **partial unique index**, not a range trigger:

```sql
CREATE UNIQUE INDEX ux_deployment_one_live_per_node
  ON deployments(node_id) WHERE status IN ('installing', 'active');
```

Verified on this SQLite build: rejects a second `active`, rejects `installing`
while `active`, allows a different node, and allows **unlimited `planned` and
`completed`** for the same node.

| Requirement | Covered | How |
|---|---|---|
| Overlapping attribution windows | **Yes** | Structural: windows are created by mutually exclusive transitions |
| Concurrent activation | **Yes** | Uniqueness enforced at storage level; SQLite is single-writer as well |
| Race conditions | **Yes** | Constraint violation, not a read-then-check |
| Direct SQL modification | **Yes** | Index enforcement is below the application |
| Future migration mistakes | **Partly** | Enforced unless a migration drops the index; `INV-17`/`INV-18` cover that |

### What it still cannot prevent

1. **A migration that drops the index, does damage, and reinstates it.** Only the
   invariants catch this — and they must, because M9's immutability trigger sets
   the precedent that migrations legitimately drop constraints.
2. **Reality diverging from record.** If a technician physically moves a node and
   nobody transitions the deployment, readings are attributed to the old building
   and every value is structurally valid. **No constraint can detect this.**
   It needs a monitoring rule, not a schema rule.
3. **Wrong-but-valid data.** A deployment pointing at the wrong building, or
   `closed_at` set to the wrong instant. Structure cannot validate intent.
4. **Backdated deployments.** Creating a deployment whose window covers
   already-ingested readings. Those readings are immutable, so they keep their
   old attribution while the new deployment claims to cover them — a silent
   divergence between stored and resolvable attribution. The index does not see
   this; it needs an explicit application check against
   `MAX(timestamp) WHERE node_id = ?`. **This is a new finding from the review.**
5. **Gaps.** A node measuring while no deployment is live yields
   `OUTSIDE_DEPLOYMENT_WINDOW` — correctly unattributed and alertable, but not
   preventable.

Items 2 and 4 are the genuine residual risks and both need application or
monitoring treatment, not constraints.

---

## Final recommendation

**What changed, and why:**

| Rev 1 | Rev 2 | Reason |
|---|---|---|
| `start_date`/`end_date` → timestamps | Keep planned dates; add `activated_at`/`closed_at` | The one-field model is what forced D1 to destroy information |
| `planned` occupies a window | `planned` constrains nothing | Rejecting Monday-A / Tuesday-B would break scheduling |
| `occupies_window` on all non-cancelled | `is_exclusive` on `installing`/`active` only | Exclusivity is about the physical node, not the calendar |
| Range-overlap triggers as primary | **Partial unique index** as primary | Simpler, atomic, race-proof, and structurally prevents overlap rather than detecting it |
| Repair edits `end_date` | Repair records `closed_at` | Records a fact instead of rewriting a plan |

**What stayed:** reject-not-auto-close with an explicit atomic supersede;
defence in depth across database, application and invariants; the repair instant
`2026-07-30 21:09:15.426`; zero historical readings modified.

**Revised migration order**

| # | Step | Risk |
|---|---|---|
| M10 | `deployment_statuses.is_exclusive` (+ backfill: `installing`, `active`) | Low |
| M11 | Add `activated_at`/`closed_at`; backfill from each deployment's own first/last reading; rename `start_date`/`end_date` → `planned_*` with API compatibility retained | Medium |
| — | **Repair (operator approval): deployment 4 `closed_at`** | Medium |
| M12 | Partial unique index, coherence trigger, `INV-17`/`INV-18` | Medium |
| M13 | API: creation in `planned`, `/activate` with atomic supersede, `/finish` sets `closed_at`, backdating check | Medium |

M12 must follow the repair, or the index installs against a violating row.

**Is this as simple as it can be while remaining correct?**

I believe so, and the test is that every part earns itself against a concrete
failure. Two date columns cannot express a campaign that overran — deployment 4
proves it. A range constraint is more machinery than a partial unique index and
gives a weaker guarantee. Making `planned` exclusive breaks scheduling for no
benefit. Timestamps typed by operators solve nothing that transition-recorded
timestamps do not solve better.

The one place I have deliberately kept complexity is the four date/time fields.
They answer four questions the domain genuinely asks, and the current data
already contains an answer to all four — it simply has nowhere to put two of
them.

Awaiting your decision before implementation.
