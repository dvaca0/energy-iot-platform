# Energy Platform — Monitoring and Alerting

Production monitoring for the University Energy Intelligence Platform. Answers,
at any moment: *is everything healthy; if not, what broke, where, since when,
how bad is it, and what should I check first?*

Built **2026-07-26**. Alerting policy revised **2026-07-29**. Version 1.1.0.

---

## What it does

- **Node heartbeats.** Every Pi reports ~50 health fields every 45 s, separately
  from its electrical measurements, so "the node is down" and "the node is up
  but not measuring" are distinguishable.
- **39 health rules** across server, database, backend, network, node,
  electrical, smart-plug, security and monitoring-self subsystems.
- **Deployment-aware alerting** driven by the platform's own lifecycle tables,
  with sustain windows, hysteresis and report-only routing so Telegram stays
  quiet. See "Alerting policy".
- **Alert lifecycle** with deduplication, duration-based escalation, automatic
  resolution and a full audit trail.
- **Telegram delivery** through a durable outbox that never discards a message.
- **Hourly status report** covering the whole platform.
- **Self-monitoring**: detects and reports its own downtime.

---

## Architecture

```
backend/app/monitoring/
  config.py        Layered typed config: defaults → monitoring_config.json → env
  severity.py      Severity levels (INFO→EMERGENCY) and presentation
  models.py        Six monitoring tables. No existing table is modified.
  storage.py       Own session factory, table creation, retention
  rules.py         Rule registry + evaluation engine  ← the extension point
  health.py        Server probes + server rules
  heartbeat.py     Node heartbeat ingest, liveness, node rules
  metrics.py       Electrical / plug / fleet metrics and rules
  alerts.py        Lifecycle: dedupe, escalate, resolve
  notifications.py Rendering, durable outbox, delivery policy
  channels/
    base.py        NotificationChannel ABC  ← add channels here
    telegram.py    Telegram implementation
  status.py        Status snapshot + hourly report
  history.py       Read queries for the future Alerts page
  scheduler.py     Runtime loop + self-monitoring watchdog
  router.py        FastAPI routes under /api/monitoring

monitoring/
  energy-platform-monitoring.service   systemd unit (needs root to install)
  run-monitoring.sh                    no-root runner, single-instance via flock
  edge/node_heartbeat.py               the Raspberry Pi agent
  edge/energy-node-heartbeat.service   the Pi systemd unit
```

**Why the scheduler is a separate process.** The backend runs `-w 1` today; at
`-w 4` an in-process scheduler would evaluate every rule four times and send
four copies of every alert. A separate process also survives a backend crash
and can therefore *report* it.

---

## Adding things

**A new health check** — one function, nowhere else:

```python
from app.monitoring.rules import Finding, RuleContext, Subsystem, rule
from app.monitoring.severity import Severity

@rule("server.my_check", Subsystem.SERVER, "What this checks")
def check_my_thing(ctx: RuleContext):
    value = ctx.server.get("something")
    if value is None or value < 100:
        return []
    return [Finding(
        rule_id="server.my_check",
        subsystem=Subsystem.SERVER,
        severity=Severity.WARNING,
        title="Something is too high",
        metric="something", current_value=str(value), expected_value="< 100",
        suggested_causes=["..."], suggested_commands=["..."], suggested_actions=["..."],
    )]
```

Registration is automatic; the rule appears in `/api/monitoring/rules`.

**A new notification channel** — implement `NotificationChannel`
(`is_configured()` and `send()`), then add one line to `build_channels()` in
`channels/__init__.py`. Rate limiting, quiet hours, retry and the outbox are
already applied for you.

---

## Configuration

Thresholds live in `backend/monitoring_config.json` (created on demand;
everything has a default). Secrets live in `backend/.env`, mode 600:

```
MONITORING_TELEGRAM_BOT_TOKEN=...
MONITORING_TELEGRAM_CHAT_ID=...
```

Monitoring owns its own thresholds and deliberately does **not** inherit
`runtime_platform_settings.json` — see "Alerting policy" below for why.

Key knobs: heartbeat interval and the 2/5/10 missed-beat ladder; escalation at
1/5/15/60 minutes; quiet hours (CRITICAL and EMERGENCY always break through);
rate limit (60/hour, EMERGENCY exempt); hourly report schedule.

