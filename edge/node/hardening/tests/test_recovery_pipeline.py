"""Unit tests for the recovery decision core.

Hermetic: no node, no radio, no meter, no reboot, no clock. `pipeline` is
loaded straight from its file so the recovery package's hardware-facing
`__init__` (smbus2, psutil, vcgencmd) is never imported.

Run:  python3 -m unittest discover -s edge/node/hardening/tests -t . -v
"""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PIPELINE = os.path.join(_HERE, "..", "lib", "recovery", "pipeline.py")

_spec = importlib.util.spec_from_file_location("recovery_pipeline", _PIPELINE)
assert _spec and _spec.loader
p = importlib.util.module_from_spec(_spec)
# dataclasses resolves annotations via sys.modules, so register before exec.
sys.modules["recovery_pipeline"] = p
_spec.loader.exec_module(p)


def results(**overrides):
    """Every stage OK unless overridden: results(collector=p.FAILED)."""
    out = []
    for stage in p.STAGE_ORDER:
        status = overrides.get(stage, p.OK)
        out.append(p.StageResult(stage, status))
    return out


class FirstFailure(unittest.TestCase):
    def test_none_when_all_ok(self):
        self.assertIsNone(p.first_failure(results()))

    def test_returns_earliest_stage_in_dependency_order(self):
        r = results(collector=p.FAILED, clock=p.FAILED)
        self.assertEqual(p.first_failure(r).stage, p.CLOCK)

    def test_unknown_is_not_a_failure(self):
        # A stage with no data source must never trigger recovery.
        r = results(sensor=p.UNKNOWN, tailscale=p.UNKNOWN)
        self.assertIsNone(p.first_failure(r))

    def test_missing_stage_is_not_a_failure(self):
        self.assertIsNone(p.first_failure([p.StageResult(p.CLOCK, p.OK)]))


class Backoff(unittest.TestCase):
    def test_grows_exponentially_then_caps(self):
        pol = p.Policy(remedy_backoff_initial=30, remedy_backoff_max=300)
        self.assertEqual(p.backoff_for(0, pol), 30)
        self.assertEqual(p.backoff_for(1, pol), 60)
        self.assertEqual(p.backoff_for(2, pol), 120)
        self.assertEqual(p.backoff_for(9, pol), 300)


class HealthyPath(unittest.TestCase):
    def test_healthy_does_nothing(self):
        d = p.decide(results(), p.Ledger(), 1000.0, p.Policy())
        self.assertEqual((d.state, d.action), (p.HEALTHY, p.NONE))


class LocalEscalation(unittest.TestCase):
    def setUp(self):
        self.pol = p.Policy(remedy_attempts=3, reboot_max=3, reboot_window_s=1800)

    def test_first_local_failure_is_a_service_remedy_not_a_reboot(self):
        d = p.decide(results(collector=p.FAILED), p.Ledger(), 1000.0, self.pol)
        self.assertEqual(d.action, p.REMEDY)
        self.assertEqual(d.stage, p.COLLECTOR)
        self.assertEqual(d.state, p.RECOVERING)

    def test_backoff_is_respected_between_remedies(self):
        led = p.Ledger(attempts={p.COLLECTOR: 1}, last_attempt={p.COLLECTOR: 1000.0})
        d = p.decide(results(collector=p.FAILED), led, 1005.0, self.pol)
        self.assertEqual(d.action, p.WAIT)

    def test_remedy_resumes_after_backoff(self):
        led = p.Ledger(attempts={p.COLLECTOR: 1}, last_attempt={p.COLLECTOR: 1000.0})
        d = p.decide(results(collector=p.FAILED), led, 1000.0 + 31, self.pol)
        self.assertEqual(d.action, p.REMEDY)

    def test_reboots_only_after_remedies_are_exhausted(self):
        led = p.Ledger(attempts={p.COLLECTOR: 3}, last_attempt={p.COLLECTOR: 0.0})
        d = p.decide(results(collector=p.FAILED), led, 10000.0, self.pol)
        self.assertEqual(d.action, p.REBOOT)

    def test_safe_mode_when_reboot_budget_is_exhausted(self):
        now = 10000.0
        led = p.Ledger(
            attempts={p.COLLECTOR: 3},
            last_attempt={p.COLLECTOR: 0.0},
            reboots=[now - 100, now - 200, now - 300],
        )
        d = p.decide(results(collector=p.FAILED), led, now, self.pol)
        self.assertEqual(d.action, p.ENTER_SAFE_MODE)

    def test_reboot_budget_is_a_rolling_window(self):
        # Three reboots, but all older than the window: budget is available.
        now = 10000.0
        led = p.Ledger(
            attempts={p.COLLECTOR: 3},
            last_attempt={p.COLLECTOR: 0.0},
            reboots=[now - 5000, now - 6000, now - 7000],
        )
        d = p.decide(results(collector=p.FAILED), led, now, self.pol)
        self.assertEqual(d.action, p.REBOOT)

    def test_filesystem_failure_outranks_a_later_stage(self):
        led = p.Ledger(attempts={p.FILESYSTEM: 3}, last_attempt={p.FILESYSTEM: 0.0})
        d = p.decide(results(filesystem=p.FAILED, collector=p.FAILED), led, 10000.0, self.pol)
        self.assertEqual(d.stage, p.FILESYSTEM)


