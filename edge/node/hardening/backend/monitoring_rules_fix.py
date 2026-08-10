"""Backend fix: null is not a state.

DEPLOYMENT BLOCKED — no SSH access to the backend host. Unit-tested locally,
never executed against the running service.

THE DEFECT CLASS
    This platform has two rules that both mishandle a missing value, in
    opposite directions:

      node.heartbeat_lost      heartbeat_age_seconds is NULL
                               -> treated as HEALTHY
                               -> silently never fires
                               -> N001 offline 43h37m, nobody told

      node.filesystem_readonly filesystem_readonly is NULL
                               -> treated as READ-ONLY
                               -> fires CRITICAL forever
                               -> "The SD card has almost certainly failed"
                                  while / was rw and writable

    Both are the same bug: a two-valued test applied to three-valued data. A
    monitoring system that cannot say "I don't know" will either cry wolf or
    stay silent. This one does both.

THE FIX
    Make the third state explicit. UNKNOWN never asserts a fault and never
    asserts health; it suppresses the alert and, once the value has been
    missing longer than a grace period, raises a distinct low-severity
    staleness alert so a field that stops being reported is still noticed.
"""

from __future__ import annotations

import enum
from typing import Any, Optional


class Tri(enum.Enum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"

    def __bool__(self):
        raise TypeError(
            "Tri must not be used in a boolean context — that is exactly the "
            "bug this class exists to prevent. Compare explicitly against "
            "Tri.TRUE / Tri.FALSE / Tri.UNKNOWN.")


def tri_state(value: Any) -> Tri:
    """Map a reported field onto three states.

    Only a real boolean (or an unambiguous textual/numeric equivalent) yields
    TRUE/FALSE. None, missing, empty string and unparseable input all yield
    UNKNOWN — never a silent default in either direction.
    """
    if value is None:
        return Tri.UNKNOWN
    if isinstance(value, bool):
        return Tri.TRUE if value else Tri.FALSE
    if isinstance(value, (int, float)):
        return Tri.TRUE if value else Tri.FALSE
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("true", "1", "yes", "on", "ro", "read-only", "readonly"):
            return Tri.TRUE
        if v in ("false", "0", "no", "off", "rw", "read-write"):
            return Tri.FALSE
        return Tri.UNKNOWN
    return Tri.UNKNOWN


class RuleOutcome:
    """What a boolean rule decided, and why."""

    FIRE = "fire"
    CLEAR = "clear"
    STALE = "stale"        # value unknown for longer than the grace period
    SKIP = "skip"          # value unknown, still inside the grace period

    def __init__(self, action: str, severity: Optional[str] = None,
                 reason: str = ""):
        self.action = action
        self.severity = severity
        self.reason = reason

    def __repr__(self):
        return f"RuleOutcome({self.action}, {self.severity}, {self.reason!r})"

    def __eq__(self, other):
        return (isinstance(other, RuleOutcome)
                and (self.action, self.severity) == (other.action, other.severity))


def evaluate_boolean_rule(value: Any,
                          fire_on: Tri = Tri.TRUE,
                          severity: str = "CRITICAL",
                          unknown_age_seconds: Optional[float] = None,
                          unknown_grace_seconds: float = 900.0,
                          stale_severity: str = "WARNING",
                          field: str = "field") -> RuleOutcome:
    """Evaluate a boolean health field without ever guessing.

    value                  the reported value (may be None/missing)
    fire_on                which concrete state constitutes a fault
    unknown_age_seconds    how long the value has been UNKNOWN, if known
    unknown_grace_seconds  how long UNKNOWN is tolerated before flagging

    NEVER returns FIRE for an UNKNOWN value. That is the whole point.
    """
    state = tri_state(value)

    if state is Tri.UNKNOWN:
        if (unknown_age_seconds is not None
                and unknown_age_seconds > unknown_grace_seconds):
            return RuleOutcome(
                RuleOutcome.STALE, stale_severity,
                f"{field} has not been reported for "
                f"{unknown_age_seconds:.0f}s — cannot evaluate. This is a "
                f"reporting gap, NOT a confirmed fault.")
        return RuleOutcome(
            RuleOutcome.SKIP, None,
            f"{field} not reported; within grace period, no assertion made")

    if state is fire_on:
        return RuleOutcome(RuleOutcome.FIRE, severity,
                           f"{field} is {state.value}")
    return RuleOutcome(RuleOutcome.CLEAR, None, f"{field} is {state.value}")


# ---------------------------------------------------------------- rules
def rule_filesystem_readonly(heartbeat: dict,
                             unknown_age_seconds: Optional[float] = None
                             ) -> RuleOutcome:
    """node.filesystem_readonly — fires ONLY on a confirmed read-only mount.

    Before: NULL (which was always the case, because the field was never
    persisted) mapped to read-only, producing a permanent CRITICAL claiming
    "The SD card has almost certainly failed" on a healthy node.
    """
    return evaluate_boolean_rule(
        heartbeat.get("filesystem_readonly"),
        fire_on=Tri.TRUE, severity="CRITICAL",
        unknown_age_seconds=unknown_age_seconds,
        field="filesystem_readonly")


def rule_undervoltage(heartbeat: dict,
                      unknown_age_seconds: Optional[float] = None
                      ) -> RuleOutcome:
    """node.undervoltage — fires on a confirmed undervoltage report."""
    return evaluate_boolean_rule(
        heartbeat.get("undervoltage"),
        fire_on=Tri.TRUE, severity="ERROR",
        unknown_age_seconds=unknown_age_seconds,
        field="undervoltage")


def rule_heartbeat_liveness(node: dict,
                            interval_seconds: float = 60.0,
                            missed_warning: int = 2,
                            missed_error: int = 5,
                            missed_critical: int = 10,
                            missed_emergency: int = 30) -> RuleOutcome:
    """node.heartbeat_lost — must distinguish 'never seen' from 'seen, fine'.

    Before: heartbeat_age_seconds NULL was treated as healthy, so a node that
    had never checked in stayed silent forever. N001 sat at ever_seen=false /
    missed_beats=0 while it was dead for 43h37m, and the only rule that did
    fire asserted "heartbeats are arriving normally".

    A registered node that has NEVER been seen is not healthy — it is
    unmonitored, which is its own fault condition and must escalate rather
    than sit at WARNING forever.
    """
    age = node.get("heartbeat_age_seconds")
    ever_seen = node.get("ever_seen")

    if tri_state(ever_seen) is Tri.FALSE or age is None:
        registered_for = node.get("registered_age_seconds")
        if registered_for is not None and registered_for > 3 * interval_seconds:
            return RuleOutcome(
                RuleOutcome.FIRE, "CRITICAL",
                "node is registered and monitored but has NEVER sent a "
                "heartbeat — liveness monitoring is not functioning for it")
        return RuleOutcome(RuleOutcome.SKIP, None,
                           "registered recently; awaiting first heartbeat")

    missed = int(age // interval_seconds)
    if missed >= missed_emergency:
        return RuleOutcome(RuleOutcome.FIRE, "EMERGENCY", f"{missed} missed")
    if missed >= missed_critical:
        return RuleOutcome(RuleOutcome.FIRE, "CRITICAL", f"{missed} missed")
    if missed >= missed_error:
        return RuleOutcome(RuleOutcome.FIRE, "ERROR", f"{missed} missed")
    if missed >= missed_warning:
        return RuleOutcome(RuleOutcome.FIRE, "WARNING", f"{missed} missed")
    return RuleOutcome(RuleOutcome.CLEAR, None, f"age {age:.0f}s")


def summary_for_measurements_stale(node: dict) -> str:
    """Text for node.measurements_stale that cannot lie about liveness.

    The 2026-08-01 alert said "Heartbeats are arriving normally, so the
    machine and its network are fine" while the machine was dead. It said that
    because heartbeat state was NULL and the template's else-branch assumed
    health. The summary must reflect what is actually known.
    """
    age = node.get("heartbeat_age_seconds")
    if tri_state(node.get("ever_seen")) is Tri.FALSE or age is None:
        return ("Measurements have stopped. Node liveness is UNKNOWN — this "
                "node has never delivered a heartbeat, so we cannot tell "
                "whether the machine is up. Check the node directly.")
    if age > 180:
        return (f"Measurements have stopped AND the last heartbeat was "
                f"{age:.0f}s ago. The node itself is probably down.")
    return ("Heartbeats are arriving normally, so the machine and its network "
            "are fine. The measurement path specifically has stopped.")