---

## Operating it

```bash
# Status
curl -s localhost:8010/api/monitoring/health   | python3 -m json.tool
curl -s localhost:8010/api/monitoring/status   | python3 -m json.tool
curl -s "localhost:8010/api/monitoring/alerts?status=open" | python3 -m json.tool

# Prove delivery end to end
curl -s -X POST localhost:8010/api/monitoring/test-notification

# Scheduler
tail -f /home/manager/energy-platform/monitoring/monitoring.log
pgrep -af "app.monitoring.scheduler"

# Tests (449 checks across 4 suites, throwaway DBs, never touch production)
cd /home/manager/energy-platform/backend && cd /home/manager/energy-platform/backend
for t in test_monitoring test_smart_plugs test_collector test_synthetic_deployment; do
  venv/bin/python3 tests/$t.py | tail -2
done
```

Backend code changes need a graceful reload (no root):

```bash
kill -HUP $(systemctl show -p MainPID --value energy-platform-backend.service)
```

The scheduler must be restarted separately — it is its own process.

---

## Deploying the Pi agent

Standard library only; no pip install needed on the node. Read-only: it never
writes to the node and never touches the collector.

```bash
# 1. Dry run first — touches nothing, prints what it would send
python3 node_heartbeat.py --node-id N00X --backend http://148.213.1.15:8010 \
    --collector-service <unit> --collector-db <path> --dry-run

# 2. Install
sudo mkdir -p /opt/energy-monitoring
sudo cp node_heartbeat.py /opt/energy-monitoring/
sudo cp energy-node-heartbeat.service /etc/systemd/system/
sudo nano /etc/systemd/system/energy-node-heartbeat.service   # set NODE_ID etc.
sudo systemctl daemon-reload
sudo systemctl enable --now energy-node-heartbeat.service
journalctl -u energy-node-heartbeat -f
```

**The collector unit name differs per node — determine it on the device.**
Observed so far:

| Node | Host | Hardware | Collector unit | Buffer DB |
|---|---|---|---|---|
| N002 | `energy-node-002` | Pi 5 | `energy-node-collector` | `/opt/energy-node/database/edge_buffer.db` |
| ?    | `ucol-UBU` | Pi 3 B+ | `udec-edge` (ADS1256) | not yet determined |

---

## Alerting policy (revised 2026-07-29)

The first production run sent **1,386 Telegram messages in four days** — 697 on
the last day alone, 73 in one hour. Technically correct, operationally useless.
The revision below was driven by that message history, not by intuition.

### What the history showed

| Rule | Alerts | Messages | Diagnosis |
|---|---:|---:|---|
| `electrical.current` | 471 | **962** | Threshold at the **94th percentile** of normal operation, flapping. 404 of 472 alerts lasted **under 2 minutes**. |
| `node.measurements_stale` | 3 | 95 | Node had no operational deployment. |
| `node.heartbeat_lost` | 1 | 64 | Node deliberately switched off. |
| `electrical.voltage_low` | 1 | 63 | Node not deployed. |
| `electrical.power_factor` | 16 | 32 | Fired at 0.89 against a 0.90 threshold. |
| `electrical.consumption_spike` | 15 | 26 | +26–35 % — a normal air-conditioning start. |

**1,288 of 1,312 alert messages (98 %) came from nodes with no operational
deployment.**

### The four mechanisms

**1. Deployment awareness** — the largest single fix. Policy is derived from the
platform's own reference tables (`node_commission_states`,
`deployment_statuses`) via `app/monitoring/lifecycle.py`, which defines **no
states of its own**. It reads three flags:

| Flag | Effect |
|---|---|
| `is_monitored` | Alert about this node at all. `registered` / `decommissioned` = never. |
| `may_upload` | Node is expected to be talking to us. `suspended` = silence is intended. |
| `is_operational` | Deployment expects live measurement. `completed` / `planned` / `cancelled` = no electrical alerts. |

Heartbeat loss **pages only while a deployment is operational**. A commissioned
node with no campaign going quiet is idle equipment: recorded, reported, not
pushed.

