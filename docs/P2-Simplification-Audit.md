# P2 — Platform simplification audit

**2026-08-07.** Nothing was deleted. Every candidate below is classified with
the evidence that justifies the verdict, because the one item that looked most
obviously redundant turned out to be load-bearing.

Verdicts: **REMOVE** (proven unused, safe now) · **BLOCKED** (removal is correct
but has a prerequisite) · **KEEP** (proven in use) · **DEFER** (needs a decision).

---

## The headline finding

`energy-node-heartbeat.service` on N002 was expected to be dead duplication —
N001 does not have it, and the canonical design is one producer per node.

**It is the opposite.** Server-side truth, last 20 minutes:

| Node | Producer version | Beats | Auth |
|---|---|---|---|
| N001 | 2.0.0 (collector) | 20 | authenticated |
| N002 | **1.0.0 (legacy agent)** | 27 | authenticated |

N002 produced **zero** v2.0.0 beats. The cause:

```
grep -c '_hb_heartbeat.publish' /opt/energy-node/app/collector.py
  N001 → 1        N002 → 0
collector.py mtime:
  N001 → 2026-08-06        N002 → 2026-07-25
```

N002's collector predates the canonical-heartbeat integration. Its `Heartbeat
OK` log lines are the *legacy* 3-field post to `/api/edge/heartbeat`, which
updates `nodes.last_sync` but writes nothing to `monitor_node_heartbeats`.

**Deleting the "duplicate" would have blinded N002's monitoring.** This is the
audit's main result: the debt is not a redundant service, it is **collector
version drift between two nodes that should be identical**.

---

## D — Duplication and drift

### D1 · `energy-node-heartbeat.service` on N002 — **DONE 2026-08-07**

* **Why it exists:** installed 2026-07-26 as the standalone v1.0.0 agent, before
  the hardening package integrated heartbeats into the collector.
* **Still needed:** **yes, today.** It is N002's only canonical-heartbeat source.
* **Depends on it:** `monitor_node_heartbeats` for N002; every node rule and the
  hourly report entry for N002.
* **Resolved:** D2 deployed the canonical collector to N002; v2.0.0 authenticated
  beats verified at a steady 60 s cadence; the unit was then disabled. Files are
  retained for rollback until the soak completes.
* **Rollback:** `systemctl enable --now energy-node-heartbeat`; the unit and
  `/opt/energy-monitoring/node_heartbeat.py` are retained until the upgrade is
  verified in production for at least one full day.

### D2 · Collector version drift — **DONE 2026-08-07**

N002's collector is 12 days behind N001's. This is the root cause of D1 and of
the heartbeat asymmetry. Upgrading is a node software deployment, not a cleanup,
and it touches the measurement path of a live (if idle) node.

* **Executed:** one node-agnostic canonical collector (`sha256 d9cc6138…`) now
  runs byte-identical on both Pi 5 nodes. The startup banner was changed from a
  literal `N001` to `CONFIG["NODE_ID"]` so the same bytes run everywhere, which
  is what makes a fleet-wide checksum meaningful.
* **Buffer preserved:** 5 660 → 5 671 pending, 34 357 discarded unchanged,
  total 40 017 → 40 028. Growth only; nothing discarded by the restart.

### D3 · Two heartbeat *endpoints* — **KEEP both, for now**

`/api/edge/heartbeat` (legacy, 3 fields, updates `last_sync`) and
`/api/monitoring/heartbeat` (canonical, ~50 fields). Both are live and both are
called — the collector posts to the legacy one and negotiates the canonical one.
Removing the legacy endpoint requires every node to be on a collector that no
longer calls it, which is downstream of D2.

---

## S — Server

### S1 · Repository drift — **REMOVE (commit)**

23 files uncommitted: 11 untracked, 12 modified. All of it is the P0/P1 and
identity work — `node_auth.py`, `provision_node.py`, `ingest_gate.py`,
migrations 013/014, `retention.py`, `Runbook-Retention.md`, `evidence/`.

* **Risk of leaving it:** the deployed platform does not match the repository.
  A fresh checkout cannot reproduce production, and CI has never seen this code.
* **Action:** commit. This is the single highest-value cleanup on the server.

### S2 · `/etc/systemd/system/energy-platform-backend.service.bak` — **REMOVE**

* **Why it exists:** a hand-edit backup from 2026-06-19.
* **Depends on it:** nothing. systemd ignores `.bak`; `systemctl list-unit-files`
  does not show it.
* **Safe:** yes, but needs root. `sudo rm` it.
* **Rollback:** it is byte-identical in purpose to the live unit; recreate by
  copying `energy-platform-backend.service`.

### S3 · N002 buffer growth — **DEFER (monitor)**

~5 500 pending rows, growing ~5 700/day, because uploads are correctly refused
(403, `registered`) and the collector retains rather than discards. No data
loss, no alert — a `registered` node is `is_monitored = 0`, which is correct.

* **Not urgent:** at 58 GB free and ~1 KB/row this is years of headroom.
* **Worth a decision:** if N002 stays `registered` indefinitely, either commission
  it or accept unbounded growth. Do **not** add an alert — the node is
  deliberately unmonitored.

### S4 · Local junk — **REMOVE (cosmetic, zero risk)**

| Item | Count / size | Status |
|---|---|---|
| `._*` AppleDouble files | 100 files, 16 KB | gitignored (`.gitignore:100`) |
| `.DS_Store` | 13 | gitignored |
| `*.tar.gz` at repo root | 3 files, 84 MB | gitignored, unreferenced |
| `backend/app_backup_20260617_142407/` | 456 KB | superseded by git history |

All are **untracked and ignored** — they exist only in the working copy, so
removal cannot affect the repository or any deployment. `._*.py` files cannot be
imported by Python (a leading dot is not a valid module name), so nothing can
depend on them.

* **Rollback:** none needed; nothing references them. The tarballs predate git
  adoption and are superseded by tags.

### S5 · `static_server_test.py` on :5175 — **DEFER**

Running 3 days (PID 1712654). It is the `frontend-src` dev server. Whether it is
still wanted is a frontend decision; it consumes nothing meaningful and is not
part of the production path (`frontend/static_server.py` on :5174 is).

---

## K — Proven in use, explicitly KEEP

Recorded so a future audit does not re-litigate them.

| Item | Evidence it is used |
|---|---|
| `energy-node-selfheal.timer` | fires every 2 min; logs `DISABLED (RECOVERY_SELF_HEAL=0) - no action` — inert by design, not dead |
| `energy-node-verify.timer` | nightly package-checksum verification |
| `energy-node-blackbox`, `energy-node-recovery-arm` | enabled oneshots; run at boot |
| `energy-node-powerlog` | running on both Pi 5 nodes; UPS/power recorder |
| `app/db/lifecycle.py` + `app/db/commissioning.py` | both read on every ingest and every monitoring tick; **not** duplicates — one owns deployment status, the other node commission state |
| `app/monitoring/lifecycle.py` | policy layer over the two above; defines no states of its own |
| `runtime_platform_settings.json` | still read by the Settings page; deliberately **not** read by alerting (see alerting policy) |
| `monitoring/run-monitoring.sh` + `@reboot` cron | the scheduler's only supervisor until the systemd unit is installed (needs root) |

---

## Not audited

* **Frontend** (`frontend-src`, `frontend`) — not surveyed.
* **AI pipeline, reports, cost engine** — not surveyed for dead code.
* **N003** — out of scope by instruction; inventory only, see
  [`monitoring/evidence/node03-audit-20260806_144255.md`](../monitoring/evidence/node03-audit-20260806_144255.md).
* **Stale migrations** — all 14 are applied and each retains its restore point;
  none is a candidate for removal. Migration 014 has a superseded duplicate
  backup which retention already removed.

---

## Recommended order

| # | Item | Effort | Risk | Blocks |
|---|---|---|---|---|
| 1 | **S1** commit the 23 files | minutes | none | everything downstream |
| 2 | **S2** remove the `.bak` unit | minutes (root) | none | — |
| 3 | **S4** remove local junk | minutes | none | — |
| 4 | **D2** upgrade N002's collector | ~1 h + soak | medium — touches a live measurement path | D1, D3 |
| 5 | **D1** remove N002's legacy heartbeat agent | minutes | low **after D2 is verified** | D3 |
| 6 | **D3** retire `/api/edge/heartbeat` | ~1 h | medium — needs whole fleet on new collector | — |
| 7 | **S3** decide N002's long-term commission state | decision | none | — |

Items 1–3 are safe now. Item 4 is the real work and needs a change window.
