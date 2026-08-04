# Smart Plugs API

Shelly Plug US Gen4 support. Smart plugs are **accessories assigned to a
deployment**, not Energy Nodes: they identify which outlet or connected
appliance consumes the most during a measurement campaign.

Base path: `/api/smart-plugs` — served by `app/routers/smart_plugs.py`.

## Identity

A plug is identified by **MAC address**. IPs are volatile (DHCP) and are
refreshed on every report; a plug rediscovered on a different IP updates the
stored IP and never creates a duplicate.

MACs are accepted in any notation (`ACEBE6F65388`, `ac:eb:e6:f6:53:88`) and
normalised to uppercase colon form (`AC:EB:E6:F6:53:88`).

The `id` used in URLs is the MAC in lowercase without separators
(`acebe6f65388`). Endpoints taking `{id}` also accept the MAC in any notation
or the numeric primary key.

## Online semantics

`online` is true only when the edge reported the plug up **and** that report is
still fresh (`ONLINE_WINDOW_SECONDS = 90`). So a plug also goes offline if the
Raspberry Pi itself stops reporting, not just when the plug dies. While a plug
is offline its instantaneous telemetry is returned as `null` rather than as
stale values that would look current.

---

## GET /api/smart-plugs

Full inventory, assigned and unassigned, online and offline. Offline plugs are
returned on purpose: they keep their assignment, their history and their
`last_seen`.

```json
[
  {
    "id": "acebe6f65388",
    "mac": "AC:EB:E6:F6:53:88",
    "model": "Shelly Plug US Gen4",
    "ip": "10.44.7.99",
    "hostname": "shellyplugusg4-acebe6f65388",
    "serial": "1234",
    "firmware": "1.4.4",
    "rssi": -58,
    "temperature_c": 42.1,
    "node": "N001",
    "building": "Edificio de prueba",
    "deployment": "Campaña Laboratorio de Redes",
    "friendly_name": "Rack de switches",
    "outlet_location": "Rack A · Contacto 3",
    "online": true,
    "last_seen": "2026-07-25T18:04:11",
    "power_w": 120.0,
    "voltage_v": 121.4,
    "current_a": 0.988,
    "power_factor": 0.98,
    "energy_today_kwh": 1.4432
  }
]
```

`energy_today_kwh` is the SQL sum of per-sample energy deltas since 00:00 UTC.
Deltas are used instead of (max − min) of the device counter so a firmware
counter reset cannot produce a spike.

## GET /api/smart-plugs/live

Only plugs currently responding, ranked by instantaneous power. This is the
campaign view: `highest_consumer` is the answer to "which outlet consumes most".

```json
{
  "count": 3,
  "total_power_w": 1325.0,
  "highest_consumer": { "...": "same shape as above" },
  "smart_plugs": [ "... sorted by power_w descending ..." ]
}
```

## GET /api/smart-plugs/{id}

One plug, with the list fields plus `energy_total_kwh` (device cumulative
counter), `created_at`, `updated_at` and `samples` (stored history rows).

`404` if unknown.

## GET /api/smart-plugs/{id}/history

| Query | Default | Range |
|---|---|---|
| `hours` | 24 | 1 – 2160 (90 days) |
| `limit` | 1000 | 1 – 5000 |

Returns the most recent `limit` samples within the window, **oldest first** so
it can be charted directly.

```json
[
  {
    "timestamp": "2026-07-25T18:03:56",
    "power_w": 120.0,
    "voltage_v": 121.4,
    "current_a": 0.988,
    "power_factor": 0.98,
    "energy_kwh": 0.0005,
    "temperature_c": 42.1
  }
]
```

## POST /api/smart-plugs/{id}/assign

Attach a plug to a building and deployment. All fields optional; only those
present are modified.

```json
{
  "friendly_name": "Rack de switches",
  "building": "Edificio de prueba",
  "deployment": "Campaña Laboratorio de Redes",
  "outlet_location": "Rack A · Contacto 3"
}
```

The UI sends free text. Each label is stored verbatim so the dialog round-trips
exactly, and when the text matches an existing `Building.name` or `Building.code`
it is also resolved to a real foreign key, so plug history can be correlated
with the deployment it belongs to. An empty string clears a field.