**2. Sustain windows** — a condition must persist before anyone is told
(30 min for current and spikes). The alert is still created immediately, so it
appears in the API and the report; only the *notification* waits. A transient
that clears inside the window never reaches Telegram at all.

**3. Hysteresis** — an alert does not close the instant the value dips
(`resolve_after_seconds`, default 900). This kills the open/resolve flap that
produced two messages per threshold crossing. Simulated: 20 crossings now
produce **1 message instead of 40**.

**4. Report-only routing** — ~30 rules are recorded and shown in the hourly
report but never pushed (`config.report_only_rules`). They **break out and page
anyway at CRITICAL** (`report_only_escalates_at`), so a rule that is usually
boring can still shout: power factor at 0.89 is silent, at 0.55 it pages.

### Thresholds now come from evidence

Monitoring **no longer inherits `runtime_platform_settings.json`.** Those are UI
display defaults — and they were the arbitrary numbers causing the noise
(`maxCurrent: 200`, `minPowerFactor: 0.90`, `demandSpike: 25`). Paging a human
is a different decision from colouring a chart.

Current thresholds resolve in this order:

1. `electrical.current_limit_by_node` — the panel or CT rating. **Set this.**
2. The node's own learned envelope: p99.5 of a 7-day window × 1.15.
3. An absolute safety ceiling (400 A / 500 A).

For N001: learned threshold **296 A** against an observed max of 273 A and a
median of 94 A. The old flat 200 A sat below its 95th percentile.

Other revisions: power factor 0.90 → **0.85** (where GDMTH penalties begin);
voltage band ±10 % → **±13 %** (CFE's own tolerance is ±10 %, so alerting there
alerts on compliant supply); consumption spike 25 % → **100 % *and* 4σ outside
the panel's own variability *and* sustained**; new
`electrical.contracted_demand` rule, because approaching contracted demand is
the case that actually costs money.

### Measured result

Replaying all 16,492 stored readings from the same four days:

| | Messages |
|---|---:|
| Old policy | **895** |
| New policy | **0** |
| Counterfactual (N001 assumed deployed the whole period) | **0** |

Since deployment: **0 messages**, with the scheduler ticking normally.

### Proof it is quiet for the right reason

`sensitivity.py` asserts 16 scenarios — that genuine faults still fire and the
known noise does not:

- **Still pages:** 480 A overload · 320 A above learned baseline · missing phase
  (CRITICAL) · total power loss · impossible sensor readings · voltage collapse
  to 95 V · **power factor 0.55** (severity breakout)
- **Now silent:** 236.7 A (the exact value from the history) · PF 0.89 ·
  +31 % spike · 17.9 % imbalance
- **Deployment gate:** a 480 A overload is silent on a node with no operational
  deployment — the gate beats severity

These are in the permanent suite (`tests/test_monitoring.py`, sections 19–23).

### Tuning it

```jsonc
// backend/monitoring_config.json
{
  "electrical": {
    "current_limit_by_node":  { "N001": 250.0 },   // panel rating — best signal
    "contracted_demand_kw":   { "N001": 100.0 }
  },
  "policy":   { "default_sustain_seconds": 600, "resolve_after_seconds": 900 },
  "node_lifecycle": { "N003": "maintenance" }      // silence one node
}
```

To stop a switched-off node being watched at all, set its commission state —
that is what the platform's state machine is for:

```sql
UPDATE nodes SET commission_state = 'decommissioned' WHERE code = 'N003';
```

`suspended` keeps hardware monitoring but expects silence; `decommissioned`
stops monitoring entirely.

---

## Physical equipment ratings — where to enter yours

Added by migration **008** (`008_physical_ratings_and_node_transitions`). Every
field is **nullable and unset**; nothing is guessed. Enter what you know, leave
the rest NULL, and the resolver falls through to the next source.

### The fields

| Field | Lives on | Meaning |
|---|---|---|
| `panel_main_breaker_a` | deployment | Main breaker rating. **The single most valuable value** — it is what protects the conductor. |
| `ct_max_current_a` | node *and* deployment | CT/clamp measurement ceiling. Readings above it are artefacts, not currents. |
| `nominal_voltage_v` | node *and* deployment | Service voltage (127 V single, 220 V line-to-line here). |
| `phase_count` | node *and* deployment | 1 or 3. Imbalance rules are meaningless on single-phase. |
| `warning_current_a` | node *and* deployment | Explicit alert level. Overrides every derivation. |
| `critical_current_a` | node *and* deployment | Explicit alert level. |
| `emergency_current_a` | node *and* deployment | Explicit alert level; outranks the duration ladder. |
| `sustained_seconds` | node *and* deployment | How long a breach must persist before anyone is told. |

