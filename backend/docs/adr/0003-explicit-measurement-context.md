# ADR-0003 — Measurement context is declared explicitly, never inferred

- **Status:** accepted
- **Date:** 2026-07-26

## Context

Bench measurements taken during the ADS1256 integration were stored
indistinguishably from production data and flowed into building metrics, model
training and anomaly detection. There was no way to ask "is this reading real
site data?" because nothing recorded the answer.

An earlier draft of this design **inferred** context from attribution: a reading
with no covering deployment was assumed to be bench data. That inference was
rejected during review.

## Decision

`energy_readings.context` is a `NOT NULL` column defaulting to `production`,
constrained to six values:

| Context | Meaning | Distinguishing test |
|---|---|---|
| `production` | Real load on a real panel during a real campaign | Default; the only context that may be attributed |
| `bench` | Hardware bring-up on a desk, no meaningful load | Is the instrument under test rather than a load? |
| `laboratory` | Controlled acquisition on a real load, outside any campaign | Real signal, but not a commissioned site |
| `calibration` | Against a reference instrument or known source | Is a reference value being compared? |
| `commissioning` | On-site verification before a campaign goes active | Installed but deployment not yet `active` |
| `simulation` | Synthetic or replayed data | Was any of it produced by a physical sensor? |

Context is taken from `nodes.measurement_context`, which is operator-set and
authoritative. A payload may **narrow** it — a technician runs a bench test on a
production node without an admin round-trip — but may never widen it to
`production`, so a misconfigured or spoofed collector cannot promote its own data
into the KPIs.

Context and attribution are independent axes:

| Context | Attribution | Meaning | System response |
|---|---|---|---|
| `production` | resolved | Normal operation | Counts in all analytics |
| `production` | NULL | **Deployment missing or mis-dated** | Stored, plus a `reading.unattributed` alert |
| non-production | NULL | Expected non-production work | Stored silently, excluded from analytics |
| non-production | resolved | Test run during a live campaign | Stored, excluded, attribution kept for traceability |

## Consequences

- Row 2 above is the reason for this ADR. Under the rejected inference model, a
  genuine production node whose deployment was simply never created would have
  been silently relabelled `bench` and vanished from every KPI with no error
  anywhere — the same class of silent loss as the deployment-gated ingestion this
  redesign removes. Making context explicit turns that into an alarm.
- Exclusion is enforced structurally, not per query: invariant
  `INV-09-nonproduction-unattributed` makes it impossible for a non-production
  reading to carry a building. A future analytics call site cannot reintroduce
  contamination by forgetting a filter.
- Bench and laboratory data remain stored, queryable and exportable through an
  explicit `?context=` parameter. Excluded by default, never deleted.
- Reclassification is cheap. Because context is a column rather than a structural
  property, a misjudged classification is one `UPDATE` over a time-bounded set,
  reversible forever.

## Alternatives considered

**A separate `bench_readings` table.** Rejected: it duplicates seventeen columns
and every index, and a reading that turns out to have been misclassified would
have to move between tables, breaking its primary key and any reference to it.

**A boolean `is_production`.** Rejected: it cannot distinguish calibration from
bench from simulation, which the thesis needs to report separately.

**Inferring context from the presence of a deployment.** Rejected, as above.
