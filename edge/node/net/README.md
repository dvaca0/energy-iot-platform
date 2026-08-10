# Energy Node — Networking & Maintenance Subsystem

A NetworkManager-integrated networking subsystem for Raspberry Pi Energy
Nodes. Its single purpose is that **a node is never unreachable**: not after a
wrong Wi-Fi password, not after the campus SSID changes, not after the router
is replaced, not after a technician moves the node to another building.

Recovery never requires removing the SD card, attaching a serial console,
reflashing, or having had a monitor attached at deployment time.

---

## Architecture

```
                        ┌──────────────────────────────────┐
                        │        energy-node-netd          │   root
                        │      (the only mutator)          │
                        │                                  │
   probes ─────────────▶│  evaluator ──▶ state machine     │
   (gateway/DNS/        │      │              │            │
    internet/backend)   │      │              ▼            │
                        │      │         wifi_manager      │
                        │      │         ap_manager        │
                        │      │              │            │
                        │      ▼              ▼            │
                        │   statefile     NetworkManager   │
                        └──────┬───────────────┬───────────┘
                               │               │ nmcli
                 ┌─────────────┴──────┐        ▼
                 │ network-state.json │   ┌──────────────┐
                 │  {"network":       │   │NetworkManager│
                 │     "available"}   │   │  (untouched, │
                 └─────────┬──────────┘   │  integrated) │
                           │              └──────────────┘
                           │ reads one key
                           ▼
                  ┌─────────────────┐
                  │    collector    │   knows only: available / unavailable
                  └─────────────────┘

        control socket  /run/energy-node/netd.sock  (0660 root:energy-net)
                           ▲                 ▲
                           │                 │
              ┌────────────┴───┐    ┌────────┴─────────┐
              │ maintenance    │    │ appliance        │   both unprivileged,
              │ portal (HTTP)  │    │ console (tty1)   │   both pure clients
              └────────────────┘    └──────────────────┘
```

### Layering

Dependencies point downward only:

| Layer | Modules | Responsibility |
|---|---|---|
| Entry points | `daemon`, `portal/__main__`, `tui/__main__`, `cli` | process lifecycle |
| Interfaces | `portal/`, `tui/` | presentation, no logic |
| Intent | `wifi_manager`, `ap_manager`, `factory_reset` | what to do |
| Decision | `evaluator`, `statemachine` | **pure**, no I/O, fully unit-tested |
| Adapters | `nm`, `probes`, `diagnostics`, `statefile`, `ipc` | all I/O |
| Data | `config`, `models` | typed values |

The decision layer performs no I/O at all. Time arrives as a parameter, so
every transition is unit-testable without a radio.

---

## The collector boundary

The networking subsystem publishes exactly one fact:

```json
{ "network": "available", "updated_at": 1785000000, "ttl_seconds": 30,
  "detail": { "…advisory only…" } }
```

at `/run/energy-node/network-state.json`. The collector reads one key via a
standalone, dependency-free module installed next to it:

```python
from energy_node_netstate import network_available

if network_available():
    upload_pending_measurements()
else:
    keep_buffering()
```

The collector never learns *how* connectivity is achieved. Ethernet, Wi-Fi
client and maintenance AP are all invisible behind this boundary, so the
networking subsystem can be redesigned without touching collector code.

**Fail-open:** if the state file is missing or stale — meaning `netd` itself
is not running — `network_available()` returns `True`. A collector that
stopped trying because the *monitor* died would turn a networking fault into a
data-loss fault.

---

## State machine

```
   BOOT ──────────────────────────────▶ ONLINE
     │  (uplink up within boot_grace)      ▲ ▲
     │ boot_grace elapsed                  │ │
     ▼                                     │ │
  CONNECTING ────────────────────────────▶─┘ │
     │  connect_grace elapsed                │
     ▼                                       │
  OFFLINE_BUFFERING ───────────────────────▶─┤ (uplink restored)
     │  offline_before_ap elapsed            │
     ▼                                       │
  MAINTENANCE_AP ──▶ RECOVERING ────────────▶┘
                     (stable_before_ap_down)
```