Returns the updated plug in the list shape.

**An assignment is never overwritten by the edge.** A plug inherits the
Raspberry's deployment only while it is still unassigned.

## POST /api/smart-plugs/discovery

Called **by the Raspberry Pis only**. Reports the inventory that Pi discovered,
plus any buffered measurements. The cloud backend never scans the network.

```json
{
  "node_id": "N001",
  "plugs": [
    {
      "mac": "ACEBE6F65388",
      "model": "S4PL-00112EU",
      "ip": "10.44.7.99",
      "hostname": "shellyplugusg4-acebe6f65388",
      "serial": "1234",
      "firmware": "1.4.4",
      "rssi": -58,
      "temperature_c": 42.1,
      "online": true,
      "last_seen": "2026-07-25T18:04:11+00:00",
      "measurements": [
        {
          "captured_at": "2026-07-25T18:04:11.123+00:00",
          "power_w": 120.0,
          "voltage_v": 121.4,
          "current_a": 0.988,
          "power_factor": 0.98,
          "energy_total_kwh": 10.0,
          "temperature_c": 42.1,
          "rssi": -58
        }
      ]
    }
  ]
}
```

`node_id` is the Node **code** (`N001`), matching the existing measurement
ingestion contract, so the edge never needs database ids.

Response:

```json
{
  "status": "ok",
  "node": "N001",
  "plugs_created": 0,
  "plugs_updated": 4,
  "readings_inserted": 4,
  "readings_duplicated": 0,
  "online_window_seconds": 90
}
```

`404` if `node_id` is not a registered Node.

### Guarantees

- **Upsert by MAC** — an IP change updates in place.
- **Nothing is ever deleted** — plugs absent from a report keep their row,
  assignment and history. `online: false` preserves the previous `last_seen`.
- **Idempotent** — `(smart_plug_id, timestamp)` is unique, so replaying a
  buffered batch after an outage inserts nothing new and is reported as
  `readings_duplicated`. This is what lets the edge retry safely forever.
- **Timestamps** are stored as naive UTC, consistent with `energy_readings`.

---

## Database

Two **new** tables. No existing table was modified, and Energy Node history
(`energy_readings`) is never written by this pipeline.

### `smart_plugs`

| Column | Notes |
|---|---|
| `id` | PK |
| `mac` | unique, indexed — permanent identity |
| `model` | |
| `ip_address`, `hostname`, `serial`, `firmware`, `rssi`, `temperature_c` | volatile, refreshed each report |
| `node_id` → `nodes.id` | which Pi discovered it |
| `building_id` → `buildings.id` | resolved from the label when it matches |
| `deployment_id` → `deployments.id` | resolved assignment |
| `building_label`, `deployment_label` | free text exactly as typed |
| `friendly_name`, `outlet_location` | |
| `online`, `last_seen` | |
| `power_w`, `voltage_v`, `current_a`, `power_factor`, `energy_total_kwh` | latest snapshot, so the live view needs no join |
| `created_at`, `updated_at` | |

### `smart_plug_readings`

| Column | Notes |
|---|---|
| `id` | PK |
| `smart_plug_id` → `smart_plugs.id` | indexed |
| `node_id`, `building_id`, `deployment_id` | denormalised, so history stays meaningful after reassignment |
| `timestamp` | indexed, naive UTC |
| `power_w`, `voltage_v`, `current_a`, `power_factor` | |
| `energy_total_kwh` | device cumulative counter |
| `energy_kwh` | per-sample delta |
| `temperature_c`, `rssi` | |
| **unique** `(smart_plug_id, timestamp)` | makes edge retries idempotent |

Tables are created by the existing `Base.metadata.create_all()` mechanism, which
only adds missing tables and never alters or drops existing ones.

## Tests

```bash
cd /home/manager/energy-platform/backend && source venv/bin/activate
python tests/test_smart_plugs.py    # 53 checks — API contract
python tests/test_collector.py      # 49 checks — edge behaviour end to end
```

Both run against throwaway SQLite databases (the `get_db` dependency is
overridden), so production history is never touched.
