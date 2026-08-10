# Backend patch set — Phase A

**DEPLOYMENT BLOCKED BY MISSING SSH ACCESS TO THE BACKEND HOST.**

```
theblackdie@148.213.1.15: Permission denied (publickey,password)
root@148.213.1.15:        Permission denied (publickey,password)
ssh keys on N001: 0     backend on tailnet: no
```

Nothing in this directory has been deployed, executed against the real
backend, or regression-tested there. It is written and unit-tested locally.
The remaining step is deployment by someone with access.

## Important caveat about form

The backend source is **not present on any node** — I searched. These are
therefore **drop-in modules plus an integration specification**, not a diff
against your tree. Whoever applies them must reconcile the module boundaries
with the real source layout. Every behavioural claim below is derived from the
live API contract (`/openapi.json`) and from black-box probing of the running
service on 2026-08-03, and each is labelled with how it was established.

---

## Defect 1 — split heartbeat (the 43h37m outage)

**Established by:** reading `/openapi.json` and `collector.py`, plus a live
probe.

There are two heartbeat concepts:

| path | written by | effect |
|---|---|---|
| `POST /api/edge/heartbeat` | collector | updates `last_sync` only |
| `POST /api/monitoring/heartbeat` | *nobody* | feeds the monitoring subsystem |

Consequence: N001 sat at `ever_seen=false`, `heartbeat_age_seconds=null`,
`missed_beats=0` **forever**. `node.heartbeat_lost` — the rule that correctly
caught N002 at EMERGENCY with 64 notifications — can never fire for a node
that has never been seen. `node.power` never fired either, across 180
undervoltage events.

**Live probe, 2026-08-03:** POSTing to `/api/monitoring/heartbeat` does **not**
update `last_sync`. Verified by capturing `last_sync` before and after; it was
byte-identical. This is why the node currently publishes to both paths.

### Fix
`canonical_heartbeat.py` — one ingest path, one store, two URL surfaces.
`/api/edge/heartbeat` becomes a thin compatibility alias that funnels into the
same handler, so it also updates the monitoring store, and
`/api/monitoring/heartbeat` also updates `last_sync`.

Once deployed, set `HEARTBEAT_LEGACY_EDGE_PUBLISH=0` in each node's
`hardening.conf`. The node then publishes exactly once. No node code change
is required — it is a config flag flip.

---

## Defect 2 — `node.filesystem_readonly` false positive

**Established by:** black-box probing on 2026-08-03. N001's `/` is genuinely
`rw` and writable (`findmnt` shows `rw,noatime`; a `touch` succeeds), yet the
rule fires **CRITICAL** with the text *"The SD card has almost certainly
failed. Local buffering is silently discarding everything it tries to write."*

### Why false / null / missing all produce the same outcome

Two faults compound:

**(a) The field is accepted but never persisted.** `filesystem_readonly` is
present in the `HeartbeatPayload` schema in `/openapi.json`, so the API
accepts it and returns HTTP 200. But it is absent from the stored heartbeat
record. `GET /api/monitoring/nodes/N001/heartbeats` returns only:

```
buffered_readings, clock_drift_seconds, collector_status, cpu_percent,
disk_percent, latency_ms, memory_percent, received_at, temperature_c,
throttled, undervoltage, uptime_seconds
```

`filesystem_readonly` is not there. The value is dropped between ingest and
storage, so the rule can only ever read NULL.

**(b) The rule treats NULL as a definite state.** A condition of the shape
`if not hb.filesystem_readonly is False` / `if hb.filesystem_readonly != False`
/ `if row.get("filesystem_readonly", True)` maps NULL onto "read-only" rather
than "unknown". Because of (a) the stored value is *always* NULL, so the alert
fires permanently and identically for `false`, `null` and a missing key —
exactly what the probe showed.

**This is the same defect class as the outage.** For heartbeats, NULL was
treated as *healthy*, so `node.heartbeat_lost` silently never fired. For the
filesystem, NULL is treated as *faulty*, so it fires forever. **Null is not a
state**, and a monitoring system that cannot say "I don't know" will either
cry wolf or stay silent — this platform does both, in different rules.

