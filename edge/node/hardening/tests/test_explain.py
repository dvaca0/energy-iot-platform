"""Tests for the plain-language explainer. Pure: dicts in, lines out."""

from __future__ import annotations

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_LIB = os.path.join(_HERE, "..", "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from recovery import explain  # noqa: E402
from recovery import pipeline as P  # noqa: E402


def health(state, first_failure=None, action=P.NONE, reason="", **kw):
    return {
        "state": state,
        "first_failure": first_failure,
        "decision": {"action": action, "stage": first_failure, "reason": reason},
        "stages": [{"stage": first_failure, "status": P.FAILED,
                    "detail": kw.get("detail", "")}] if first_failure else [],
        "ledger": {"reboots_last_window": kw.get("used", 0)},
        "observe_only": kw.get("observe_only", False),
    }


class Explain(unittest.TestCase):
    def test_no_state_published_says_so(self):
        lines = explain.explain(None)
        self.assertIn("has not published any state", " ".join(lines))

    def test_healthy_is_a_first_class_answer(self):
        lines = explain.explain(health(P.HEALTHY))
        self.assertTrue(lines[0].startswith("The node is HEALTHY"))

    def test_healthy_without_a_measured_time_does_not_say_unknown(self):
        lines = explain.explain(
            health(P.HEALTHY), boot={"boot_complete": 1,
                                     "time_to_healthy_s": None})
        joined = " ".join(lines)
        self.assertNotIn("in unknown", joined)
        self.assertIn("not measured", joined)

    def test_local_failure_explains_escalation(self):
        lines = explain.explain(
            health(P.RECOVERING, P.COLLECTOR, P.REMEDY, "remedy 1/3"),
            boot={"failure_owner": "LOCAL", "service_restarts": 1,
                  "reboot_attempts": 0, "safe_mode_entered": 0})
        joined = " ".join(lines)
        self.assertIn("collector service is not running", joined)
        self.assertIn("Owner: LOCAL", joined)
        self.assertIn("reboot", joined)

    def test_external_failure_promises_no_reboot(self):
        lines = explain.explain(
            health(P.DEGRADED, P.BACKEND, P.REMEDY, "external"),
            boot={"failure_owner": "EXTERNAL"})
        joined = " ".join(lines)
        self.assertIn("backend server cannot be reached", joined)
        self.assertIn("never reboot", joined)

    def test_safe_mode_says_it_is_not_permanent(self):
        lines = explain.explain(
            health(P.SAFE_MODE, P.COLLECTOR, P.WAIT, "waiting"),
            boot={"failure_owner": "LOCAL", "safe_mode_entered": 1})
        joined = " ".join(lines)
        self.assertIn("SAFE MODE", joined)
        self.assertIn("not permanent", joined)
        self.assertIn("forever", joined)

    def test_observe_only_is_called_out(self):
        lines = explain.explain(
            health(P.RECOVERING, P.COLLECTOR, P.REMEDY, "r", observe_only=True))
        self.assertIn("OBSERVE-ONLY", " ".join(lines))

    def test_every_stage_has_human_wording(self):
        for stage in P.STAGE_ORDER:
            self.assertIn(stage, explain.HUMAN, f"{stage} has no plain-English text")
