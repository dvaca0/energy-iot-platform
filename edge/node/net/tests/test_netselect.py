"""Unit tests for the network selection strategy.

Pure: no radio, no scan, no clock. Every rule from the agreed strategy has a
test, and so does every way it could strand a node offline.
"""

from __future__ import annotations

import unittest

from netd.netselect import (BASELINE, OPERATOR, Candidate, KnownNetwork,
                            NetHealth, SelectionPolicy, backoff_seconds,
                            in_backoff, merge_whitelist,
                            most_recently_successful, next_to_try, rank,
                            record_failure, record_success, retry_after,
                            should_raise_ap)


def net(ssid, priority=0, **kw):
    return KnownNetwork(ssid=ssid, priority=priority, **kw)


class Backoff(unittest.TestCase):
    def test_no_failures_means_no_wait(self):
        self.assertEqual(backoff_seconds(0, SelectionPolicy()), 0)

    def test_exponential_then_capped(self):
        p = SelectionPolicy(backoff_initial=15, backoff_max=300)
        self.assertEqual(backoff_seconds(1, p), 15)
        self.assertEqual(backoff_seconds(2, p), 30)
        self.assertEqual(backoff_seconds(3, p), 60)
        self.assertEqual(backoff_seconds(9, p), 300)

    def test_in_backoff_expires(self):
        p = SelectionPolicy(backoff_initial=15)
        h = NetHealth("A", last_failure=1000.0, consecutive_failures=1)
        self.assertTrue(in_backoff(h, 1005.0, p))
        self.assertFalse(in_backoff(h, 1016.0, p))

    def test_unknown_health_is_never_in_backoff(self):
        self.assertFalse(in_backoff(None, 1000.0, SelectionPolicy()))


class Rule1MostRecentlySuccessful(unittest.TestCase):
    def test_the_network_that_worked_most_recently_goes_first(self):
        known = [net("HighPrio", 90), net("Worked", 10)]
        health = {"Worked": NetHealth("Worked", last_success=990.0)}
        order = [c.network.ssid for c in rank(known, health, None, 1000.0)]
        self.assertEqual(order[0], "Worked")

    def test_it_beats_a_much_higher_priority(self):
        known = [net("A", 100), net("B", 1)]
        health = {"B": NetHealth("B", last_success=999.0)}
        self.assertEqual(next_to_try(known, health, None, 1000.0).ssid, "B")

    def test_a_stale_success_does_not_win(self):
        p = SelectionPolicy(recent_success_window=3600)
        known = [net("A", 100), net("B", 1)]
        health = {"B": NetHealth("B", last_success=1000.0)}
        # Two days later the node has probably been moved.
        self.assertEqual(next_to_try(known, health, None, 1000.0 + 200000, p).ssid, "A")

    def test_the_most_recent_of_several_successes_wins(self):
        known = [net("A"), net("B"), net("C")]
        health = {
            "A": NetHealth("A", last_success=100.0),
            "B": NetHealth("B", last_success=300.0),
            "C": NetHealth("C", last_success=200.0),
        }
        self.assertEqual(most_recently_successful(known, health, 400.0,
                                                  SelectionPolicy()), "B")


class Rule2Priority(unittest.TestCase):
    def test_priority_orders_networks_with_no_history(self):
        known = [net("low", 1), net("high", 50), net("mid", 10)]
        order = [c.network.ssid for c in rank(known, {}, None, 0.0)]
        self.assertEqual(order, ["high", "mid", "low"])

    def test_ties_break_stably_by_ssid(self):
        known = [net("bravo", 5), net("alpha", 5)]
        order = [c.network.ssid for c in rank(known, {}, None, 0.0)]
        self.assertEqual(order, ["alpha", "bravo"])


