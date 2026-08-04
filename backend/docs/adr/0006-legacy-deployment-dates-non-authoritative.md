# ADR-0006 — Legacy deployment dates and the placeholder building are non-authoritative

- **Status:** accepted
- **Date:** 2026-07-26

## Context

Adopting timestamp-based attribution (ADR-0004) exposed that the existing
deployment metadata does not describe reality.

Both deployments declare `2026-06-14 → 2026-06-21`, and both point at building 8,
`B-MANUAL-72-edificio-de-prueba` ("Edificio de prueba"), on the same panel.
Measured against the readings themselves:

| Node | Rows inside its deployment window | Rows outside |
|---|---:|---:|
| N001 | 25,779 | **75,903 (75%)** |
| N003 | 158 | **123,459 (99.9%)** |

N001 has measured continuously since 2026-06-14 and is still measuring. Under
strict timestamp attribution against the declared window, every reading it
produces from now on would land unattributed.

Two facts were established with the platform owner:

- N003's May–June data is **real historical acquisition from the prototype**. It
  predates the deployment model and must not be retroactively attributed.
- Building 8 is a **development placeholder**, not authoritative production
  metadata.

## Decision

**Legacy dates are non-authoritative.** Deployment 4's `end_date` is set to
`NULL` — open-ended — so N001's ongoing measurement is attributed rather than
stranded. The declared `2026-06-21` end is treated as an artefact of the
prototype, not a statement about the campaign.

**The placeholder building is retained and flagged**, via
`buildings.is_placeholder`. Building-level analytics — cost per building, model
building profiles, mining — exclude placeholder buildings. Fleet-level totals
still count the energy, flagged as not attributable to a real site.

**N003's prototype data is de-attributed**, not reclassified as production:
`context='laboratory'` for the May–June set, `context='bench'` for the July
ADS1256 bring-up at the noise floor, both with NULL attribution.

## Consequences

- A placeholder building is not the same as non-production data. N001's 101,682
  readings are real measurements of a real load; what is unreliable is the label
  on where they were taken. Treating them as non-production would discard valid
  data to fix a metadata error, so `is_placeholder` is a separate axis from
  `context` (ADR-0003).
- Deployment 5 remains in place with zero attributed readings. That is the honest
  record of what happened, and it stays available if part of that data is later
  determined to have been a real campaign.
- Re-pointing N001's historical readings to a real building, once one is named,
  remains available as an explicit opt-in migration under ADR-0004's supervised
  exception.
- The `laboratory` classification for N003's May set is an interpretation of the
  owner's description, not a verified fact. Because context is a column, it is one
  `UPDATE` to change.

## Alternatives considered

**Widen deployment 4's `end_date` to a fixed future date.** Rejected: it encodes
a guess about when the campaign ends and would strand data again once passed.
NULL states the truth — the campaign has no scheduled end.

**Create a real building now and re-point everything.** Rejected: the real
building is not known, and inventing one would replace a known-placeholder with a
plausible-looking fabrication, which is worse.
