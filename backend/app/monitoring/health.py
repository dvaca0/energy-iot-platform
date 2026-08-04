"""Server-side health probing and the server rule set.

Split in two halves:

* :func:`collect_server_snapshot` gathers every server fact once per tick.
  Every probe is individually guarded — a probe that fails records ``None`` and
  a reason, and never propagates an exception into the tick.
* The ``@rule`` functions below turn that snapshot into findings.

Deliberate absences
-------------------
Several checks in the specification have no data source on this host, and are
registered as *unavailable* rather than faked:

``ssl.certificate_expiry``
    There is no TLS anywhere in this deployment. The backend serves plain HTTP
    on :8010, the frontend on :5174, and ``/etc/letsencrypt`` does not exist.
``network.tailscale``
    ``tailscale`` is not installed on the server.
``server.firewall``
    ``ufw status`` requires root and ``sudo`` needs a password here.
``server.package_updates``
    Reported when the apt metadata files exist; they are not maintained for a
    non-root user, so this frequently reports unavailable.

Each becomes a live check the moment its source exists, with no code change.
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import time
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from app.monitoring.rules import (
    Finding,
    RuleContext,
    Subsystem,
    rule,
    unavailable,
)
from app.monitoring.severity import Severity
from app.monitoring.storage import database_file_sizes

log = logging.getLogger("monitoring.health")

try:  # psutil is the primary source; /proc fallbacks cover its absence.
    import psutil
except ImportError:  # pragma: no cover - psutil is a declared dependency
    psutil = None  # type: ignore[assignment]


# --------------------------------------------------------------------------
# Low-level probes
# --------------------------------------------------------------------------

def _run(command: list[str], timeout: float = 5.0) -> tuple[int, str, str]:
    """Run a command, never raising.

    Returns ``(returncode, stdout, stderr)``. A missing binary or a timeout is
    reported as a non-zero return code with the reason in stderr, so callers
    handle every failure the same way.
    """
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return 127, "", f"{command[0]}: not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"{command[0]}: timed out after {timeout}s"
    except OSError as exc:
        return 1, "", str(exc)


def probe_cpu() -> dict[str, Any]:
    """CPU utilisation and per-mode breakdown.

    Uses a short blocking sample: ``psutil.cpu_percent`` without an interval
    returns the average since process start, which for a long-lived scheduler
    is meaningless. 0.5 s is enough to be representative without stalling the
    tick.
    """
    out: dict[str, Any] = {"percent": None, "iowait": None, "cores": os.cpu_count()}
    if psutil is None:
        return out

    try:
        out["percent"] = psutil.cpu_percent(interval=0.5)
        times = psutil.cpu_times_percent(interval=None)
        out["iowait"] = getattr(times, "iowait", None)
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
    return out


def probe_memory() -> dict[str, Any]:
    """RAM and swap utilisation."""
    out: dict[str, Any] = {}
    if psutil is None:
        return out
    try:
        virtual = psutil.virtual_memory()
        swap = psutil.swap_memory()
        out["percent"] = virtual.percent
        out["total_mb"] = round(virtual.total / 1024 / 1024, 1)
        out["available_mb"] = round(virtual.available / 1024 / 1024, 1)
        # A swap-less host reports total 0; percent would then be 0 and could
        # be mistaken for "healthy swap". Record the distinction explicitly.
        out["swap_present"] = swap.total > 0
        out["swap_percent"] = swap.percent if swap.total > 0 else None
        out["swap_total_mb"] = round(swap.total / 1024 / 1024, 1)
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
    return out


def probe_disks(mounts: Iterable[str]) -> dict[str, dict[str, Any]]:
    """Capacity for each configured mount point."""
    out: dict[str, dict[str, Any]] = {}
    for mount in mounts:
        try:
            usage = shutil.disk_usage(mount)
            out[mount] = {
                "percent": round(usage.used / usage.total * 100, 2),
                "free_gb": round(usage.free / 1024 ** 3, 2),
                "total_gb": round(usage.total / 1024 ** 3, 2),
            }
        except OSError as exc:
            out[mount] = {"error": str(exc)}
    return out


def probe_filesystem_readonly(mounts: Iterable[str]) -> dict[str, bool]:
    """Detect read-only mounts.

    A filesystem that has remounted read-only after an I/O error still serves
    reads, so the platform looks alive while every write silently fails. That
    is exactly the failure this catches.
    """
    out: dict[str, bool] = {}
    try:
        mount_info = Path("/proc/mounts").read_text().splitlines()
    except OSError:
        return out

    for mount in mounts:
        for line in mount_info:
            parts = line.split()
            if len(parts) >= 4 and parts[1] == mount:
                options = parts[3].split(",")
                out[mount] = "ro" in options
                break
    return out


def probe_load() -> dict[str, Any]:
    """Load average, absolute and normalised per core."""
    out: dict[str, Any] = {}
    try:
        one, five, fifteen = os.getloadavg()
        cores = os.cpu_count() or 1
        out.update(
            {
                "load_1": round(one, 2),
                "load_5": round(five, 2),
                "load_15": round(fifteen, 2),
                "per_core_1": round(one / cores, 2),
                "per_core_5": round(five / cores, 2),
                "cores": cores,
            }
        )
    except OSError as exc:
        out["error"] = str(exc)
    return out


def probe_temperature() -> dict[str, Any]:
    """Highest CPU/package temperature reported by the kernel.

    Many virtualised hosts expose no thermal zones at all; that is reported as
    unavailable rather than as 0 °C, which would read as suspiciously cold.
    """
    out: dict[str, Any] = {"celsius": None, "available": False}
    if psutil is None:
        return out
    try:
        sensors = psutil.sensors_temperatures()
    except Exception:  # noqa: BLE001
        return out

    hottest: float | None = None
    for entries in (sensors or {}).values():
        for entry in entries:
            if entry.current is None:
                continue
            hottest = entry.current if hottest is None else max(hottest, entry.current)

    if hottest is not None:
        out["celsius"] = round(hottest, 1)
        out["available"] = True
    return out


def probe_uptime() -> dict[str, Any]:
    """Host uptime and boot time.

    A boot time that moved since the previous snapshot means the host rebooted,
    which is how an unexpected restart is detected.
    """
    out: dict[str, Any] = {}
    if psutil is None:
        return out
    try:
        boot = psutil.boot_time()
        out["boot_time"] = datetime.utcfromtimestamp(boot).isoformat()
        out["boot_timestamp"] = boot
        out["uptime_seconds"] = round(time.time() - boot, 1)
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
    return out


def probe_services(units: Iterable[str]) -> dict[str, dict[str, Any]]:
    """State of each watched systemd unit."""
    out: dict[str, dict[str, Any]] = {}
    for unit in units:
        code, stdout, stderr = _run(["systemctl", "is-active", unit])
        active = stdout or ("unknown" if code == 127 else stderr or "unknown")
        entry: dict[str, Any] = {"active": active, "ok": active == "active"}

        if not entry["ok"]:
            # Only pay for the richer query when something looks wrong.
            _, props, _ = _run(
                [
                    "systemctl",
                    "show",
                    unit,
                    "-p",
                    "SubState,Result,NRestarts,ExecMainStartTimestamp",
                ]
            )
            for line in props.splitlines():
                if "=" in line:
                    key, _, value = line.partition("=")
                    entry[key.lower()] = value

        out[unit] = entry
    return out


def probe_failed_units() -> dict[str, Any]:
    """Any systemd unit in a failed state, not only the watched ones."""
    code, stdout, stderr = _run(
        ["systemctl", "list-units", "--state=failed", "--no-legend", "--no-pager"]
    )
    if code != 0:
        return {"available": False, "reason": stderr or f"exit {code}"}

    units = [line.split()[0] for line in stdout.splitlines() if line.strip()]
    return {"available": True, "failed": units, "count": len(units)}


def probe_api(base_url: str, timeout: float) -> dict[str, Any]:
    """Self-probe the backend's own health endpoint.

    Uses the real HTTP path rather than checking the systemd unit, because a
    process can be ``active`` while the application inside it is wedged and
    answering nothing.
    """
    import urllib.error
    import urllib.request

    url = base_url.rstrip("/") + "/health"
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read(2048).decode("utf-8", "replace")
            elapsed = time.perf_counter() - started
            return {
                "ok": 200 <= response.status < 300,
                "status_code": response.status,
                "latency_seconds": round(elapsed, 3),
                "body": body[:200],
            }
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "status_code": exc.code,
            "latency_seconds": round(time.perf_counter() - started, 3),
            "error": f"HTTP {exc.code}",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status_code": None,
            "latency_seconds": round(time.perf_counter() - started, 3),
            "error": str(exc),
        }


def probe_port(host: str, port: int, timeout: float = 3.0) -> bool:
    """True when a TCP connect succeeds."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def probe_internet(host: str) -> dict[str, Any]:
    """Outbound connectivity, measured by a TCP connect rather than ICMP.

    ICMP is frequently filtered on university networks, which would make a
    perfectly healthy link look dead. Port 443 reaching a well-known host is a
    better proxy for "the platform can talk to the outside world", which is
    what actually matters for notification delivery.
    """
    started = time.perf_counter()
    ok = probe_port(host, 443, timeout=4.0)
    return {
        "ok": ok,
        "host": host,
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
    }