class ExternalNeverReboots(unittest.TestCase):
    """A node must not turn somebody else's outage into its own reboot loop."""

    def test_backend_down_never_escalates_however_many_attempts(self):
        pol = p.Policy(remedy_attempts=3)
        led = p.Ledger(attempts={p.BACKEND: 99}, last_attempt={p.BACKEND: 0.0})
        d = p.decide(results(backend=p.FAILED), led, 10000.0, pol)
        self.assertEqual(d.action, p.REMEDY)
        self.assertEqual(d.state, p.DEGRADED)

    def test_sensor_down_never_escalates_by_default(self):
        led = p.Ledger(attempts={p.SENSOR: 99}, last_attempt={p.SENSOR: 0.0})
        d = p.decide(results(sensor=p.FAILED), led, 10000.0, p.Policy())
        self.assertEqual(d.action, p.REMEDY)

    def test_sensor_can_be_reclassified_local_for_on_board_hardware(self):
        # ADS1256 lives on the Pi's SPI bus, so a reboot IS a plausible remedy.
        pol = p.Policy(stage_class={**p.DEFAULT_STAGE_CLASS, p.SENSOR: p.LOCAL})
        led = p.Ledger(attempts={p.SENSOR: 3}, last_attempt={p.SENSOR: 0.0})
        d = p.decide(results(sensor=p.FAILED), led, 10000.0, pol)
        self.assertEqual(d.action, p.REBOOT)


class SafeMode(unittest.TestCase):
    def setUp(self):
        self.pol = p.Policy(safe_mode_retry_s=900, safe_mode_reboot_after_s=21600)

    def test_waits_between_periodic_attempts(self):
        now = 10000.0
        led = p.Ledger(safe_mode_since=now - 100, safe_mode_last_retry=now - 100)
        d = p.decide(results(collector=p.FAILED), led, now, self.pol)
        self.assertEqual((d.state, d.action), (p.SAFE_MODE, p.WAIT))

    def test_retries_recovery_periodically_forever(self):
        now = 10000.0
        led = p.Ledger(safe_mode_since=now - 1000, safe_mode_last_retry=now - 901)
        d = p.decide(results(collector=p.FAILED), led, now, self.pol)
        self.assertEqual((d.state, d.action), (p.SAFE_MODE, p.REMEDY))

    def test_leaves_safe_mode_once_healthy(self):
        led = p.Ledger(safe_mode_since=5000.0)
        d = p.decide(results(), led, 10000.0, self.pol)
        self.assertEqual(d.action, p.LEAVE_SAFE_MODE)

    def test_no_reboot_before_the_long_cooldown(self):
        now = 10000.0
        led = p.Ledger(safe_mode_since=now - 3600, safe_mode_last_retry=now - 901)
        d = p.decide(results(collector=p.FAILED), led, now, self.pol)
        self.assertEqual(d.action, p.REMEDY)  # not REBOOT

    def test_one_more_reboot_after_the_long_cooldown(self):
        now = 100000.0
        led = p.Ledger(safe_mode_since=now - 21601, safe_mode_last_retry=now - 901)
        d = p.decide(results(collector=p.FAILED), led, now, self.pol)
        self.assertEqual(d.action, p.REBOOT)

    def test_cooldown_reboot_still_respects_the_rolling_budget(self):
        now = 100000.0
        led = p.Ledger(
            safe_mode_since=now - 21601,
            safe_mode_last_retry=now - 901,
            reboots=[now - 10, now - 20, now - 30],
        )
        d = p.decide(results(collector=p.FAILED), led, now, self.pol)
        self.assertEqual(d.action, p.REMEDY)

    def test_external_failure_in_safe_mode_never_reboots(self):
        now = 100000.0
        led = p.Ledger(safe_mode_since=now - 99999, safe_mode_last_retry=now - 901)
        d = p.decide(results(backend=p.FAILED), led, now, self.pol)
        self.assertEqual(d.action, p.REMEDY)


class NeverGivesUp(unittest.TestCase):
    """The property the whole design exists to guarantee."""

    def test_safe_mode_always_produces_an_action_eventually(self):
        pol = p.Policy()
        led = p.Ledger(safe_mode_since=0.0, safe_mode_last_retry=0.0)
        # Simulate a week parked in SAFE MODE; an attempt must keep occurring.
        acted = 0
        now = 0.0
        for _ in range(7 * 24 * 4):  # a week in 15-minute ticks
            now += 900
            d = p.decide(results(collector=p.FAILED), led, now, pol)
            self.assertEqual(d.state, p.SAFE_MODE)
            if d.action in (p.REMEDY, p.REBOOT):
                acted += 1
                led.safe_mode_last_retry = now
                if d.action == p.REBOOT:
                    led.reboots.append(now)
                    led.safe_mode_last_reboot = now
        self.assertGreater(acted, 100, "SAFE MODE must keep trying, forever")

    def test_no_infinite_reboot_loop(self):
        """Over a simulated week the node must not reboot without bound."""
        pol = p.Policy()
        led = p.Ledger()
        now = 0.0
        reboots = 0
        for _ in range(7 * 24 * 60):  # a week in 1-minute ticks
            now += 60
            d = p.decide(results(collector=p.FAILED), led, now, pol)
            if d.action == p.REMEDY:
                led.attempts[d.stage] = led.attempts.get(d.stage, 0) + 1
                led.last_attempt[d.stage] = now
            elif d.action == p.REBOOT:
                reboots += 1
                led.reboots.append(now)
                led.attempts[d.stage] = 0
                if led.safe_mode_since is not None:
                    led.safe_mode_last_reboot = now
                    led.safe_mode_last_retry = now
            elif d.action == p.ENTER_SAFE_MODE:
                led.safe_mode_since = now
                led.safe_mode_last_retry = now
            elif d.action == p.WAIT and led.safe_mode_since is None:
                pass
        # 3 in the first window, then SAFE MODE with one per 6h cooldown.
        self.assertLessEqual(reboots, 3 + 7 * 4, f"reboot loop: {reboots} reboots/week")
        self.assertGreater(reboots, 0, "must have tried rebooting at least once")


if __name__ == "__main__":
    unittest.main(verbosity=2)
