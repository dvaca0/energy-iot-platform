# Architecture Decision Records

Decisions taken during the deployment / ingestion / attribution redesign of
2026-07-26, and the reasoning behind them. Each record states what was decided,
why, what it costs, and what was rejected.

| # | Decision | Status |
|---|---|---|
| [0001](0001-separate-identity-health-lifecycle-attribution.md) | Separate node identity, runtime health, deployment lifecycle and measurement attribution | accepted |
| [0002](0002-upload-authorization.md) | Uploads are authorized by node commissioning, not deployment lifecycle | accepted (auth phased) |
| [0003](0003-explicit-measurement-context.md) | Measurement context is declared explicitly, never inferred | accepted |
| [0004](0004-immutable-timestamp-attribution.md) | Attribution is resolved from the measurement timestamp and is immutable | accepted |
| [0005](0005-migration-invariants.md) | Migrations are gated by invariants, not by review alone | accepted |
| [0006](0006-legacy-deployment-dates-non-authoritative.md) | Legacy deployment dates and the placeholder building are non-authoritative | accepted |

## The problem in one paragraph

Four concepts — is this node registered, is it online, what stage is the
installation campaign at, and where does a reading count — had collapsed into two
columns, `Node.last_sync` and `Deployment.status`. The dashboard reported node
count as deployment count; the deployment API overwrote stored lifecycle with
connectivity; ingestion was gated on campaign stage, so completing a campaign
silently stopped data collection; and alerting iterated active deployments, of
which there were none. Bench measurements from the ADS1256 integration were
stored indistinguishably from production data. These records separate the four
concepts and give each exactly one owner.

## Reading order

0001 establishes the separation. 0002, 0003 and 0004 each take one of the
resulting boundaries — authorization, classification, attribution — and decide
how it works. 0005 is about how the change is delivered safely. 0006 records the
two judgements about existing data that everything else depends on.