* No transition requires a reboot.
* Every state has a path back to `ONLINE`.
* `MAINTENANCE_AP` self-heals: after `ap_min_uptime`, if no operator is
  associated, the AP drops briefly to look for known networks, then re-raises
  if none are found.
* Reconnects use exponential backoff (`retry_backoff_initial` →
  `retry_backoff_max`) so a node never enters a tight reconnect loop.

---

## Connectivity priority

Requested order is Ethernet → Wi-Fi client → maintenance AP. On these nodes
`eth0` is normally the **private Shelly sensor segment** (`192.168.50.0/24`,
meter at `.10`) and carries no default route.

`interfaces.ethernet_is_uplink` controls this:

| Mode | Behaviour |
|---|---|
| `auto` *(default)* | Ethernet becomes the uplink **only when it carries a default route**. Otherwise it is recognised as the sensor segment and Wi-Fi keeps the uplink role. |
| `always` | Ethernet always wins when the link is up. |
| `never` | Ethernet is never an uplink. |

So a real Ethernet uplink does take priority the moment one appears — but a
sensor segment with no gateway never masquerades as one.

**A node is "online" if it can reach its default gateway or its backend.**
Internet access is reported but not required: a campus LAN behind a filtering
proxy is still a usable network.

---

## Maintenance access point

* Raised only when needed — never permanently.
* SSID `EnergyNode-N001` / `-N002` / `-N003`, unique passphrase per node.
* Portal at **http://192.168.66.1**.
* NetworkManager `ap` mode with `ipv4.method=shared` (its own DHCP/DNS via
  `dnsmasq-base`) — no hostapd or dnsmasq config to maintain.
* Profile is `autoconnect=no`, priority `-999`: it comes up because the
  supervisor decided so, never because NetworkManager picked it.
* Torn down automatically once an uplink has been stable for
  `stable_before_ap_down`, unless an operator pinned it.

> **192.168.50.0/24 is deliberately not used.** That is the Shelly sensor
> segment; an AP there would collide with the meter and break the collector's
> path to it.

Raised automatically on: first boot with no Wi-Fi, invalid credentials, no
saved network in range, or being offline longer than `offline_before_ap`.

---

## Services

| Unit | User | Purpose |
|---|---|---|
| `energy-node-netd.service` | root | Supervisor: evaluates, decides, acts, publishes. The only component that mutates network state. `Type=notify`, watchdog 120 s, `StartLimitIntervalSec=0` so it can never be permanently rate-limited into being stopped. |
| `energy-node-portal.service` | `energy-net` | Web portal. `CAP_NET_BIND_SERVICE` only; every action delegated over the control socket. |
| `energy-node-console.service` | `energy-net` | urwid appliance console on tty1, replacing the login prompt. |

`energy-node-netd` deliberately does **not** wait for `network-online.target`.
It must start when the network is broken — that is when it is needed.

---

## Interfaces

### Web portal — `http://192.168.66.1` (or the node's LAN address)

Status · Networks · Saved · Diagnostics · Logs · System.
Server-rendered HTML, one inline stylesheet, ~30 lines of vanilla JS for live
status. No framework, no build step, no external asset — it works on a node
with no internet, on whatever phone a technician has.

**Not a captive portal.** `/generate_204` is answered honestly rather than
hijacked, so the browser opens normally instead of forcing a sign-in sheet.

**Trust boundary:** status pages are readable from anywhere the portal is
reachable; *mutating* actions are restricted to `portal.trusted_networks`
(AP segment, sensor segment, loopback, Tailscale by default). The portal is
unauthenticated by design — a technician at a dead node must not need a
password — so the boundary is *where you connect from*.

### Appliance console — HDMI + keyboard on tty1

Menu: Network Status · Scan Networks · Saved Networks · Diagnostics ·
Collector Status · Service Status · Networking Logs · Collector Logs ·
Restart Services · Power.

Keys: `1`–`9` screens, `TAB` move, `ENTER` select, `r` refresh, `s` scan,
`q` exit.

> Login prompts remain available on **Alt+F2 … Alt+F6**.

### `netdctl` — command line