class Rule3Backoff(unittest.TestCase):
    def test_a_failing_network_is_skipped_while_backing_off(self):
        p = SelectionPolicy(backoff_initial=15)
        known = [net("Broken", 100), net("Works", 1)]
        health = {"Broken": NetHealth("Broken", last_failure=1000.0,
                                      consecutive_failures=3)}
        self.assertEqual(next_to_try(known, health, None, 1010.0, p).ssid, "Works")

    def test_it_returns_once_the_backoff_expires(self):
        p = SelectionPolicy(backoff_initial=15)
        known = [net("Broken", 100), net("Works", 1)]
        health = {"Broken": NetHealth("Broken", last_failure=1000.0,
                                      consecutive_failures=1)}
        self.assertEqual(next_to_try(known, health, None, 1100.0, p).ssid, "Broken")

    def test_a_skipped_network_still_explains_itself(self):
        p = SelectionPolicy(backoff_initial=15)
        known = [net("Broken", 100)]
        health = {"Broken": NetHealth("Broken", last_failure=1000.0,
                                      consecutive_failures=2)}
        c = rank(known, health, None, 1005.0, p)[0]
        self.assertFalse(c.eligible)
        self.assertIn("backing off", c.reason)
        self.assertIsNotNone(c.retry_after)

    def test_success_clears_the_backoff_immediately(self):
        health = {}
        record_failure(health, "A", 1000.0, "bad password")
        record_failure(health, "A", 1100.0, "bad password")
        self.assertEqual(health["A"].consecutive_failures, 2)
        record_success(health, "A", 1200.0, signal=-55)
        self.assertEqual(health["A"].consecutive_failures, 0)
        self.assertEqual(health["A"].last_signal, -55)
        self.assertFalse(in_backoff(health["A"], 1201.0, SelectionPolicy()))


class Rule4OpenNetworks(unittest.TestCase):
    def test_open_networks_are_refused_by_default(self):
        known = [net("FreeWifi", 100, open=True)]
        c = rank(known, {}, None, 0.0)[0]
        self.assertFalse(c.eligible)
        self.assertIn("refused by policy", c.reason)
        self.assertIsNone(next_to_try(known, {}, None, 0.0))

    def test_open_networks_are_allowed_only_when_explicitly_enabled(self):
        known = [net("FreeWifi", 100, open=True)]
        p = SelectionPolicy(allow_open=True)
        self.assertEqual(next_to_try(known, {}, None, 0.0, p).ssid, "FreeWifi")

    def test_an_unlisted_ssid_is_never_a_candidate(self):
        # Only the whitelist is ever ranked; a visible stranger is not.
        known = [net("Known")]
        order = [c.network.ssid for c in rank(known, {}, {"Stranger": -40}, 0.0)]
        self.assertNotIn("Stranger", order)


class Visibility(unittest.TestCase):
    def test_networks_out_of_range_are_deferred(self):
        known = [net("Far", 100), net("Near", 1)]
        c = rank(known, {}, {"Near": -50}, 0.0)
        self.assertEqual(c[0].network.ssid, "Near")
        self.assertFalse(c[1].eligible)
        self.assertEqual(c[1].reason, "not in range")

    def test_hidden_networks_are_always_considered(self):
        known = [net("Hidden", 100, hidden=True)]
        self.assertEqual(next_to_try(known, {}, {"Other": -50}, 0.0).ssid, "Hidden")

    def test_a_failed_scan_does_not_strand_the_node(self):
        # visible=None means "no scan data", not "nothing is in range".
        known = [net("A", 10)]
        self.assertIsNotNone(next_to_try(known, {}, None, 0.0))

    def test_signal_is_carried_through_when_known(self):
        known = [net("A")]
        self.assertEqual(rank(known, {}, {"A": -61}, 0.0)[0].signal, -61)


