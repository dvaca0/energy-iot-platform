"""Diagnostics collection.

Read-only inspection of the node, gathered on demand for the portal and the
TUI.  Nothing here mutates state, and every collector degrades gracefully:
a node without a collector database, without ``iw``, or without a configured
backend still produces a complete report with the missing pieces marked
unavailable, because a diagnostics page that throws is useless exactly when it
is needed.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import Config
from .models import ProbeResult
from .nm import NetworkManager
from . import probes as probe_mod

log = logging.getLogger("netd.diagnostics")


def _run(argv: List[str], timeout: int = 10) -> str:
    """Run a read-only command and return its output, or an error marker."""
    try:
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return f"<unavailable: {exc}>"
    return (proc.stdout or proc.stderr or "").strip() or "<no output>"


class Diagnostics:
    """Gathers diagnostic information about the node."""

    def __init__(self, config: Config, nm: NetworkManager) -> None:
        self._config = config
        self._nm = nm

    # ------------------------------------------------------------------
    # networking
    # ------------------------------------------------------------------
    def routes(self) -> str:
        return _run(["ip", "route", "show"])

    def addresses(self) -> str:
        return _run(["ip", "-brief", "address", "show"])

    def interfaces(self) -> List[Dict[str, Any]]:
        return [i.to_dict() for i in self._nm.devices()]

    def dns_config(self) -> str:
        try:
            return Path("/etc/resolv.conf").read_text(encoding="utf-8").strip()
        except OSError as exc:
            return f"<unavailable: {exc}>"

    def connectivity_tests(self) -> List[Dict[str, Any]]:
        """Run the full probe suite once and return the results."""
        cfg = self._config
        timeout = cfg.timing.probe_timeout
        results: List[ProbeResult] = []

        route = probe_mod.primary_route()
        results.append(probe_mod.gateway_probe(route.gateway if route else None, timeout))
        results.append(probe_mod.dns_resolve(cfg.probes.dns_names, timeout))
        results.append(probe_mod.internet_probe(cfg.probes.internet_hosts, timeout))
        if cfg.probes.backend_url:
            results.append(probe_mod.backend_probe(cfg.probes.backend_url, cfg.probes.backend_timeout))
        else:
            results.append(ProbeResult("backend", False, "no backend configured"))
        if cfg.probes.shelly_host:
            results.append(probe_mod.shelly_probe(cfg.probes.shelly_host, timeout))
        else:
            results.append(ProbeResult("shelly", False, "no shelly configured"))
        return [r.to_dict() for r in results]

    # ------------------------------------------------------------------
    # system health
    # ------------------------------------------------------------------
    def system_health(self) -> Dict[str, Any]:
        """Disk, memory, CPU, temperature and uptime."""
        health: Dict[str, Any] = {
            "hostname": socket.gethostname(),
            "uptime_seconds": self._uptime_seconds(),
            "load_average": list(os.getloadavg()),
            "temperature_c": self._temperature(),
            "cpu_percent": self._cpu_percent(),
        }

        try:
            usage = shutil.disk_usage("/")
            health["disk"] = {
                "total_gb": round(usage.total / 1024**3, 2),
                "used_gb": round(usage.used / 1024**3, 2),
                "free_gb": round(usage.free / 1024**3, 2),
                "percent_used": round(usage.used / usage.total * 100, 1) if usage.total else 0.0,
            }
        except OSError as exc:
            health["disk"] = {"error": str(exc)}

        health["memory"] = self._memory()
        return health

    @staticmethod
    def _uptime_seconds() -> float:
        try:
            with open("/proc/uptime", "r", encoding="utf-8") as handle:
                return round(float(handle.read().split()[0]), 1)
        except (OSError, ValueError, IndexError):
            return 0.0

    @staticmethod
    def _temperature() -> Optional[float]:
        """SoC temperature in degrees Celsius."""
        for path in (
            "/sys/class/thermal/thermal_zone0/temp",
            "/sys/devices/virtual/thermal/thermal_zone0/temp",
        ):
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    return round(int(handle.read().strip()) / 1000.0, 1)
            except (OSError, ValueError):
                continue
        return None

    @staticmethod
    def _memory() -> Dict[str, Any]:
        try:
            info: Dict[str, int] = {}
            with open("/proc/meminfo", "r", encoding="utf-8") as handle:
                for line in handle:
                    key, _, rest = line.partition(":")
                    value = rest.strip().split(" ")[0]
                    try:
                        info[key] = int(value)
                    except ValueError:
                        continue
            total = info.get("MemTotal", 0)
            available = info.get("MemAvailable", 0)
            used = total - available
            return {
                "total_mb": round(total / 1024, 1),
                "available_mb": round(available / 1024, 1),
                "used_mb": round(used / 1024, 1),
                "percent_used": round(used / total * 100, 1) if total else 0.0,
            }
        except OSError as exc:
            return {"error": str(exc)}

    @staticmethod
    def _cpu_percent() -> Optional[float]:
        """Instantaneous CPU utilisation sampled over a short window."""
        def snapshot() -> Optional[tuple[int, int]]:
            try:
                with open("/proc/stat", "r", encoding="utf-8") as handle:
                    parts = handle.readline().split()
            except OSError:
                return None
            if len(parts) < 5 or parts[0] != "cpu":
                return None
            try:
                values = [int(x) for x in parts[1:]]
            except ValueError:
                return None
            idle = values[3] + (values[4] if len(values) > 4 else 0)
            return sum(values), idle

        first = snapshot()
        if first is None:
            return None
        time.sleep(0.15)
        second = snapshot()
        if second is None:
            return None
        total_delta = second[0] - first[0]
        idle_delta = second[1] - first[1]
        if total_delta <= 0:
            return None
        return round((1.0 - idle_delta / total_delta) * 100.0, 1)

    # ------------------------------------------------------------------
    # services and collector
    # ------------------------------------------------------------------
    def service_status(self, unit: str) -> Dict[str, Any]:
        """Systemd state of one unit."""
        result = _run(
            [
                "systemctl", "show", unit,
                "--property=LoadState,ActiveState,SubState,UnitFileState,ExecMainStartTimestamp,NRestarts",
                "--no-pager",
            ],
            timeout=10,
        )
        info: Dict[str, Any] = {"unit": unit}
        for line in result.splitlines():
            key, _, value = line.partition("=")
            if key:
                info[key] = value
        info["present"] = info.get("LoadState") == "loaded"
        info["running"] = info.get("ActiveState") == "active"
        return info

    def services(self) -> List[Dict[str, Any]]:
        return [self.service_status(u) for u in self._config.services.manageable]

    def collector_stats(self) -> Dict[str, Any]:
        """Buffered sample counts and last synchronisation, read-only.

        Opened with ``mode=ro`` so diagnostics can never interfere with the
        collector's own writes.
        """
        db_path = self._config.paths.collector_db
        stats: Dict[str, Any] = {
            "database": str(db_path),
            "present": db_path.is_file(),
            "buffered": None,
            "total": None,
            "last_sync": None,
            "last_sync_ok": None,
            "last_measurement": None,
        }
        if not stats["present"]:
            stats["error"] = "no collector database on this node"
            return stats

        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
            try:
                conn.execute("PRAGMA query_only = ON")
                cur = conn.execute("SELECT COUNT(*) FROM measurements WHERE sync_status = 0")
                stats["buffered"] = cur.fetchone()[0]
                cur = conn.execute("SELECT COUNT(*) FROM measurements")
                stats["total"] = cur.fetchone()[0]
                cur = conn.execute("SELECT MAX(captured_at) FROM measurements")
                stats["last_measurement"] = cur.fetchone()[0]
                cur = conn.execute(
                    "SELECT attempted_at, success, rows_confirmed, error_detail "
                    "FROM sync_log ORDER BY id DESC LIMIT 1"
                )
                row = cur.fetchone()
                if row:
                    stats["last_sync"] = row[0]
                    stats["last_sync_ok"] = bool(row[1])
                    stats["last_sync_rows"] = row[2]
                    stats["last_sync_error"] = row[3]
            finally:
                conn.close()
        except sqlite3.Error as exc:
            stats["error"] = f"could not read collector database: {exc}"
        return stats

    # ------------------------------------------------------------------
    # logs
    # ------------------------------------------------------------------
    def journal(
        self,
        units: Optional[List[str]] = None,
        lines: int = 100,
        since: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Recent journal entries for the given units, newest last."""
        argv = ["journalctl", "--no-pager", "-o", "json", "-n", str(max(1, min(lines, 2000)))]
        for unit in units or []:
            argv += ["-u", unit]
        if since:
            argv += ["--since", since]
        raw = _run(argv, timeout=20)
        entries: List[Dict[str, Any]] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            timestamp = record.get("__REALTIME_TIMESTAMP")
            try:
                when = time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime(int(timestamp) / 1_000_000)
                )
            except (TypeError, ValueError):
                when = ""
            entries.append(
                {
                    "time": when,
                    "unit": record.get("_SYSTEMD_UNIT") or record.get("SYSLOG_IDENTIFIER", ""),
                    "priority": record.get("PRIORITY", "6"),
                    "message": record.get("MESSAGE", ""),
                }
            )
        return entries

    def network_events(self, lines: int = 100) -> List[Dict[str, Any]]:
        """Networking history: the subsystem's own log plus NetworkManager."""
        return self.journal(
            ["energy-node-netd.service", "NetworkManager.service"], lines=lines
        )

    def collector_events(self, lines: int = 100) -> List[Dict[str, Any]]:
        return self.journal([self._config.services.collector], lines=lines)

    # ------------------------------------------------------------------
    def full_report(self) -> Dict[str, Any]:
        """Everything, for the diagnostics page."""
        return {
            "generated_at": time.time(),
            "node": {
                "id": self._config.node.id,
                "hostname": socket.gethostname(),
                "model": self._config.node.model,
            },
            "connectivity": self.connectivity_tests(),
            "interfaces": self.interfaces(),
            "routes": self.routes(),
            "addresses": self.addresses(),
            "dns": self.dns_config(),
            "health": self.system_health(),
            "services": self.services(),
            "collector": self.collector_stats(),
        }
