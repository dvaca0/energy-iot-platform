"""Regression tests for the null-is-not-a-state fix.

Run:  python3 -m pytest /opt/energy-node/hardening/backend/tests -v
      (or: python3 test_monitoring_rules.py  — falls back to a plain runner)

These are pure functions; no backend required. The commands that DO require a
deployed backend are listed in ../README.md and must be run after deployment.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitoring_rules_fix import (  # noqa: E402
    Tri, tri_state, RuleOutcome, evaluate_boolean_rule,
    rule_filesystem_readonly, rule_undervoltage, rule_heartbeat_liveness,
    summary_for_measurements_stale,
)

FIRE, CLEAR, STALE, SKIP = (RuleOutcome.FIRE, RuleOutcome.CLEAR,
                            RuleOutcome.STALE, RuleOutcome.SKIP)


# ------------------------------------------------------------ tri_state
def test_tri_state_booleans():
    assert tri_state(True) is Tri.TRUE
    assert tri_state(False) is Tri.FALSE


def test_tri_state_unknown_variants():
    # Every way the value can be absent must land on UNKNOWN, never a default.
    for v in (None, "", "  ", "maybe", [], {}, object()):
        assert tri_state(v) is Tri.UNKNOWN, f"{v!r} should be UNKNOWN"


def test_tri_state_strings():
    for v in ("true", "TRUE", "1", "yes", "on", "ro", "read-only", "readonly"):
        assert tri_state(v) is Tri.TRUE, v
    for v in ("false", "0", "no", "off", "rw", "read-write"):
        assert tri_state(v) is Tri.FALSE, v


def test_tri_cannot_be_used_as_bool():
    """The original bug was `if value:` — make that impossible."""
    try:
        bool(Tri.UNKNOWN)
    except TypeError:
        return
    raise AssertionError("Tri must refuse boolean coercion")


# --------------------------------------------- filesystem_readonly (Part 2)
def test_filesystem_false_does_not_alert():
    """THE REGRESSION. N001 sent false and got CRITICAL 'SD card has failed'."""
    out = rule_filesystem_readonly({"filesystem_readonly": False})
    assert out.action == CLEAR, out


def test_filesystem_true_still_alerts():
    """The fix must not suppress a genuine fault."""
    out = rule_filesystem_readonly({"filesystem_readonly": True})
    assert out.action == FIRE and out.severity == "CRITICAL", out


def test_filesystem_null_does_not_alert():
    out = rule_filesystem_readonly({"filesystem_readonly": None})
    assert out.action == SKIP, out
    assert out.severity is None


def test_filesystem_missing_key_does_not_alert():
    out = rule_filesystem_readonly({})
    assert out.action == SKIP, out


def test_filesystem_null_becomes_stale_not_critical():
    """Missing for a long time is a REPORTING GAP, not a confirmed fault."""
    out = rule_filesystem_readonly({}, unknown_age_seconds=3600)
    assert out.action == STALE
    assert out.severity == "WARNING"        # not CRITICAL
    assert "NOT a confirmed fault" in out.reason


def test_filesystem_all_unknown_forms_agree():
    """false / null / missing must NOT all produce the same alarming outcome.

    Before the fix they did — that is precisely the reported bug.
    """
    false_out = rule_filesystem_readonly({"filesystem_readonly": False})
    null_out = rule_filesystem_readonly({"filesystem_readonly": None})
    missing_out = rule_filesystem_readonly({})
    assert false_out.action == CLEAR
    assert null_out.action == SKIP
    assert missing_out.action == SKIP
    # and crucially none of them fire
    assert all(o.action != FIRE for o in (false_out, null_out, missing_out))


def test_filesystem_string_forms():
    assert rule_filesystem_readonly({"filesystem_readonly": "ro"}).action == FIRE
    assert rule_filesystem_readonly({"filesystem_readonly": "rw"}).action == CLEAR


# ------------------------------------------------------------ undervoltage
def test_undervoltage_true_fires_error():
    out = rule_undervoltage({"undervoltage": True})
    assert out.action == FIRE and out.severity == "ERROR"


def test_undervoltage_false_clears():
    assert rule_undervoltage({"undervoltage": False}).action == CLEAR


def test_undervoltage_null_does_not_fire():
    assert rule_undervoltage({"undervoltage": None}).action == SKIP


# --------------------------------------------- heartbeat liveness (Part 1)
def test_heartbeat_never_seen_escalates():
    """THE 43h37m BUG. ever_seen=false previously stayed a quiet WARNING."""
    out = rule_heartbeat_liveness(
        {"ever_seen": False, "heartbeat_age_seconds": None,
         "registered_age_seconds": 86400})
    assert out.action == FIRE
    assert out.severity == "CRITICAL"
    assert "NEVER sent a heartbeat" in out.reason


def test_heartbeat_never_seen_but_just_registered_is_patient():
    out = rule_heartbeat_liveness(
        {"ever_seen": False, "heartbeat_age_seconds": None,
         "registered_age_seconds": 30})
    assert out.action == SKIP


def test_heartbeat_null_age_is_not_treated_as_healthy():
    """The original defect: NULL age fell through to 'healthy'."""
    out = rule_heartbeat_liveness(
        {"ever_seen": True, "heartbeat_age_seconds": None,
         "registered_age_seconds": 86400})
    assert out.action != CLEAR, "NULL age must never read as healthy"


def test_heartbeat_escalation_ladder():
    for age, sev in ((0, None), (60, None), (120, "WARNING"),
                     (300, "ERROR"), (600, "CRITICAL"), (1800, "EMERGENCY")):
        out = rule_heartbeat_liveness(
            {"ever_seen": True, "heartbeat_age_seconds": age})
        assert out.severity == sev, f"age={age} -> {out}"


# ------------------------------------------------- misleading summary text
def test_summary_does_not_claim_health_when_liveness_unknown():
    """The Aug 1 alert said the machine was fine while it was dead."""
    s = summary_for_measurements_stale(
        {"ever_seen": False, "heartbeat_age_seconds": None})
    assert "fine" not in s
    assert "UNKNOWN" in s


def test_summary_reports_node_down_when_heartbeat_old():
    s = summary_for_measurements_stale(
        {"ever_seen": True, "heartbeat_age_seconds": 4000})
    assert "probably down" in s


def test_summary_keeps_original_text_when_genuinely_alive():
    s = summary_for_measurements_stale(
        {"ever_seen": True, "heartbeat_age_seconds": 20})
    assert "measurement path specifically has stopped" in s


# ------------------------------------------------------------ generic rule
def test_unknown_never_fires_regardless_of_grace():
    for age in (0, 10, 1e9):
        out = evaluate_boolean_rule(None, unknown_age_seconds=age)
        assert out.action != FIRE, f"UNKNOWN must never FIRE (age={age})"


if __name__ == "__main__":
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception as exc:
            failed += 1
            print(f"  FAIL  {name}: {exc}")
    print(f"\n  {len(fns)} tests, {len(fns)-failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
