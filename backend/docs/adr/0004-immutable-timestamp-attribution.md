# ADR-0004 — Attribution is resolved from the measurement timestamp and is immutable

- **Status:** accepted
- **Date:** 2026-07-26

## Context

`routers/edge.py:60-68` selected the attribution deployment with
`.order_by(Deployment.id.desc()).first()` — the **newest** deployment for the
node — and stamped every measurement in the batch with it, regardless of each
measurement's `captured_at`.

The edge buffer holds roughly 19,000 rows and replays after an outage. A node
that buffers across a deployment change therefore writes historical data into the
new campaign's building. This is silent, permanent misattribution, and it was not
in the original audit; it was found while verifying it.

Separately, attribution was partly re-derived on read, so editing or re-dating a
deployment retroactively changed what historical readings appeared to mean.

## Decision

**Resolved from the timestamp.** For each measurement *independently*, find the
deployment where `node_id` matches, the measurement's own timestamp falls within
`start_date <= captured_at < COALESCE(end_date + 1 day, ∞)`, and status is
`active` or `completed`. Found → stamp `deployment_id`, `building_id`,
`electrical_panel_id`. Not found → all NULL. Per-measurement rather than
per-batch is what fixes the replay defect.

**Written once, at ingest.** No read path re-derives attribution. No read path
joins `Deployment` to decide what a reading means.

**Immutable at runtime.** Enforced structurally by a `BEFORE UPDATE` trigger on
`energy_readings` that aborts any statement touching `node_id`, `deployment_id`,
`building_id`, `electrical_panel_id` or `context`.

## Scope of immutability

Taken literally and without exception, immutability would permanently freeze the
very misattribution this redesign exists to correct. The invariant is therefore
scoped precisely:

> **Immutable at runtime; correctable only by supervised migration.**

The trigger blocks all application writes. A migration that must correct
attribution drops the trigger, acts within a backed-up and reversible step that
declares the `allow_attribution_change` waiver, and reinstates it. Every such
migration is listed explicitly and is never a side effect of an API call.

Measured values — voltage, current, power, energy, timestamp — are immutable
under **all** circumstances. Invariant `INV-02-measurements-immutable` has no
waiver and no migration may alter them.

## Consequences

- Historical data becomes stable under deployment edits. Cancelling or re-dating
  a campaign cannot rewrite what was already measured.
- Legacy deployment dates are unreliable — deployment 4 declares
  `2026-06-14 → 06-21` while N001 has measured continuously since, so only 25% of
  its readings fall inside its own window. Those dates are treated as
  non-authoritative and `end_date` is set to NULL; see ADR-0006.
- Re-pointing N001's historical readings to a real building, once one is named,
  is an explicit opt-in migration rather than an incidental fix.

## Alternatives considered

**Recompute attribution on read.** Rejected: this is effectively today's
behaviour, and it means historical figures change whenever campaign metadata is
edited — unacceptable for a thesis dataset.

**Attribute per batch using the batch's median timestamp.** Rejected: cheaper,
but it still misattributes exactly the replay case that motivated the change.
