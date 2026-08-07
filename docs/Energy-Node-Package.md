# The Energy Node Package

The reference build for every production node. A node either matches this
document or is drift — there is no third state.

**Version 2.1** · reference build established 2026-08-07 by the D2 convergence.

---

## Compatibility matrix

| Capability | Pi 5 | Pi 3B+ | Behaviour when unsupported |
|---|:--:|:--:|---|
| Collector (`app/collector.py`) | ✅ | ⚠ untested | — |
| Hardening package 2.0.0 | ✅ | ⚠ untested | — |
| Canonical heartbeat | ✅ | ⚠ untested | — |
| Credential authentication | ✅ | ✅ | — |
| PMIC ADC (per-rail power) | ✅ | ❌ | `caps["pmic_adc"] = False`; payload omits per-rail fields and `local_alerts` says *per-rail power unavailable on this board*. **Never faked.** |
| UPS HAT over I²C | ✅ (`i2c-1`) | ❌ if GPIO I²C not enabled | `ups.read()` returns `present=False`; `local_alerts` says *UPS not detected*, with the confidence that produced that verdict |
| SPI sensors | ✅ where `spidev` exists | ✅ | `spi_ok` is reported **only when present**; absence is silence, not `False` — a node with no SPI is not a node with broken SPI |
| `vcgencmd get_throttled` | ✅ | ✅ | absent → `throttled`/`undervoltage` are NULL, not False |

> [!WARNING]
> Reporting `False` for a capability a board does not have is a lie the
> monitoring system will act on. Every probe above distinguishes **absent**
> (NULL, no finding) from **present and failing** (False, a finding). The
> `node.filesystem_readonly` false EMERGENCY of 2026-08-04 came from exactly
> this confusion.

## Included services

| Unit | Responsibility | Type |
|---|---|---|
| `energy-node-collector` | **Sole** measurement, sync and heartbeat producer | long-running |
| `energy-node-netd` | Networking supervisor; publishes `/run/energy-node/network-state.json` | long-running |
| `energy-node-portal` | Maintenance portal | long-running |
| `energy-node-console` | Appliance console on tty1 | long-running |
| `energy-node-powerlog` | UPS / power telemetry recorder | long-running |
| `energy-node-blackbox` | Crash and black-box recorder | oneshot at boot |
| `energy-node-recovery-arm` | Arms recovery | oneshot at boot |
| `energy-node-selfheal.timer` | 2-min collector self-heal check; **inert unless `RECOVERY_SELF_HEAL=1`** | timer |
| `energy-node-verify.timer` | Nightly package checksum verification | timer |

**One responsibility per component.** There is exactly one heartbeat producer
per node — the collector. `energy-node-heartbeat.service` is **not** part of this
package; it was a transitional standalone agent, removed from N002 by D1 on
2026-08-07.

## Configuration

`/opt/energy-node/config/node.env`, **mode 600, owned by the collector user**.

| Key | Purpose |
|---|---|
| `NODE_ID` | Node code as registered in the platform. Must match the credential's subject or ingest returns 403. |
| `NODE_AUTH_TOKEN` | Bearer credential (ADR-0002). Issued by `provision_node`, never recoverable from the server. |
| `CENTRAL_API_URL` | Backend base URL |
| `SHELLY_IP`, `SHELLY_ID` | Meter identity |
| `DB_PATH` | Local buffer, default `/opt/energy-node/database/edge_buffer.db` |
| `POLL_INTERVAL` / `SYNC_INTERVAL` | 15 s / 60 s |

> [!WARNING]
> `collector.py` line 52 still defaults `NODE_ID` to `"N001"` when the variable
> is absent. A node with a missing or unreadable `node.env` would therefore claim
> to be N001. Authentication contains the blast radius — a mismatched credential
> is refused 403 `subject_mismatch` — but this default should become a hard
> failure. Tracked as a follow-up; not changed during convergence to avoid
> conflating a behaviour change with a version upgrade.

## Layout

```
/opt/energy-node/
  app/collector.py              the canonical collector
  hardening/lib/                12 modules, version 2.0.0
    telemetry.py  heartbeat.py  sysinfo.py  ups.py  sensors.py
    doctor.py  selftest.py  blackbox.py  powerlog.py  enconfig.py
    tristate.py  i2cbus.py  version.py
  hardening/bin/                executables
  config/node.env               mode 600
  database/edge_buffer.db       local buffer (WAL)
  backups/                      timestamped, before every change
  venv/                         collector runtime
```

