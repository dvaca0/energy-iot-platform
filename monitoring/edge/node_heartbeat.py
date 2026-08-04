#!/usr/bin/env python3
"""Energy Platform node heartbeat agent.

Runs on each Raspberry Pi and reports node health to the backend every
30–60 seconds. This is the health of the *node itself*, not its electrical
measurements — the two are deliberately separate signals so the server can tell
"the node is down" from "the node is up but its sensors are dead".

Design constraints, all deliberate:

**Standard library only.** No requests, no psutil, no third-party anything. The
Pis are field-deployed behind NAT and may not have pip access; an agent that
cannot be installed is worth nothing. Every probe reads ``/proc``, ``/sys`` or
shells out to a tool that is present on Raspberry Pi OS.

**Every probe is individually guarded.** A probe that fails contributes ``None``
and never prevents the heartbeat from being sent. A heartbeat that says "I am
alive but I could not read my temperature" is far more useful than no heartbeat
at all, which would be indistinguishable from the node being dead.

**It never touches the collector.** No shared files, no shared database, no
signals. It reads the collector's state through systemd and, optionally, the
size of its buffer database. If this agent crashes, collection is unaffected.

**Read-only.** It changes nothing on the node.

Usage::

    python3 node_heartbeat.py --node-id N001 --backend http://host:8010
    python3 node_heartbeat.py --node-id N001 --backend http://host:8010 --once --verbose

Configuration comes from CLI flags, then environment variables:
``NODE_ID``, ``BACKEND_URL``, ``HEARTBEAT_INTERVAL``, ``COLLECTOR_SERVICE``,
``COLLECTOR_DB``, ``SOFTWARE_VERSION``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VERSION = "1.0.0"

log = logging.getLogger("node-heartbeat")

_shutdown = False


# ---------------------------------------------------------------------------
# Probe helpers
# ---------------------------------------------------------------------------

def _run(command: list[str], timeout: float = 5.0) -> tuple[int, str]:
    """Run a command, returning ``(returncode, stdout)``. Never raises."""
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False
        )
        return result.returncode, result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def _read(path: str) -> str | None:
    """Read a file, returning ``None`` on any error."""
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def safe(func, default=None):
    """Call a probe, swallowing any failure.

    The agent's contract is that it always sends *something*. A probe that
    raises must degrade that one field, not the whole heartbeat.
    """
    try:
        return func()
    except Exception as exc:  # noqa: BLE001
        log.debug("probe %s failed: %s", getattr(func, "__name__", func), exc)
        return default


# ---------------------------------------------------------------------------
# Individual probes
# ---------------------------------------------------------------------------

def probe_uptime() -> dict[str, Any]:
    raw = _read("/proc/uptime")
    if not raw:
        return {}
    seconds = float(raw.split()[0])
    boot = datetime.now(timezone.utc).timestamp() - seconds
    return {
        "uptime_seconds": round(seconds, 1),
        "boot_time": datetime.fromtimestamp(boot, timezone.utc).isoformat(),
    }


_prev_cpu: tuple[int, int] | None = None


def probe_cpu() -> dict[str, Any]:
    """CPU utilisation from ``/proc/stat``.

    Computed as a delta against the previous sample rather than a blocking
    measurement, so the agent never sleeps inside a probe. The first call after
    startup has no previous sample and reports ``None`` instead of a fabricated
    value.
    """
    global _prev_cpu

    raw = _read("/proc/stat")
    if not raw:
        return {}

    for line in raw.splitlines():
        if not line.startswith("cpu "):
            continue
        values = [int(v) for v in line.split()[1:]]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        total = sum(values)

        result: dict[str, Any] = {}
        if _prev_cpu is not None:
            prev_idle, prev_total = _prev_cpu
            delta_total = total - prev_total
            delta_idle = idle - prev_idle
            if delta_total > 0:
                result["cpu_percent"] = round(
                    100.0 * (delta_total - delta_idle) / delta_total, 1
                )
        _prev_cpu = (idle, total)
        return result
    return {}


def probe_load() -> dict[str, Any]:
    raw = _read("/proc/loadavg")
    if not raw:
        return {}
    parts = raw.split()
    return {
        "load_1": float(parts[0]),
        "load_5": float(parts[1]),
        "load_15": float(parts[2]),
    }


def probe_memory() -> dict[str, Any]:
    raw = _read("/proc/meminfo")
    if not raw:
        return {}

    values: dict[str, int] = {}
    for line in raw.splitlines():
        key, _, rest = line.partition(":")
        try:
            values[key] = int(rest.strip().split()[0])
        except (IndexError, ValueError):
            continue

    out: dict[str, Any] = {}
    total = values.get("MemTotal")
    available = values.get("MemAvailable")
    if total and available is not None:
        out["memory_percent"] = round(100.0 * (total - available) / total, 1)

    swap_total = values.get("SwapTotal")
    swap_free = values.get("SwapFree")
    if swap_total and swap_free is not None and swap_total > 0:
        out["swap_percent"] = round(100.0 * (swap_total - swap_free) / swap_total, 1)
    return out


def probe_disk(path: str = "/") -> dict[str, Any]:
    stat = os.statvfs(path)
    total = stat.f_blocks * stat.f_frsize
    free = stat.f_bavail * stat.f_frsize
    if total <= 0:
        return {}
    return {
        "disk_percent": round(100.0 * (total - free) / total, 1),
        "disk_free_mb": round(free / 1024 / 1024, 1),
    }


def probe_filesystem_readonly(mount: str = "/") -> dict[str, Any]:
    """Detect a root filesystem remounted read-only.

    On a Pi this almost always means the SD card has failed. The node keeps
    running from page cache and looks healthy while every buffered write is
    silently lost, so this is one of the most valuable fields in the payload.
    """
    raw = _read("/proc/mounts")
    if not raw:
        return {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[1] == mount:
            return {"filesystem_readonly": "ro" in parts[3].split(",")}
    return {}


def probe_temperature() -> dict[str, Any]:
    """SoC temperature, preferring the kernel thermal zone over vcgencmd."""
    raw = _read("/sys/class/thermal/thermal_zone0/temp")
    if raw:
        try:
            return {"cpu_temperature_c": round(int(raw) / 1000.0, 1)}
        except ValueError:
            pass

    code, out = _run(["vcgencmd", "measure_temp"])
    if code == 0:
        match = re.search(r"([\d.]+)", out)
        if match:
            return {"cpu_temperature_c": float(match.group(1))}
    return {}


#: Bit meanings from `vcgencmd get_throttled`. The low bits are live state, the
#: high bits are sticky "has occurred since boot" flags.
_THROTTLE_BITS = {
    0: "under-voltage now",
    1: "arm frequency capped now",
    2: "currently throttled",
    3: "soft temperature limit now",
    16: "under-voltage has occurred",
    17: "arm frequency capping has occurred",
    18: "throttling has occurred",
    19: "soft temperature limit has occurred",
}


def probe_throttling() -> dict[str, Any]:
    """Raspberry Pi power and thermal throttling state.

    Only the live bits (0-3) drive the boolean flags. The sticky bits are
    reported in the text description because "it browned out at some point
    since boot" is useful history but must not raise a standing alert.
    """
    code, out = _run(["vcgencmd", "get_throttled"])
    if code != 0 or "=" not in out:
        return {}

    try:
        value = int(out.split("=")[1], 16)
    except (IndexError, ValueError):
        return {}

    flags = [text for bit, text in _THROTTLE_BITS.items() if value & (1 << bit)]
    return {
        "undervoltage": bool(value & (1 << 0)),
        "throttled": bool(value & (1 << 1) or value & (1 << 2)),
        "throttle_flags": ", ".join(flags) if flags else "none",
    }


def probe_network() -> dict[str, Any]:
    """Interface state, primary address, WiFi association and AP mode."""
    out: dict[str, Any] = {}

    code, routes = _run(["ip", "-o", "route", "get", "1.1.1.1"])
    if code == 0:
        match = re.search(r"src\s+(\S+)", routes)
        if match:
            out["ip_address"] = match.group(1)

    code, links = _run(["ip", "-o", "link"])
    if code == 0:
        for line in links.splitlines():
            match = re.match(r"\d+:\s+([^:@]+)[:@]", line)
            if not match:
                continue
            name = match.group(1).strip()
            is_up = "state UP" in line
            if name.startswith(("eth", "enx", "en")):
                out["ethernet_up"] = out.get("ethernet_up", False) or is_up
            elif name.startswith("wlan"):
                out["wifi_up"] = out.get("wifi_up", False) or is_up

    code, wifi = _run(["iwgetid", "-r"])
    if code == 0 and wifi:
        out["wifi_ssid"] = wifi

    # Signal strength from /proc/net/wireless, which needs no extra tooling.
    raw = _read("/proc/net/wireless")
    if raw:
        for line in raw.splitlines()[2:]:
            parts = line.split()
            if len(parts) >= 4:
                try:
                    out["wifi_signal_dbm"] = float(parts[3].rstrip("."))
                except ValueError:
                    pass
                break

    # An active AP normally means the node failed to join the campus WiFi and
    # fell back to broadcasting its own network.
    code, _ = _run(["systemctl", "is-active", "--quiet", "hostapd"])
    out["access_point_active"] = code == 0

    code, tailscale = _run(["tailscale", "status", "--json"], timeout=6.0)
    if code == 0 and tailscale:
        try:
            out["tailscale_up"] = json.loads(tailscale).get("BackendState") == "Running"
        except ValueError:
            pass

    return out


def probe_internet(host: str = "1.1.1.1", port: int = 443) -> dict[str, Any]:
    """Outbound reachability via TCP rather than ICMP.

    University networks routinely filter ICMP, which would make a working link
    look dead.
    """
    try:
        with socket.create_connection((host, port), timeout=4.0):
            return {"internet_ok": True}
    except OSError:
        return {"internet_ok": False}


def probe_backend_latency(backend_url: str) -> dict[str, Any]:
    """Round-trip time to the backend's health endpoint."""
    url = backend_url.rstrip("/") + "/health"
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            response.read(256)
        return {"latency_ms": round((time.perf_counter() - started) * 1000, 1)}
    except Exception:  # noqa: BLE001
        return {}


