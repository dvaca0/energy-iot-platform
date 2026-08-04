# Handoff prompt — Raspberry Pi Smart Plug collector integration

Paste everything below the line into the new chat (the one with SSH access).

---

## Context (already done — do not redo)

This is my University thesis project: an energy platform at
`/home/manager/energy-platform` on the cloud server. Read
`/home/manager/energy-platform/backend/CLAUDE.md`-style rules below before
touching anything.

Smart Plug (Shelly Plug US Gen4) support was implemented and **is already live
on the cloud server**. Smart plugs are **accessories assigned to a deployment**,
NOT Energy Nodes. Their purpose: identify which outlet or connected equipment
consumes the most during a measurement campaign.

Completed in a previous session:

- **Backend live** on port **8010** (gunicorn, single worker, SQLite at
  `backend/energy_platform.db` in WAL mode — it is NOT PostgreSQL).
  New router `backend/app/routers/smart_plugs.py`, registered in `app/main.py`.
  Endpoints working now: `GET /api/smart-plugs`, `/live`, `/{id}`,
  `/{id}/history`, `POST /{id}/assign`, `POST /api/smart-plugs/discovery`.
- **Database extended** with two NEW tables only: `smart_plugs`,
  `smart_plug_readings`. Existing tables untouched. `energy_readings` (Energy
  Node history) is never written by the plug pipeline.
- **Frontend deployed** to production (`frontend/dist`, served by
  `static_server.py` on port **5174**). Smart Plugs page, sidebar entry and
  dashboard widget are live and call the real API. All mock data was removed.
- **Tests**: `backend/tests/test_smart_plugs.py` (53 checks) and
  `backend/tests/test_collector.py` (49 checks). Both pass, both run against
  throwaway SQLite DBs. Run them with
  `cd /home/manager/energy-platform/backend && source venv/bin/activate`.
- **API docs**: `backend/docs/smart-plugs-api.md`.

`GET /api/smart-plugs` currently returns `[]` — correct, because no Raspberry Pi
is running the collector yet. **That is the only remaining work.**

## Your task

Install the Smart Plug collection source on the Raspberry Pis, integrating it
into the **existing** collector rather than running a second one.

The code is already written and tested, staged at
`/home/manager/energy-platform/edge/`:

| File | Purpose |
|---|---|
| `smart_plug_source.py` | The collection source. Importable class + standalone runner. |
| `energy-collector-smartplugs.service` | systemd unit, standalone mode only. |
| `README-smart-plugs.md` | Install + behaviour reference. Read this first. |

### Order of work — do not skip step 1

1. **Inspect the existing collector on the Pi FIRST.** Find it (try
   `systemctl list-units | grep -i collect`, `ls /opt`, `ls /home/*/`,
   `systemctl cat <unit>` to get `ExecStart`). Read it completely. Then
   **explain to me what it currently does** — its main loop, its buffering, its
   retry logic, its watchdog, its SQLite usage, its sync behaviour, how it knows
   its node code and backend URL. Do not modify anything until you have done
   this and I have confirmed your understanding.
2. **Timestamped backup** of every file you will touch, before touching it.
3. **Extend, do not replace.** Add the plug source as an additional source
   inside the existing collector:

   ```python
   from smart_plug_source import SmartPlugSource

   plug_source = SmartPlugSource(
       node_id="<the node code this Pi already uses, e.g. N001>",
       backend_url="<the backend base URL this Pi already uses>",
       buffer_path="<a path in the same state dir the collector already uses>",
   )
   plug_source.start()   # spawns 2 daemon threads, returns immediately
   ```

   `start()` must not disturb the Energy Node pipeline, its buffering, retries,
   watchdog, logging, SQLite or deployment-aware behaviour. The plug buffer is a
   **separate** SQLite file by design — do not point it at the collector's
   existing database.
4. **Dry run before enabling anything.** This touches nothing and exits:

   ```bash
   python3 smart_plug_source.py --node-id N001 --backend http://<backend>:8010 --once --log-level DEBUG
   ```

   It prints the networks it detected, the plugs it found, and what the backend
   accepted. Only proceed if it finds plugs.
5. Use the standalone systemd unit **only** if the existing collector genuinely
   cannot be extended. Tell me before choosing that path.

### Verify after deploying

- `curl http://<backend>:8010/api/smart-plugs` returns the discovered plugs with
  real MAC, IP, firmware, RSSI, power, voltage.
- `curl http://<backend>:8010/api/smart-plugs/live` reports `highest_consumer`.
- **Energy Node collection still works**: `energy_readings` count still growing,
  `nodes.last_sync` still current, edge POSTs still returning 200 in
  `journalctl -u energy-platform-backend.service`.