def probe_dns(name: str) -> dict[str, Any]:
    """Resolve a name, timing the lookup."""
    started = time.perf_counter()
    try:
        socket.getaddrinfo(name, 443, proto=socket.IPPROTO_TCP)
        return {
            "ok": True,
            "name": name,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    except OSError as exc:
        return {"ok": False, "name": name, "error": str(exc)}


def probe_time_sync() -> dict[str, Any]:
    """NTP synchronisation state.

    Clock correctness is load-bearing here: every reading, heartbeat and alert
    is timestamped, and a drifting server clock corrupts every duration the
    monitoring system reports.
    """
    code, stdout, stderr = _run(["timedatectl", "show"])
    if code != 0:
        return {"available": False, "reason": stderr or f"exit {code}"}

    values = {}
    for line in stdout.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            values[key] = value

    return {
        "available": True,
        "synchronized": values.get("NTPSynchronized") == "yes",
        "ntp_service": values.get("NTP") == "yes",
        "timezone": values.get("Timezone"),
    }


def probe_reboot_required() -> dict[str, Any]:
    """Whether the kernel or a core library needs a restart to take effect."""
    marker = Path("/var/run/reboot-required")
    packages = Path("/var/run/reboot-required.pkgs")
    required = marker.exists()
    out: dict[str, Any] = {"required": required}
    if required and packages.exists():
        try:
            out["packages"] = sorted(set(packages.read_text().split()))
        except OSError:
            pass
    return out


def probe_oom_and_kernel() -> dict[str, Any]:
    """Recent OOM kills and kernel error indicators from the journal.

    Reads only the current boot, so an OOM from three reboots ago does not keep
    firing. Requires journal read access; without it, reports unavailable.
    """
    code, stdout, stderr = _run(
        ["journalctl", "-k", "-b", "-p", "err", "--no-pager", "-n", "200"],
        timeout=10.0,
    )
    if code != 0:
        return {"available": False, "reason": stderr or f"exit {code}"}

    lines = stdout.splitlines()
    oom = [line for line in lines if "Out of memory" in line or "oom-kill" in line.lower()]
    panic = [line for line in lines if "Kernel panic" in line or "BUG:" in line]
    return {
        "available": True,
        "error_lines": len(lines),
        "oom_events": len(oom),
        "oom_samples": oom[-3:],
        "panic_events": len(panic),
        "panic_samples": panic[-3:],
    }


def probe_tailscale() -> dict[str, Any]:
    """Tailscale state, when the binary is present."""
    if shutil.which("tailscale") is None:
        return {"available": False, "reason": "tailscale is not installed on this host"}

    code, stdout, stderr = _run(["tailscale", "status", "--json"], timeout=8.0)
    if code != 0:
        return {"available": False, "reason": stderr or f"exit {code}"}

    import json

    try:
        data = json.loads(stdout)
    except ValueError as exc:
        return {"available": False, "reason": f"unparseable output: {exc}"}

    return {
        "available": True,
        "backend_state": data.get("BackendState"),
        "ok": data.get("BackendState") == "Running",
        "peers": len(data.get("Peer") or {}),
    }


def probe_firewall() -> dict[str, Any]:
    """Firewall state. Requires root on this host, so usually unavailable."""
    if shutil.which("ufw") is None:
        return {"available": False, "reason": "ufw is not installed"}
    code, stdout, stderr = _run(["ufw", "status"])
    if code != 0:
        return {
            "available": False,
            "reason": (stderr or stdout or f"exit {code}")[:200],
        }
    return {"available": True, "active": "Status: active" in stdout, "raw": stdout[:400]}


def probe_certificates() -> dict[str, Any]:
    """TLS certificate expiry.

    This deployment terminates no TLS: no nginx, no Let's Encrypt directory,
    both services serve plain HTTP. Reported as unavailable rather than as a
    passing check, so the gap stays visible.
    """
    letsencrypt = Path("/etc/letsencrypt/live")
    if not letsencrypt.exists():
        return {
            "available": False,
            "reason": "no TLS on this deployment (no /etc/letsencrypt, services serve plain HTTP)",
        }

    certs: list[dict[str, Any]] = []
    for cert_dir in letsencrypt.iterdir():
        cert_file = cert_dir / "fullchain.pem"
        if not cert_file.exists():
            continue
        code, stdout, _ = _run(
            ["openssl", "x509", "-enddate", "-noout", "-in", str(cert_file)]
        )
        if code == 0 and "=" in stdout:
            certs.append({"name": cert_dir.name, "not_after": stdout.split("=", 1)[1]})
    return {"available": True, "certificates": certs}


def probe_database() -> dict[str, Any]:
    """Database size, WAL size and responsiveness.

    The probe query is deliberately trivial. Its purpose is to measure whether
    the database *answers*, and how quickly — a slow response here means lock
    contention or I/O trouble, not an expensive query.
    """
    out: dict[str, Any] = dict(database_file_sizes())

    from sqlalchemy import text

    from app.monitoring.storage import session_scope

    started = time.perf_counter()
    try:
        with session_scope() as session:
            session.execute(text("SELECT 1")).scalar()
        out["ok"] = True
        out["query_seconds"] = round(time.perf_counter() - started, 4)
    except Exception as exc:  # noqa: BLE001
        out["ok"] = False
        out["query_seconds"] = round(time.perf_counter() - started, 4)
        out["error"] = str(exc)

    try:
        with session_scope() as session:
            result = session.execute(text("PRAGMA integrity_check")).scalar()
        out["integrity"] = result
        out["integrity_ok"] = result == "ok"
    except Exception as exc:  # noqa: BLE001
        out["integrity"] = None
        out["integrity_ok"] = None
        out["integrity_error"] = str(exc)

    return out


def collect_server_snapshot(config) -> dict[str, Any]:
    """Gather every server fact for one evaluation tick.

    Each probe is independently guarded so a single failure degrades one field
    instead of blinding the whole tick.
    """
    snapshot: dict[str, Any] = {"collected_at": datetime.utcnow().isoformat()}

    probes: dict[str, Any] = {
        "cpu": lambda: probe_cpu(),
        "memory": lambda: probe_memory(),
        "disks": lambda: probe_disks(config.watched_mounts),
        "readonly": lambda: probe_filesystem_readonly(config.watched_mounts),
        "load": lambda: probe_load(),
        "temperature": lambda: probe_temperature(),
        "uptime": lambda: probe_uptime(),
        "services": lambda: probe_services(config.watched_services),
        "failed_units": lambda: probe_failed_units(),
        "api": lambda: probe_api(config.api_base_url, config.server.api_latency_critical + 5),
        "internet": lambda: probe_internet(config.internet_probe_host),
        "dns": lambda: probe_dns(config.dns_probe_name),
        "time_sync": lambda: probe_time_sync(),
        "reboot": lambda: probe_reboot_required(),
        "kernel": lambda: probe_oom_and_kernel(),
        "tailscale": lambda: probe_tailscale(),
        "firewall": lambda: probe_firewall(),
        "certificates": lambda: probe_certificates(),
        "database": lambda: probe_database(),
    }

    for name, probe in probes.items():
        try:
            snapshot[name] = probe()
        except Exception as exc:  # noqa: BLE001
            log.exception("Server probe %s failed", name)
            snapshot[name] = {"error": str(exc)}

    snapshot["hostname"] = socket.gethostname()
    return snapshot


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------

_SERVER_COMMANDS = ["systemctl status energy-platform-backend.service", "df -h", "free -m"]


@rule("server.cpu", Subsystem.SERVER, "Server CPU utilisation")
def check_cpu(ctx: RuleContext) -> Iterable[Finding]:
    cpu = ctx.server.get("cpu") or {}
    value = cpu.get("percent")
    if value is None:
        return [
            unavailable(
                "server.cpu", Subsystem.SERVER, "Server CPU", "psutil unavailable"
            )
        ]

    severity = ctx.threshold_severity(
        value, ctx.config.server.cpu_warning, ctx.config.server.cpu_critical
    )
    if severity is Severity.OK:
        return []

    return [
        Finding(
            rule_id="server.cpu",
            subsystem=Subsystem.SERVER,
            severity=severity,
            title="Server CPU utilisation is high",
            metric="cpu_percent",
            current_value=f"{value:.1f}%",
            expected_value=f"< {ctx.config.server.cpu_warning:.0f}%",
            hostname=ctx.server.get("hostname"),
            suggested_causes=[
                "A report or ML job running longer than expected",
                "Another tenant on this host (a second backend and OpenWebUI share it)",
                "A request loop or a runaway worker",
            ],
            suggested_commands=["top -b -n1 | head -20", "ps aux --sort=-%cpu | head -10"],
            suggested_actions=["Identify the top consumer before restarting anything."],
            context={"cores": cpu.get("cores"), "iowait": cpu.get("iowait")},
        )
    ]


@rule("server.memory", Subsystem.SERVER, "Server RAM utilisation")
def check_memory(ctx: RuleContext) -> Iterable[Finding]:
    memory = ctx.server.get("memory") or {}
    value = memory.get("percent")
    if value is None:
        return [
            unavailable(
                "server.memory", Subsystem.SERVER, "Server memory", "psutil unavailable"
            )
        ]

    severity = ctx.threshold_severity(
        value, ctx.config.server.memory_warning, ctx.config.server.memory_critical
    )
    if severity is Severity.OK:
        return []

    return [
        Finding(
            rule_id="server.memory",
            subsystem=Subsystem.SERVER,
            severity=severity,
            title="Server memory utilisation is high",
            metric="memory_percent",
            current_value=f"{value:.1f}%",
            expected_value=f"< {ctx.config.server.memory_warning:.0f}%",
            hostname=ctx.server.get("hostname"),
            suggested_causes=[
                "A pandas or scikit-learn job holding a large frame",
                "Gunicorn workers grown large and never recycled",
                "The other tenants on this host",
            ],
            suggested_commands=["free -m", "ps aux --sort=-%mem | head -10"],
            suggested_actions=[
                "If gunicorn is the top consumer, a graceful reload frees it: "
                "kill -HUP $(systemctl show -p MainPID --value energy-platform-backend.service)"
            ],
            context={"available_mb": memory.get("available_mb")},
        )
    ]


@rule("server.swap", Subsystem.SERVER, "Server swap utilisation")
def check_swap(ctx: RuleContext) -> Iterable[Finding]:
    memory = ctx.server.get("memory") or {}
    if not memory.get("swap_present"):
        return [
            unavailable(
                "server.swap",
                Subsystem.SERVER,
                "Server swap",
                "no swap configured on this host",
            )
        ]

    value = memory.get("swap_percent")
    severity = ctx.threshold_severity(
        value, ctx.config.server.swap_warning, ctx.config.server.swap_critical
    )
    if severity is Severity.OK:
        return []

    return [
        Finding(
            rule_id="server.swap",
            subsystem=Subsystem.SERVER,
            severity=severity,
            title="Server is swapping heavily",
            metric="swap_percent",
            current_value=f"{value:.1f}%",
            expected_value=f"< {ctx.config.server.swap_warning:.0f}%",
            hostname=ctx.server.get("hostname"),
            suggested_causes=["Memory pressure forcing pages to disk"],
            suggested_commands=["free -m", "vmstat 1 5"],
            suggested_actions=[
                "Sustained swapping makes SQLite writes slow and can cascade into "
                "ingest timeouts. Free memory before it reaches that point."
            ],
        )
    ]


@rule("server.disk", Subsystem.SERVER, "Filesystem capacity")
def check_disk(ctx: RuleContext) -> Iterable[Finding]:
    findings: list[Finding] = []
    for mount, usage in (ctx.server.get("disks") or {}).items():
        if "error" in usage:
            findings.append(
                unavailable(
                    "server.disk",
                    Subsystem.SERVER,
                    f"Filesystem {mount}",
                    usage["error"],
                    target=mount,
                )
            )
            continue

        value = usage.get("percent")
        severity = ctx.threshold_severity(
            value, ctx.config.server.disk_warning, ctx.config.server.disk_critical
        )
        if severity is Severity.OK:
            continue

        findings.append(
            Finding(
                rule_id="server.disk",
                subsystem=Subsystem.SERVER,
                severity=severity,
                title=f"Filesystem {mount} is filling up",
                target=mount,
                metric="disk_percent",
                current_value=f"{value:.1f}% used, {usage.get('free_gb')} GB free",
                expected_value=f"< {ctx.config.server.disk_warning:.0f}% used",
                hostname=ctx.server.get("hostname"),
                suggested_causes=[
                    "Database and WAL growth",
                    "Generated reports accumulating in backend/generated_reports",
                    "Timestamped backups accumulating in backend/backups",
                    "Journal logs",
                ],
                suggested_commands=[
                    f"du -xh {mount} --max-depth=2 2>/dev/null | sort -rh | head -20",
                    "du -sh /home/manager/energy-platform/backend/backups",
                    "journalctl --disk-usage",
                ],
                suggested_actions=[
                    "A full disk stops SQLite writes and silently ends ingestion. "
                    "Clear space before it reaches 100%.",
                ],
                context=dict(usage),
            )
        )
    return findings


@rule("server.filesystem_readonly", Subsystem.SERVER, "Read-only filesystem detection")
def check_readonly(ctx: RuleContext) -> Iterable[Finding]:
    findings: list[Finding] = []
    for mount, is_ro in (ctx.server.get("readonly") or {}).items():
        if not is_ro:
            continue
        findings.append(
            Finding(
                rule_id="server.filesystem_readonly",
                subsystem=Subsystem.SERVER,
                severity=Severity.EMERGENCY,
                title=f"Filesystem {mount} is mounted read-only",
                target=mount,
                metric="mount_options",
                current_value="ro",
                expected_value="rw",
                hostname=ctx.server.get("hostname"),
                suggested_causes=[
                    "The kernel remounted read-only after an I/O error",
                    "Underlying storage failure",
                ],
                suggested_commands=["dmesg | tail -50", "mount | grep ' / '"],
                suggested_actions=[
                    "Every write is failing right now, including all ingestion. "
                    "Check dmesg for the I/O error that triggered the remount.",
                ],
            )
        )
    return findings


@rule("server.load", Subsystem.SERVER, "Load average per core")
def check_load(ctx: RuleContext) -> Iterable[Finding]:
    load = ctx.server.get("load") or {}
    value = load.get("per_core_5")
    if value is None:
        return []

    severity = ctx.threshold_severity(
        value, ctx.config.server.load_warning, ctx.config.server.load_critical
    )
    if severity is Severity.OK:
        return []

    return [
        Finding(
            rule_id="server.load",
            subsystem=Subsystem.SERVER,
            severity=severity,
            title="Server load average is elevated",
            metric="load_per_core_5m",
            current_value=f"{value:.2f} per core ({load.get('load_5')} over {load.get('cores')} cores)",
            expected_value=f"< {ctx.config.server.load_warning:.1f} per core",
            hostname=ctx.server.get("hostname"),
            suggested_causes=["CPU saturation", "I/O wait from disk pressure"],
            suggested_commands=["uptime", "top -b -n1 | head -15"],
            suggested_actions=["Correlate with CPU and iowait to tell compute from I/O."],
        )
    ]


@rule("server.iowait", Subsystem.SERVER, "I/O wait")
def check_iowait(ctx: RuleContext) -> Iterable[Finding]:
    value = (ctx.server.get("cpu") or {}).get("iowait")
    if value is None:
        return []

    severity = ctx.threshold_severity(
        value, ctx.config.server.iowait_warning, ctx.config.server.iowait_critical
    )
    if severity is Severity.OK:
        return []

    return [
        Finding(
            rule_id="server.iowait",
            subsystem=Subsystem.SERVER,
            severity=severity,
            title="High I/O wait",
            metric="iowait_percent",
            current_value=f"{value:.1f}%",
            expected_value=f"< {ctx.config.server.iowait_warning:.0f}%",
            hostname=ctx.server.get("hostname"),
            suggested_causes=[
                "SQLite checkpointing a large WAL",
                "A backup or report generation running",
                "Storage contention with the other tenants on this host",
            ],
            suggested_commands=["iostat -x 1 5", "iotop -b -n2 2>/dev/null | head -20"],
            suggested_actions=["Sustained I/O wait slows every write, including ingest."],
        )
    ]


@rule("server.temperature", Subsystem.SERVER, "Server temperature")
def check_temperature(ctx: RuleContext) -> Iterable[Finding]:
    temp = ctx.server.get("temperature") or {}
    if not temp.get("available"):
        return [
            unavailable(
                "server.temperature",
                Subsystem.SERVER,
                "Server temperature",
                "no thermal zones exposed (virtualised host)",
            )
        ]

    value = temp.get("celsius")
    severity = ctx.threshold_severity(
        value,
        ctx.config.server.temperature_warning_c,
        ctx.config.server.temperature_critical_c,
    )
    if severity is Severity.OK:
        return []

    return [
        Finding(
            rule_id="server.temperature",
            subsystem=Subsystem.SERVER,
            severity=severity,
            title="Server temperature is high",
            metric="temperature_c",
            current_value=f"{value:.1f} °C",
            expected_value=f"< {ctx.config.server.temperature_warning_c:.0f} °C",
            hostname=ctx.server.get("hostname"),
            suggested_commands=["sensors 2>/dev/null || cat /sys/class/thermal/thermal_zone*/temp"],
            suggested_actions=["Check cooling and ambient temperature."],
        )
    ]


@rule("server.services", Subsystem.SERVER, "Watched systemd units")
def check_services(ctx: RuleContext) -> Iterable[Finding]:
    findings: list[Finding] = []
    for unit, state in (ctx.server.get("services") or {}).items():
        if state.get("ok"):
            continue
        if state.get("active") == "unknown":
            findings.append(
                unavailable(
                    "server.services",
                    Subsystem.SERVER,
                    f"Service {unit}",
                    "systemctl unavailable",
                    target=unit,
                )
            )
            continue

        is_backend = "backend" in unit
        findings.append(
            Finding(
                rule_id="server.services",
                subsystem=Subsystem.BACKEND if is_backend else Subsystem.FRONTEND,
                severity=Severity.CRITICAL,
                title=f"Service {unit} is not running",
                target=unit,
                metric="systemd_state",
                current_value=str(state.get("active")),
                expected_value="active",
                hostname=ctx.server.get("hostname"),
                related_services=[unit],
                suggested_causes=[
                    "The process crashed and exhausted its restart budget",
                    "A syntax or import error introduced by a recent code change",
                    "A port conflict",
                ],
                suggested_commands=[
                    f"systemctl status {unit}",
                    f"journalctl -u {unit} -n 100 --no-pager",
                ],
                suggested_actions=[
                    "The platform is down for users while this unit is inactive. "
                    "Read the journal before restarting, so the cause is not lost.",
                ],
                context=dict(state),
            )
        )
    return findings


@rule("server.failed_units", Subsystem.SERVER, "Any failed systemd unit")
def check_failed_units(ctx: RuleContext) -> Iterable[Finding]:
    info = ctx.server.get("failed_units") or {}
    if not info.get("available"):
        return [
            unavailable(
                "server.failed_units",
                Subsystem.SERVER,
                "Failed systemd units",
                info.get("reason", "unavailable"),
            )
        ]

    failed = info.get("failed") or []
    if not failed:
        return []

    return [
        Finding(
            rule_id="server.failed_units",
            subsystem=Subsystem.SERVER,
            severity=Severity.WARNING,
            title=f"{len(failed)} systemd unit(s) in failed state",
            metric="failed_units",
            current_value=", ".join(failed[:5]),
            expected_value="none",
            hostname=ctx.server.get("hostname"),
            suggested_commands=["systemctl --failed", "journalctl -p err -b --no-pager -n 50"],
            suggested_actions=["Not necessarily platform-affecting, but worth clearing."],
            context={"units": failed},
        )
    ]


@rule("backend.api", Subsystem.BACKEND, "Backend API reachability and latency")
def check_api(ctx: RuleContext) -> Iterable[Finding]:
    api = ctx.server.get("api") or {}

    if not api.get("ok"):
        return [
            Finding(
                rule_id="backend.api",
                subsystem=Subsystem.BACKEND,
                severity=Severity.CRITICAL,
                title="Backend API is not responding",
                metric="http_health",
                current_value=str(api.get("error") or api.get("status_code")),
                expected_value="HTTP 200",
                hostname=ctx.server.get("hostname"),
                related_services=["energy-platform-backend.service"],
                suggested_causes=[
                    "Gunicorn worker wedged or crashed",
                    "The single worker is blocked on a long request",
                    "A database lock stalling every request",
                ],
                suggested_commands=[
                    "systemctl status energy-platform-backend.service",
                    "journalctl -u energy-platform-backend.service -n 100 --no-pager",
                    f"curl -sS -m 5 {ctx.config.api_base_url}/health",
                ],
                suggested_actions=[
                    "Every node is failing to deliver data while this is down; they "
                    "buffer locally, so recovery should replay rather than lose data.",
                    "Graceful reload: kill -HUP $(systemctl show -p MainPID --value "
                    "energy-platform-backend.service)",
                ],
                context=dict(api),
            )
        ]

    latency = api.get("latency_seconds")
    severity = ctx.threshold_severity(
        latency, ctx.config.server.api_latency_warning, ctx.config.server.api_latency_critical
    )
    if severity is Severity.OK:
        return []

    return [
        Finding(
            rule_id="backend.api_latency",
            subsystem=Subsystem.BACKEND,
            severity=severity,
            title="Backend API is slow",
            metric="api_latency_seconds",
            current_value=f"{latency:.2f}s",
            expected_value=f"< {ctx.config.server.api_latency_warning:.1f}s",
            hostname=ctx.server.get("hostname"),
            suggested_causes=[
                "The backend runs a single gunicorn worker; one slow request blocks all others",
                "Database lock contention",
            ],
            suggested_commands=["journalctl -u energy-platform-backend.service -n 50 --no-pager"],
            suggested_actions=["Check for a long-running report or ML request."],
        )
    ]


@rule("database.health", Subsystem.DATABASE, "Database responsiveness, size and integrity")
def check_database(ctx: RuleContext) -> Iterable[Finding]:
    database = ctx.server.get("database") or {}
    findings: list[Finding] = []

    if not database.get("ok"):
        return [
            Finding(
                rule_id="database.offline",
                subsystem=Subsystem.DATABASE,
                severity=Severity.EMERGENCY,
                title="Database is not answering",
                metric="probe_query",
                current_value=str(database.get("error")),
                expected_value="SELECT 1 returns immediately",
                hostname=ctx.server.get("hostname"),
                suggested_causes=[
                    "Database file missing, moved or permission-denied",
                    "Disk full",
                    "Filesystem remounted read-only",
                ],
                suggested_commands=[
                    "ls -la /home/manager/energy-platform/backend/energy_platform.db*",
                    "df -h /",
                ],
                suggested_actions=[
                    "Nothing is being stored while this is true. Restore from the newest "
                    "backup in backend/backups only after establishing the cause.",
                ],
                context=dict(database),
            )
        ]

    if database.get("integrity_ok") is False:
        findings.append(
            Finding(
                rule_id="database.corruption",
                subsystem=Subsystem.DATABASE,
                severity=Severity.EMERGENCY,
                title="Database integrity check failed",
                metric="integrity_check",
                current_value=str(database.get("integrity"))[:200],
                expected_value="ok",
                hostname=ctx.server.get("hostname"),
                suggested_causes=[
                    "Storage-level corruption",
                    "An unclean shutdown during a write",
                ],
                suggested_commands=[
                    "sqlite3 energy_platform.db 'PRAGMA integrity_check'",
                    "ls -la /home/manager/energy-platform/backend/backups/",
                ],
                suggested_actions=[
                    "Stop writing before anything else. Take a copy of the current file, "
                    "then restore the newest known-good backup.",
                ],
            )
        )

    query_seconds = database.get("query_seconds")
    severity = ctx.threshold_severity(
        query_seconds,
        ctx.config.database.query_warning_seconds,
        ctx.config.database.query_critical_seconds,
    )
    if severity is not Severity.OK:
        findings.append(
            Finding(
                rule_id="database.slow",
                subsystem=Subsystem.DATABASE,
                severity=severity,
                title="Database is responding slowly",
                metric="probe_query_seconds",
                current_value=f"{query_seconds:.3f}s",
                expected_value=f"< {ctx.config.database.query_warning_seconds}s",
                hostname=ctx.server.get("hostname"),
                suggested_causes=[
                    "Write lock held by a long transaction (SQLite allows one writer)",
                    "Disk I/O saturation",
                ],
                suggested_commands=["iostat -x 1 3"],
                suggested_actions=["A trivial query taking this long means contention, not query cost."],
            )
        )

    size_mb = database.get("db_mb")
    severity = ctx.threshold_severity(
        size_mb, ctx.config.database.size_warning_mb, ctx.config.database.size_critical_mb
    )
    if severity is not Severity.OK:
        findings.append(
            Finding(
                rule_id="database.size",
                subsystem=Subsystem.DATABASE,
                severity=severity,
                title="Database file is large",
                metric="db_size_mb",
                current_value=f"{size_mb:.0f} MB",
                expected_value=f"< {ctx.config.database.size_warning_mb:.0f} MB",
                hostname=ctx.server.get("hostname"),
                suggested_actions=[
                    "Readings are never deleted by policy; plan capacity rather than pruning.",
                ],
            )
        )

    wal_mb = database.get("wal_mb")
    severity = ctx.threshold_severity(
        wal_mb, ctx.config.database.wal_warning_mb, ctx.config.database.wal_critical_mb
    )
    if severity is not Severity.OK:
        findings.append(
            Finding(
                rule_id="database.wal",
                subsystem=Subsystem.DATABASE,
                severity=severity,
                title="Write-ahead log is not checkpointing",
                metric="wal_size_mb",
                current_value=f"{wal_mb:.0f} MB",
                expected_value=f"< {ctx.config.database.wal_warning_mb:.0f} MB",
                hostname=ctx.server.get("hostname"),
                suggested_causes=[
                    "A long-lived read transaction preventing checkpoint",
                    "Continuous writes leaving no checkpoint window",
                ],
                suggested_commands=[
                    "ls -la /home/manager/energy-platform/backend/energy_platform.db-wal",
                    "sqlite3 energy_platform.db 'PRAGMA wal_checkpoint(TRUNCATE)'",
                ],
                suggested_actions=[
                    "An unbounded WAL eventually consumes the disk and is a common cause "
                    "of sudden capacity loss.",
                ],
            )
        )

    return findings


@rule("network.internet", Subsystem.NETWORK, "Outbound internet connectivity")
def check_internet(ctx: RuleContext) -> Iterable[Finding]:
    internet = ctx.server.get("internet") or {}
    if internet.get("ok"):
        return []

    return [
        Finding(
            rule_id="network.internet",
            subsystem=Subsystem.NETWORK,
            severity=Severity.ERROR,
            title="Server has no outbound internet connectivity",
            metric="tcp_443",
            current_value=f"cannot reach {internet.get('host')}",
            expected_value="reachable",
            hostname=ctx.server.get("hostname"),
            suggested_causes=["Upstream link down", "Egress filtering changed"],
            suggested_commands=[
                f"ping -c3 {ctx.config.internet_probe_host}",
                "ip route",
                "curl -sS -m 5 https://api.telegram.org",
            ],
            suggested_actions=[
                "Alert delivery is affected: notifications will queue in the outbox "
                "and be retried automatically once connectivity returns.",
            ],
        )
    ]


@rule("network.dns", Subsystem.NETWORK, "DNS resolution")
def check_dns(ctx: RuleContext) -> Iterable[Finding]:
    dns = ctx.server.get("dns") or {}
    if dns.get("ok"):
        return []

    return [
        Finding(
            rule_id="network.dns",
            subsystem=Subsystem.NETWORK,
            severity=Severity.ERROR,
            title="DNS resolution is failing",
            metric="getaddrinfo",
            current_value=str(dns.get("error"))[:200],
            expected_value=f"{dns.get('name')} resolves",
            hostname=ctx.server.get("hostname"),
            suggested_commands=["resolvectl status", f"dig {ctx.config.dns_probe_name}"],
            suggested_actions=["Telegram delivery needs DNS; messages queue until it recovers."],
        )
    ]


@rule("server.time_sync", Subsystem.SERVER, "Clock synchronisation")
def check_time_sync(ctx: RuleContext) -> Iterable[Finding]:
    sync = ctx.server.get("time_sync") or {}
    if not sync.get("available"):
        return [
            unavailable(
                "server.time_sync",
                Subsystem.SERVER,
                "Clock synchronisation",
                sync.get("reason", "timedatectl unavailable"),
            )
        ]
    if sync.get("synchronized"):
        return []

    return [
        Finding(
            rule_id="server.time_sync",
            subsystem=Subsystem.SERVER,
            severity=Severity.WARNING,
            title="Server clock is not NTP-synchronised",
            metric="ntp_synchronized",
            current_value="no",
            expected_value="yes",
            hostname=ctx.server.get("hostname"),
            suggested_commands=["timedatectl status", "systemctl status systemd-timesyncd"],
            suggested_actions=[
                "Every reading, heartbeat and alert duration is timestamped against this "
                "clock. Drift corrupts all of them, and node clock-drift detection "
                "compares against it.",
            ],
        )
    ]


@rule("server.reboot_required", Subsystem.SERVER, "Pending reboot")
def check_reboot(ctx: RuleContext) -> Iterable[Finding]:
    reboot = ctx.server.get("reboot") or {}
    if not reboot.get("required"):
        return []

    return [
        Finding(
            rule_id="server.reboot_required",
            subsystem=Subsystem.SERVER,
            severity=Severity.INFO,
            title="Server requires a reboot",
            metric="reboot_required",
            current_value="yes",
            expected_value="no",
            hostname=ctx.server.get("hostname"),
            suggested_commands=["cat /var/run/reboot-required.pkgs"],
            suggested_actions=["Schedule a window; a reboot interrupts ingestion briefly."],
            context={"packages": reboot.get("packages")},
        )
    ]


@rule("server.kernel", Subsystem.SERVER, "OOM kills and kernel errors")
def check_kernel(ctx: RuleContext) -> Iterable[Finding]:
    kernel = ctx.server.get("kernel") or {}
    if not kernel.get("available"):
        return [
            unavailable(
                "server.kernel",
                Subsystem.SERVER,
                "Kernel error scan",
                kernel.get("reason", "journal unreadable"),
            )
        ]

    findings: list[Finding] = []

    if kernel.get("oom_events"):
        findings.append(
            Finding(
                rule_id="server.oom",
                subsystem=Subsystem.SERVER,
                severity=Severity.CRITICAL,
                title="Out-of-memory kills detected this boot",
                metric="oom_events",
                current_value=str(kernel["oom_events"]),
                expected_value="0",
                hostname=ctx.server.get("hostname"),
                suggested_commands=["journalctl -k -b | grep -i 'out of memory'"],
                suggested_actions=[
                    "The kernel killed a process to reclaim memory. Confirm it was not "
                    "the backend or the monitoring service.",
                ],
                context={"samples": kernel.get("oom_samples")},
            )
        )

    if kernel.get("panic_events"):
        findings.append(
            Finding(
                rule_id="server.kernel_errors",
                subsystem=Subsystem.SERVER,
                severity=Severity.ERROR,
                title="Kernel BUG or panic indicators in the journal",
                metric="panic_events",
                current_value=str(kernel["panic_events"]),
                expected_value="0",
                hostname=ctx.server.get("hostname"),
                suggested_commands=["journalctl -k -b -p err --no-pager | tail -50"],
                context={"samples": kernel.get("panic_samples")},
            )
        )

    return findings


@rule("network.tailscale", Subsystem.NETWORK, "Tailscale VPN state")
def check_tailscale(ctx: RuleContext) -> Iterable[Finding]:
    tailscale = ctx.server.get("tailscale") or {}
    if not tailscale.get("available"):
        return [
            unavailable(
                "network.tailscale",
                Subsystem.NETWORK,
                "Tailscale",
                tailscale.get("reason", "unavailable"),
            )
        ]
    if tailscale.get("ok"):
        return []

    return [
        Finding(
            rule_id="network.tailscale",
            subsystem=Subsystem.NETWORK,
            severity=Severity.ERROR,
            title="Tailscale is not running",
            metric="backend_state",
            current_value=str(tailscale.get("backend_state")),
            expected_value="Running",
            hostname=ctx.server.get("hostname"),
            suggested_commands=["tailscale status", "systemctl status tailscaled"],
            suggested_actions=["Node addresses on the tailnet are unreachable while this is down."],
        )
    ]


@rule("server.firewall", Subsystem.SECURITY, "Firewall state")
def check_firewall(ctx: RuleContext) -> Iterable[Finding]:
    firewall = ctx.server.get("firewall") or {}
    if not firewall.get("available"):
        return [
            unavailable(
                "server.firewall",
                Subsystem.SECURITY,
                "Firewall",
                firewall.get("reason", "requires root"),
            )
        ]
    if firewall.get("active"):
        return []

    return [
        Finding(
            rule_id="server.firewall",
            subsystem=Subsystem.SECURITY,
            severity=Severity.WARNING,
            title="Firewall is inactive",
            metric="ufw_status",
            current_value="inactive",
            expected_value="active",
            hostname=ctx.server.get("hostname"),
            suggested_commands=["sudo ufw status verbose"],
        )
    ]


@rule("security.certificates", Subsystem.SECURITY, "TLS certificate expiry")
def check_certificates(ctx: RuleContext) -> Iterable[Finding]:
    certificates = ctx.server.get("certificates") or {}
    if not certificates.get("available"):
        return [
            unavailable(
                "security.certificates",
                Subsystem.SECURITY,
                "TLS certificates",
                certificates.get("reason", "no TLS configured"),
            )
        ]

    # With a real certificate store present, expiry parsing becomes meaningful.
    # Until then this branch is unreachable on this deployment.
    findings: list[Finding] = []
    for cert in certificates.get("certificates") or []:
        findings.append(
            Finding(
                rule_id="security.certificates",
                subsystem=Subsystem.SECURITY,
                severity=Severity.INFO,
                title=f"Certificate {cert['name']} expiry",
                target=cert["name"],
                metric="not_after",
                current_value=cert.get("not_after"),
                expected_value="> 30 days remaining",
            )
        )
    return findings


__all__ = ["collect_server_snapshot"]