def probe_collector(service: str) -> dict[str, Any]:
    """Collector service state, PID and restart count, read from systemd."""
    out: dict[str, Any] = {}

    code, state = _run(["systemctl", "is-active", service])
    if state:
        out["collector_status"] = state
    elif code == 127:
        return out

    code, props = _run(["systemctl", "show", service, "-p", "MainPID,NRestarts"])
    if code == 0:
        for line in props.splitlines():
            key, _, value = line.partition("=")
            if key == "MainPID" and value.isdigit() and int(value) > 0:
                out["collector_pid"] = int(value)
            elif key == "NRestarts" and value.isdigit():
                out["collector_restarts"] = int(value)
    return out


def probe_buffer(db_path: str | None) -> dict[str, Any]:
    """Size of the collector's local buffer database and its WAL.

    Opened read-only through a URI so the agent can never lock, modify or
    checkpoint the collector's database. Row counts are attempted only for
        tables whose names look like a buffer; a failure here is silent.
    """
    if not db_path:
        return {}

    path = Path(db_path)
    if not path.exists():
        return {}

    out: dict[str, Any] = {
        "sqlite_size_mb": round(path.stat().st_size / 1024 / 1024, 2)
    }

    wal = Path(str(path) + "-wal")
    if wal.exists():
        out["sqlite_wal_mb"] = round(wal.stat().st_size / 1024 / 1024, 2)

    try:
        import sqlite3

        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=3.0)
        try:
            cursor = connection.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND (name LIKE '%buffer%' OR name LIKE '%pending%' "
                "OR name LIKE '%queue%' OR name LIKE '%reading%' "
                "OR name LIKE '%measurement%')"
            )
            tables = [row[0] for row in cursor.fetchall()]

            total = 0
            counted = False

            for table in tables:
                # Table names come from sqlite_master on the node's own disk,
                # not from user input, and cannot be parameterised in DDL
                # position; quote them defensively regardless.
                columns = [
                    row[1] for row in cursor.execute(f'PRAGMA table_info("{table}")')
                ]

                # Only rows still awaiting upload count as "buffered". The
                # deployed collector retains synced and deliberately-discarded
                # rows in the same table (sync_status 0=pending, 1=sent,
                # 2=discarded in standby), so counting every row would report
                # ~19k pending on a perfectly healthy node and trip a false
                # CRITICAL on the very first heartbeat.
                status_column = next(
                    (
                        candidate
                        for candidate in (
                            "sync_status",
                            "synced",
                            "sent",
                            "uploaded",
                            "is_synced",
                        )
                        if candidate in columns
                    ),
                    None,
                )

                if status_column:
                    cursor.execute(
                        f'SELECT COUNT(*) FROM "{table}" WHERE "{status_column}" = 0'
                    )
                else:
                    cursor.execute(f'SELECT COUNT(*) FROM "{table}"')

                total += cursor.fetchone()[0]
                counted = True

            if counted:
                out["buffered_readings"] = total
                out["pending_sync"] = total
        finally:
            connection.close()
    except Exception:  # noqa: BLE001
        pass

    return out