- Unplug one plug → it becomes `online: false` with `last_seen` preserved, and is
  **not** deleted. Plug it back in → recovers automatically.
- Reboot the Pi → known plugs come back from the local buffer.

## Facts you will need

- **Known plug MACs** (the deployed fleet):
  `AC:EB:E6:F6:53:88`, `AC:EB:E6:F2:91:B8`, `AC:EB:E6:F2:57:EC`,
  `AC:EB:E6:F2:83:08`
- Three plugs are on SSID **`wirelesslan`**. The Pi with the 120 A node is on a
  **different** WiFi network. The code detects the active interface and subnets
  from the kernel at runtime — there is no `wlan0`, `eth0`, IP range or gateway
  anywhere in it. Do not add any.
- **Node codes in the platform**: `N001`, `N002`, `N003`. Each Pi must report
  with the code it already uses for Energy Node ingestion. **Determine the
  mapping from Pi to node code on the device** — do not guess it.
- The Pis are behind NAT and push outbound only; the cloud server cannot reach
  them. Their source IPs seen in the backend journal are `148.213.2.245`,
  `148.213.2.153`, `148.213.168.238` (SSH port 22 open on the first two,
  filtered on the third).
- `zeroconf` is optional (`pip3 install zeroconf` makes mDNS discovery faster).
  Without it, discovery falls back to a bounded subnet sweep and still works.
- Schedule built into the source: full discovery every **5 min**, poll known
  plugs every **15 s**, immediate targeted rediscovery when a known plug stops
  responding, SQLite buffering whenever the backend is unavailable.
- The source only ever issues **read-only** Shelly RPC calls
  (`Shelly.GetDeviceInfo`, `Switch.GetStatus`, `WiFi.GetStatus`). It never
  switches a plug on or off. Keep it that way.

## Backend contract the Pi must satisfy

`POST /api/smart-plugs/discovery` — `node_id` is the Node **code**, not a
database id. Upsert is keyed on **MAC**, so a plug on a new IP updates in place
and never duplicates. `(smart_plug_id, timestamp)` is unique, so replaying a
buffered batch after an outage is idempotent.

```json
{
  "node_id": "N001",
  "plugs": [{
    "mac": "ACEBE6F65388",
    "model": "S4PL-00112EU", "ip": "10.44.7.99",
    "hostname": "shellyplugusg4-acebe6f65388", "serial": "1234",
    "firmware": "1.4.4", "rssi": -58, "temperature_c": 42.1,
    "online": true, "last_seen": "2026-07-25T18:04:11+00:00",
    "measurements": [{
      "captured_at": "2026-07-25T18:04:11.123+00:00",
      "power_w": 120.0, "voltage_v": 121.4, "current_a": 0.988,
      "power_factor": 0.98, "energy_total_kwh": 10.0,
      "temperature_c": 42.1, "rssi": -58
    }]
  }]
}
```

Full reference: `/home/manager/energy-platform/backend/docs/smart-plugs-api.md`.

## Rules — these override defaults

- The platform is **operational**. Do NOT redesign it, do NOT rewrite working
  code, do NOT recreate anything from scratch. Always extend.
- Before changing any file: inspect it completely, explain what it does, make a
  **timestamped backup**, then change only what is necessary.
- Never delete historical readings. Never reset the database.
- **Do NOT `git commit` or `git push`.** Use timestamped backups.
- Never leave the project broken. If something fails, STOP and fix it.
- If you are unsure how a subsystem works: STOP, inspect it, explain your
  understanding, ask before making architectural decisions. Never guess.
- On the cloud server `sudo` requires a password that is not available. To apply
  backend code changes, SIGHUP the gunicorn master instead (it runs as
  `manager`, graceful, no dropped connections):
  ```bash
  kill -HUP $(systemctl show -p MainPID --value energy-platform-backend.service)
  ```
  On the Pi you will likely have real `sudo` — confirm before relying on it.
- Ask for my approval before deploying anything to production or enabling a new
  service.

## Known limitations carried over

- `_mdns_candidates()` and the real subnet sweep were **stubbed in tests** — the
  Pi is their first real exercise. Expect to debug discovery there.
- Nothing about the existing Pi collector is known: it was never inspectable
  from the cloud server. Step 1 is genuinely necessary.
- Rollback for the cloud side, if ever needed:
  `backend/backups/models.py-before-smart-plugs-20260725_175022`,
  `backend/backups/main.py-before-smart-plugs-20260725_175022`,
  `backend/backups/energy_platform.db-before-smart-plugs-20260725_175022`,
  `frontend/backups/dist-before-smart-plugs-20260725_181242.tar.gz`.
