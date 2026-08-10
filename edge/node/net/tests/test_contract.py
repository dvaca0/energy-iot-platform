"""Tests for the collector-facing contract and configuration loading."""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from netd.config import Config, load_config
from netd.nm import parse_security, split_terse
from netd.models import Security
from netd.statefile import StatePublisher, network_available, read_state


class ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.path = Path(self._dir.name) / "network-state.json"

    def tearDown(self) -> None:
        self._dir.cleanup()

    def test_publishes_available(self) -> None:
        StatePublisher(self.path, ttl_seconds=30).publish(available=True)
        self.assertTrue(network_available(self.path))
        self.assertEqual(read_state(self.path)["network"], "available")

    def test_publishes_unavailable(self) -> None:
        StatePublisher(self.path, ttl_seconds=30).publish(available=False)
        self.assertFalse(network_available(self.path))

    def test_document_is_world_readable(self) -> None:
        """An unprivileged collector must be able to read it."""
        StatePublisher(self.path).publish(available=True)
        self.assertTrue(self.path.stat().st_mode & 0o004)

    def test_missing_file_fails_open(self) -> None:
        """A dead supervisor must not stop the collector from trying."""
        missing = Path(self._dir.name) / "absent.json"
        self.assertTrue(network_available(missing))
        self.assertFalse(network_available(missing, fail_open=False))

    def test_stale_document_fails_open(self) -> None:
        document = {
            "schema": 1,
            "network": "unavailable",
            "updated_at": time.time() - 10_000,
            "ttl_seconds": 30,
            "detail": {},
        }
        self.path.write_text(json.dumps(document), encoding="utf-8")
        self.assertTrue(network_available(self.path))

    def test_corrupt_document_fails_open(self) -> None:
        self.path.write_text("{not json", encoding="utf-8")
        self.assertTrue(network_available(self.path))

    def test_detail_never_required_by_the_contract(self) -> None:
        """The collector reads one key; detail is advisory only."""
        StatePublisher(self.path).publish(available=True, detail={"link": "wifi"})
        data = read_state(self.path)
        self.assertIn("network", data)
        self.assertEqual(data["detail"]["link"], "wifi")

    def test_standalone_client_agrees_with_publisher(self) -> None:
        """The file shipped to the collector must read what netd writes."""
        import importlib.util

        import netd

        # Locate the shipped file through the installed package rather than by
        # walking up from this test's own path, so the test works wherever the
        # suite is run from.
        module_path = Path(netd.__file__).resolve().parent / "client" / "energy_node_netstate.py"
        self.assertTrue(module_path.is_file(), f"contract client missing at {module_path}")
        spec = importlib.util.spec_from_file_location("energy_node_netstate", module_path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        StatePublisher(self.path, ttl_seconds=30).publish(available=False)
        self.assertFalse(module.network_available(str(self.path)))
        StatePublisher(self.path, ttl_seconds=30).publish(available=True)
        self.assertTrue(module.network_available(str(self.path)))


class ConfigTests(unittest.TestCase):
    def test_missing_config_yields_working_defaults(self) -> None:
        """A broken config must never stop networking from starting."""
        config = load_config("/nonexistent/network.yaml")
        self.assertEqual(config.access_point.address, "192.168.66.1")
        self.assertEqual(config.interfaces.wifi, "wlan0")
        self.assertTrue(config.access_point.enabled)

    def test_malformed_yaml_yields_defaults(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as handle:
            handle.write("node: {id: 'N001'\n  broken: [")
            name = handle.name
        try:
            config = load_config(name)
            self.assertEqual(config.node.id, "N000")
        finally:
            Path(name).unlink()

    def test_partial_config_keeps_defaults_for_rest(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as handle:
            handle.write("node:\n  id: 'N007'\n")
            name = handle.name
        try:
            config = load_config(name)
            self.assertEqual(config.node.id, "N007")
            self.assertEqual(config.timing.offline_before_ap, 180)
        finally:
            Path(name).unlink()

    def test_ssid_is_rendered_per_node(self) -> None:
        config = Config.from_dict({"node": {"id": "N003"}})
        self.assertEqual(config.ap_ssid, "EnergyNode-N003")

    def test_malformed_ssid_format_falls_back(self) -> None:
        config = Config.from_dict(
            {"node": {"id": "N003"}, "access_point": {"ssid_format": "Broken-{oops}"}}
        )
        self.assertEqual(config.ap_ssid, "EnergyNode-N003")

    def test_password_is_redacted_for_display(self) -> None:
        config = Config.from_dict({"access_point": {"password": "hunter2secret"}})
        self.assertEqual(config.redacted()["access_point"]["password"], "********")

    def test_invalid_timing_values_fall_back(self) -> None:
        config = Config.from_dict({"timing": {"offline_before_ap": "not-a-number"}})
        self.assertEqual(config.timing.offline_before_ap, 180)


class NmcliParsingTests(unittest.TestCase):
    def test_escaped_colon_in_ssid_survives(self) -> None:
        """An SSID containing a colon must not be split into two fields."""
        self.assertEqual(
            split_terse(r"yes:Cafe\: Wifi:72:WPA2"), ["yes", "Cafe: Wifi", "72", "WPA2"]
        )

    def test_plain_fields(self) -> None:
        self.assertEqual(split_terse("wlan0:wifi:connected:Lab"), ["wlan0", "wifi", "connected", "Lab"])

    def test_empty_trailing_field(self) -> None:
        self.assertEqual(split_terse("eth0:ethernet:unavailable:"), ["eth0", "ethernet", "unavailable", ""])

    def test_security_normalisation(self) -> None:
        self.assertIs(parse_security("WPA2"), Security.WPA_PSK)
        self.assertIs(parse_security("WPA1 WPA2"), Security.WPA_PSK)
        self.assertIs(parse_security("WPA2 802.1X"), Security.WPA_EAP)
        self.assertIs(parse_security(""), Security.OPEN)
        self.assertIs(parse_security("--"), Security.OPEN)
        self.assertIs(parse_security("WEP"), Security.WEP)


if __name__ == "__main__":
    unittest.main()
