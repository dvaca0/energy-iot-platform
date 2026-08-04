# Changelog

All notable changes to this project are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
across four independently released components — see
[docs/Versioning.md](docs/Versioning.md).

Component changelogs with finer detail:
[`edge/CHANGELOG.md`](edge/CHANGELOG.md) ·
[`monitoring/README.md`](monitoring/README.md) ·
[`backend/docs/adr/`](backend/docs/adr/README.md)

---

## [Unreleased]

### Added

- Public repository structure: documentation set, brand assets, CI workflows,
  issue and PR templates, contribution and security policy.
- `scripts/gen_api_docs.py` and `scripts/check_api_docs.py` — the API reference
  is generated from the running OpenAPI schema and verified in CI, so an
  undocumented route fails the build.

### Changed

- The frontend's 59 commits (2026-06-14 → 06-19) were rewritten under a
  `frontend/` path prefix and merged into this repository, preserving their
  original authorship and dates.

### Known gaps

- Ingestion endpoints remain unauthenticated — see
  [docs/Security.md](docs/Security.md).
- The base measurement collector is still maintained on the devices rather than
  in this repository.
- The frontend has no test suite.

---

## [1.1.0] — 2026-07-29 — Alerting policy

Monitoring subsystem 1.1.0. Rebuilt from the message history of the first
production run.

### Context

> The first production run sent **1,386 Telegram messages in four days** — 697
> on one day, 73 in a single hour.

### Changed

- **Deployment gating.** Rules are evaluated against the platform's own
  lifecycle tables (`node_commission_states`, `deployment_statuses`). 98% of the
  noise — 1,288 of 1,312 messages — came from nodes with no operational
  deployment.
- **Threshold derivation.** Resolution order is now panel/breaker rating → node
  CT rating → learned baseline (operational deployments only, minimum 500
  samples) → conservative fallback. A learned baseline may never exceed the
  physical ceiling. The previous 200 A default sat at N001's 94th percentile and
  produced 962 messages on its own.
- **Sustain windows and hysteresis.** 404 of 472 alerts had lasted under two
  minutes. A condition must now persist before notifying and be absent before
  resolving.
- **Routing by consequence.** Most rules became report-only, escalating to
  Telegram at CRITICAL. Power factor 0.89 is noise; 0.55 is a fault on the same
  metric.
- Alerting no longer inherits `runtime_platform_settings.json`. Those are UI
  display defaults, and reusing them for paging was the direct cause of the
  worst noise.

### Added

- Sensitivity checks (`tests/test_monitoring.py` §19–25,
  `tests/test_synthetic_deployment.py`) asserting that real faults still fire —
  missing phase, overload, power loss, power-factor collapse — while known noise
  stays silent.

---

## [1.0.0] — 2026-07-26 — Monitoring and the measurement model

Two substantial pieces of work landed together.

### Added — monitoring subsystem

- 39 health rules across server, database, backend, network, node, electrical,
  smart-plug, security and monitoring-self subsystems.
- Node heartbeats: ~50 health fields every 45 s, on a path separate from
  measurements, so "the node is down" and "the node is up but not measuring"
  stay distinguishable.
- Alert lifecycle with deduplication, duration-based escalation, automatic
  resolution and a full audit trail.
- Telegram delivery through a durable outbox that never discards a message.
- Hourly platform status report.
- Self-monitoring — the scheduler detects and reports its own downtime.
- Six monitoring tables in their own namespace. **No existing table is
  modified.**
- The scheduler runs as a separate process under `flock`, so it cannot
  double-alert and does not die with the API.

### Added — canonical measurement model

Migrations 001–012, with shadow runs and invariant checks.

- Identity, authorisation, lifecycle, attribution and semantics separated into
  five concerns with five owners
  ([ADR-0001](backend/docs/adr/0001-separate-identity-health-lifecycle-attribution.md)).
- Explicit measurement context, so bench and bring-up data are separated from
  production data by classification rather than by deletion
  ([ADR-0003](backend/docs/adr/0003-explicit-measurement-context.md)).
- Timestamp-based attribution: each reading resolves to the deployment active at
  its own `captured_at`
  ([ADR-0004](backend/docs/adr/0004-immutable-timestamp-attribution.md)).
- Mandatory `energy_source` on the ingestion contract
  ([ADR-0007](backend/docs/adr/0007-canonical-measurement-model.md)).
- Migration invariants and reversibility as a standing requirement
  ([ADR-0005](backend/docs/adr/0005-migration-invariants.md)).

### Fixed

- Batch attribution assigned every row to the newest deployment by id, ignoring
  each measurement's `captured_at`. With a ~19k-row buffer replaying after an
  outage, buffered data landed against the wrong building — silently and
  permanently.
- ML building profiles, `anomaly_engine` and `metrics` were reading bench data.
  Cost figures were never affected: every cost path filters
  `energy_kwh IS NOT NULL`, and the bench node reported `NULL` on all 123,617 of
  its rows.

---

## [0.3.0] — 2026-07-25 — Smart plugs

Edge component 1.2.0. Full detail in [`edge/CHANGELOG.md`](edge/CHANGELOG.md).

### Added

- Shelly Plug US Gen4 integration over Gen4 RPC, as **accessories of a
  deployment** rather than as Energy Nodes — separate tables, separate buffer
  file, separate API prefix.
- Discovery and polling run **only on the Raspberry Pi**. The backend never
  scans a network, which is what lets nodes sit behind ordinary consumer NAT.
- `health()` API and a `smart-plug-health` CLI wrapper for one-command node
  diagnostics.
- Idempotent installer with version detection, config preservation and
  post-install verification.

### Changed

- **Explicit plug ownership.** The first node to report a plug claims it;
  reports from other nodes are rejected rather than accepted as the latest
  writer. Previously the last reporter won.
- Validation rejects malformed MACs, duplicate MACs within a report, and
  implausible timestamps.

---

## [0.2.0] — 2026-06-19 — Platform surface

### Added

- Executive dashboard, campus map, buildings, deployments, live monitoring, cost
  analysis, AI centre, data mining, data explorer, reports, infrastructure and
  settings screens.
- CFE **GDMTH** tariff model with base, intermediate and peak periods, driven by
  a scraper so published rates do not go stale.
- Forecasting (`RandomForestRegressor`), anomaly detection
  (`IsolationForest`) and building clustering (`KMeans`), each refusing to
  produce output without sufficient history rather than inventing it.
- PDF, CSV and XLSX report generation.
- Optional LLM narration over computed figures, fully disabled by
  `LLM_ENABLED=0`.

---

## [0.1.0] — 2026-06-14 — First measurements

### Added

- FastAPI backend with SQLite in WAL mode.
- Edge collector with a local buffer and independent sync loop — a backend
  outage delays data rather than losing it.
- React dashboard migrated from a static prototype.
- First continuous production series from node N001.

Measurement data in the platform begins **2026-05-13**, from prototype
acquisition that predates the deployment model. It is retained and classified
rather than back-attributed — see
[ADR-0006](backend/docs/adr/0006-legacy-deployment-dates-non-authoritative.md).

---

[Unreleased]: https://github.com/dvaca0/energy-iot-platform/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/dvaca0/energy-iot-platform/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/dvaca0/energy-iot-platform/compare/v0.3.0...v1.0.0
[0.3.0]: https://github.com/dvaca0/energy-iot-platform/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/dvaca0/energy-iot-platform/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/dvaca0/energy-iot-platform/releases/tag/v0.1.0
