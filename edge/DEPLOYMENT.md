# Smart Plug deployment procedure

Standardised install of the Smart Plug collection source onto any Energy Node
Raspberry Pi. The collector already running on the node is **extended, never
replaced**.

Version: see `VERSION`.

## One command

From this directory, on the target Pi:

```bash
./install-smart-plugs.sh --node-id N001 --enable
```

Everything else is auto-detected from the node itself: the systemd unit, the
collector path, the interpreter, the service user, the backend URL, and a
buffer location the hardened unit is actually allowed to write to. Nothing
about the network — interface, subnet, gateway, SSID — appears anywhere.

Flags:

| Flag | Meaning |
|---|---|
| `--node-id` | Node code. Auto-detected when the unit exposes `NODE_ID`; required otherwise. |
| `--backend` | Backend base URL. Auto-detected from `CENTRAL_API_URL`. |
| `--enable` / `--disable` | Whether the source actually runs. Default: disabled. |

Re-running is safe and is the supported upgrade path: the source file is
replaced, the collector patch is detected and skipped, and the config is
rewritten.

## What it does

1. **Inspect** — locate the unit, collector, interpreter, service user, node
   code, backend URL and a writable buffer directory.
2. **Verify compatibility** — the collector must provide `import os`, a
   module-level `log`, `def main()` and a `polling_loop()` call site, and the
   interpreter must have the required stdlib. Incompatible → abort, nothing
   changed.
3. **Timestamped backup** — collector, env file, existing config and the unit
   text, into `<node-root>/backups/smart-plugs-<timestamp>/`.
4. **Install** `smart_plug_source.py` beside the collector, plus the README,
   plus the buffer directory owned by the service user.
5. **Integrate** — insert one config reader, one starter function and one call.
   The patcher refuses if any pre-existing line would change, then byte-compiles.
6. **Configure** `/etc/energy-node/smart-plugs.conf`.
7. **Restart** the collector (only if it was already running).
8. **Verify** the journal shows the source started or is deliberately disabled.

## Why a config file instead of the collector's env file

The nodes do not pass configuration the same way — some use
`EnvironmentFile=`, others inline `Environment=` lines, and not all define
`NODE_ID`. `/etc/energy-node/smart-plugs.conf` works on all of them and leaves
each node's Energy Node configuration untouched. The environment still wins if
a variable is set there.

## One node per subnet

**Only one node per subnet may have `SMART_PLUGS_ENABLED=1`.**

The backend upserts plugs on MAC and sets `plug.node_id` on every report. Two
nodes on the same subnet discover the same plugs, so ownership would flip
between them every cycle and each plug would receive two independent
measurement streams.

Enable it on the node that should own the plugs on that subnet; install it
disabled elsewhere so it is ready to take over.

## Rollback

```bash
sudo cp <backup>/collector.py <collector path>
sudo rm -f /etc/energy-node/smart-plugs.conf
sudo systemctl restart <unit>
```

Or simply set `SMART_PLUGS_ENABLED=0` and restart — the Energy Node pipeline is
unaffected either way, since the integration is inert when disabled.

## Verification after deployment

```bash
# Energy Node still collecting, and no plug errors
journalctl -u <unit> --since '-5 min' | grep -E 'Stored|Heartbeat|Smart Plug'

# Backend inventory: real MAC / IP / firmware / RSSI, no Energy Meter present
curl -s http://<backend>:8010/api/smart-plugs
curl -s http://<backend>:8010/api/smart-plugs/live
```

A Shelly **Energy Meter must never appear** in that inventory. Plugs are
identified by capability — see “What counts as a Smart Plug” in
`README-smart-plugs.md`.
