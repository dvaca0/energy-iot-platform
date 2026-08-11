"""Tests for the two-tier whitelist, the secrets store and network health.

The three guarantees under test are the ones that were decided deliberately:

    a deployment from git can never delete an operator-added network
    passphrases never appear outside the 0600 secrets store
    "reset operator networks" is explicit, and is the only way back
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from netd.config import Config
from netd.knownnets import KnownNetworkStore
from netd.netselect import BASELINE, OPERATOR, KnownNetwork, NetHealth


def baseline(*pairs):
    return [KnownNetwork(ssid=s, priority=p, source=BASELINE) for s, p in pairs]


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.store = KnownNetworkStore(self.dir, baseline(("Campus", 60),
                                                          ("Backup", 30)))


class TwoTierWhitelist(StoreCase):
    def test_baseline_alone_is_the_effective_list(self):
        self.assertEqual([n.ssid for n in self.store.effective()],
                         ["Campus", "Backup"])

    def test_operator_network_is_added_on_top(self):
        self.store.add_operator_network("TechAdded", priority=90)
        self.assertEqual([n.ssid for n in self.store.effective()][0], "TechAdded")

    def test_a_git_deploy_never_deletes_an_operator_network(self):
        """A new baseline ships that has never heard of the operator's network."""
        self.store.add_operator_network("TechAdded", priority=15)
        redeployed = KnownNetworkStore(self.dir, baseline(("Campus", 60)))
        ssids = [n.ssid for n in redeployed.effective()]
        self.assertIn("TechAdded", ssids)

    def test_operator_entry_overrides_the_baseline_for_the_same_ssid(self):
        self.store.add_operator_network("Campus", priority=99, notes="moved")
        eff = {n.ssid: n for n in self.store.effective()}
        self.assertEqual(eff["Campus"].priority, 99)
        self.assertEqual(eff["Campus"].source, OPERATOR)

    def test_forgetting_a_baseline_network_survives_redeployment(self):
        ok, _ = self.store.remove_operator_network("Backup")
        self.assertTrue(ok)
        redeployed = KnownNetworkStore(self.dir, baseline(("Campus", 60),
                                                          ("Backup", 30)))
        self.assertNotIn("Backup", [n.ssid for n in redeployed.effective()])

    def test_re_adding_a_suppressed_network_un_suppresses_it(self):
        self.store.remove_operator_network("Backup")
        self.store.add_operator_network("Backup", priority=5)
        self.assertIn("Backup", [n.ssid for n in self.store.effective()])

    def test_removing_something_unknown_is_reported_not_silent(self):
        ok, msg = self.store.remove_operator_network("NoSuchNetwork")
        self.assertFalse(ok)
        self.assertIn("not a known network", msg)


class ResetIsExplicit(StoreCase):
    def test_reset_returns_to_the_baseline(self):
        self.store.add_operator_network("A", 10)
        self.store.add_operator_network("B", 20)
        ok, msg = self.store.reset_operator_networks()
        self.assertTrue(ok)
        self.assertIn("2 operator network", msg)
        self.assertEqual([n.ssid for n in self.store.effective()],
                         ["Campus", "Backup"])

    def test_reset_also_clears_those_credentials(self):
        self.store.add_operator_network("A", 10)
        self.store.set_secret("A", "hunter2")
        self.store.reset_operator_networks()
        self.assertIsNone(self.store.secret_for("A"))

    def test_reset_does_not_happen_by_itself(self):
        self.store.add_operator_network("A", 10)
        # Merely rebuilding the store (as a deployment does) must not reset.
        again = KnownNetworkStore(self.dir, baseline(("Campus", 60)))
        self.assertIn("A", [n.ssid for n in again.effective()])


