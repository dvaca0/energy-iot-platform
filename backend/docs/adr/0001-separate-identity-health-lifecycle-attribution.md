# ADR-0001 — Separate node identity, runtime health, deployment lifecycle and measurement attribution

- **Status:** accepted
- **Date:** 2026-07-26
- **Supersedes:** the implicit model in place since the prototype

## Context

Four distinct concepts had collapsed into two columns, `Node.last_sync` and
`Deployment.status`. The audit of 2026-07-26 found each of the following in
production code:

- `routers/dashboard.py:340` reported `active_deployments` as the count of nodes
  whose `last_sync` was recent. The `Deployment` table was never consulted.
- `routers/deployments.py:48` replaced the stored lifecycle with an
  `effective_status` derived from node connectivity, so a completed campaign on a
  live node reported as active and an active campaign on an unplugged node
  reported as historic.
- `routers/edge.py:64` gated ingestion on `Deployment.status`, so completing a
  campaign silently stopped data collection. This had already forced a hotfix
  widening the filter to `("active", "completed")`.
- `routers/alerts.py:55` iterated only active deployments. With every deployment
  in the database `completed`, that endpoint emitted nothing at all.

The shared cause is that connectivity, authorization and campaign stage were
being read from whichever column happened to be nearby.

## Decision

Four concepts, four owners, no shared columns.

| Concept | Owner | Source of truth |
|---|---|---|
| Identity and authorization | `Node` | `commission_state`, `auth_token_hash` |
| Runtime health | derived projection | `monitor_node_heartbeat_latest` |
| Campaign stage | `Deployment` | `status` enum |
| Where a reading counts | `EnergyReading` | `node_id`, `deployment_id`, `building_id`, `context` |

No entity reads another's state to answer its own question. A node going offline
changes no deployment. Completing a deployment changes no node state and stops no
ingestion.

Runtime health is deliberately **not** a stored column on `Node`. It is
recomputed from heartbeat telemetry on every scheduler tick. The existing
`monitoring/heartbeat.py` already does this correctly, iterating every node
unconditionally; this ADR formalises what it does rather than replacing it.

## Consequences

- `Node.status` becomes a third, stale vocabulary (`online` / `offline` /
  `available`) with no owner. It is retired in M9 — see ADR-0005.
- The dashboard KPI changes value: `active_deployments` will read `0` where it
  read `2`, because there are genuinely zero active deployments. This is the bug
  being fixed, not a regression.
- The API contract is preserved. `active_deployments` stays in the payload, so
  the existing frontend bundle needs no rebuild.

## Alternatives considered

**Keep the derived `effective_status` and rename it.** Rejected: the problem is
not the name. Any field that mixes lifecycle with connectivity has no correct
value when the two disagree, which is precisely the state the platform is in
today.

**Store health on `Node` and update it on each heartbeat.** Rejected: it
introduces a second source of truth that drifts whenever a write is missed. The
database currently holds `N003 status='offline'` alongside a `last_sync` from
seconds earlier, which is exactly that failure already happening.
