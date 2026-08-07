# Fleet manifest

Canonical inventory of every node. **Purpose: detect configuration drift
immediately.** Any cell marked ⚠ is a divergence from the reference build, not a
design decision.

Captured **2026-08-07**. Regenerate with `scripts/fleet_manifest.py` (see
"Regenerating" below); do not hand-edit the measured columns.

Reference build = **N001**. It is the only node whose collector publishes the
canonical heartbeat, so it defines what "current" means until N002 is brought up
to it.

---

## Identity and access

| | N001 | N002 | N003 |
|---|---|---|---|
| Hostname | `energy-node-001` | `energy-node-002` | `ucol-UBU` |
| Tailscale | `100.125.1.37` | `100.98.67.31` | `100.79.227.108` |
| Public NAT (reachable from server) | `148.213.2.186` | `148.213.2.245` | `148.213.2.153` |
| SSH password | `Colimote902` | `Colimote902` | `hacktheworld` ⚠ |
| `sudo` | passwordless | passwordless | **password required** ⚠ |

> [!WARNING]
> Tailscale addresses **do not route from the cloud server** — tailscale is not
> installed there and installing it needs root. All server→node work uses the
> public NAT addresses. Those are shared and change; they are never identity.

## Hardware

| | N001 | N002 | N003 |
|---|---|---|---|
| Model | Raspberry Pi 5 Model B Rev 1.1 | Raspberry Pi 5 Model B Rev 1.1 | **Raspberry Pi 3 Model B+ Rev 1.3** ⚠ |
| Meter | Shelly Pro 3EM `shellypro3em-a4f00fd05558` | Shelly Pro 3EM 400 A `shellypro3em400-ecc9ffe730f4` | Shelly EM over HTTP |
| Rated CT | 120 A | 400 A | 1000 A |
| UPS | Waveshare UPS HAT (SKU25567) | Waveshare UPS HAT (SKU25567) | Waveshare UPS HAT (SKU25567) — **not readable** ⚠ |
| Bootloader | 2026-05-26 | **2026-01-21** ⚠ (4 months behind) | not surveyed |
| I²C buses | `i2c-1`, `i2c-13`, `i2c-14` | `i2c-1`, `i2c-13`, `i2c-14` | **`i2c-2` only** ⚠ (HDMI DDC; GPIO bus not enabled) |
| SPI | `spidev0.0`, `spidev0.1` | **none** ⚠ | `spidev0.0`, `spidev0.1` |
| PMIC ADC | yes | yes | **no** (Pi 3 has none) |
| `get_throttled` | `0x50000` (undervoltage + throttling *have occurred*) | `0x50000` (same) | `0x80000` (soft temp limit occurred) |

## Software

| | N001 | N002 | N003 |
|---|---|---|---|
| OS | Debian 13 (trixie) | Debian 13 (trixie) | Debian 13 (trixie) |
| Kernel | `6.18.34+rpt-rpi-2712` | `6.18.34+rpt-rpi-2712` | not surveyed |
| Python | 3.13.5 | 3.13.5 | 3.13.5 |
| Collector | `/opt/energy-node/app/collector.py` | same | **`/home/theblackdie/udec-edge/poller.py`** ⚠ |
| Collector venv | `/opt/energy-node/venv` | same | **none — system python** ⚠ |
| Collector mtime | 2026-08-06 | **2026-07-25** ⚠ (12 days behind) | 2026-07-24 |
| **Canonical heartbeat in collector** | **yes** | **no** ⚠ | **no** ⚠ |
| Hardening package | 2.0.0, 12 modules | 2.0.0, 12 modules | **absent** ⚠ |
| `config/node.env` | present, mode 600 | present, mode 600 | **absent** ⚠ |

## Platform state

| | N001 | N002 | N003 |
|---|---|---|---|
| Node code | N001 | N002 | N003 |
| Commission state | `commissioned` | `registered` | `registered` |
| `may_upload` | yes | no | no |
| Credential issued | yes | yes | yes |
| Credential **installed on node** | yes | yes | **no** ⚠ |
| Authenticating | yes | yes | **n/a — 401** |
| Measurement context | `infrastructure_validation` | `infrastructure_validation` | `infrastructure_validation` |
| Operational deployment | none | none | none |
| Monitored (`is_monitored`) | yes | no | no |
| Uploads accepted | yes (unattributed) | **403** (by design) | **401** (no credential) |

