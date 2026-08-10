"""Connectivity evaluation.

Turns raw interface state and probe results into a single
:class:`~netd.models.ConnectivityVerdict`.

The one piece of real judgement here is uplink selection.  The requested
priority is Ethernet, then Wi-Fi client, then maintenance AP -- but on these
nodes ``eth0`` is normally a private sensor segment carrying the Shelly meter
and offering no default route.  Preferring it unconditionally would report a
node as online while it has no path to anything at all.  So in the default
``auto`` mode Ethernet is promoted to uplink only when it actually carries a
default route; otherwise it is recognised as the sensor segment and Wi-Fi
keeps the uplink role.  ``always`` and ``never`` are available for sites where
the wiring is known.
"""

from __future__ import annotations

import logging
import time
from typing import List, Optional, Tuple

from .config import Config
from .models import ConnectivityVerdict, InterfaceInfo, LinkKind, ProbeResult
from .nm import NetworkManager
from . import probes as probe_mod

log = logging.getLogger("netd.evaluator")


class ConnectivityEvaluator:
    """Builds a connectivity verdict from live system state."""

    def __init__(self, config: Config, nm: NetworkManager) -> None:
        self._config = config
        self._nm = nm
        # Results of the last full probe sweep, carried forward between
        # sweeps. Without this a shallow cycle would report DNS, internet and
        # backend as *failed* when they were simply not measured -- which is
        # the difference between a useful status page and a misleading one.
        self._last_deep: Optional[Tuple[bool, bool, bool, List[ProbeResult], float]] = None

    def forget_deep_results(self) -> None:
        """Discard carried-forward probe results (used when the link changes)."""
        self._last_deep = None

    # ------------------------------------------------------------------
    def select_uplink(
        self, devices: List[InterfaceInfo], ap_active: bool
    ) -> tuple[LinkKind, Optional[InterfaceInfo], Optional[probe_mod.DefaultRoute]]:
        """Choose which interface is carrying the node's uplink."""
        ifaces = self._config.interfaces
        by_name = {d.device: d for d in devices}
        eth = by_name.get(ifaces.ethernet)
        wifi = by_name.get(ifaces.wifi)

        if ap_active:
            return LinkKind.AP, wifi, None

        eth_route = probe_mod.route_for_device(ifaces.ethernet)
        eth_connected = eth is not None and eth.state.startswith("connected")

        prefer_eth = False
        if eth_connected:
            mode = ifaces.ethernet_is_uplink
            if mode == "always":
                prefer_eth = True
            elif mode == "auto":
                prefer_eth = eth_route is not None
            # "never" leaves prefer_eth False

        if prefer_eth and eth is not None:
            return LinkKind.ETHERNET, eth, eth_route

        wifi_connected = wifi is not None and wifi.state.startswith("connected")
        if wifi_connected and wifi is not None:
            return LinkKind.WIFI, wifi, probe_mod.route_for_device(ifaces.wifi)

        # Ethernet with no default route is still better than nothing if the
        # backend happens to live on that segment.
        if eth_connected and eth is not None:
            return LinkKind.ETHERNET, eth, eth_route

        return LinkKind.NONE, None, None

    # ------------------------------------------------------------------
    def evaluate(self, ap_active: bool = False, deep: bool = True) -> ConnectivityVerdict:
        """Run the probe suite and return a verdict.

        When ``deep`` is False only cheap local checks run (link state and
        gateway).  The supervisor uses shallow evaluation between full sweeps
        to stay responsive without hammering the backend.
        """
        cfg = self._config
        timeout = cfg.timing.probe_timeout
        devices = self._nm.devices()
        link, iface, route = self.select_uplink(devices, ap_active)

        results: List[ProbeResult] = []
        ipv4 = iface.ipv4 if iface else None
        ssid: Optional[str] = None
        if link is LinkKind.WIFI and iface is not None and iface.connection:
            # ``InterfaceInfo.connection`` is the NetworkManager *profile*
            # name, which frequently differs from the broadcast SSID (netplan
            # generates names like 'netplan-wlan0-wirelesslan'). Operators
            # recognise the SSID, so resolve it and fall back to the profile
            # name only if the lookup fails.
            ssid = self._nm.connection_ssid(iface.connection) or iface.connection
        elif link is LinkKind.AP:
            ssid = cfg.ap_ssid

        if link is LinkKind.AP:
            # In AP mode the node is intentionally not an uplink client.
            verdict = ConnectivityVerdict(
                link=LinkKind.AP,
                interface=iface.device if iface else cfg.interfaces.wifi,
                ipv4=cfg.access_point.cidr,
                ssid=ssid,
                gateway_ok=False,
                dns_ok=False,
                internet_ok=False,
                backend_ok=False,
                probes=results,
            )
            return verdict

        gateway = route.gateway if route else None
        gw_result = probe_mod.gateway_probe(gateway, timeout=timeout)
        results.append(gw_result)

        dns_ok = False
        internet_ok = False
        backend_ok = False
        deep_age: Optional[float] = None

        if deep and link is not LinkKind.NONE:
            dns_result = probe_mod.dns_resolve(cfg.probes.dns_names, timeout=timeout)
            results.append(dns_result)
            dns_ok = dns_result.ok

            inet_result = probe_mod.internet_probe(cfg.probes.internet_hosts, timeout=timeout)
            results.append(inet_result)
            internet_ok = inet_result.ok

            deep_results = [dns_result, inet_result]

            if cfg.probes.backend_url:
                backend_result = probe_mod.backend_probe(
                    cfg.probes.backend_url, timeout=cfg.probes.backend_timeout
                )
                results.append(backend_result)
                backend_ok = backend_result.ok
                deep_results.append(backend_result)

            self._last_deep = (dns_ok, internet_ok, backend_ok, deep_results, time.time())
            deep_age = 0.0
        elif self._last_deep is not None and link is not LinkKind.NONE:
            # Shallow cycle: reuse the last real measurement rather than
            # inventing failures.
            dns_ok, internet_ok, backend_ok, cached, measured_at = self._last_deep
            results.extend(cached)
            deep_age = max(0.0, time.time() - measured_at)

        return ConnectivityVerdict(
            link=link,
            interface=iface.device if iface else None,
            ipv4=ipv4,
            ssid=ssid,
            gateway_ok=gw_result.ok,
            dns_ok=dns_ok,
            internet_ok=internet_ok,
            backend_ok=backend_ok,
            probes=results,
            deep_age=deep_age,
        )
