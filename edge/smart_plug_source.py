"""Smart Plug (Shelly Plug US Gen4) collection source for the Raspberry Pi.

This is an additional *source* inside the edge collector, not a second
collector. It is designed to be started from the existing collector process:

    from smart_plug_source import SmartPlugSource

    source = SmartPlugSource(node_id="N001", backend_url="http://host:8010")
    source.start()          # runs its own daemon threads, returns immediately

It can also run standalone (systemd unit) for Raspberry Pis whose collector
cannot be modified:

    python3 smart_plug_source.py --node-id N001 --backend http://host:8010

Design rules enforced here
-------------------------
* A Smart Plug is identified by *capability*, never by product identity. See
  `has_switch_metering()`: a device qualifies only if it answers
  Shelly.GetDeviceInfo, exposes a controllable Switch component, and reports
  power and cumulative energy for that switch. Model strings, app strings,
  firmware versions and MAC allowlists are deliberately never consulted, so
  future Shelly plug models and generations work without any code change,
  while Energy Meters such as the Pro3EM are excluded automatically.
* A plug is identified by MAC address, never by IP. When a known MAC reappears
  on a different IP, the stored IP is updated and no duplicate is created.
* Nothing about the network is hardcoded: no wlan0/eth0, no IP range, no
  gateway, no SSID. The active interface and its subnet are detected at
  runtime, so the same code works on the plugs' WiFi and on the network the
  120 A node's Raspberry uses.
* Full discovery every 5 minutes; known plugs polled every 15 seconds.
* A known plug that stops responding triggers immediate rediscovery of that
  device, without waiting for the next 5 minute cycle.
* If the backend is unavailable, measurements are buffered in SQLite and
  retried. Measurements are never dropped because of a temporary outage.
* A plug that disappears is never deleted: it is reported online=false with
  its last seen preserved, and recovers automatically when rediscovered.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import logging
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

LOG = logging.getLogger("smart_plugs")

__version__ = "1.2.0"

# ----------------------------------------------------------------- schedule
DISCOVERY_INTERVAL_S = 300     # full discovery every 5 minutes
POLL_INTERVAL_S = 15           # poll every known plug every 15 seconds
UPLOAD_INTERVAL_S = 15         # flush buffered measurements at poll cadence
# A plug seen within this window counts as online for diagnostics. Matches the
# backend's ONLINE_WINDOW_SECONDS so `--health` and the dashboard agree.
HEALTH_ONLINE_WINDOW_S = 90

# ------------------------------------------------------------------ network
RPC_TIMEOUT_S = 2.0            # per-device RPC timeout while polling
SWEEP_TIMEOUT_S = 0.6          # shorter timeout while sweeping the subnet
SWEEP_WORKERS = 64             # parallel probes during a sweep
BACKEND_TIMEOUT_S = 15.0

# A sweep is only reasonable on a small subnet. Anything larger relies on mDNS
# plus the last known IPs, so we never flood a university-wide network.
MAX_SWEEP_HOSTS = 1024

# Devices whose MAC is known to belong to this platform. Discovery still works
# for any Shelly plug; this list only documents the deployed fleet.
KNOWN_FLEET = {
    "AC:EB:E6:F6:53:88",
    "AC:EB:E6:F2:91:B8",
    "AC:EB:E6:F2:57:EC",
    "AC:EB:E6:F2:83:08",
}


def utc_now_iso() -> str:
    """Sample timestamp, UTC, with millisecond precision.

    Sub-second precision matters: both the local buffer and the backend treat
    (device, timestamp) as the identity of a measurement, which is what makes
    retries idempotent. At whole-second resolution two samples taken inside the
    same second would be silently discarded as duplicates, so the resolution is
    kept finer than any polling cadence.
    """
    stamp = datetime.now(timezone.utc)
    return stamp.replace(microsecond=(stamp.microsecond // 1000) * 1000).isoformat()


def normalize_mac(mac: str) -> str:
    """Uppercase colon-separated MAC. Shelly reports bare hex."""
    cleaned = "".join(ch for ch in str(mac) if ch.isalnum()).upper()

    if len(cleaned) != 12:
        return str(mac).strip().upper()

    return ":".join(cleaned[i:i + 2] for i in range(0, 12, 2))


# =========================================================== network probing
def active_source_ip() -> str | None:
    """Source IP of the interface that actually carries traffic.

    Uses a connectionless UDP socket, so nothing is sent: the kernel simply
    resolves the route and tells us which local address it would use. This is
    interface-name agnostic by construction.
    """
    for probe in ("8.8.8.8", "1.1.1.1"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(1.0)
                sock.connect((probe, 53))
                return sock.getsockname()[0]
        except OSError:
            continue

    return None


def local_networks() -> list[ipaddress.IPv4Network]:
    """Every IPv4 network this Raspberry is currently attached to.

    Parsed from the kernel, so it follows the Pi wherever it is connected: a
    different SSID, a different subnet or a renamed interface all just work.
    Loopback and link-local are excluded.
    """
    networks: list[ipaddress.IPv4Network] = []

    try:
        output = subprocess.run(
            ["ip", "-o", "-f", "inet", "addr", "show", "scope", "global"],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        LOG.warning("could not read interface addresses: %s", exc)
        output = ""

    for line in output.splitlines():
        parts = line.split()
        if "inet" not in parts:
            continue

        cidr = parts[parts.index("inet") + 1]

        try:
            network = ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            continue

        if not isinstance(network, ipaddress.IPv4Network):
            continue
        if network.is_loopback or network.is_link_local:
            continue

        networks.append(network)

    # Fallback: derive a /24 around the active source address.
    if not networks:
        source = active_source_ip()
        if source:
            try:
                networks.append(ipaddress.ip_network(f"{source}/24", strict=False))
            except ValueError:
                pass

    return networks


def rpc_get(ip: str, method: str, timeout: float = RPC_TIMEOUT_S, params: str = "") -> dict | None:
    """Call a Shelly Gen4 RPC endpoint over HTTP.

    Gen4 exposes RPC as GET /rpc/<Method>. Any failure returns None; callers
    treat that as "not responding" and never as a fatal error.
    """
    url = f"http://{ip}/rpc/{method}"
    if params:
        url = f"{url}?{params}"

    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            if response.status != 200:
                return None
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return None


def has_switch_metering(ip: str, timeout: float = RPC_TIMEOUT_S) -> bool:
    """Does the device at `ip` behave like a metered, controllable outlet?

    A Smart Plug is defined by what it *can do*, never by what it is called.
    Product model, app string, firmware version and MAC prefix are deliberately
    not consulted, for two reasons:

    * a plug model or generation bought in the future must be collected without
      anyone editing this file, and
    * an Energy Meter is also a Shelly device answering the same discovery RPC,
      so a name-based rule would either admit it or need a growing blocklist.

    The device qualifies only when all of the following hold:

    1. it exposes a Switch component at id=0 (`Switch.GetStatus`);
    2. that switch is *controllable* — it reports its output state;
    3. that switch carries metering — instantaneous power *and* cumulative
       energy are reported for it.

    The Shelly Pro3EM Energy Node meter fails at (1): it has no Switch
    component and answers HTTP 404 "No handler for Switch.GetStatus", so it is
    never mistaken for an accessory plug.
    """
    status = rpc_get(ip, "Switch.GetStatus", timeout=timeout, params="id=0")

    if not isinstance(status, dict):
        return False

    # (2) controllable: the switch reports the state of its output.
    if not isinstance(status.get("output"), bool):
        return False

    # (3a) instantaneous power for this switch.
    if not isinstance(status.get("apower"), (int, float)):
        return False

    # (3b) cumulative energy for this switch.
    energy = status.get("aenergy")
    if not isinstance(energy, dict) or not isinstance(energy.get("total"), (int, float)):
        return False

    return True


def identify(ip: str, timeout: float = RPC_TIMEOUT_S) -> dict | None:
    """Return device identity if `ip` hosts a Smart Plug, else None.

    Identity is only read after the capability test in `has_switch_metering()`
    passes, so a Shelly device that is not a metered controllable outlet is
    never registered as a plug. The extra RPC costs nothing during a sweep: it
    runs only for the handful of addresses that answered GetDeviceInfo at all.
    """
    info = rpc_get(ip, "Shelly.GetDeviceInfo", timeout=timeout)

    if not isinstance(info, dict) or not info.get("mac"):
        return None

    if not has_switch_metering(ip, timeout=timeout):
        LOG.debug("%s is a Shelly device but has no metered switch; not a plug", ip)
        return None

    return {
        "mac": normalize_mac(info["mac"]),
        "ip": ip,
        "hostname": info.get("id"),
        "model": info.get("model") or "Shelly Plug US Gen4",
        "firmware": info.get("ver") or info.get("fw_id"),
        "serial": str(info["serial"]) if info.get("serial") is not None else None,
        "gen": info.get("gen"),
    }


def read_telemetry(ip: str) -> dict | None:
    """Instantaneous switch telemetry plus WiFi signal.

    Shelly reports energy in Wh and power in W; energy is converted to kWh to
    match the backend contract.
    """
    status = rpc_get(ip, "Switch.GetStatus", params="id=0")

    if not isinstance(status, dict):
        return None

    energy = status.get("aenergy") or {}
    temperature = status.get("temperature") or {}

    total_wh = energy.get("total")

    sample = {
        "captured_at": utc_now_iso(),
        "power_w": status.get("apower"),
        "voltage_v": status.get("voltage"),
        "current_a": status.get("current"),
        "power_factor": status.get("pf"),
        "energy_total_kwh": round(total_wh / 1000.0, 6) if isinstance(total_wh, (int, float)) else None,
        "temperature_c": temperature.get("tC"),
        "rssi": None,
    }

    wifi = rpc_get(ip, "WiFi.GetStatus", timeout=1.5)
    if isinstance(wifi, dict):
        sample["rssi"] = wifi.get("rssi")

    return sample


# ================================================================== buffering
class MeasurementBuffer:
    """Durable store-and-forward queue for plug measurements.

    Its own SQLite file, deliberately separate from whatever database the
    existing collector uses, so Energy Node buffering is never disturbed.
    """

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _init_schema(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_measurements (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    mac          TEXT NOT NULL,
                    captured_at  TEXT NOT NULL,
                    payload      TEXT NOT NULL,
                    UNIQUE(mac, captured_at)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS known_plugs (
                    mac        TEXT PRIMARY KEY,
                    ip         TEXT,
                    identity   TEXT,
                    last_seen  TEXT
                )
                """
            )
            # Diagnostics. Persisted rather than kept in memory so `--health`
            # can report on a *running* collector from a separate process,
            # which is the situation you are in when troubleshooting.
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS source_state (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                )
                """
            )

    # ----------------------------------------------------------- diagnostics
    def set_state(self, key: str, value) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT INTO source_state (key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)),
            )

    def get_state(self) -> dict[str, str]:
        with self._lock, self._connect() as connection:
            return {
                key: value
                for key, value in connection.execute("SELECT key, value FROM source_state")
            }

    # ------------------------------------------------------------ measurements
    def add(self, mac: str, sample: dict) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO pending_measurements (mac, captured_at, payload) VALUES (?,?,?)",
                (mac, sample["captured_at"], json.dumps(sample)),
            )

    def take(self, limit: int = 500) -> list[tuple[int, str, dict]]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT id, mac, payload FROM pending_measurements ORDER BY id LIMIT ?",
                (limit,),
            ).fetchall()

        return [(row[0], row[1], json.loads(row[2])) for row in rows]

    def drop(self, ids: list[int]) -> None:
        if not ids:
            return

        with self._lock, self._connect() as connection:
            connection.executemany(
                "DELETE FROM pending_measurements WHERE id = ?", [(i,) for i in ids]
            )

    def pending_count(self) -> int:
        with self._lock, self._connect() as connection:
            return connection.execute("SELECT COUNT(*) FROM pending_measurements").fetchone()[0]

    # ------------------------------------------------------------ inventory
    def remember(self, mac: str, ip: str | None, identity: dict, last_seen: str | None) -> None:
        """Persist the inventory so a reboot does not lose known devices."""
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO known_plugs (mac, ip, identity, last_seen) VALUES (?,?,?,?)
                ON CONFLICT(mac) DO UPDATE SET ip=excluded.ip,
                                               identity=excluded.identity,
                                               last_seen=excluded.last_seen
                """,
                (mac, ip, json.dumps(identity), last_seen),
            )

    def load_known(self) -> dict[str, dict]:
        with self._lock, self._connect() as connection:
            rows = connection.execute("SELECT mac, ip, identity, last_seen FROM known_plugs").fetchall()

        known = {}
        for mac, ip, identity, last_seen in rows:
            try:
                parsed = json.loads(identity) if identity else {}
            except json.JSONDecodeError:
                parsed = {}

            parsed["ip"] = ip
            known[mac] = {"identity": parsed, "last_seen": last_seen}

        return known