### Fix
`monitoring_rules_fix.py` introduces `tri_state()` and `evaluate_boolean_rule()`.
NULL becomes an explicit `UNKNOWN` that suppresses the alert and, after a grace
period, raises a low-severity *staleness* alert instead — so a field that stops
being reported is still noticed, without asserting a fault that isn't there.
Plus the persistence fix so the field is actually stored.

---

## Files

| file | purpose |
|---|---|
| `canonical_heartbeat.py` | unified ingest; `/api/edge/heartbeat` as alias |
| `monitoring_rules_fix.py` | `tri_state()`, fixed filesystem + heartbeat rules |
| `migrations/001_heartbeat_filesystem_readonly.sql` | adds the missing column |
| `tests/test_monitoring_rules.py` | regression tests, every case |
| `tests/test_canonical_heartbeat.py` | ingest/alias equivalence tests |
| `MIGRATION.md` | ordered deployment + rollback runbook |

## Run the tests

Locally, no backend required (pure functions):

```bash
python3 -m pytest /opt/energy-node/hardening/backend/tests -v
```

## Post-deployment regression commands

These **require the running backend** and must be executed after deployment.
Exact commands, ready to paste:

```bash
# 1. filesystem_readonly must NOT alert when the node reports false
curl -s -X POST http://148.213.1.15:8010/api/monitoring/heartbeat \
  -H 'Content-Type: application/json' \
  -d '{"node_id":"N001","filesystem_readonly":false}' -o /dev/null -w '%{http_code}\n'
sleep 90
curl -s http://148.213.1.15:8010/api/monitoring/alerts \
  | python3 -c "import json,sys;a=[x for x in json.load(sys.stdin)['alerts'] if x['rule_id']=='node.filesystem_readonly' and x['node_code']=='N001'];print('OPEN' if any(x['is_open'] for x in a) else 'RESOLVED (expected)')"

# 2. it MUST still alert when genuinely read-only
curl -s -X POST http://148.213.1.15:8010/api/monitoring/heartbeat \
  -H 'Content-Type: application/json' \
  -d '{"node_id":"N001","filesystem_readonly":true}' -o /dev/null -w '%{http_code}\n'
sleep 90
# expect an OPEN node.filesystem_readonly alert

# 3. the field must now round-trip
curl -s http://148.213.1.15:8010/api/monitoring/nodes/N001/heartbeats \
  | python3 -c "import json,sys;h=json.load(sys.stdin)['heartbeats'][0];print('filesystem_readonly' in h, h.get('filesystem_readonly'))"
# expect: True False

# 4. canonical heartbeat must update BOTH stores
before=$(curl -s http://148.213.1.15:8010/api/nodes | python3 -c "import json,sys;print([n for n in json.load(sys.stdin) if n['id']=='N001'][0]['last_sync'])")
curl -s -X POST http://148.213.1.15:8010/api/monitoring/heartbeat \
  -H 'Content-Type: application/json' -d '{"node_id":"N001"}' -o /dev/null
after=$(curl -s http://148.213.1.15:8010/api/nodes | python3 -c "import json,sys;print([n for n in json.load(sys.stdin) if n['id']=='N001'][0]['last_sync'])")
[ "$before" != "$after" ] && echo "PASS: last_sync updated" || echo "FAIL: still split"

# 5. only after 4 passes, on each node:
sudo sed -i 's/^HEARTBEAT_LEGACY_EDGE_PUBLISH=1/HEARTBEAT_LEGACY_EDGE_PUBLISH=0/' \
  /opt/energy-node/hardening/config/hardening.conf
sudo systemctl restart energy-node-collector.service
sudo /opt/energy-node/hardening/bin/energy-node-verify
```

## Not fixed here (out of scope, still open)

- **Alert fatigue.** 968 of 1375 notifications (70%) came from
  `electrical.current` on N001 — 480 alerts in two days. Needs hysteresis or
  rate limiting on that rule. Left alone because it touches electrical alert
  semantics, which this task explicitly protects.
