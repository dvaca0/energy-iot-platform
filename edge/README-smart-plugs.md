# Smart Plug collection source — Raspberry Pi side

Collects Shelly Plug US Gen4 measurements on each Raspberry Pi and reports them
to the platform backend. Smart plugs are **accessories of a deployment**, not
Energy Nodes: they answer which outlet or appliance consumes the most during a
measurement campaign.

Discovery runs **only here, on the Raspberry Pis**. The cloud backend never
scans the network; it only receives what each Pi already found.

## Files

| File | Purpose |
|---|---|
| `smart_plug_source.py` | The collection source. Importable module *and* standalone runner. |
| `energy-collector-smartplugs.service` | systemd unit for the standalone mode. |

## Two ways to run it

### A. Inside the existing collector (preferred)

The source is a plain class with its own daemon threads, so the existing
collector keeps ownership of the process, its watchdog and its logging:

```python
from smart_plug_source import SmartPlugSource

plug_source = SmartPlugSource(
    node_id="N001",                       # same Node code the collector uses
    backend_url="http://<backend>:8010",  # same backend base URL
    buffer_path="/var/lib/energy-collector/smart_plugs.db",
)
plug_source.start()   # returns immediately; nothing else in the collector changes
```

`start()` spawns two daemon threads (`plug-discovery`, `plug-poll`) and returns.
It does not touch the Energy Node pipeline, the existing SQLite database, the
existing buffering, retries, watchdog or synchronisation. Its buffer is a
separate SQLite file by design.

### B. Standalone service

For a Pi whose collector should not be modified:

```bash
sudo install -D -m 755 smart_plug_source.py /opt/energy-collector/smart_plug_source.py
sudo install -D -m 644 energy-collector-smartplugs.service \
    /etc/systemd/system/energy-collector-smartplugs.service
sudo sed -i 's|http://CHANGE-ME:8010|http://<backend>:8010|; s|NODE_ID=N001|NODE_ID=<node code>|' \
    /etc/systemd/system/energy-collector-smartplugs.service
sudo systemctl daemon-reload
sudo systemctl enable --now energy-collector-smartplugs.service
journalctl -u energy-collector-smartplugs -f
```

## Dry run before enabling anything

One discover/poll/report cycle, then exit — safe to run by hand:

```bash
python3 smart_plug_source.py --node-id N001 --backend http://<backend>:8010 --once --log-level DEBUG
```

It prints the networks it detected, the plugs it found and what the backend
accepted.

## Behaviour

| Requirement | Implementation |
|---|---|
| Identify a plug by capability, never by product name | See “What counts as a Smart Plug” below. |
| Identify by MAC, never IP | Inventory is keyed on the normalised MAC. A known MAC on a new IP updates the stored IP in place; no duplicate is created. |
| No hardcoded interface | The active interface and its subnets are read from the kernel at runtime (`ip -o -f inet addr show scope global`), plus a routing probe for the active source address. No `wlan0`, `eth0`, IP range or gateway appears in the code. |
| Works on any SSID/subnet | Discovery targets whatever networks the Pi is currently attached to, so the plugs' `wirelesslan` and the 120 A node's separate WiFi both work with the same code. |
| Full discovery every 5 min | `DISCOVERY_INTERVAL_S = 300`. mDNS (`_shelly._tcp`) when `zeroconf` is installed, plus a bounded subnet sweep, plus the last known IPs. |
| Poll every 15 s | `POLL_INTERVAL_S = 15`, against each plug's latest known IP. |
| Immediate rediscovery on failure | A failed poll wakes the discovery loop at once; it does not wait for the next 5 minute cycle. |
| Backend outage | Measurements are written to SQLite *before* upload and only deleted after the backend accepts them. Nothing is lost. |
| Reboot / WiFi reconnect | The inventory and last known IPs are persisted, so a restarted Pi resumes with its known devices instead of starting blind. |
| Plug disappears | Never deleted, assignment and history untouched: reported `online=false` with `last_seen` preserved, and it recovers automatically on rediscovery. |

`zeroconf` is optional. Without it, discovery falls back to the subnet sweep and
still works; installing it (`pip3 install zeroconf`) makes discovery faster.

A subnet larger than 1024 addresses is not swept — the university network is
never flooded. On such a network discovery relies on mDNS and the last known
IPs.

## What counts as a Smart Plug

**Smart Plugs are identified by capability, not by product name.** A device is
registered as a plug only when *all three* conditions hold:

1. it answers `Shelly.GetDeviceInfo` with a MAC — it is a Shelly device;
2. it exposes a **controllable Switch** at id 0 — `Switch.GetStatus?id=0`
   returns an `output` boolean;
3. that switch carries **metering** — it reports instantaneous power (`apower`)
   *and* cumulative energy (`aenergy.total`).

Implemented in `has_switch_metering()`, applied by `identify()` before any
device is registered.

The rule deliberately never consults the **model string, app string, firmware
version, or a known-MAC list**. Two consequences matter to future contributors:

- **Buying a new plug model or a future Shelly generation requires no code
  change.** Anything that presents a metered, controllable outlet is collected
  automatically.
- **Energy Meters are excluded automatically, not by blocklist.** The Shelly
  Pro3EM used by the Energy Node is also a Shelly device and answers the same
  discovery RPC, but it has no Switch component — it replies HTTP 404
  `No handler for Switch.GetStatus` — so it fails condition 2 and is never
  mistaken for an accessory plug. This matters because a Pi polls its Energy
  Node meter on the same networks it sweeps for plugs, and the backend upserts
  purely on MAC and never deletes a plug once created.

`KNOWN_FLEET` remains documentation only; no behaviour depends on it.

## Ownership

Each plug has exactly one **authoritative owner node**. The first node to report
a plug claims it; the backend **rejects** reports from any other node rather
than accepting the latest writer, and returns them in `rejected_not_owner`.
Ownership survives reboots, IP changes and rediscovery, and is only reassigned
explicitly via `POST /api/smart-plugs/{id}/transfer`.

So two nodes on one subnet no longer corrupt each other, though enabling only
the node that should own the plugs is still the tidy arrangement.

## Health checks

```bash
smart-plug-health           # human readable
smart-plug-health --json    # machine readable
```

Reports collector status, version, known and online plugs, pending
measurements, backend reachability, and the timestamps of the last discovery,
poll, successful poll and report. Safe to run at any time: read-only, and it
never disturbs the collector.

## Device RPC endpoints used

Read-only Shelly Gen4 RPC over HTTP. Nothing is ever written to a device, so
the plugs are never switched on or off by this software.

- `GET /rpc/Shelly.GetDeviceInfo` — MAC, model, firmware, serial
- `GET /rpc/Switch.GetStatus?id=0` — power, voltage, current, PF, energy, temperature
- `GET /rpc/WiFi.GetStatus` — RSSI

## Deployed fleet

```
Plug 1  AC:EB:E6:F6:53:88
Plug 2  AC:EB:E6:F2:91:B8
Plug 3  AC:EB:E6:F2:57:EC
Plug 4  AC:EB:E6:F2:83:08
```

Listed in `KNOWN_FLEET` for documentation only; discovery accepts any Shelly
plug it finds, and no behaviour depends on that list.