## Heartbeat producers — the current divergence

| Node | Producer | Version | Unit | Status |
|---|---|---|---|---|
| N001 | collector, canonical `telemetry.build()` | 2.0.0 | `energy-node-collector` | ✅ reference |
| N002 | **legacy standalone agent** | 1.0.0 | `energy-node-heartbeat` | ⚠ **load-bearing, not redundant** |
| N003 | none | — | — | ⚠ no heartbeat at all |

**N002's collector does not contain the canonical heartbeat call** —
`grep -c '_hb_heartbeat.publish' collector.py` returns **0** on N002 and **1** on
N001. Its `Heartbeat OK` log lines are the *legacy* 3-field post to
`/api/edge/heartbeat`, which updates `nodes.last_sync` but writes nothing to
`monitor_node_heartbeats`.

> [!WARNING]
> `energy-node-heartbeat.service` on N002 looks like duplication and is **not**.
> It is currently N002's only source of canonical heartbeats. Removing it before
> upgrading N002's collector would blind the node. See
> [P2-Simplification-Audit.md](P2-Simplification-Audit.md) item **D1**.

## systemd units

Both Pi 5 nodes run the same appliance stack:

| Unit | Purpose | N001 | N002 |
|---|---|---|---|
| `energy-node-collector` | measurement + sync + heartbeat | ✅ running | ✅ running |
| `energy-node-netd` | networking supervisor | ✅ running | ✅ running |
| `energy-node-portal` | maintenance portal | ✅ running | ✅ running |
| `energy-node-console` | tty1 appliance console | ✅ running | ✅ running |
| `energy-node-powerlog` | UPS/power telemetry recorder | ✅ running | ✅ running |
| `energy-node-blackbox` | crash/black-box recorder | enabled, oneshot | enabled, oneshot |
| `energy-node-recovery-arm` | recovery arming | enabled, oneshot | enabled, oneshot |
| `energy-node-selfheal.timer` | 2-min self-heal check (inert unless enabled) | ✅ | ✅ |
| `energy-node-verify.timer` | nightly package verification | ✅ | ✅ |
| `energy-node-heartbeat` | **legacy standalone heartbeat** | absent ✅ | ⚠ **present** |
| `energy-node-wifi-fallback` | maintenance AP fallback | absent | absent (N003 only) |

N003 runs `udec-edge` plus the netd/portal/console/wifi-fallback subset; it has
no collector, powerlog, blackbox, recovery or verify units.

## Local storage

| | N001 | N002 |
|---|---|---|
| Disk | 58 GB, 14 % used | 58 GB, 14 % used |
| `/opt/energy-node/backups` | **218 MB, 26 entries** ⚠ | 1.6 MB, 13 entries |
| Buffer pending (`sync_status=0`) | 0 | **~5 500 and growing** ⚠ |

N002's buffer grows because its uploads are refused (403, `registered`) and the
collector retains rather than discards them. That is correct behaviour and no
data is lost, but it is unbounded: roughly **5 700 rows/day**. No alert fires,
because a `registered` node is `is_monitored = 0`. Tracked as audit item **S3**.

## Capabilities and honest degradation

| Capability | N001 | N002 | N003 |
|---|---|---|---|
| Per-rail power (PMIC ADC) | yes | yes | **no — reported as unavailable, never faked** |
| UPS telemetry | HAT present | HAT present | **HAT unreadable — no GPIO I²C bus** |
| SPI sensors | available | **no spidev** | available (ADS1256 hardware present) |
| Canonical heartbeat | yes | via legacy agent | **none** |
| Authentication | yes | yes | **no** |

## Regenerating

The measured columns come from a fixed probe set run over SSH. Re-run it after
any node change and diff against this file; any new ⚠ is drift.

```bash
# Per node (public NAT address, not tailscale)
ssh theblackdie@<ip> 'hostname; cat /proc/device-tree/model; \
  grep -c "_hb_heartbeat.publish" /opt/energy-node/app/collector.py; \
  vcgencmd get_throttled; ls /dev/i2c* /dev/spidev* 2>/dev/null'
```

Server-side state:

```bash
cd backend
venv/bin/python3 -m app.db.provision_node list
sqlite3 energy_platform.db "SELECT node_code, software_version, auth_status,
  COUNT(*) FROM monitor_node_heartbeats
  WHERE received_at > datetime('now','-20 minutes')
  GROUP BY 1,2,3;"
```
