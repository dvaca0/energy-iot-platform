# API reference

**90 operations across 85 paths.** This page is generated from the running
service's OpenAPI schema, so it cannot drift from the implementation:

```bash
curl -s http://<host>:8010/openapi.json | python3 scripts/gen_api_docs.py - > docs/API.md
```

Interactive schema: `http://<host>:8010/docs`.

---

## Conventions

| | |
|---|---|
| **Base URL** | `http://<host>:8010` |
| **Content type** | `application/json`, except report endpoints which return `application/pdf`, `text/csv` or an XLSX stream |
| **Timestamps** | ISO 8601, **UTC**. `timestamp` is when a sample was *taken*, never when it was sent. |
| **Errors** | FastAPI's standard shape — `{"detail": ...}` with a conventional status code |
| **Versioning** | Only the ingestion path is version-prefixed (`/api/v1/`). See [Versioning.md](Versioning.md). |

> [!CAUTION]
> **The ingestion endpoints are unauthenticated.** `POST /api/v1/measurements/batch`,
> `POST /api/readings` and `POST /api/edge/heartbeat` accept a self-asserted
> `node_id`. A forged heartbeat can suppress a real outage alert. This is a known,
> documented gap — see [Security.md § Known gaps](Security.md#known-gaps) and
> [ADR-0002](../backend/docs/adr/0002-upload-authorization.md). Firewall port 8010
> accordingly.

### Authorisation on the ingest path

Although the caller is not authenticated, a *registered* node is still
constrained by `node_commission_states`:

| Flag | Effect |
|---|---|
| `may_upload` | False ⇒ measurements are rejected. The node keeps buffering and retrying; the only visible symptom is a growing buffer. |
| `is_monitored` | False ⇒ the node is excluded from deployment-gated alerting |

This is authorisation, not authentication: it controls *which registered nodes*
may write, not whether the caller is that node.

---

## Ingestion contract

The one contract that must not change casually — historical data has already
been stored under its current meaning.

```json
POST /api/v1/measurements/batch
{
  "node_id": "N001",
  "timestamp": "2026-07-31T20:15:00Z",
  "power_kw": 12.4,
  "interval_energy_kwh": 0.0517,
  "interval_seconds": 15.0,
  "energy_source": "measured",

  "meter_energy_kwh": 26411.882,
  "voltage": 127.3,
  "current": 97.4,
  "power_factor": 0.95,
  "frequency_hz": 60.0
}
```

`energy_source` is mandatory and must be one of `measured`, `counter_delta` or
`power_integral`. Without it, `interval_energy_kwh` is unfalsifiable. Full
specification: [Collector.md](Collector.md) and
[`backend/docs/collector-contract.md`](../backend/docs/collector-contract.md).

Each row in a batch is attributed **by its own `timestamp`**, not by the batch's
arrival time — so a node replaying seven days of buffer after an outage still
lands each reading in the deployment that was active when it was captured.

---

## Routes

### Health

Liveness probe. No authentication, no database access.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Health |

### Ingestion

The canonical measurement endpoint. Contract: [Collector.md](Collector.md).

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/measurements/batch` | Ingest Batch |

### Edge heartbeat

Node health reporting — ~50 fields every 45 s.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/edge/heartbeat` | Heartbeat |

### Readings (legacy)

Retained so existing collectors keep working. New collectors use `/api/v1/measurements/batch`.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/readings` | Create Reading |
| `GET` | `/api/readings/latest` | Latest Readings |

### Dashboard

Executive rollups.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/dashboard/summary` | Dashboard Summary |

### Metrics

Live and historical electrical metrics.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/metrics/buildings` | Building Metrics |
| `GET` | `/api/metrics/campuses` | Campus Metrics |
| `GET` | `/api/metrics/daily` | Daily Metrics |
| `GET` | `/api/metrics/hourly` | Hourly Metrics |
| `GET` | `/api/metrics/live` | Live Metrics |
| `GET` | `/api/metrics/live/deployments` | Live Deployments |
| `GET` | `/api/metrics/live/history` | Live History |
| `GET` | `/api/metrics/live/snapshot` | Live Snapshot |
| `GET` | `/api/metrics/tariffs` | Tariff Metrics |

### Cost

CFE GDMTH tariff arithmetic.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/cost/hourly` | Hourly Cost |
| `GET` | `/api/cost/summary` | Cost Summary |

### Organisation

Delegations, campuses, units, buildings, panels.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/org/buildings` | List Buildings |
| `GET` | `/api/org/buildings/by-unit/{unit_id}` | Buildings By Unit |
| `GET` | `/api/org/campuses` | List Campuses |
| `GET` | `/api/org/campuses/by-delegation/{delegation_id}` | Campuses By Delegation |
| `GET` | `/api/org/delegations` | List Delegations |
| `GET` | `/api/org/panels/by-building/{building_id}` | Panels By Building |
| `GET` | `/api/org/units` | List Units |
| `GET` | `/api/org/units/by-campus/{campus_id}` | Units By Campus |

### Buildings

Building inventory and coverage.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/buildings` | List Buildings |
| `GET` | `/api/buildings/{building_id}` | Get Building |

### Nodes

Identity, commissioning and physical ratings.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/nodes` | List Nodes |
| `GET` | `/api/nodes/commission-states` | Commission States |
| `GET` | `/api/nodes/online` | Online Nodes |
| `GET` | `/api/nodes/{code}/commission-history` | Commission History |
| `POST` | `/api/nodes/{code}/commission-state` | Set Commission State |
| `GET` | `/api/nodes/{code}/ratings` | Get Node Ratings |
| `PUT` | `/api/nodes/{code}/ratings` | Set Node Ratings |

### Deployments

Installation-campaign lifecycle.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/deployments` | List Deployments |
| `POST` | `/api/deployments` | Create Deployment |
| `GET` | `/api/deployments/lifecycle` | Deployment Lifecycle |
| `GET` | `/api/deployments/{deployment_id}` | Get Deployment |
| `PATCH` | `/api/deployments/{deployment_id}` | Edit Plan |
| `POST` | `/api/deployments/{deployment_id}/activate` | Activate Deployment |
| `POST` | `/api/deployments/{deployment_id}/begin-installation` | Begin Installation |
| `POST` | `/api/deployments/{deployment_id}/cancel` | Cancel Deployment |
| `POST` | `/api/deployments/{deployment_id}/complete` | Complete Deployment |
| `POST` | `/api/deployments/{deployment_id}/finish` | Finish Deployment |
| `GET` | `/api/deployments/{deployment_id}/ratings` | Get Deployment Ratings |
| `PUT` | `/api/deployments/{deployment_id}/ratings` | Set Deployment Ratings |

### Monitoring

Alerts, rules, health and Telegram configuration. See [Monitoring.md](Monitoring.md).

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/monitoring/alerts` | List Alerts |
| `GET` | `/api/monitoring/alerts/statistics` | Alert Statistics |
| `GET` | `/api/monitoring/alerts/{alert_id}` | Get Alert |
| `POST` | `/api/monitoring/alerts/{alert_id}/acknowledge` | Acknowledge Alert |
| `GET` | `/api/monitoring/channels` | List Channels |
| `GET` | `/api/monitoring/config` | Get Monitoring Config |
| `GET` | `/api/monitoring/health` | Monitoring Health |
| `POST` | `/api/monitoring/heartbeat` | Post Heartbeat |
| `GET` | `/api/monitoring/nodes/{node_code}/heartbeats` | Node Heartbeats |
| `GET` | `/api/monitoring/rules` | List Rules |
| `GET` | `/api/monitoring/status` | Get Status |
| `GET` | `/api/monitoring/telegram/discover-chat` | Discover Chat |
| `GET` | `/api/monitoring/telegram/verify` | Verify Telegram |
| `POST` | `/api/monitoring/test-notification` | Test Notification |

### Alerts (legacy)

Deployment-gated legacy surface — silent by design.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/alerts/status` | Alert Status |

### Anomalies

Threshold-rule anomalies. **Not** the alerting system.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/anomalies` | List Anomalies |

### AI insights

Narrative insights.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/ai/insights` | Ai Insights |

### AI Centre

Forecasting, clustering and optional narration. See [AI.md](AI.md).

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/ai-center` | Ai Center |
| `POST` | `/api/ai-center/assistant` | Ai Assistant |

### Data mining

Clustering and pattern analysis.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/mining` | Mining Analytics |

### Data explorer

Ad-hoc query surface.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/data-explorer` | Data Explorer |
| `GET` | `/api/data-explorer/options` | Data Explorer Options |

### Reports

PDF, CSV and XLSX generation.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/reports/anomalies.pdf` | Anomalies Pdf |
| `GET` | `/api/reports/building-comparison.pdf` | Building Comparison Pdf |
| `GET` | `/api/reports/dataset.csv` | Dataset Csv |
| `GET` | `/api/reports/deployment/{deployment_id}.csv` | Deployment Csv |
| `GET` | `/api/reports/deployment/{deployment_id}.pdf` | Deployment Pdf |
| `GET` | `/api/reports/deployment/{deployment_id}.xlsx` | Deployment Xlsx |
| `POST` | `/api/reports/deployment/{deployment_id}/generate` | Generate Deployment Report Files |
| `GET` | `/api/reports/deployments` | List Deployment Reports |
| `GET` | `/api/reports/deployments.pdf` | Deployments Pdf |
| `GET` | `/api/reports/raw-readings.csv` | Raw Readings Csv |
| `GET` | `/api/reports/raw-readings.pdf` | Raw Readings Pdf |
| `GET` | `/api/reports/sustainability.pdf` | Sustainability Pdf |
| `GET` | `/api/reports/weekly-cost.pdf` | Weekly Cost Pdf |

### Smart plugs

See [Smart-Plugs.md](Smart-Plugs.md).

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/smart-plugs` | List Smart Plugs |
| `POST` | `/api/smart-plugs/discovery` | Report Discovery |
| `GET` | `/api/smart-plugs/live` | Live Smart Plugs |
| `GET` | `/api/smart-plugs/{plug_id}` | Get Smart Plug |
| `POST` | `/api/smart-plugs/{plug_id}/assign` | Assign Smart Plug |
| `GET` | `/api/smart-plugs/{plug_id}/history` | Get Smart Plug History |
| `POST` | `/api/smart-plugs/{plug_id}/transfer` | Transfer Ownership |

### Settings

Runtime platform settings and CFE tariff sync.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/settings` | Read Settings |
| `PUT` | `/api/settings` | Update Settings |
| `POST` | `/api/settings/cfe/scrape` | Scrape Cfe Gdmth |
| `GET` | `/api/settings/cfe/status` | Cfe Scraper Status |

### Infrastructure

Infrastructure status.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/infra` | Infrastructure Status |

---

## Notable behaviours

### Reports are generated, not cached

`POST /api/reports/deployment/{id}/generate` builds the file set; the `GET`
variants stream them. Generation is synchronous and can take seconds on a large
deployment — a client should not treat a slow response as a failure.

### `/api/metrics/live` is polled, not pushed

There is no WebSocket. The live monitoring screen polls at 3 s. For a series
whose source cadence is 15 s, polling is sufficient and removes an entire class
of connection-state bugs. See [Frontend.md](Frontend.md).

### The live view is three endpoints, not one

`/api/metrics/live` feeds the production dashboard and is unchanged.
`/api/metrics/live/snapshot` and `/api/metrics/live/history` back the technical
*Monitoreo en Vivo* screen and are separated because their costs are opposite:
the snapshot is ~5 KB and polled at 3 s, the window is tens of kilobytes and is
either extended with `?since=` or refreshed on a slow cadence. Splitting them is
what keeps a page that stays open all day from re-downloading its whole window
twenty times a minute. `history` declares its own `resolution_seconds` and
`aggregation`, so a caller can always tell a stored sample from a bucket mean.
See [Live-Monitoring.md](Live-Monitoring.md).

### The deployment range is scoped by deployment, not by node and dates

`/api/metrics/live/history?range=deployment&deployment_id=N` filters on
`energy_readings.deployment_id` and bounds the window with that campaign's own
`activated_at`/`closed_at`. `node_ids` is ignored — the campaign decides which
nodes appear, discovered from the readings rather than assumed. Every response
carries `readings_in_window` and `readings_outside_window`, because a campaign
can legitimately own readings its own dates do not cover, and an empty chart
should be explained rather than merely blank.
`/api/metrics/live/deployments` lists the activated campaigns for the selector.

### Two anomaly surfaces that are not the alerting system

`/api/anomalies` (threshold rules) and `/api/ai-center` (IsolationForest) both
report anomalies. **Neither pages anyone.** Alerting is `/api/monitoring`, which
derives thresholds from physical ratings rather than UI display defaults —
precisely because reusing display defaults for alerting caused a 1,386-message
incident. See [Monitoring.md](Monitoring.md).

### Deployment lifecycle is a state machine

The `POST` routes under `/api/deployments/{id}/` — `begin-installation`,
`activate`, `complete`, `finish`, `cancel` — are transitions, not setters. An
invalid transition is rejected rather than silently applied, and every
transition is recorded in `deployment_status_transitions`.

---

## Regenerating this page

```bash
curl -s http://127.0.0.1:8010/openapi.json -o /tmp/openapi.json
python3 scripts/gen_api_docs.py /tmp/openapi.json > /tmp/routes.md
# splice /tmp/routes.md into the "Routes" section
```

CI checks that the route count in this document matches the running schema, so a
new route that is never documented fails the build rather than quietly
disappearing.
