# ADR-0002 — Uploads are authorized by node commissioning, not deployment lifecycle

- **Status:** accepted (authentication phased — see Consequences)
- **Date:** 2026-07-26

## Context

Ingestion was gated on `Deployment.status`. Completing a deployment stopped
uploads, so an administrative action silently destroyed field data. The
workaround — widening the filter to accept `("active", "completed")` — restored
synchronisation but left an unbounded set of nodes uploading against campaigns
that had formally ended.

Separately, the ingestion endpoints have **no authentication of any kind**.
`POST /api/v1/measurements/batch`, `POST /api/readings` and
`POST /api/edge/heartbeat` accept a `device_id` string and trust it. Any host
able to reach port 8010 can inject readings attributed to any node, or forge a
heartbeat that suppresses a genuine outage alert.

## Decision

Ingestion answers three separate questions in order, and never conflates them.

1. **Authenticate — who is this?** A bearer token compared against
   `nodes.auth_token_hash`. Unknown or wrong token → `401`.
2. **Authorize — may it write?** `commission_state == 'commissioned'` → accept.
   `registered` or `suspended` → `403`; the node buffers locally and retries, so
   nothing is lost.
3. **Attribute — where does it count?** Resolved from the measurement's own
   timestamp. See ADR-0004.

Once authenticated and authorized, **data is always stored and never rejected.**
A reading that cannot be attributed is stored unattributed, not refused.

## Consequences

- Rejection is no longer used to express "this data does not belong to a
  campaign". That distinction moves to `context` (ADR-0003), which preserves the
  evidence instead of destroying it. The current design's rejection path is what
  produced N002's discarded readings.
- A `commission_state` boolean alone would **not** have been sufficient. Without
  step 1 the identity is self-asserted, so the flag gates nothing. This is the
  substantive correction to the original proposal, which stopped at step 2.
- **Authentication is phased.** In the current implementation the token is
  accepted and logged but not enforced, so no Raspberry Pi needs to be visited
  and the legacy Shelly collectors keep working unchanged. Enforcement is a
  separate change requiring token distribution to all three nodes.

## Alternatives considered

**Keep deployment gating, widen the accepted statuses.** Rejected: this is the
current hotfix. It does not scale — every new lifecycle state requires revisiting
the filter — and it still couples data collection to campaign administration.

**Per-node IP allowlist.** Rejected: the Pis are behind NAT on dynamic public
addresses, and an allowlist authenticates a network location rather than a
device.
