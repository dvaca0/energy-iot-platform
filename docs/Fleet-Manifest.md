# Fleet manifest

Canonical inventory of every node. **Purpose: detect configuration drift
immediately.** Any cell marked ⚠ is a divergence from the reference build, not a
design decision.

Captured **2026-08-07**. Regenerate with `scripts/fleet_manifest.py` (see
"Regenerating" below); do not hand-edit the measured columns.

Reference build = the **Energy Node Package v2.1**
([Energy-Node-Package.md](Energy-Node-Package.md)). N001 and N002 both run it,
byte-identical. N003 does not and is out of scope.

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
| Collector mtime | 2026-08-07 | 2026-08-07 (converged) | 2026-07-24 |
| Collector SHA-256 (24) | `d9cc6138c8be60b273615d13` | `d9cc6138c8be60b273615d13` ✅ identical | n/a ⚠ |
| **Canonical heartbeat in collector** | **yes** | **yes** ✅ (D2, 2026-08-07) | **no** ⚠ |
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

## Heartbeat producers — one per node

| Node | Producer | Version | Unit | Status |
|---|---|---|---|---|
| N001 | collector, canonical `telemetry.build()` | 2.0.0 | `energy-node-collector` | ✅ reference |
| N002 | collector, canonical `telemetry.build()` | 2.0.0 | `energy-node-collector` | ✅ converged 2026-08-07 |
| N003 | none | — | — | ⚠ no heartbeat at all |

**Resolved 2026-08-07.** Before convergence, N002's collector lacked the
canonical heartbeat call entirely (`grep -c '_hb_heartbeat.publish'` returned 0
on N002, 1 on N001) and its `Heartbeat OK` lines were the *legacy* 3-field post
to `/api/edge/heartbeat`, which updates `nodes.last_sync` but writes nothing to
`monitor_node_heartbeats`. N002's collector was upgraded to the canonical build
(D2), verified producing v2.0.0 authenticated beats at a 60 s cadence, and the
legacy `energy-node-heartbeat.service` was then disabled (D1). Both Pi 5 nodes
now run byte-identical collectors with exactly one heartbeat producer each.
The legacy unit and agent are **retained on N002 for rollback** until the soak
completes; see [Energy-Node-Package.md](Energy-Node-Package.md).

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
| `energy-node-heartbeat` | legacy standalone heartbeat (retired) | absent ✅ | disabled ✅ (files retained for rollback) |
| `energy-node-wifi-fallback` | maintenance AP fallback | absent | absent (N003 only) |

N003 runs `udec-edge` plus the netd/portal/console/wifi-fallback subset; it has
no collector, powerlog, blackbox, recovery or verify units.

## Local storage

| | N001 | N002 |
|---|---|---|
| Disk | 58 GB, 14 % used | 58 GB, 14 % used |
| `/opt/energy-node/backups` | **218 MB, 26 entries** ⚠ | 1.6 MB, 13 entries |
| Buffer pending (`sync_status=0`) | 0 | **~5 700 and growing** ⚠ |

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
| Canonical heartbeat | yes | yes | **none** |
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