def probe_sensors() -> dict[str, Any]:
    """Presence of the buses the sensor chain depends on.

    Reports whether the *interfaces* exist, not whether a specific sensor is
    healthy — the collector owns that judgement. A missing bus explains a whole
    class of measurement failures that otherwise look like wiring faults.
    """
    out: dict[str, Any] = {}

    # Only ever report SPI as *present*. A node with a networked meter (Shelly
    # over HTTP) has no spidev nodes and is perfectly healthy; reporting
    # spi_ok=False there produced a standing ERROR about hardware the node
    # does not use. False must mean "expected but broken", and nothing on the
    # node can establish that expectation — so stay silent instead.
    if list(Path("/dev").glob("spidev*")):
        out["spi_ok"] = True

    i2c = list(Path("/dev").glob("i2c-*"))
    if i2c:
        code, detected = _run(["i2cdetect", "-y", "1"], timeout=8.0)
        if code == 0:
            # ADS1x15 converters answer on 0x48-0x4b.
            out["ads_ok"] = any(
                addr in detected for addr in ("48", "49", "4a", "4b")
            )
        else:
            out["ads_ok"] = None

    if Path("/dev/gpiochip0").exists() or Path("/sys/class/gpio").exists():
        out["gpio_ok"] = True

    return out


def probe_versions(collector_db: str | None) -> dict[str, Any]:
    """Software, collector and configuration versions, plus a git commit."""
    out: dict[str, Any] = {"software_version": os.getenv("SOFTWARE_VERSION", VERSION)}

    for candidate in (
        "/opt/energy-collector/VERSION",
        "/opt/energy-collector/version.txt",
    ):
        value = _read(candidate)
        if value:
            out["collector_version"] = value.splitlines()[0].strip()
            break

    for repo in ("/opt/energy-collector", "/home/pi/energy-collector", os.getcwd()):
        if not Path(repo, ".git").exists():
            continue
        code, commit = _run(["git", "-C", repo, "rev-parse", "--short", "HEAD"])
        if code == 0 and commit:
            out["git_commit"] = commit
            break

    for candidate in (
        "/etc/energy-collector/config.json",
        "/opt/energy-collector/config.json",
    ):
        if Path(candidate).exists():
            try:
                data = json.loads(Path(candidate).read_text())
                if isinstance(data, dict) and data.get("version"):
                    out["config_version"] = str(data["version"])
            except (OSError, ValueError):
                pass
            break

    return out