class Secrets(StoreCase):
    def test_secrets_file_is_0600(self):
        self.store.set_secret("Campus", "topsecret")
        mode = stat.S_IMODE(os.stat(self.store.secrets_path).st_mode)
        self.assertEqual(mode, 0o600, f"secrets file is {oct(mode)}, must be 0600")

    def test_credentials_are_never_in_the_operator_file(self):
        self.store.add_operator_network("A", 10)
        self.store.set_secret("A", "SUPERSECRET")
        text = self.store.operator_path.read_text(encoding="utf-8")
        self.assertNotIn("SUPERSECRET", text)

    def test_describe_reports_presence_but_never_the_secret(self):
        self.store.set_secret("Campus", "SUPERSECRET")
        d = self.store.describe()
        blob = json.dumps(d)
        self.assertNotIn("SUPERSECRET", blob)
        campus = [n for n in d["effective"] if n["ssid"] == "Campus"][0]
        self.assertTrue(campus["has_credential"])

    def test_audit_lists_ssids_not_passwords(self):
        self.store.set_secret("Campus", "SUPERSECRET")
        audit = self.store.secrets_audit()
        self.assertEqual(audit["ssids_with_credentials"], ["Campus"])
        self.assertNotIn("SUPERSECRET", json.dumps(audit))
        self.assertEqual(audit["mode"], "0o600")

    def test_clearing_a_secret_removes_it(self):
        self.store.set_secret("Campus", "x")
        self.store.set_secret("Campus", None)
        self.assertIsNone(self.store.secret_for("Campus"))

    def test_removing_a_network_forgets_its_credential(self):
        self.store.add_operator_network("A", 1)
        self.store.set_secret("A", "x")
        self.store.remove_operator_network("A")
        self.assertIsNone(self.store.secret_for("A"))


class HealthPersistence(StoreCase):
    def test_health_round_trips(self):
        h = {"Campus": NetHealth("Campus", last_success=1000.0,
                                 consecutive_failures=2, last_signal=-61)}
        self.store.save_health(h)
        back = self.store.health()
        self.assertEqual(back["Campus"].last_success, 1000.0)
        self.assertEqual(back["Campus"].consecutive_failures, 2)
        self.assertEqual(back["Campus"].last_signal, -61)

    def test_missing_health_is_empty_not_an_error(self):
        self.assertEqual(self.store.health(), {})

    def test_corrupt_health_degrades_to_empty(self):
        self.store.health_path.write_text("{ not json", encoding="utf-8")
        self.assertEqual(self.store.health(), {})

    def test_corrupt_operator_file_does_not_hide_the_baseline(self):
        """A broken operator list must never strand the node offline."""
        self.store.operator_path.write_text("{{{", encoding="utf-8")
        self.assertEqual([n.ssid for n in self.store.effective()],
                         ["Campus", "Backup"])


class AtomicWrites(StoreCase):
    def test_no_temp_files_are_left_behind(self):
        self.store.add_operator_network("A", 1)
        self.store.set_secret("A", "x")
        self.store.save_health({"A": NetHealth("A")})
        leftovers = [f for f in os.listdir(self.dir) if f.startswith(".")]
        self.assertEqual(leftovers, [])


class ConfigBaseline(unittest.TestCase):
    def test_networks_are_read_from_yaml(self):
        c = Config.from_dict({"wifi": {"networks": [
            {"ssid": "Campus", "priority": 60, "notes": "main"},
            {"ssid": "Hidden", "priority": 5, "hidden": True},
        ]}})
        self.assertEqual([n.ssid for n in c.wifi.networks], ["Campus", "Hidden"])
        self.assertTrue(c.wifi.networks[1].hidden)

    def test_a_declared_passphrase_is_refused_not_stored(self):
        c = Config.from_dict({"wifi": {"networks": [
            {"ssid": "Lab", "priority": 1, "password": "LEAKED"},
        ]}})
        net = c.wifi.networks[0]
        self.assertFalse(hasattr(net, "password"))
        self.assertNotIn("LEAKED", str(net))

    def test_open_networks_are_refused_by_default(self):
        self.assertFalse(Config.from_dict({}).wifi.allow_open_networks)

    def test_malformed_entries_are_skipped_not_fatal(self):
        c = Config.from_dict({"wifi": {"networks": [
            "garbage", {"priority": 3}, {"ssid": "Good"}]}})
        self.assertEqual([n.ssid for n in c.wifi.networks], ["Good"])

    def test_missing_wifi_section_yields_defaults(self):
        c = Config.from_dict({})
        self.assertEqual(c.wifi.networks, [])
        self.assertEqual(c.wifi.backoff_initial, 15)


if __name__ == "__main__":
    unittest.main(verbosity=2)
