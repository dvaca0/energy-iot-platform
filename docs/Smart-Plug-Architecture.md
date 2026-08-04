# Smart Plug subsystem — architecture

Smart plugs (Shelly Plug US Gen4) are **accessories of a deployment, not Energy
Nodes**. They answer one question during a measurement campaign: *which outlet
or connected appliance is consuming the most?* They never participate in Energy
Node ingestion, and the Energy Node tables are never written by this subsystem.

Version: see `edge/VERSION` and `edge/CHANGELOG.md`.

---

## 1. Overall architecture

```
   Shelly plugs (read-only RPC over HTTP)
        ▲   ▲   ▲   ▲
        │   │   │   │      discovery + polling happen ONLY on the Pi
   ┌────┴───┴───┴───┴─────────────────────────┐
   │  Raspberry Pi (Energy Node collector)    │
   │                                          │
   │  ┌────────────────┐  ┌────────────────┐  │
   │  │ Energy Node    │  │ SmartPlugSource│  │
   │  │ pipeline       │  │  (2 threads)   │  │
   │  │ (untouched)    │  │                │  │
   │  └───────┬────────┘  └───────┬────────┘  │
   │  edge_buffer.db      smart_plugs.db      │   separate SQLite files
   └──────────┼───────────────────┼───────────┘
              │ POST /api/readings │ POST /api/smart-plugs/discovery
              │ POST /api/edge/…   │
              ▼                    ▼
   ┌──────────────────────────────────────────┐
   │  Backend (FastAPI, gunicorn :8010)       │
   │  ownership + validation + persistence    │
   │  smart_plugs / smart_plug_readings       │
   └──────────────────┬───────────────────────┘
                      │ GET /api/smart-plugs, /live, /{id}/history
                      ▼
   ┌──────────────────────────────────────────┐
   │  Frontend (static SPA :5174)             │
   └──────────────────────────────────────────┘
```

The cloud never scans anything. It only receives what each Pi already found.

## 2. Responsibilities

### Raspberry Pi

- Discover plugs on whatever networks it is currently attached to.
- Poll each known plug and buffer every measurement locally **before** upload.
- Report inventory plus buffered measurements to the backend.
- Survive backend outages, reboots and DHCP changes without losing data.
- Never write to a plug: only `Shelly.GetDeviceInfo`, `Switch.GetStatus`,
  `WiFi.GetStatus` are used, so a plug is never switched on or off.

### Backend

- Enforce **ownership**: only the owning node may report a plug.
- Validate every report (MAC format, duplicates, timestamps).
- Persist inventory and history; never delete a plug.
- Serve inventory, live view and history to the frontend.

### Frontend

- Display inventory, live consumption and the highest consumer.
- Allow assigning a plug to a building/deployment with a friendly name.
- It performs no discovery and holds no device logic.

## 3. Discovery flow

```
every 300 s  ─┬─► mDNS (_shelly._tcp) if zeroconf installed
              ├─► bounded sweep of each attached subnet (≤1024 addresses)
              └─► last known IPs (cheapest hit)
                        │
                        ▼
              identify(ip)  ──► Shelly.GetDeviceInfo → MAC?
                        │            no → discard
                        ▼
              has_switch_metering(ip)  ──► not a plug → discard
                        │
                        ▼
              _register(identity)  ── upsert by MAC, IP updated in place
```

Nothing about the network is hardcoded: interfaces and subnets are read from
the kernel (`ip -o -f inet addr show scope global`) at runtime, so the same code
works on any SSID or subnet. A subnet larger than 1024 addresses is never swept,
so a university-wide network is not flooded; discovery then relies on mDNS and
last known IPs.

## 4. Polling flow

```
every 15 s ─► poll each known plug at its latest IP (thread pool)
                │
                ├─ success → buffer measurement, mark online, refresh last_seen
                │
                └─ failure → mark offline, increment failures,
                             wake the discovery loop IMMEDIATELY
                                (targeted rediscovery, not a 5 minute wait)
             ─► report(): upload buffered batch, delete only once accepted
```

## 5. Capability detection

**Smart Plugs are identified by capability, never by product name.** A device
qualifies only when all three hold:

1. it answers `Shelly.GetDeviceInfo` with a MAC;
2. it exposes a **controllable Switch** at id 0 — `Switch.GetStatus?id=0`
   returns an `output` boolean;
3. that switch carries **metering** — instantaneous power (`apower`) *and*
   cumulative energy (`aenergy.total`).

Implemented in `has_switch_metering()`, applied by `identify()`.