# ---------------------------------------------------------------------------
# Assembly and delivery
# ---------------------------------------------------------------------------

def build_heartbeat(args) -> dict[str, Any]:
    """Assemble the full payload, tolerating any individual probe failure."""
    payload: dict[str, Any] = {
        "node_id": args.node_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "hostname": safe(socket.gethostname),
    }

    for probe in (
        probe_uptime,
        probe_cpu,
        probe_load,
        probe_memory,
        probe_temperature,
        probe_throttling,
        probe_network,
        probe_internet,
        probe_sensors,
    ):
        result = safe(probe, {})
        if result:
            payload.update(result)

    for probe, argument in (
        (probe_disk, "/"),
        (probe_filesystem_readonly, "/"),
        (probe_backend_latency, args.backend),
        (probe_collector, args.collector_service),
        (probe_buffer, args.collector_db),
        (probe_versions, args.collector_db),
    ):
        result = safe(lambda p=probe, a=argument: p(a), {})
        if result:
            payload.update(result)

    # Local judgements the server cannot make for itself.
    local: list[str] = []
    if payload.get("undervoltage"):
        local.append("undervoltage detected")
    if payload.get("filesystem_readonly"):
        local.append("root filesystem is read-only")
    if payload.get("access_point_active"):
        local.append("access point active")
    if payload.get("internet_ok") is False:
        local.append("no internet connectivity")
    if local:
        payload["local_alerts"] = local

    return {key: value for key, value in payload.items() if value is not None}


