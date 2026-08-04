# Changelog — Smart Plug collection source

Canonical repository: `/home/manager/energy-platform/edge/`.
Every Raspberry Pi runs the version recorded here, installed with
`install-smart-plugs.sh`. Versions are ordered newest first.

---

## 1.2.0 — 2026-07-25

**Summary.** Health diagnostics on the edge, explicit plug ownership enforced by
the backend, and an installer that understands upgrades.

Added:

- `smart_plug_source.py` exposes `__version__`, a `health()` method and a
  `--health` / `--health --json` CLI. Diagnostics are persisted in a new
  `source_state` table so health can be read from a separate process while the
  collector is running: last discovery, last poll, last successful poll, last
  report, known and online plugs, pending measurements, backend reachability.
- `smart-plug-health` wrapper, installed to `/usr/local/bin`, for one-command
  troubleshooting on any node.
- The source now logs when the backend rejects a plug because another node owns
  it, so a plug that never appears in the platform is explainable from the
  node's own journal.
- Installer: version detection and comparison, upgrade of changed files only,
  configuration preservation, restart only when needed, post-install
  verification, and an auto-generated deployment report.

Changed:

- Backend enforces **explicit ownership**. The first node to report a plug
  claims it; reports from any other node are rejected instead of being accepted
  as the latest writer. See “Ownership model” in
  `docs/Smart-Plug-Architecture.md`.
- Backend validation rejects malformed MACs, duplicate MACs within one report,
  and implausible timestamps, logging each clearly.

**Breaking changes.** None for the edge. Behavioural change on the backend: a
node that is not a plug's owner no longer updates it. Previously the last
reporter won. Any node reporting a plug it does not own now gets that plug
listed in `rejected_not_owner` and its measurements dropped.

**Upgrade notes.** Re-run the installer; it preserves
`/etc/energy-node/smart-plugs.conf`, so `SMART_PLUGS_ENABLED` and the node code
survive. The backend needs the `smart_plugs.owner_claimed_at` column, added
with `ALTER TABLE` and backfilled from existing `node_id` values, so plugs
already in the database keep their current owner. Upgrade the backend before
or with the nodes: an older backend simply ignores the new response fields.

**Rollback notes.** Restore `collector.py` (or `poller.py`) and
`smart_plug_source.py` from the timestamped backup the installer created under
`<node-root>/backups/smart-plugs-<timestamp>/`, then restart the unit. Or set
`SMART_PLUGS_ENABLED=0` and restart — the integration is inert when disabled
and the Energy Node pipeline is unaffected either way. On the backend, restore
`app/routers/smart_plugs.py` and `app/db/models.py` from
`backend/backups/*-before-ownership-*`; the extra column is harmless if left in
place.

---

## 1.1.0 — 2026-07-25

**Summary.** Smart Plugs are identified by capability rather than product name.

Changed:

- `identify()` registers a device only if it answers `Shelly.GetDeviceInfo`,
  exposes a controllable `Switch` at id 0, and reports both instantaneous power
  and cumulative energy for that switch (`has_switch_metering()`).
- Model strings, app strings, firmware versions and MAC allowlists are never
  consulted, so new plug models and future generations work without a code
  change and Energy Meters are excluded automatically.

**Why.** The Shelly Pro3EM used by the Energy Node answers the same discovery
RPC as a plug. Without a capability test each Pi registered its own energy
meter as a smart plug, and because the backend upserts on MAC and never deletes
a plug, that phantom row could not be removed without editing the database.

**Breaking changes.** None. A device that was previously mis-registered is no
longer reported; existing rows are untouched.

**Upgrade notes.** Re-run the installer. If a phantom meter was already
registered before upgrading, it stays in the database until removed manually —
it will simply stop being updated.

**Rollback notes.** Restore `smart_plug_source.py` from the node's backup
directory and restart the unit.

---

## 1.0.0 — 2026-07-25

**Summary.** First field deployment of the Smart Plug collection source.

Added:

- `smart_plug_source.py`: discovery, polling, SQLite store-and-forward
  buffering and reporting for Shelly plugs, usable as an importable source
  inside an existing collector or as a standalone service.
- Identity keyed on MAC, never IP: a plug on a new IP updates in place.
- Runtime network detection — no interface name, subnet, gateway or SSID
  appears anywhere in the code.
- Full discovery every 5 minutes, polling every 15 seconds, immediate targeted
  rediscovery when a known plug stops responding.
- `energy-collector-smartplugs.service` for standalone operation.
- `install-smart-plugs.sh` and `integrate_collector.py` for extending an
  existing collector without replacing it.

**Breaking changes.** None — new subsystem. Energy Node collection, buffering,
retries, deployment-aware discarding and synchronisation are untouched, and the
plug buffer is a separate SQLite file.

**Upgrade notes.** First release; nothing to upgrade from.

**Rollback notes.** Set `SMART_PLUGS_ENABLED=0` and restart, or restore the
collector from the installer's backup directory.