Model strings, app strings, firmware versions and MAC allowlists are never
consulted. Two consequences:

- **A new plug model or future generation needs no code change.**
- **Energy Meters are excluded automatically, not by blocklist.** The Shelly
  Pro3EM used by the Energy Node is also a Shelly device answering the same
  discovery RPC, but it has no Switch component — it replies HTTP 404
  `No handler for Switch.GetStatus` — so it fails condition 2. This matters
  because every Pi polls its own Pro3EM on a subnet it also sweeps for plugs.

`KNOWN_FLEET` is documentation only; no behaviour depends on it.

## 6. Ownership model

Each plug has exactly one **authoritative owner node**.

- The first node to report a plug **claims** it (`node_id`, `owner_claimed_at`).
- Reports from any other node are **rejected**, per plug, and returned in
  `rejected_not_owner`. They are not accepted as the latest writer.
- Ownership lives in the database, so it survives **reboots, IP changes and
  rediscovery**.
- Transfer is **explicit only**: `POST /api/smart-plugs/{id}/transfer`.

Why: two Pis on the same subnet discover the same plugs. Under last-writer-wins
the owner would flip every cycle and each plug would receive two independent
measurement streams. The node's own journal logs the rejection, so a plug that
never appears in the platform is explainable from the node.

The older rule — *one enabled node per subnet* — is now only a convenience.
Ownership is enforced by the backend regardless.

## 7. Buffering

- Measurements are written to SQLite **before** upload and deleted **only after**
  the backend accepts them, so nothing is lost to an outage.
- `UNIQUE(mac, captured_at)` locally and `UNIQUE(smart_plug_id, timestamp)` on
  the backend make replaying a buffered batch idempotent.
- The plug buffer is a **separate SQLite file** from the Energy Node buffer, by
  design. Energy Node buffering, retries and deployment-aware discarding are
  never touched.
- Inventory and last known IPs are persisted, so a rebooted Pi resumes with its
  known devices instead of starting blind.

## 8. Database schema

### Edge — `smart_plugs.db`

| Table | Purpose |
|---|---|
| `pending_measurements(id, mac, captured_at, payload)` | store-and-forward queue, `UNIQUE(mac, captured_at)` |
| `known_plugs(mac, ip, identity, last_seen)` | inventory, survives reboot |
| `source_state(key, value)` | diagnostics for `--health` |

### Backend

`smart_plugs` — identity and live snapshot:

| Column | Notes |
|---|---|
| `mac` | unique, the permanent identity |
| `ip_address`, `hostname`, `serial`, `firmware`, `rssi`, `temperature_c` | volatile, refreshed each report |
| `node_id` | **authoritative owner** |
| `owner_claimed_at` | when ownership was established |
| `building_id`, `deployment_id`, `friendly_name`, `outlet_location` | assignment |
| `online`, `last_seen`, `power_w`, `voltage_v`, `current_a`, `power_factor`, `energy_total_kwh` | live snapshot |

`smart_plug_readings` — history, `UNIQUE(smart_plug_id, timestamp)`, with
denormalised `node_id` / `building_id` / `deployment_id` so history stays
meaningful after reassignment.

Both tables are new; no existing table was modified beyond adding
`smart_plugs.owner_claimed_at`.

## 9. API endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/smart-plugs` | full inventory, assigned and unassigned |
| GET | `/api/smart-plugs/live` | live view plus `highest_consumer` |
| GET | `/api/smart-plugs/{id}` | one plug |
| GET | `/api/smart-plugs/{id}/history` | historical readings |
| POST | `/api/smart-plugs/{id}/assign` | assign to building/deployment |
| POST | `/api/smart-plugs/{id}/transfer` | **explicit ownership transfer** |
| POST | `/api/smart-plugs/discovery` | edge report (inventory + measurements) |

`{id}` accepts the slug (`acebe6f65388`), the MAC in any notation, or the
numeric primary key.

`online` is true only when the edge reported the plug up **and** that report is
still fresh (`ONLINE_WINDOW_SECONDS = 90`), so a plug also goes offline when the
Pi itself stops reporting. While offline, telemetry is returned as `null` rather
than stale values.

### Discovery response

```json
{
  "status": "ok", "node": "N002",
  "plugs_created": 0, "plugs_updated": 4,
  "readings_inserted": 4, "readings_duplicated": 0,
  "rejected_malformed_mac": [], "rejected_duplicate_mac": [],
  "rejected_not_owner": [], "rejected_timestamps": 0
}
```

## 10. Installer workflow

