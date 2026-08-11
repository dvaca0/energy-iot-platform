"""Tests for SAFE MODE behaviour. Hermetic: no radio, no services, no reboot.

The most important test here is the one that would have caught the defect
Stage A found: SAFE MODE must never PIN the access point. These nodes have one
radio, so a pinned AP is an AP the node can never leave to rejoin Wi-Fi, which
would make SAFE MODE permanent and require the physical visit the whole design
exists to avoid.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_LIB = os.path.join(_HERE, "..", "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from recovery import pipeline as P  # noqa: E402


def load_daemon():
    path = os.path.join(_LIB, "recovery", "daemon.py")
    spec = importlib.util.spec_from_file_location("daemon_sm", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["daemon_sm"] = mod
    spec.loader.exec_module(mod)
    return mod


class SafeModeNeverPinsTheRadio(unittest.TestCase):
    def setUp(self):
        self.d = load_daemon()
        self.commands = []
        self.d.run = lambda cmd, timeout=90: self.commands.append(list(cmd)) or True

    def test_entering_returns_the_ap_to_automatic_control(self):
        self.d.enter_safe_mode()
        joined = [" ".join(c) for c in self.commands]
        self.assertTrue(any("ap auto" in c for c in joined),
                        f"expected 'netdctl ap auto', got {joined}")

    def test_entering_never_pins_the_ap_open(self):
        self.d.enter_safe_mode()
        joined = [" ".join(c) for c in self.commands]
        for c in joined:
            self.assertNotIn("ap start", c,
                             "SAFE MODE must never force the AP: a pinned AP "
                             "on a single radio can never be left")

    def test_entering_keeps_ssh_and_the_portal_up(self):
        self.d.enter_safe_mode()
        joined = " ".join(" ".join(c) for c in self.commands)
        self.assertIn("ssh.service", joined)
        self.assertIn("energy-node-portal.service", joined)

    def test_entering_never_stops_the_collector(self):
        self.d.enter_safe_mode()
        joined = " ".join(" ".join(c) for c in self.commands)
        self.assertNotIn("stop", joined)
        self.assertNotIn("reboot", joined)

    def test_dry_run_actuates_nothing(self):
        self.d.enter_safe_mode(dry=True)
        self.assertEqual(self.commands, [])

    def test_leaving_does_not_fight_netd_for_the_radio(self):
        self.d.leave_safe_mode()
        self.assertEqual(self.commands, [],
                         "netd lowers the AP itself once the uplink is stable")

    def test_the_plan_matches_what_entering_actually_does(self):
        plan = " ".join(self.d.safe_mode_actions())
        self.d.enter_safe_mode()
        done = " ".join(" ".join(c) for c in self.commands)
        for token in ("ssh.service", "energy-node-portal.service", "ap auto"):
            self.assertIn(token, plan)
            self.assertIn(token, done)


class SafeModeStateMachine(unittest.TestCase):
    """Entry, retry cadence and exit, through the pure core."""

    def setUp(self):
        self.pol = P.Policy(remedy_attempts=3, reboot_max=3,
                            reboot_window_s=1800, safe_mode_retry_s=900)

    def sweep(self, **o):
        return [P.StageResult(s, o.get(s, P.OK)) for s in P.STAGE_ORDER]

    def test_entry_only_after_the_reboot_budget_is_spent(self):
        now = 10000.0
        led = P.Ledger(attempts={P.COLLECTOR: 3}, last_attempt={P.COLLECTOR: 0.0},
                       reboots=[now - 10, now - 20, now - 30])
        d = P.decide(self.sweep(collector=P.FAILED), led, now, self.pol)
        self.assertEqual(d.action, P.ENTER_SAFE_MODE)

    def test_retries_continue_on_a_fixed_cadence(self):
        now = 10000.0
        led = P.Ledger(safe_mode_since=now - 5000, safe_mode_last_retry=now - 901)
        d = P.decide(self.sweep(collector=P.FAILED), led, now, self.pol)
        self.assertEqual(d.action, P.REMEDY)

    def test_it_waits_between_retries_rather_than_spinning(self):
        now = 10000.0
        led = P.Ledger(safe_mode_since=now - 5000, safe_mode_last_retry=now - 10)
        d = P.decide(self.sweep(collector=P.FAILED), led, now, self.pol)
        self.assertEqual(d.action, P.WAIT)

    def test_exit_is_automatic_the_moment_every_stage_is_healthy(self):
        led = P.Ledger(safe_mode_since=1000.0, safe_mode_last_retry=1000.0)
        d = P.decide(self.sweep(), led, 5000.0, self.pol)
        self.assertEqual(d.action, P.LEAVE_SAFE_MODE)

    def test_exit_needs_no_human_and_no_retry_window(self):
        # Healthy one second after entering: it must still leave immediately.
        led = P.Ledger(safe_mode_since=1000.0, safe_mode_last_retry=1000.0)
        d = P.decide(self.sweep(), led, 1001.0, self.pol)
        self.assertEqual(d.action, P.LEAVE_SAFE_MODE)

    def test_safe_mode_state_persists_in_the_ledger(self):
        from recovery import ledger as L
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "l.json")
        L.save(P.Ledger(safe_mode_since=1234.0, safe_mode_last_retry=1250.0), path)
        back = L.load(path)
        self.assertEqual(back.safe_mode_since, 1234.0)
        self.assertEqual(back.safe_mode_last_retry, 1250.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class ZeroRebootBudget(unittest.TestCase):
    """A budget of 0 reaches SAFE MODE through the real ladder, with no reboot.

    This is what makes an honest end-to-end validation possible on a node that
    must not be rebooted: the fault, the remedies and the escalation are all
    genuine, only the reboot rung is removed.
    """

    def sweep(self, **o):
        return [P.StageResult(s, o.get(s, P.OK)) for s in P.STAGE_ORDER]

    def test_exhausted_remedies_go_straight_to_safe_mode(self):
        pol = P.Policy(remedy_attempts=3, reboot_max=0)
        led = P.Ledger(attempts={P.COLLECTOR: 3}, last_attempt={P.COLLECTOR: 0.0})
        d = P.decide(self.sweep(collector=P.FAILED), led, 10000.0, pol)
        self.assertEqual(d.action, P.ENTER_SAFE_MODE)

    def test_remedies_still_run_first(self):
        pol = P.Policy(remedy_attempts=3, reboot_max=0)
        d = P.decide(self.sweep(collector=P.FAILED), P.Ledger(), 10000.0, pol)
        self.assertEqual(d.action, P.REMEDY)

    def test_no_reboot_is_ever_chosen(self):
        pol = P.Policy(remedy_attempts=2, reboot_max=0)
        led = P.Ledger()
        now = 0.0
        for _ in range(200):
            now += 60
            d = P.decide(self.sweep(collector=P.FAILED), led, now, pol)
            self.assertNotEqual(d.action, P.REBOOT)
            if d.action == P.REMEDY:
                led.attempts[P.COLLECTOR] = led.attempts.get(P.COLLECTOR, 0) + 1
                led.last_attempt[P.COLLECTOR] = now
                if led.safe_mode_since:
                    led.safe_mode_last_retry = now
            elif d.action == P.ENTER_SAFE_MODE:
                led.safe_mode_since = now
                led.safe_mode_last_retry = now
        self.assertIsNotNone(led.safe_mode_since)
