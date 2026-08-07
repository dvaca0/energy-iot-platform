# Identity-collision root-cause report

Captured 2026-08-06 (UTC). All findings measured directly; nothing inferred from NAT.

## Verdict

**Not a separate physical machine.** Both producers ran on N001
(`energy-node-001`, Raspberry Pi 5). Proven by host-unique discriminators
present in both payloads:

| Discriminator | v2.0.0 producer | v1.0.0 producer | N001 measured on-device |
|---|---|---|---|
| `collector_pid` | 1305 | 1305 | **1305** |
| `sqlite_size_mb` | 25.15 | 25.1 | 25.10 (25,104,384 B) |
| `uptime_seconds` | 154440.6 | 153640.3 | ~1d18h, same boot |
| `hostname` | energy-node-001 | energy-node-001 | energy-node-001 |
| `ip_address` | 192.168.50.2 | 192.168.50.2 | 192.168.50.2 |

Same PID, same boot, same buffer file. One machine.

## Producer 1 — legitimate

* Source: `energy-node-collector.service` (PID 1305), via
  `/opt/energy-node/hardening/lib/{telemetry,heartbeat}.py`
* Version 2.0.0, cadence 60 s, endpoint `POST /api/monitoring/heartbeat`
* Authentication: **none**
* Payload hash basis: 31 keys produced node-side; server stores 47
  (`HeartbeatPayload.model_dump()` fills undeclared fields with defaults)

## Producer 2 — accidental impersonation

* Source: `/opt/energy-node/backups/pre-m14-hardening-20260803_082109/app/node_agent.py`
* Version 1.0.0, cadence 60 s (`DEFAULT_INTERVAL`), same endpoint
* Reads `NODE_ID=N001` from `/opt/energy-node/config/node.env`
* **Argument handling (line 277): `once = "--once" in sys.argv`.** It parses no
  other flags. A `--dry-run` flag is *silently ignored* and the agent enters
  its infinite publish loop (line 303).
* Windows observed: 2026-08-03 14:00 (34 beats, during M14 hardening work) and
  2026-08-06 13:23:25 - 13:30:25 (8 beats).

**The second window was caused by this audit.** A read-only probe invoked that
backup file with `--dry-run`, which it ignored. It published as N001 until the
SSH channel closed. Disclosed rather than left as an unexplained anomaly.

## The real defect

`POST /api/monitoring/heartbeat` requires **no credential**. Any process, on any
host, can publish arbitrary telemetry for any `node_id`. The `nodes.auth_token_hash`
column exists (migration 002, ADR-0002) but is **unused by every ingest path**.

`grep -n 'auth|token|Authorization|hmac|secret'` over the node's `heartbeat.py`
returns nothing; `node.env` contains no token.

Class of defect: **not** a rogue machine — an *old collector left in a backup
directory* that anyone can execute, against an endpoint with no identity check.

## Contradiction that the collision exposed

The two producers disagreed on `filesystem_readonly` (True vs False) and
`disk_percent` (17.5 vs 13.9). Root cause is independent of the collision and is
documented in `filesystem-readonly-<ts>.md`.