def send_heartbeat(backend: str, payload: dict[str, Any], timeout: float = 15.0) -> bool:
    """POST one heartbeat. Returns True on success.

    Failures are logged and swallowed: the next beat is only 30–60 seconds
    away, and a missing beat is itself the signal the server needs. Retrying
    hard here would only delay the next fresh reading.
    """
    url = backend.rstrip("/") + "/api/monitoring/heartbeat"
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": f"energy-node-heartbeat/{VERSION}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8", "replace"))
            log.debug("heartbeat accepted: %s", data)
            if data.get("registered") is False:
                log.warning(
                    "Backend does not recognise node id %r — its measurements "
                    "cannot be attributed to a deployment",
                    payload.get("node_id"),
                )
            drift = data.get("clock_drift_seconds")
            if drift is not None and abs(drift) > 30:
                log.warning("Clock differs from the server by %.0fs", drift)
            return True
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:300]
        except Exception:  # noqa: BLE001
            pass
        log.error("heartbeat rejected: HTTP %s %s", exc.code, detail)
    except urllib.error.URLError as exc:
        log.warning("heartbeat not delivered: %s", exc.reason)
    except Exception as exc:  # noqa: BLE001
        log.warning("heartbeat failed: %s", exc)
    return False


def _handle_signal(signum, _frame):
    global _shutdown
    log.info("received signal %s, exiting after this cycle", signum)
    _shutdown = True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Energy Platform node heartbeat agent",
    )
    parser.add_argument(
        "--node-id",
        default=os.getenv("NODE_ID"),
        help="Node code as registered in the platform (N001, N002...)",
    )
    parser.add_argument(
        "--backend",
        default=os.getenv("BACKEND_URL"),
        help="Backend base URL, e.g. http://host:8010",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.getenv("HEARTBEAT_INTERVAL", "45")),
        help="Seconds between heartbeats (default 45)",
    )
    parser.add_argument(
        "--collector-service",
        default=os.getenv("COLLECTOR_SERVICE", "energy-collector"),
        help="systemd unit name of the collector",
    )
    parser.add_argument(
        "--collector-db",
        default=os.getenv("COLLECTOR_DB"),
        help="Path to the collector's buffer database (read-only)",
    )
    parser.add_argument("--once", action="store_true", help="Send one heartbeat and exit")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Collect and print a heartbeat without sending it",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
    )

    if not args.node_id:
        parser.error("--node-id is required (or set NODE_ID)")
    if not args.backend and not args.dry_run:
        parser.error("--backend is required (or set BACKEND_URL)")

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    log.info(
        "node heartbeat agent %s starting: node=%s backend=%s interval=%ss",
        VERSION,
        args.node_id,
        args.backend,
        args.interval,
    )

    # Prime the CPU delta so the first real heartbeat carries a usable value.
    safe(probe_cpu, {})

    if args.dry_run:
        time.sleep(1)
        print(json.dumps(build_heartbeat(args), indent=2, sort_keys=True))
        return 0

    failures = 0
    while not _shutdown:
        started = time.monotonic()

        payload = build_heartbeat(args)
        if send_heartbeat(args.backend, payload):
            failures = 0
        else:
            failures += 1
            if failures in (1, 5, 20) or failures % 60 == 0:
                log.warning("%d consecutive heartbeat failures", failures)

        if args.once:
            return 0

        elapsed = time.monotonic() - started
        # Sleep in short slices so SIGTERM is honoured promptly instead of
        # waiting out a full interval during a service restart.
        remaining = max(1.0, args.interval - elapsed)
        while remaining > 0 and not _shutdown:
            time.sleep(min(1.0, remaining))
            remaining -= 1.0

    return 0


if __name__ == "__main__":
    sys.exit(main())