```bash
netdctl status
netdctl scan
netdctl saved
netdctl connect "Laboratory" --priority 50
netdctl forget "Old-SSID"
netdctl priority "University" 40
netdctl ap start | stop
netdctl diagnostics
netdctl logs network -n 200
netdctl restart networking
netdctl factory-network-reset --yes
```

---

## Factory network reset

Deliberately narrow. Deletes **Wi-Fi client profiles only**, then restarts
NetworkManager and raises the maintenance AP.

Preserved: the SQLite buffer and every measurement, all logs and journal
history, node identity, subsystem configuration, Ethernet profiles (the Shelly
sensor segment), and the AP profile itself.

Deleted profiles are exported to
`/var/lib/energy-node-net/network-reset-backups/<timestamp>/` first, so even
this is reversible.

---

## Configuration

`/opt/energy-node/net/config/network.yaml` (0640 `root:energy-net` — it holds
the AP passphrase). Every value has a documented default in `netd/config.py`;
a missing or malformed file degrades to defaults rather than preventing
startup. Apply changes with `sudo systemctl restart energy-node-netd`.

Key timings (seconds):

| Key | Default | Meaning |
|---|---|---|
| `boot_grace` | 45 | let NetworkManager settle before judging |
| `connect_grace` | 60 | how long `CONNECTING` may last |
| `offline_before_ap` | 180 | continuous offline time before raising the AP |
| `stable_before_ap_down` | 60 | uplink stability required before AP teardown |
| `monitor_interval` | 10 | evaluation cadence |
| `ap_min_uptime` | 120 | AP stays up at least this long once raised |
| `retry_backoff_initial` / `_max` | 15 / 300 | reconnect backoff bounds |

---

## Logging

Everything to journald under stable identifiers:

```bash
journalctl -u energy-node-netd -f          # every transition
journalctl -u energy-node-portal           # operator actions
journalctl -u energy-node-netd -u NetworkManager --since "1 hour ago"
```

The portal's **Logs** page and the console's **Logs** screens read the same
journal, so operators see exactly what the daemon recorded.

Logged: state transitions with reasons, AP raise/lower, Wi-Fi connect/
disconnect, profile add/remove/priority changes, reconnect attempts with
backoff, every operator action (passwords redacted), and every failure.

---

## Deployment

```bash
cd deploy
./deploy.sh --check          # connectivity preflight, no changes
./deploy.sh                  # all nodes
./deploy.sh N002             # one node
./deploy.sh --keep-going     # do not stop at the first failing node
```

The orchestrator refuses to ship a payload whose unit tests do not pass, and
deploys one node at a time, stopping on failure by default.

`install.sh` is idempotent. Each run: preflight → backup (code tree, units, NM
profiles, full network state, collector DB size) → dependencies → service
account → code → rendered config → `netdctl` → contract client → units →
retire superseded helpers → enable/start → **verify** → report.

Backups: `/opt/energy-node/backups/networking/<timestamp>/`.

Deployment happens over Tailscale, which stays reachable while the underlying
Wi-Fi changes — what makes remote deployment of a *networking* change
survivable.

---

## Tests

```bash
python3 -m unittest discover -s tests -t . -v
```

46 tests covering the state machine (boot grace, first-boot→AP, stable-before-
teardown, flapping links, backoff and its cap, operator overrides, AP
self-healing), uplink selection (all three Ethernet modes, the sensor-segment
case), the collector contract (fail-open on missing/stale/corrupt), config
degradation, and `nmcli` terse parsing including colon-escaped SSIDs.

The installer re-runs the suite on each node after installing.

---

## Recovering a node

1. **Over the network** — `netdctl status`, or the portal on the node's LAN
   address, or Tailscale.
2. **Over the maintenance AP** — join `EnergyNode-Nxxx`, open
   `http://192.168.66.1`. Appears automatically ~3 minutes after the node
   goes offline.
3. **With a monitor and keyboard** — the console is already on tty1.
   Alt+F2 for a shell.
4. **Last resort** — `netdctl factory-network-reset --yes`, then rejoin over
   the AP. Measurements are preserved.
