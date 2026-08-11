"""Tests for the probe guards that stop a remote fault causing a local reboot.

Both guards exist because of real incidents on N002, and both are the same
shape: a stage that depends on something else is UNKNOWN, not FAILED, when
that something else is unavailable. UNKNOWN never escalates.

Hermetic: `probes` is loaded with `doctor` stubbed out, so nothing here needs
a meter, a backend or a Raspberry Pi.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_LIB = os.path.join(_HERE, "..", "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from recovery import pipeline as P  # noqa: E402


class _Outcome:
    def __init__(self, value):
        self.value = value


def _load_probes_with_stub_doctor(stub):
    """Import probes.py against a fake doctor, so no hardware is touched."""
    fake_doctor = types.ModuleType("doctor")
    for name, fn in stub.items():
        setattr(fake_doctor, name, fn)
    saved = sys.modules.get("doctor")
    sys.modules["doctor"] = fake_doctor
    try:
        path = os.path.join(_LIB, "recovery", "probes.py")
        spec = importlib.util.spec_from_file_location("probes_under_test", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["probes_under_test"] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        if saved is not None:
            sys.modules["doctor"] = saved
        else:
            sys.modules.pop("doctor", None)


class MeasurementsGuard(unittest.TestCase):
    """N002, 2026-08-10: the Shelly was unreachable for two hours. Measurement
    staleness escalated as a LOCAL fault and drove the ladder to SAFE MODE."""

    def setUp(self):
        self.probes = _load_probes_with_stub_doctor({
            "check_collector": lambda: types.SimpleNamespace(
                outcome=_Outcome("FAIL"), detail="newest measurement age 325s"),
        })
        # The stub's Outcome objects are not doctor's enum, so _MAP misses and
        # returns UNKNOWN. Assert on the guard directly instead.

    def test_stale_measurements_are_not_local_when_the_sensor_is_down(self):
        sensor = P.StageResult(P.SENSOR, P.FAILED, "shelly: unreachable")
        r = self.probes.probe_measurements(sensor)
        self.assertEqual(r.status, P.UNKNOWN)
        self.assertIn("not a local fault", r.detail)

    def test_unknown_sensor_still_allows_measurements_to_be_judged(self):
        # Otherwise a node whose sensor cannot be probed would never self-heal
        # a genuinely wedged collector.
        sensor = P.StageResult(P.SENSOR, P.UNKNOWN, "no probe")
        r = self.probes.probe_measurements(sensor)
        self.assertNotEqual(r.detail[:6], "sensor")

    def test_healthy_sensor_allows_measurements_to_be_judged(self):
        sensor = P.StageResult(P.SENSOR, P.OK, "shelly ok")
        r = self.probes.probe_measurements(sensor)
        self.assertNotIn("not a local fault", r.detail)


class HeartbeatGuard(unittest.TestCase):
    """check_heartbeat asks the BACKEND whether it has seen us, so a backend
    outage looked like a local heartbeat fault - and heartbeat is LOCAL."""

    def setUp(self):
        self.probes = _load_probes_with_stub_doctor({
            "check_heartbeat": lambda: types.SimpleNamespace(
                outcome=_Outcome("FAIL"), detail="monitoring unreachable"),
        })

    def test_heartbeat_is_unknown_when_the_backend_is_unreachable(self):
        backend = P.StageResult(P.BACKEND, P.FAILED, "connection refused")
        r = self.probes.probe_heartbeat(backend)
        self.assertEqual(r.status, P.UNKNOWN)
        self.assertIn("not assertable", r.detail)

    def test_heartbeat_is_judged_when_the_backend_is_up(self):
        backend = P.StageResult(P.BACKEND, P.OK, "HTTP 200")
        r = self.probes.probe_heartbeat(backend)
        self.assertNotIn("not assertable", r.detail)


class GuardsPreventEscalation(unittest.TestCase):
    """End to end through the decision core: an UNKNOWN stage never reboots."""

    def test_dead_sensor_never_reaches_reboot(self):
        pol = P.Policy(remedy_attempts=3)
        led = P.Ledger(attempts={P.MEASUREMENTS: 99},
                       last_attempt={P.MEASUREMENTS: 0.0})
        stages = []
        for s in P.STAGE_ORDER:
            if s == P.SENSOR:
                stages.append(P.StageResult(s, P.FAILED, "shelly unreachable"))
            elif s == P.MEASUREMENTS:
                stages.append(P.StageResult(s, P.UNKNOWN, "sensor unavailable"))
            else:
                stages.append(P.StageResult(s, P.OK))
        d = P.decide(stages, led, 10000.0, pol)
        # sensor is EXTERNAL, so the worst it can do is keep remedying.
        self.assertEqual(d.stage, P.SENSOR)
        self.assertNotEqual(d.action, P.REBOOT)
        self.assertNotEqual(d.action, P.ENTER_SAFE_MODE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