```
./install-smart-plugs.sh --node-id N002 --enable

1 inspect        unit, collector, interpreter, service user, node id,
                 backend URL, writable buffer dir — all auto-detected
2 versions       installed vs available, shown before anything changes
3 compatibility  import os / log / def main() / polling_loop() + stdlib
                 incompatible → abort, nothing modified
4 backup         <node-root>/backups/smart-plugs-<timestamp>/
5 install        changed files only ([SAME] is skipped)
6 integrate      1 config reader + 1 starter + 1 call; refuses if any
                 pre-existing line would change; byte-compiles
7 configure      /etc/energy-node/smart-plugs.conf, preserving settings
8 restart        only if something actually changed
9 verify         journal, version on node, activity and error counts
10 report        edge/reports/<hostname>-<timestamp>.md
```

`--dry-run` stops after step 2. Re-running is safe and is the upgrade path.

Configuration lives in `/etc/energy-node/smart-plugs.conf` rather than each
node's env file because nodes do not pass configuration the same way — N001/N002
use `EnvironmentFile=`, N003 uses inline `Environment=` lines and defines no
`NODE_ID`. One path works everywhere and leaves Energy Node config untouched.

## 11. Upgrade workflow

1. Update the canonical repo `/home/manager/energy-platform/edge/` and bump
   `VERSION` plus `CHANGELOG.md`.
2. Copy the kit to the node and run the installer with no `--enable`/`--disable`
   flag, so the existing enable state is preserved.
3. The installer replaces only changed files, keeps the config, restarts only if
   needed, and writes a report.

## 12. Rollback workflow

Fastest, no code change:

```bash
sudo sed -i 's/^SMART_PLUGS_ENABLED=1/SMART_PLUGS_ENABLED=0/' /etc/energy-node/smart-plugs.conf
sudo systemctl restart energy-node-collector.service
```

The integration is inert when disabled, and the Energy Node pipeline is
unaffected either way.

Full restore:

```bash
sudo cp <backup>/collector.py /opt/energy-node/app/collector.py
sudo cp <backup>/smart_plug_source.py /opt/energy-node/app/
sudo cp <backup>/smart-plugs.conf /etc/energy-node/
sudo systemctl restart energy-node-collector.service
```

Backend: restore `app/routers/smart_plugs.py` and `app/db/models.py` from
`backend/backups/*-before-ownership-*`, then
`kill -HUP $(systemctl show -p MainPID --value energy-platform-backend.service)`.

## 13. Troubleshooting

Start here, on the node:

```bash
smart-plug-health          # or: smart-plug-health --json
```

It reports collector unit and status, whether the source is enabled, version,
known and online plugs, pending measurements, backend reachability, and the
timestamps of the last discovery, last poll, last successful poll and last
report.

| Symptom | Likely cause |
|---|---|
| A plug is visible on the network but absent from the platform | Another node owns it. Check `rejected (not owner)` in health, and the backend journal. Use `/transfer` to move it. |
| `found 0 plug(s)` | The plugs are on a different subnet from this Pi. `local_networks()` output is printed with `--once`. |
| Energy Meter appears as a plug | Should be impossible ≥1.1.0. Verify `has_switch_metering` exists in the installed source. |
| `pending measurements` climbing | Backend unreachable. Check `last backend error`. Nothing is lost; it drains on recovery. |
| Plug stuck offline | Poll failing. Rediscovery is automatic and immediate; check the plug has power and the same SSID. |
| Nothing in the journal about plugs | `SMART_PLUGS_ENABLED=0`, or the collector was never restarted after install. |

Useful journal filters:

```bash
journalctl -u energy-node-collector.service | grep -E 'Smart Plug|discovery probed|reported'
journalctl -u energy-platform-backend.service | grep -iE 'rejected|claimed|transfer'
```

## 14. Deployment examples

Fresh install, node owns the plugs on its subnet:

```bash
./install-smart-plugs.sh --node-id N002 --enable
```

Install on a second node on the same subnet, ready but not collecting:

```bash
./install-smart-plugs.sh --node-id N003 --backend http://148.213.1.15:8010 --disable
```

Upgrade every node, preserving each one's enable state:

```bash
./install-smart-plugs.sh --node-id N001
```

Preview without touching anything:

```bash
./install-smart-plugs.sh --node-id N001 --dry-run
```

Hand a plug to another node:

```bash
curl -X POST -H 'Content-Type: application/json' \
     -d '{"node_id":"N003"}' \
     http://148.213.1.15:8010/api/smart-plugs/acebe6f65388/transfer
```