## Installation

Prerequisites: Debian 13, Python 3.13, network reachability to the backend.

```bash
# 1. Register the node and issue its credential (on the server)
cd backend
venv/bin/python3 -m app.db.provision_node issue N00X     # token shown ONCE

# 2. Install configuration on the node
sudo install -m 600 -o theblackdie -g theblackdie node.env /opt/energy-node/config/node.env

# 3. Install the package
sudo install -m 644 -o theblackdie -g theblackdie collector.py /opt/energy-node/app/collector.py
sudo /opt/energy-node/venv/bin/python -m py_compile /opt/energy-node/app/collector.py

# 4. Start
sudo systemctl enable --now energy-node-collector
```

## Upgrade

The procedure used for the D2 convergence, and the one to reuse:

```bash
# 1. Capture the buffer BEFORE, so preservation can be proved
sudo /opt/energy-node/venv/bin/python -c "
import sqlite3; c=sqlite3.connect('file:/opt/energy-node/database/edge_buffer.db?mode=ro',uri=True)
print(list(c.execute('select sync_status,count(*) from measurements group by sync_status')))"

# 2. Timestamped backup
TS=$(date +%Y%m%d_%H%M%S)
sudo cp -a /opt/energy-node/app/collector.py /opt/energy-node/backups/collector.py-before-<reason>-$TS

# 3. Install and compile BEFORE restarting — a syntax error must not reach systemd
sudo install -o theblackdie -g theblackdie -m 644 new_collector.py /opt/energy-node/app/collector.py
sudo /opt/energy-node/venv/bin/python -m py_compile /opt/energy-node/app/collector.py

# 4. Restart and verify
sudo systemctl restart energy-node-collector
systemctl is-active energy-node-collector
```

## Verification

Every check must pass before an upgrade is considered complete.

```bash
# On the node
grep -c '_hb_heartbeat.publish'  /opt/energy-node/app/collector.py   # must be 1
grep -c '_reading_auth_headers'  /opt/energy-node/app/collector.py   # must be >=1
sha256sum /opt/energy-node/app/collector.py                          # must match the fleet
systemctl is-active energy-node-collector                            # active
```

```sql
-- On the server: exactly ONE producer, authenticated, ~60s cadence
SELECT node_code, software_version, auth_status, COUNT(*)
  FROM monitor_node_heartbeats
 WHERE received_at > datetime('now','-5 minutes')
 GROUP BY 1,2,3;
```

Buffer preservation: `sync_status` counts after the restart must be **greater
than or equal to** the counts before. A decrease means rows were discarded.

## Checksums — reference build 2026-08-07

| Artefact | SHA-256 (first 24) | Nodes |
|---|---|---|
| `app/collector.py` | `d9cc6138c8be60b273615d13` | N001, N002 |
| hardening package | version 2.0.0, 12 modules | N001, N002 |

The collector is **node-agnostic**: identity comes from `node.env` only. The
startup banner uses `CONFIG["NODE_ID"]` rather than a literal, so the same bytes
run on every node — which is what makes a fleet-wide checksum meaningful.

## Rollback

```bash
sudo systemctl stop energy-node-collector
sudo cp -a /opt/energy-node/backups/collector.py-before-<reason>-<TS> \
           /opt/energy-node/app/collector.py
sudo systemctl start energy-node-collector
```

The buffer is untouched by a collector rollback — it is a separate SQLite file
and no upgrade step writes to it.

To restore the transitional standalone heartbeat agent (should the canonical
heartbeat ever fail on a node):

```bash
sudo systemctl enable --now energy-node-heartbeat
```

The unit and `/opt/energy-monitoring/node_heartbeat.py` are **retained on N002**
until the soak completes. They are not part of this package and must be deleted
once the canonical heartbeat has run clean for a full day.

## Unsupported hardware

**Raspberry Pi 3B+ (N003)** is not supported by this package. It runs a
different collector (`/home/theblackdie/udec-edge/poller.py`, system Python, no
venv, no hardening, no credential). Migrating it is its own project — see
[`monitoring/evidence/node03-audit-20260806_144255.md`](../monitoring/evidence/node03-audit-20260806_144255.md).
Do not install this package there without first resolving:

* no PMIC ADC → per-rail telemetry must degrade, not fake;
* GPIO I²C bus not enabled → the UPS HAT is unreadable;
* 905 MB RAM versus the Pi 5's headroom;
* `sudo` requires a password, unlike N001/N002.
