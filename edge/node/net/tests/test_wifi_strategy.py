"""WifiManager integration: whitelist, health and NetworkManager reconciliation.

Uses a stub NetworkManager, so the strategy is exercised end to end without a
radio. The point of these tests is that the ranking actually reaches
NetworkManager - a correct ordering that never gets applied changes nothing.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from netd.config import Config
from netd.knownnets import KnownNetworkStore
from netd.models import SavedNetwork, ScanResult, Security
from netd.netselect import BASELINE, KnownNetwork
from netd.wifi_manager import WifiManager


class StubNM:
    """Just enough NetworkManager to observe what the manager decides."""

    def __init__(self, saved=()):
        self._saved = list(saved)
        self.priorities = {}
        self.autoconnect = {}
        self.added = []
        self.upped = []
        self.up_ok = True

    def connections(self):
        return list(self._saved)

    def set_priority(self, uuid, priority):
        # SavedNetwork is frozen, so replace rather than mutate.
        self.priorities[uuid] = priority
        self._saved = [
            SavedNetwork(name=n.name, uuid=n.uuid, ssid=n.ssid,
                         autoconnect=n.autoconnect, priority=priority)
            if n.uuid == uuid else n
            for n in self._saved
        ]
        return True, "ok"

    def set_autoconnect(self, uuid, enabled):
        self.autoconnect[uuid] = enabled
        return True, "ok"

    def add_wifi(self, ssid, password, device=None, priority=0, hidden=False):
        self.added.append({"ssid": ssid, "has_password": bool(password),
                           "priority": priority, "hidden": hidden})
        n = SavedNetwork(uuid=f"uuid-{ssid}", name=ssid, ssid=ssid,
                         priority=priority, autoconnect=True)
        self._saved.append(n)
        return True, ssid

    def up(self, ident, timeout=60):
        self.upped.append(ident)

        class R:
            ok = self.up_ok
            message = "" if self.up_ok else "auth failed"
        return R()

    def delete(self, uuid):
        self._saved = [n for n in self._saved if n.uuid != uuid]

        class R:
            ok = True
            message = "deleted"
        return R()

    def scan(self, device, rescan=True):
        return []


def saved(ssid, priority=0):
    return SavedNetwork(uuid=f"uuid-{ssid}", name=ssid, ssid=ssid,
                        priority=priority, autoconnect=True)


def seen(ssid, signal):
    """A scan result. NetworkManager reports signal as quality, 0-100."""
    return ScanResult(ssid=ssid, signal=signal, security=Security.WPA_PSK)


class WifiStrategyCase(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.cfg = Config.from_dict({
            "paths": {"var_dir": str(self.dir)},
            "wifi": {"networks": [
                {"ssid": "Campus", "priority": 60},
                {"ssid": "Backup", "priority": 30},
            ]},
        })
        self.store = KnownNetworkStore(
            self.dir,
            [KnownNetwork("Campus", 60, BASELINE),
             KnownNetwork("Backup", 30, BASELINE)])
        self.nm = StubNM([saved("Campus", 1), saved("Backup", 1)])
        self.wifi = WifiManager(self.cfg, self.nm, self.store)
        self.wifi._last_scan = [seen("Campus", 80), seen("Backup", 45)]
        self.wifi._last_scan_at = 1e12


class Reconciliation(WifiStrategyCase):
    def test_ranking_is_pushed_onto_networkmanager(self):
        self.wifi.reconcile(now=1000.0)
        # Campus ranks first, so it must end up with the higher NM priority.
        self.assertGreater(self.nm.priorities["uuid-Campus"],
                           self.nm.priorities["uuid-Backup"])

    def test_a_recent_success_outranks_a_higher_configured_priority(self):
        self.wifi.note_result("Backup", True, now=990.0)
        self.wifi.reconcile(now=1000.0)
        self.assertGreater(self.nm.priorities["uuid-Backup"],
                           self.nm.priorities["uuid-Campus"])

    def test_a_backing_off_network_has_autoconnect_switched_off(self):
        for i in range(3):
            self.wifi.note_result("Campus", False, "auth failed", now=1000.0 + i)
        self.wifi.reconcile(now=1005.0)
        self.assertFalse(self.nm.autoconnect["uuid-Campus"])
        self.assertTrue(self.nm.autoconnect["uuid-Backup"])

    def test_autoconnect_returns_once_the_backoff_expires(self):
        self.wifi.note_result("Campus", False, "auth failed", now=1000.0)
        self.wifi.reconcile(now=1005.0)
        self.assertFalse(self.nm.autoconnect["uuid-Campus"])
        self.wifi.reconcile(now=1100.0)
        self.assertTrue(self.nm.autoconnect["uuid-Campus"])

    def test_a_network_out_of_range_keeps_autoconnect_on(self):
        # Otherwise it could never come back when it reappears.
        self.wifi._last_scan = [seen("Campus", 80)]
        self.wifi.reconcile(now=1000.0)
        self.assertTrue(self.nm.autoconnect["uuid-Backup"])

    def test_declared_network_without_a_credential_is_reported_not_created(self):
        self.nm._saved = []
        actions = self.wifi.reconcile(now=1000.0)
        self.assertIn("no credential stored", actions["Campus"])
        self.assertEqual(self.nm.added, [])

    def test_declared_network_with_a_stored_credential_is_created(self):
        self.nm._saved = []
        self.store.set_secret("Campus", "hunter2")
        self.wifi.reconcile(now=1000.0)
        self.assertEqual([a["ssid"] for a in self.nm.added], ["Campus"])
        self.assertTrue(self.nm.added[0]["has_password"])


class ConnectRecordsEverything(WifiStrategyCase):
    def test_a_successful_connect_stores_network_secret_and_health(self):
        ok, _ = self.wifi.connect("NewNet", "hunter2", priority=40)
        self.assertTrue(ok)
        self.assertIn("NewNet", [n.ssid for n in self.store.operator_networks()])
        self.assertEqual(self.store.secret_for("NewNet"), "hunter2")
        self.assertIsNotNone(self.store.health()["NewNet"].last_success)

    def test_a_failed_connect_is_recorded_as_a_failure(self):
        self.nm.up_ok = False
        ok, _ = self.wifi.connect("BadNet", "wrong")
        self.assertFalse(ok)
        h = self.store.health()["BadNet"]
        self.assertEqual(h.consecutive_failures, 1)
        self.assertIn("auth failed", h.last_error)

    def test_the_credential_never_lands_in_the_operator_file(self):
        self.wifi.connect("NewNet", "SUPERSECRET")
        text = self.store.operator_path.read_text(encoding="utf-8")
        self.assertNotIn("SUPERSECRET", text)

    def test_forget_removes_it_from_the_operator_store_and_secrets(self):
        self.wifi.connect("NewNet", "hunter2")
        ok, _ = self.wifi.forget("NewNet")
        self.assertTrue(ok)
        self.assertNotIn("NewNet",
                         [n.ssid for n in self.store.operator_networks()])
        self.assertIsNone(self.store.secret_for("NewNet"))

    def test_forgetting_a_baseline_network_suppresses_it(self):
        ok, _ = self.wifi.forget("Backup")
        self.assertTrue(ok)
        self.assertIn("Backup", self.store.suppressed())
        self.assertNotIn("Backup", [n.ssid for n in self.wifi.known_networks()])


class APDecisionIsHealthDriven(WifiStrategyCase):
    def test_ap_stays_down_while_something_is_worth_trying(self):
        self.assertFalse(self.wifi.should_raise_ap(now=1000.0))

    def test_ap_goes_up_only_when_every_known_network_is_exhausted(self):
        for ssid in ("Campus", "Backup"):
            for i in range(4):
                self.wifi.note_result(ssid, False, "no", now=1000.0 + i)
        self.assertTrue(self.wifi.should_raise_ap(now=1005.0))

    def test_ap_comes_back_down_path_once_a_backoff_expires(self):
        for ssid in ("Campus", "Backup"):
            self.wifi.note_result(ssid, False, "no", now=1000.0)
        self.assertTrue(self.wifi.should_raise_ap(now=1005.0))
        # 15s later the backoff has lapsed: there IS something to try again.
        self.assertFalse(self.wifi.should_raise_ap(now=1100.0))


if __name__ == "__main__":
    unittest.main(verbosity=2)


class EmptyWhitelistFailSafe(unittest.TestCase):
    """An un-migrated node must not strand itself by raising the AP."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        cfg = Config.from_dict({"paths": {"var_dir": str(self.dir)}})
        self.store = KnownNetworkStore(self.dir, [])       # nothing declared
        self.nm = StubNM([saved("Campus", 1)])
        self.wifi = WifiManager(cfg, self.nm, self.store)
        self.wifi._last_scan_at = 1e12

    def test_no_ap_when_a_saved_profile_is_in_range(self):
        self.wifi._last_scan = [seen("Campus", 80)]
        self.assertFalse(self.wifi.should_raise_ap(now=1000.0))

    def test_ap_when_nothing_saved_is_in_range(self):
        self.wifi._last_scan = [seen("Stranger", 80)]
        self.assertTrue(self.wifi.should_raise_ap(now=1000.0))

    def test_reconcile_is_a_no_op_with_an_empty_whitelist(self):
        self.wifi._last_scan = [seen("Campus", 80)]
        self.assertEqual(self.wifi.reconcile(now=1000.0), {})
        self.assertEqual(self.nm.autoconnect, {})
