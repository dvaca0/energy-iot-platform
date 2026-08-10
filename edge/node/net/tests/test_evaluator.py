"""Uplink selection tests.

The critical case: on these nodes ``eth0`` is the private Shelly sensor
segment with no default route.  Treating it as an uplink would report the node
online while it can reach nothing.
"""

from __future__ import annotations

import unittest
from typing import List, Optional
from unittest import mock

from netd.config import Config, InterfaceConfig, ProbeConfig
from netd.evaluator import ConnectivityEvaluator
from netd.models import ConnectivityVerdict, InterfaceInfo, LinkKind, ProbeResult
from netd.nm import NetworkManager
from netd.probes import DefaultRoute


def interfaces(eth_state: str = "connected", wifi_state: str = "connected") -> List[InterfaceInfo]:
    return [
        InterfaceInfo("eth0", "ethernet", eth_state, "shelly-lan", "192.168.50.2/24", None),
        InterfaceInfo("wlan0", "wifi", wifi_state, "Campus", "10.0.0.5/24", "10.0.0.1"),
    ]


class UplinkSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = Config(interfaces=InterfaceConfig(ethernet_is_uplink="auto"))
        self.nm = mock.Mock(spec=NetworkManager)
        self.evaluator = ConnectivityEvaluator(self.config, self.nm)

    def _select(self, routes: dict[str, Optional[DefaultRoute]], devices=None, ap=False):
        def route_for_device(device: str, timeout: int = 5) -> Optional[DefaultRoute]:
            return routes.get(device)

        with mock.patch("netd.evaluator.probe_mod.route_for_device", route_for_device):
            return self.evaluator.select_uplink(devices or interfaces(), ap)

    def test_sensor_ethernet_does_not_become_uplink(self) -> None:
        """eth0 with no default route must not displace working Wi-Fi."""
        link, iface, _route = self._select({"wlan0": DefaultRoute("10.0.0.1", "wlan0", 600)})
        self.assertIs(link, LinkKind.WIFI)
        self.assertEqual(iface.device, "wlan0")

    def test_ethernet_wins_when_it_carries_a_default_route(self) -> None:
        """Real Ethernet uplink takes priority over Wi-Fi, as designed."""
        link, iface, route = self._select(
            {
                "eth0": DefaultRoute("192.168.1.1", "eth0", 100),
                "wlan0": DefaultRoute("10.0.0.1", "wlan0", 600),
            }
        )
        self.assertIs(link, LinkKind.ETHERNET)
        self.assertEqual(iface.device, "eth0")
        self.assertEqual(route.gateway, "192.168.1.1")

    def test_always_mode_forces_ethernet_priority(self) -> None:
        self.config = Config(interfaces=InterfaceConfig(ethernet_is_uplink="always"))
        self.evaluator = ConnectivityEvaluator(self.config, self.nm)
        link, _iface, _route = self._select({"wlan0": DefaultRoute("10.0.0.1", "wlan0", 600)})
        self.assertIs(link, LinkKind.ETHERNET)

    def test_never_mode_ignores_ethernet(self) -> None:
        self.config = Config(interfaces=InterfaceConfig(ethernet_is_uplink="never"))
        self.evaluator = ConnectivityEvaluator(self.config, self.nm)
        link, _iface, _route = self._select(
            {
                "eth0": DefaultRoute("192.168.1.1", "eth0", 100),
                "wlan0": DefaultRoute("10.0.0.1", "wlan0", 600),
            }
        )
        self.assertIs(link, LinkKind.WIFI)

    def test_ap_mode_reports_ap_link(self) -> None:
        link, _iface, _route = self._select({}, ap=True)
        self.assertIs(link, LinkKind.AP)

    def test_no_connected_interface_yields_no_link(self) -> None:
        link, iface, _route = self._select(
            {}, devices=interfaces(eth_state="unavailable", wifi_state="disconnected")
        )
        self.assertIs(link, LinkKind.NONE)
        self.assertIsNone(iface)

    def test_ethernet_used_as_last_resort_without_wifi(self) -> None:
        """A backend on the sensor segment is better than nothing."""
        link, iface, _route = self._select(
            {}, devices=interfaces(wifi_state="disconnected")
        )
        self.assertIs(link, LinkKind.ETHERNET)
        self.assertEqual(iface.device, "eth0")

class DeepProbeCarryForwardTests(unittest.TestCase):
    """A shallow cycle must not report unmeasured probes as failures.

    Regression: DNS/internet/backend run only on every third monitor cycle.
    Reporting them as False on the other two made the status page claim a
    healthy node was failing three checks.
    """

    def setUp(self) -> None:
        self.config = Config(
            probes=ProbeConfig(
                backend_url="http://backend.example/",
                dns_names=["example.test"],
                internet_hosts=["192.0.2.1"],
            )
        )
        self.nm = mock.Mock(spec=NetworkManager)
        self.nm.devices.return_value = interfaces()
        self.nm.connection_ssid.return_value = "Campus"
        self.evaluator = ConnectivityEvaluator(self.config, self.nm)

    def _evaluate(self, deep: bool) -> ConnectivityVerdict:
        """Evaluate with every probe stubbed to succeed."""
        route = DefaultRoute("10.0.0.1", "wlan0", 600)
        passing = {
            name: mock.patch(
                f"netd.evaluator.probe_mod.{name}", return_value=ProbeResult(name, True)
            )
            for name in ("gateway_probe", "dns_resolve", "internet_probe", "backend_probe")
        }
        with mock.patch("netd.evaluator.probe_mod.route_for_device", return_value=route):
            with passing["gateway_probe"], passing["dns_resolve"], \
                 passing["internet_probe"], passing["backend_probe"]:
                return self.evaluator.evaluate(ap_active=False, deep=deep)

    def test_deep_cycle_records_results(self) -> None:
        v = self._evaluate(deep=True)
        self.assertTrue(v.dns_ok and v.internet_ok and v.backend_ok)
        self.assertIsNotNone(v.deep_age)
        self.assertTrue(v.to_dict()["deep_measured"])

    def test_shallow_cycle_carries_previous_results_forward(self) -> None:
        self._evaluate(deep=True)
        v = self._evaluate(deep=False)
        self.assertTrue(v.dns_ok, "carried-forward DNS result was lost")
        self.assertTrue(v.internet_ok)
        self.assertTrue(v.backend_ok)
        self.assertTrue(v.to_dict()["deep_measured"])

    def test_shallow_cycle_before_any_deep_is_marked_unmeasured(self) -> None:
        v = self._evaluate(deep=False)
        self.assertIsNone(v.deep_age)
        self.assertFalse(v.to_dict()["deep_measured"], "unmeasured must not read as measured")

    def test_link_still_governs_usability_on_shallow_cycles(self) -> None:
        v = self._evaluate(deep=False)
        self.assertTrue(v.usable, "gateway alone must keep the node usable")


if __name__ == "__main__":
    unittest.main()