Deployment values win over node values, because the panel changes between
campaigns while the clamp travels with the Pi.

### How to enter them

**Per deployment** (preferred — this is where the panel lives):

```bash
curl -X PUT localhost:8010/api/deployments/4/ratings \
  -H 'Content-Type: application/json' \
  -d '{"panel_main_breaker_a": 250, "nominal_voltage_v": 127, "phase_count": 3}'
```

**Per node** (the clamp that travels with the hardware):

```bash
curl -X PUT localhost:8010/api/nodes/N001/ratings \
  -H 'Content-Type: application/json' \
  -d '{"ct_max_current_a": 200, "nominal_voltage_v": 127, "phase_count": 3}'
```

**See what is set and what it resolves to** — this reports the source of every
threshold, so you can tell a nameplate from a statistic:

```bash
curl -s localhost:8010/api/deployments/4/ratings | python3 -m json.tool
curl -s localhost:8010/api/nodes/N001/ratings    | python3 -m json.tool
```

A `monitoring_config.json` override (`electrical.current_limit_by_node`) still
works and is checked too, but the database fields are the better home: they
survive a config reset and they sit next to the deployment they describe.

### Resolution order

1. **Deployment** explicit `warning/critical/emergency_current_a`.
2. **Deployment** `panel_main_breaker_a` or `ct_max_current_a` → warning at 90 %
   of the rating, critical at the rating, emergency at 115 %.
3. **Node** explicit limits.
4. **Node** `ct_max_current_a`, derived the same way.
5. **Learned baseline** — p99.5 × 1.15 of the node's own history, computed
   **only from readings taken during operational deployments**, and only with
   at least 500 such samples.
6. **Conservative fallback** — a fixed safety ceiling, so an unconfigured node
   still reports something genuinely dangerous.

**A learned baseline can never exceed the physical rating.** Two failure modes
this prevents: a baseline that *learns an overload* (run a panel at 110 % of its
breaker for a week and the percentile quietly adopts it as normal), and a
baseline computed from *CT saturation artefacts* above the clamp's range. The
cap is `min(panel breaker, deployment CT, node CT)` — whichever piece of
equipment gives out first.

---

## Node lifecycle transitions

Migration 008 also added what M7 left out: `node_commission_transitions` (legal
moves) and `node_commission_events` (the audit trail). Before this, the only way
to change `commission_state` was raw SQL — the exact bypass ADR-0001 removed for
deployments.

```bash
# What is this node, and where can it go?
curl -s localhost:8010/api/nodes/N002/commission-history | python3 -m json.tool

# Move it, with a reason that is recorded forever
curl -X POST localhost:8010/api/nodes/N002/commission-state \
  -H 'Content-Type: application/json' \
  -d '{"to_state":"commissioned","reason":"redeployed to Building X","actor":"you"}'
```

An illegal move returns **409** and changes nothing, listing the legal targets.

### Choosing a state

| State | `is_monitored` | `may_upload` | Use it for |
|---|:--:|:--:|---|
| `registered` | 0 | 0 | **Available hardware, powered off, stored.** Reversible; silence is expected. |
| `commissioned` | 1 | 1 | In service. Silence is an alarm. |
| `suspended` | 1 | 0 | Uploads revoked but **still physically installed** — so still watched as hardware. |
| `decommissioned` | 0 | 0 | **Terminal.** Permanently retired; there is no transition out. |

`registered` is the correct state for stored, reusable hardware. Its description
still reads "not yet verified in the field" — written for the pre-commissioning
case — but its flags and its reversibility are exactly right, and it is the only
non-terminal unmonitored state. Moving back is one call to
`/commission-state` with `commissioned`.

For a *temporary* silence where monitoring should resume shortly, prefer
`node_lifecycle: {"N00X": "maintenance"}` in `monitoring_config.json` — it needs
no state change and no audit entry.