class APDecision(unittest.TestCase):
    def test_ap_is_not_raised_while_something_is_worth_trying(self):
        self.assertFalse(should_raise_ap([net("A")], {}, {"A": -50}, 0.0))

    def test_ap_is_raised_when_nothing_is_eligible(self):
        p = SelectionPolicy(backoff_initial=15)
        known = [net("A")]
        health = {"A": NetHealth("A", last_failure=1000.0, consecutive_failures=4)}
        self.assertTrue(should_raise_ap(known, health, {"A": -50}, 1005.0, p))

    def test_ap_is_raised_when_no_known_network_is_in_range(self):
        self.assertTrue(should_raise_ap([net("A")], {}, {"Other": -50}, 0.0))

    def test_ap_is_raised_when_the_whitelist_is_empty(self):
        self.assertTrue(should_raise_ap([], {}, {"Any": -50}, 0.0))

    def test_backoff_expiry_takes_the_ap_back_down_path(self):
        # Once the backoff lapses there IS something to try again, so the
        # node must go back to trying rather than sitting on the AP.
        p = SelectionPolicy(backoff_initial=15)
        known = [net("A")]
        health = {"A": NetHealth("A", last_failure=1000.0, consecutive_failures=1)}
        self.assertTrue(should_raise_ap(known, health, {"A": -50}, 1005.0, p))
        self.assertFalse(should_raise_ap(known, health, {"A": -50}, 1100.0, p))


class Whitelist(unittest.TestCase):
    def test_operator_entries_override_baseline_for_the_same_ssid(self):
        base = [KnownNetwork("Campus", 10, source=BASELINE)]
        op = [KnownNetwork("Campus", 90, source=OPERATOR)]
        merged = merge_whitelist(base, op)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].priority, 90)
        self.assertEqual(merged[0].source, OPERATOR)

    def test_a_git_deploy_can_never_delete_an_operator_network(self):
        """The whole point of the two-tier design."""
        op = [KnownNetwork("TechAdded", 50, source=OPERATOR)]
        # A later deployment ships a baseline that knows nothing about it.
        merged = merge_whitelist([KnownNetwork("Campus", 10)], op)
        self.assertIn("TechAdded", [n.ssid for n in merged])

    def test_suppression_lets_an_operator_forget_a_baseline_network(self):
        base = [KnownNetwork("Old", 10), KnownNetwork("Campus", 20)]
        merged = merge_whitelist(base, [], suppressed=["Old"])
        self.assertEqual([n.ssid for n in merged], ["Campus"])

    def test_merged_list_is_priority_ordered(self):
        merged = merge_whitelist(
            [KnownNetwork("low", 1), KnownNetwork("high", 99)], [])
        self.assertEqual([n.ssid for n in merged], ["high", "low"])

    def test_known_network_never_carries_a_passphrase(self):
        n = KnownNetwork("A", 1)
        self.assertNotIn("password", n.redacted())
        self.assertNotIn("psk", str(n.redacted()).lower())
        self.assertFalse(hasattr(n, "password"))


class Integration(unittest.TestCase):
    def test_a_realistic_recovery_sequence(self):
        """Password changes on the preferred network; node falls back, then
        returns once the operator fixes it."""
        p = SelectionPolicy(backoff_initial=15, backoff_max=300)
        known = [net("Campus", 60), net("Backup", 30)]
        health = {}
        visible = {"Campus": -55, "Backup": -70}
        now = 1000.0

        # Campus was fine yesterday.
        record_success(health, "Campus", now - 100)
        self.assertEqual(next_to_try(known, health, visible, now, p).ssid, "Campus")

        # Password changed: three failures.
        for i in range(3):
            now += 20
            record_failure(health, "Campus", now, "auth failed")
        self.assertEqual(next_to_try(known, health, visible, now, p).ssid, "Backup")

        # Backup works, and now leads.
        record_success(health, "Backup", now)
        self.assertEqual(next_to_try(known, health, visible, now, p).ssid, "Backup")

        # Operator fixes Campus from the portal; a success resets it.
        now += 5000
        record_success(health, "Campus", now)
        self.assertEqual(next_to_try(known, health, visible, now, p).ssid, "Campus")

        # And the AP was never needed, because something was always eligible.
        self.assertFalse(should_raise_ap(known, health, visible, now, p))


if __name__ == "__main__":
    unittest.main(verbosity=2)