# =================================================================== the source
class SmartPlugSource:
    """Discovers, polls and reports Shelly plugs for one Raspberry Pi."""

    def __init__(
        self,
        node_id: str,
        backend_url: str,
        buffer_path: str | None = None,
    ):
        self.node_id = node_id
        self.backend_url = backend_url.rstrip("/")
        self.buffer = MeasurementBuffer(
            buffer_path or os.environ.get("SMART_PLUG_BUFFER", "/var/lib/energy-collector/smart_plugs.db")
        )

        # mac -> {"identity": {...}, "online": bool, "last_seen": iso, "failures": int}
        self.plugs: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._rediscover_now = threading.Event()

        self._restore_inventory()

    # ------------------------------------------------------------- inventory
    def _restore_inventory(self) -> None:
        """Reboot recovery: last known plugs and IPs come back from SQLite."""
        for mac, stored in self.buffer.load_known().items():
            self.plugs[mac] = {
                "identity": stored["identity"],
                "online": False,          # proven again by the first poll
                "last_seen": stored["last_seen"],
                "failures": 0,
            }

        if self.plugs:
            LOG.info("restored %d known plug(s) from buffer", len(self.plugs))

    def _remember(self, mac: str, entry: dict) -> None:
        self.buffer.remember(
            mac, entry["identity"].get("ip"), entry["identity"], entry.get("last_seen")
        )

    # ------------------------------------------------------------- discovery
    def discover(self, targets: list[str] | None = None) -> int:
        """Find plugs on every network this Pi is attached to.

        mDNS first when available (cheap and immediate), then a bounded sweep
        of the local subnets, which is what makes discovery work on any SSID or
        subnet without configuration.
        """
        candidates: list[str] = []

        if targets:
            candidates.extend(targets)
        else:
            candidates.extend(self._mdns_candidates())
            candidates.extend(self._sweep_candidates())

        # Always re-probe last known IPs: usually the cheapest hit.
        with self._lock:
            candidates.extend(
                entry["identity"]["ip"]
                for entry in self.plugs.values()
                if entry["identity"].get("ip")
            )

        seen: set[str] = set()
        ordered = [ip for ip in candidates if ip and not (ip in seen or seen.add(ip))]

        if not ordered:
            LOG.warning("discovery found no candidate addresses")
            return 0

        found = 0
        with ThreadPoolExecutor(max_workers=SWEEP_WORKERS) as pool:
            for identity in pool.map(lambda ip: identify(ip, SWEEP_TIMEOUT_S), ordered):
                if identity:
                    self._register(identity)
                    found += 1

        LOG.info("discovery probed %d address(es), found %d plug(s)", len(ordered), found)

        self.buffer.set_state("last_discovery_at", utc_now_iso())
        self.buffer.set_state("last_discovery_probed", len(ordered))
        self.buffer.set_state("last_discovery_found", found)

        return found

    def _mdns_candidates(self) -> list[str]:
        """Shelly devices advertise _shelly._tcp. zeroconf is optional."""
        try:
            from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
        except ImportError:
            return []

        found: list[str] = []

        class Listener(ServiceListener):
            def add_service(self, zc, type_, name):
                info = zc.get_service_info(type_, name, timeout=1500)
                if info:
                    for raw in info.addresses:
                        try:
                            found.append(str(ipaddress.ip_address(raw)))
                        except ValueError:
                            continue

            def update_service(self, zc, type_, name):
                self.add_service(zc, type_, name)

            def remove_service(self, zc, type_, name):
                """A device leaving mDNS is not a removal: plugs are never deleted."""

        zeroconf = Zeroconf()
        try:
            for service in ("_shelly._tcp.local.", "_http._tcp.local."):
                ServiceBrowser(zeroconf, service, Listener())
            time.sleep(3.0)
        except OSError as exc:
            LOG.debug("mDNS browse failed: %s", exc)
        finally:
            zeroconf.close()

        return found

    def _sweep_candidates(self) -> list[str]:
        """Every host address of the currently attached subnets, if small enough."""
        candidates: list[str] = []

        for network in local_networks():
            if network.num_addresses > MAX_SWEEP_HOSTS:
                LOG.info("skipping sweep of %s: %d addresses is too large",
                         network, network.num_addresses)
                continue

            candidates.extend(str(host) for host in network.hosts())

        return candidates

    def _register(self, identity: dict) -> None:
        """Upsert by MAC. An IP change updates in place, never duplicates."""
        mac = identity["mac"]

        with self._lock:
            entry = self.plugs.get(mac)

            if entry is None:
                LOG.info("discovered new plug %s at %s", mac, identity.get("ip"))
                entry = {"identity": identity, "online": True,
                         "last_seen": utc_now_iso(), "failures": 0}
                self.plugs[mac] = entry
            else:
                previous_ip = entry["identity"].get("ip")

                if previous_ip != identity.get("ip"):
                    LOG.info("plug %s moved from %s to %s", mac, previous_ip, identity.get("ip"))

                entry["identity"].update(identity)
                entry["failures"] = 0

            snapshot = dict(entry)

        self._remember(mac, snapshot)

    # ------------------------------------------------------------------ poll
    def poll_once(self) -> None:
        """Poll every known plug at its latest IP."""
        with self._lock:
            targets = [(mac, entry["identity"].get("ip")) for mac, entry in self.plugs.items()]

        if not targets:
            return

        lost: list[str] = []

        def poll(target):
            mac, ip = target
            return mac, (read_telemetry(ip) if ip else None)

        with ThreadPoolExecutor(max_workers=min(16, max(1, len(targets)))) as pool:
            for mac, sample in pool.map(poll, targets):
                if sample:
                    self.buffer.add(mac, sample)

                    with self._lock:
                        entry = self.plugs[mac]
                        entry["online"] = True
                        entry["last_seen"] = sample["captured_at"]
                        entry["failures"] = 0

                        if sample.get("rssi") is not None:
                            entry["identity"]["rssi"] = sample["rssi"]
                        if sample.get("temperature_c") is not None:
                            entry["identity"]["temperature_c"] = sample["temperature_c"]

                        snapshot = dict(entry)

                    self._remember(mac, snapshot)
                else:
                    with self._lock:
                        entry = self.plugs[mac]
                        entry["failures"] += 1
                        was_online = entry["online"]
                        entry["online"] = False

                    if was_online:
                        LOG.warning("plug %s stopped responding at %s; rediscovering now",
                                    mac, entry["identity"].get("ip"))
                    lost.append(mac)

        self.buffer.set_state("last_poll_at", utc_now_iso())
        self.buffer.set_state("last_poll_targets", len(targets))
        self.buffer.set_state("last_poll_failed", len(lost))

        if len(lost) < len(targets):
            self.buffer.set_state("last_successful_poll_at", utc_now_iso())

        # A plug that stopped answering is rediscovered immediately, not in 5 min.
        if lost:
            self._rediscover_now.set()

    def rediscover_lost(self) -> None:
        """Targeted rediscovery for the plugs that are currently down."""
        with self._lock:
            lost = [mac for mac, entry in self.plugs.items() if not entry["online"]]

        if not lost:
            return

        LOG.info("targeted rediscovery for %d plug(s): %s", len(lost), ", ".join(lost))
        self.discover()

    # ---------------------------------------------------------------- upload
    def report(self) -> bool:
        """Send inventory plus buffered measurements. Keep the buffer on failure."""
        batch = self.buffer.take(limit=500)

        grouped: dict[str, list[dict]] = {}
        for _, mac, sample in batch:
            grouped.setdefault(mac, []).append(sample)

        with self._lock:
            inventory = {
                mac: {"identity": dict(entry["identity"]),
                      "online": entry["online"],
                      "last_seen": entry["last_seen"]}
                for mac, entry in self.plugs.items()
            }

        # Plugs with buffered data but no inventory entry (e.g. removed from
        # memory) still get reported, so no measurement is ever orphaned.
        for mac in grouped:
            inventory.setdefault(mac, {"identity": {"mac": mac}, "online": False, "last_seen": None})

        if not inventory:
            return True

        plugs_payload = []
        for mac, entry in inventory.items():
            identity = entry["identity"]

            plugs_payload.append({
                "mac": mac,
                "model": identity.get("model"),
                "ip": identity.get("ip"),
                "hostname": identity.get("hostname"),
                "serial": identity.get("serial"),
                "firmware": identity.get("firmware"),
                "rssi": identity.get("rssi"),
                "temperature_c": identity.get("temperature_c"),
                "online": entry["online"],
                "last_seen": entry["last_seen"],
                "measurements": grouped.get(mac, []),
            })

        payload = {"node_id": self.node_id, "plugs": plugs_payload}

        request = urllib.request.Request(
            f"{self.backend_url}/api/smart-plugs/discovery",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=BACKEND_TIMEOUT_S) as response:
                if response.status != 200:
                    LOG.warning("backend returned HTTP %s; keeping buffer", response.status)
                    return False

                body = json.loads(response.read().decode("utf-8", errors="replace"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            LOG.warning("backend unavailable (%s); %d measurement(s) buffered",
                        exc, self.buffer.pending_count())
            self.buffer.set_state("last_backend_error", f"{utc_now_iso()} {exc}")
            self.buffer.set_state("backend_reachable", "0")
            return False

        # Only now is it safe to forget the measurements.
        self.buffer.drop([row_id for row_id, _, _ in batch])

        LOG.info("reported %d plug(s), %d measurement(s) accepted (%s inserted, %s duplicate)",
                 len(plugs_payload), len(batch),
                 body.get("readings_inserted"), body.get("readings_duplicated"))

        self.buffer.set_state("last_report_at", utc_now_iso())
        self.buffer.set_state("backend_reachable", "1")

        # The backend rejects reports for plugs owned by another node. Surface
        # that here: otherwise a plug this Pi can see simply never appears in
        # the platform, with nothing in the local log to explain why.
        not_owner = body.get("rejected_not_owner") or []
        if not_owner:
            LOG.warning(
                "backend rejected %d plug(s) owned by another node: %s",
                len(not_owner), ", ".join(not_owner),
            )
        self.buffer.set_state("last_rejected_not_owner", ",".join(not_owner))

        for field in ("rejected_malformed_mac", "rejected_duplicate_mac"):
            values = body.get(field) or []
            if values:
                LOG.warning("backend rejected %s: %s", field, ", ".join(map(str, values)))

        return True

    # ------------------------------------------------------------------ loops
    def _discovery_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.discover()
            except Exception:
                LOG.exception("discovery cycle failed; continuing")

            # Wake early when a poll detected a plug going down.
            if self._rediscover_now.wait(timeout=DISCOVERY_INTERVAL_S):
                self._rediscover_now.clear()

                try:
                    self.rediscover_lost()
                except Exception:
                    LOG.exception("targeted rediscovery failed; continuing")

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()

            try:
                self.poll_once()
            except Exception:
                LOG.exception("poll cycle failed; continuing")

            try:
                self.report()
            except Exception:
                LOG.exception("report failed; measurements remain buffered")

            self._stop.wait(max(0.0, POLL_INTERVAL_S - (time.monotonic() - started)))

    # ------------------------------------------------------------- diagnostics
    def health(self, probe_backend: bool = True) -> dict:
        """Everything needed to troubleshoot this node's plug collection.

        Reads the persisted state, so it reports correctly on a *running*
        collector when invoked from a separate process — which is how it is
        normally used. Online status is derived from how recently each plug was
        last seen rather than from in-memory flags, because a health check runs
        in its own process where those flags are always still false.
        """
        state = self.buffer.get_state()

        def seen_recently(last_seen: str | None) -> bool:
            if not last_seen:
                return False
            try:
                stamp = datetime.fromisoformat(last_seen)
            except ValueError:
                return False
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - stamp).total_seconds()
            return age <= HEALTH_ONLINE_WINDOW_S

        with self._lock:
            inventory = {
                mac: {"ip": entry["identity"].get("ip"), "last_seen": entry.get("last_seen")}
                for mac, entry in self.plugs.items()
            }

        if not inventory:
            inventory = {
                mac: {"ip": stored["identity"].get("ip"), "last_seen": stored["last_seen"]}
                for mac, stored in self.buffer.load_known().items()
            }

        plugs = [
            {
                "mac": mac,
                "ip": entry["ip"],
                "online": seen_recently(entry["last_seen"]),
                "last_seen": entry["last_seen"],
            }
            for mac, entry in sorted(inventory.items())
        ]

        known = len(plugs)
        online = sum(1 for plug in plugs if plug["online"])

        backend_reachable = state.get("backend_reachable")

        if probe_backend:
            try:
                request = urllib.request.Request(
                    f"{self.backend_url}/api/smart-plugs", method="GET"
                )
                with urllib.request.urlopen(request, timeout=10) as response:
                    backend_reachable = "1" if response.status == 200 else "0"
            except (urllib.error.URLError, OSError, ValueError):
                backend_reachable = "0"

        return {
            "version": __version__,
            "node_id": self.node_id,
            "backend_url": self.backend_url,
            "buffer_path": self.buffer.path,
            "known_plugs": known,
            "online_plugs": online,
            "pending_measurements": self.buffer.pending_count(),
            "backend_reachable": backend_reachable == "1",
            "last_discovery_at": state.get("last_discovery_at"),
            "last_discovery_found": state.get("last_discovery_found"),
            "last_discovery_probed": state.get("last_discovery_probed"),
            "last_poll_at": state.get("last_poll_at"),
            "last_successful_poll_at": state.get("last_successful_poll_at"),
            "last_poll_failed": state.get("last_poll_failed"),
            "last_report_at": state.get("last_report_at"),
            "last_backend_error": state.get("last_backend_error"),
            "last_rejected_not_owner": state.get("last_rejected_not_owner") or "",
            "plugs": plugs,
        }

    def start(self) -> None:
        """Start both loops as daemon threads and return immediately."""
        threading.Thread(target=self._discovery_loop, name="plug-discovery", daemon=True).start()
        threading.Thread(target=self._poll_loop, name="plug-poll", daemon=True).start()
        LOG.info("smart plug source started for node %s -> %s", self.node_id, self.backend_url)

    def stop(self) -> None:
        self._stop.set()

    def run_forever(self) -> None:
        self.start()
        try:
            while not self._stop.is_set():
                time.sleep(1.0)
        except KeyboardInterrupt:
            self.stop()


# ==================================================================== standalone
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Shelly Plug US Gen4 collection source")
    parser.add_argument("--node-id", default=os.environ.get("NODE_ID"),
                        help="Node code as registered in the platform, e.g. N001")
    parser.add_argument("--backend", default=os.environ.get("BACKEND_URL"),
                        help="Backend base URL, e.g. http://host:8010")
    parser.add_argument("--buffer", default=os.environ.get("SMART_PLUG_BUFFER"),
                        help="Path to the SQLite buffer file")
    parser.add_argument("--log-level", default=os.environ.get("LOG_LEVEL", "INFO"))
    parser.add_argument("--once", action="store_true",
                        help="Run a single discover/poll/report cycle and exit (for testing)")
    parser.add_argument("--health", action="store_true",
                        help="Print collection diagnostics and exit (safe on a running node)")
    parser.add_argument("--json", action="store_true",
                        help="With --health, emit JSON instead of text")
    parser.add_argument("--version", action="version", version=f"smart_plug_source {__version__}")

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    if not args.node_id or not args.backend:
        parser.error("--node-id and --backend are required (or set NODE_ID / BACKEND_URL)")

    source = SmartPlugSource(
        node_id=args.node_id,
        backend_url=args.backend,
        buffer_path=args.buffer,
    )

    if args.health:
        report = source.health()

        if args.json:
            print(json.dumps(report, indent=2))
            return 0 if report["backend_reachable"] else 1

        def show(label, value):
            print(f"  {label:<26} {value}")

        print(f"Smart Plug source {report['version']} — node {report['node_id']}")
        show("backend", report["backend_url"])
        show("backend reachable", "yes" if report["backend_reachable"] else "NO")
        show("buffer", report["buffer_path"])
        show("known plugs", report["known_plugs"])
        show("online plugs", report["online_plugs"])
        show("pending measurements", report["pending_measurements"])
        show("last discovery", f"{report['last_discovery_at']} "
                               f"(probed {report['last_discovery_probed']}, "
                               f"found {report['last_discovery_found']})")
        show("last poll", report["last_poll_at"])
        show("last successful poll", report["last_successful_poll_at"])
        show("last report to backend", report["last_report_at"])

        if report["last_rejected_not_owner"]:
            show("rejected (not owner)", report["last_rejected_not_owner"])
        if report["last_backend_error"]:
            show("last backend error", report["last_backend_error"])

        print("  plugs:")
        for plug in report["plugs"]:
            state = "online" if plug["online"] else "OFFLINE"
            print(f"    {plug['mac']}  {str(plug['ip']):<16} {state:<8} last_seen={plug['last_seen']}")

        return 0 if report["backend_reachable"] else 1

    if args.once:
        LOG.info("networks detected: %s", ", ".join(str(n) for n in local_networks()) or "none")
        source.discover()
        source.poll_once()
        source.report()
        return 0

    source.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
