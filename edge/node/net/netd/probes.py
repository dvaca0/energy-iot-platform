"""Connectivity probes.

Each probe answers exactly one question and returns a :class:`ProbeResult`.
They are intentionally independent so a fault can be localised: a node that
resolves DNS but cannot reach the backend is a different problem from a node
that has lost its default gateway, and an operator standing in front of the
portal needs to be told which one it is.

All probes are bounded in time and never raise.
"""

from __future__ import annotations

import logging
import re
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from .models import ProbeResult

log = logging.getLogger("netd.probes")

_DEFAULT_ROUTE_RE = re.compile(
    r"^default\s+via\s+(?P<gw>\S+)\s+dev\s+(?P<dev>\S+).*?(?:metric\s+(?P<metric>\d+))?$"
)


@dataclass(frozen=True)
class DefaultRoute:
    """A default route as reported by the kernel."""

    gateway: str
    device: str
    metric: int = 0


def default_routes(timeout: int = 5) -> List[DefaultRoute]:
    """Return all IPv4 default routes, lowest metric (most preferred) first."""
    try:
        proc = subprocess.run(
            ["ip", "-4", "route", "show", "default"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if proc.returncode != 0:
        return []

    routes: List[DefaultRoute] = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        match = _DEFAULT_ROUTE_RE.match(line)
        if not match:
            continue
        metric_raw = match.group("metric")
        routes.append(
            DefaultRoute(
                gateway=match.group("gw"),
                device=match.group("dev"),
                metric=int(metric_raw) if metric_raw else 0,
            )
        )
    return sorted(routes, key=lambda r: r.metric)


def primary_route(timeout: int = 5) -> Optional[DefaultRoute]:
    """The default route the kernel would actually use."""
    routes = default_routes(timeout)
    return routes[0] if routes else None


def route_for_device(device: str, timeout: int = 5) -> Optional[DefaultRoute]:
    """The default route carried by ``device``, if it has one."""
    for route in default_routes(timeout):
        if route.device == device:
            return route
    return None


def ping(host: str, timeout: int = 4, count: int = 1) -> ProbeResult:
    """ICMP-ping ``host`` once."""
    name = f"ping:{host}"
    if not host:
        return ProbeResult(name, False, "no host configured")
    started = time.monotonic()
    try:
        proc = subprocess.run(
            ["ping", "-n", "-q", "-c", str(count), "-W", str(timeout), host],
            capture_output=True,
            text=True,
            timeout=timeout * count + 3,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ProbeResult(name, False, "timed out")
    except OSError as exc:
        return ProbeResult(name, False, str(exc))
    elapsed = (time.monotonic() - started) * 1000.0
    if proc.returncode == 0:
        return ProbeResult(name, True, "reachable", round(elapsed, 1))
    return ProbeResult(name, False, "unreachable", round(elapsed, 1))


def tcp_connect(host: str, port: int, timeout: int = 4) -> ProbeResult:
    """Open and immediately close a TCP connection.

    Useful where ICMP is filtered, which is common on campus networks.
    """
    name = f"tcp:{host}:{port}"
    started = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            elapsed = (time.monotonic() - started) * 1000.0
            return ProbeResult(name, True, "connected", round(elapsed, 1))
    except OSError as exc:
        elapsed = (time.monotonic() - started) * 1000.0
        return ProbeResult(name, False, str(exc), round(elapsed, 1))


def dns_resolve(names: Sequence[str], timeout: int = 4) -> ProbeResult:
    """Resolve the first name that answers."""
    if not names:
        return ProbeResult("dns", False, "no names configured")
    original = socket.getdefaulttimeout()
    socket.setdefaulttimeout(timeout)
    try:
        for name in names:
            started = time.monotonic()
            try:
                addr = socket.gethostbyname(name)
            except OSError:
                continue
            elapsed = (time.monotonic() - started) * 1000.0
            return ProbeResult("dns", True, f"{name} -> {addr}", round(elapsed, 1))
        return ProbeResult("dns", False, f"could not resolve any of {', '.join(names)}")
    finally:
        socket.setdefaulttimeout(original)


def gateway_probe(gateway: Optional[str], timeout: int = 4) -> ProbeResult:
    """Whether the default gateway answers."""
    if not gateway:
        return ProbeResult("gateway", False, "no default route")
    result = ping(gateway, timeout=timeout)
    return ProbeResult(
        "gateway",
        result.ok,
        f"{gateway}: {result.detail}",
        result.latency_ms,
    )


def internet_probe(hosts: Sequence[str], timeout: int = 4) -> ProbeResult:
    """Whether any well-known internet host is reachable.

    Tries ICMP first, then TCP/443, because plenty of networks drop ICMP but
    pass HTTPS.
    """
    if not hosts:
        return ProbeResult("internet", False, "no hosts configured")
    for host in hosts:
        result = ping(host, timeout=timeout)
        if result.ok:
            return ProbeResult("internet", True, f"{host} reachable (icmp)", result.latency_ms)
    for host in hosts:
        result = tcp_connect(host, 443, timeout=timeout)
        if result.ok:
            return ProbeResult("internet", True, f"{host}:443 reachable (tcp)", result.latency_ms)
    return ProbeResult("internet", False, f"no route to {', '.join(hosts)}")


def _split_url(url: str) -> Tuple[Optional[str], Optional[int]]:
    """Extract ``(host, port)`` from a URL for a fallback TCP probe."""
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return None, None
    if not parsed.hostname:
        return None, None
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed.hostname, port


def backend_probe(url: str, timeout: int = 6) -> ProbeResult:
    """Whether the central backend answers.

    Any HTTP status counts as reachable: a 404 from the health path still
    proves the node can talk to the server, which is the question being asked.
    """
    if not url:
        return ProbeResult("backend", False, "no backend configured")
    started = time.monotonic()
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "netd/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            elapsed = (time.monotonic() - started) * 1000.0
            return ProbeResult("backend", True, f"HTTP {response.status}", round(elapsed, 1))
    except urllib.error.HTTPError as exc:
        elapsed = (time.monotonic() - started) * 1000.0
        return ProbeResult("backend", True, f"HTTP {exc.code}", round(elapsed, 1))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        # Fall back to a bare TCP check before declaring the backend down.
        host, port = _split_url(url)
        if host and port:
            tcp = tcp_connect(host, port, timeout=timeout)
            if tcp.ok:
                return ProbeResult("backend", True, f"tcp {host}:{port} open", tcp.latency_ms)
        elapsed = (time.monotonic() - started) * 1000.0
        reason = getattr(exc, "reason", exc)
        return ProbeResult("backend", False, str(reason), round(elapsed, 1))


def shelly_probe(host: str, timeout: int = 4) -> ProbeResult:
    """Whether the local Shelly meter answers on the sensor segment."""
    if not host:
        return ProbeResult("shelly", False, "no shelly configured")
    result = tcp_connect(host, 80, timeout=timeout)
    return ProbeResult("shelly", result.ok, f"{host}: {result.detail}", result.latency_ms)