---

## Deployment status

| Component | State |
|---|---|
| Backend router `/api/monitoring` | **live** |
| Six monitoring tables | **created**, operational schema untouched |
| Scheduler | **running**, `@reboot` crontab persistence |
| Telegram delivery | **verified end to end** |
| Heartbeat agent on **N002** | **installed and running** |
| Heartbeat agent on the other two nodes | **not installed** — see below |
| systemd unit for the scheduler | **not installed** — needs root |

### Remaining work

**1. Install the scheduler as a systemd service** (needs your password):

```bash
sudo cp /home/manager/energy-platform/monitoring/energy-platform-monitoring.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now energy-platform-monitoring.service
```

Then remove the interim `@reboot` line from `crontab -e`. Until then monitoring
runs via `run-monitoring.sh`, which survives reboots but not a machine-level
crash of the process supervisor.

**2. Install the agent on the remaining two nodes.** Neither is reachable from
the cloud server: their Tailscale addresses (`100.79.227.108`, `100.98.67.31`,
`100.125.1.37`) do not route from here because Tailscale is not installed on the
server, and `148.213.2.153` began refusing authentication after a failed login
attempt — almost certainly fail2ban. Install from your own machine using the
steps above, or install Tailscale on the server to reach all three directly.

---

## Deliberate non-coverage

These are registered rules that report *why they cannot run* rather than
silently passing. Each becomes live the moment its data source exists.

| Check | Why unavailable |
|---|---|
| `electrical.ups` | No UPS integration exists in the platform (no NUT client, no UPS fields) |
| `network.tailscale` | Tailscale is not installed on the server |
| `security.certificates` | No TLS anywhere — both services serve plain HTTP, no `/etc/letsencrypt` |
| `server.firewall` | `ufw status` requires root; `sudo` needs a password here |
| `server.temperature` | Virtualised host exposes no thermal zones |

Git commit reporting is also unavailable server-side: `/home/manager/energy-platform`
is not a git repository.

---

## False positives found and fixed during commissioning

Recorded because each was found against real data, and each would have
destroyed trust in the system within a day.

1. **Current imbalance at the noise floor.** N003's phases read ~1e-5 A when
   idle. The percentage spread between noise samples was 39.6 %, reported as
   CRITICAL. Fixed with a minimum-current floor (`imbalance_min_current_a`).
2. **Reverse power flow at −0.00 kW.** An idle meter reports ~−1e-9 kW. A bare
   `< 0` test called that reverse flow. Fixed with a deadband.
3. **SPI unavailable on a node with no SPI.** N002 uses a networked Shelly Pro
   3EM. The agent now reports SPI only when present, never as a fault.
4. **Standby mistaken for data loss.** N002 has no deployment, so the backend
   returns HTTP 400 and the collector logs *"pre-deployment reading(s) discarded
   safely"* — designed behaviour, not a bug. Reclassified from ERROR
   "data loss" to WARNING "in standby".
5. **Commissioning gaps escalating to EMERGENCY.** "Node has never sent a
   heartbeat" is a persistent state, not a worsening incident. Added
   `Finding.max_severity`, which also suppresses hourly reminders for such
   states.
6. **Buffer count including discarded rows.** The node buffer holds
   `sync_status` 0/1/2; counting every row reported ~19 000 pending on a healthy
   node. The agent now counts only unsent rows (observed: 2).

---

## Known state of the fleet (2026-07-26)

- **N001** — measuring normally (~15 s cadence). Genuine **17.9 % current
  imbalance** (36.6 / 28.8 / 27.7 A). Worth investigating: NEMA guidance is
  under 10 % for motor loads. No heartbeat agent yet.
- **N002** — `energy-node-002`, Pi 5. Alive, collecting, **in standby**: no
  deployment exists, so its electrical readings are discarded by design. Owns
  the four smart plugs. Heartbeat agent installed. Its `vcgencmd get_throttled`
  reports `0x50000` — undervoltage and throttling **have occurred** since boot,
  though not currently active. Worth checking the power supply.
- **N003** — measuring (~50 s cadence), currently drawing ~0 A with voltage
  present. No heartbeat agent yet.
