<div align="center">
  <img src="../assets/branding/logo.svg" alt="Energy IQ" width="300">
  <h1>Documentation</h1>
  <p><em>Everything about how this platform is built, run and recovered.</em></p>
</div>

---

## Start here

| If you want to… | Read |
|---|---|
| Understand the system in one sitting | [Architecture.md](Architecture.md) |
| Run it locally | [Development.md](Development.md) |
| Put it on a server | [Deployment.md](Deployment.md) |
| Build and install a node | [Hardware.md](Hardware.md) · [Collector.md](Collector.md) |
| Call the API | [API.md](API.md) |
| Understand an alert you received | [Monitoring.md](Monitoring.md) |
| Fix something that is broken | [Troubleshooting.md](Troubleshooting.md) · [Recovery.md](Recovery.md) |

## Contents

### System

| Document | Covers |
|---|---|
| [Architecture.md](Architecture.md) | The three tiers, the five concepts, and the structural decisions behind them |
| [Database.md](Database.md) | Schema, the 33 tables, migrations, WAL-mode consequences |
| [Backend.md](Backend.md) | FastAPI service: routers, services, request lifecycle |
| [Frontend.md](Frontend.md) | React dashboard: screens, state, styling approach |
| [Collector.md](Collector.md) | The edge collector, the measurement contract, buffering and sync |
| [Hardware.md](Hardware.md) | Nodes, ADC, CT clamps, smart plugs, physical installation |
| [Networking.md](Networking.md) | Topology, ports, NAT traversal, node access |

### Capability

| Document | Covers |
|---|---|
| [AI.md](AI.md) | Forecasting, anomaly detection, clustering, and the honesty guarantees around them |
| [Monitoring.md](Monitoring.md) | 39 health rules, the alerting policy, and why it is tuned the way it is |
| [Smart-Plugs.md](Smart-Plugs.md) | Shelly Gen4 integration, discovery, assignment, sub-metering |
| [CampusMap.md](CampusMap.md) | OSM building footprints, how they are curated and joined to Energy IQ buildings |

### Operations

| Document | Covers |
|---|---|
| [Deployment.md](Deployment.md) | Release process, systemd units, zero-downtime reload, staging |
| [Recovery.md](Recovery.md) | Backups, restore, node recovery, disaster procedures |
| [Troubleshooting.md](Troubleshooting.md) | Symptom-first diagnostic guide |
| [Security.md](Security.md) | Threat model, secret handling, known gaps stated plainly |
| [Versioning.md](Versioning.md) | Semantic versioning across four independently released components |

### Reference

| Document | Covers |
|---|---|
| [API.md](API.md) | All 90 routes, ingestion contract, error semantics |
| [Development.md](Development.md) | Local setup, code style, testing, contribution workflow |
| [Changelog.md](Changelog.md) | Release history |
| [diagrams/](diagrams/README.md) | All 12 system diagrams in one place |

## Deeper engineering record

The documents above describe the system as it is. The material below records
*why* it is that way, and is kept beside the code it governs.

| Location | Contents |
|---|---|
| [`backend/docs/adr/`](../backend/docs/adr/README.md) | 7 architecture decision records |
| [`backend/docs/ARCHITECTURE.md`](../backend/docs/ARCHITECTURE.md) | The definitive backend technical reference |
| [`backend/docs/collector-contract.md`](../backend/docs/collector-contract.md) | The canonical measurement contract any hardware must satisfy |
| [`backend/migrations/README.md`](../backend/migrations/README.md) | Migration runner, shadow runs, invariants |
| [`monitoring/README.md`](../monitoring/README.md) | Monitoring subsystem operator guide |
| [`edge/`](../edge/) | Smart-plug collector deployment and handover notes |

## Conventions

- **Mermaid for every diagram.** Diagrams diff as text and never fall silently
  out of date behind a binary image.
- **Callouts carry weight.** A `> [!WARNING]` marks something that has actually
  gone wrong in production, not a hypothetical.
- **Numbers are measured, not estimated.** Where a document states a figure —
  255,379 readings, 39 rules, 90 routes — it was read from the running system
  on 2026-08-04 and is reproducible with the command shown beside it.
