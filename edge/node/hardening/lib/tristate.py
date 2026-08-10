"""Tri-state evaluation — NULL is not a state.

THE ARCHITECTURAL DEFECT THIS FIXES
    The platform had two rules that both mishandled a missing value, in
    opposite directions:

      node.heartbeat_lost       heartbeat_age_seconds NULL
                                -> treated as HEALTHY
                                -> silently never fired
                                -> N001 offline 43h37m, nobody told

      node.filesystem_readonly  filesystem_readonly NULL (never persisted)
                                -> treated as READ-ONLY
                                -> permanent CRITICAL "the SD card has almost
                                   certainly failed" on a healthy node

    Same bug: a two-valued test applied to three-valued data. A monitoring
    system that cannot say "I don't know" will either cry wolf or stay silent.
    This one did both.

THE RULE
    Every optional field resolves to exactly TRUE, FALSE or UNKNOWN.
    UNKNOWN is never silently coerced. It suppresses the assertion and, once
    the value has been missing longer than a grace period, raises a distinct
    low-severity WARN — so a field that stops being reported is still noticed,
    without inventing a fault that was never observed.

STDLIB ONLY — shared by the node (telemetry, doctor) and the backend patch, so
there is exactly one implementation of this logic in the platform.
"""

from __future__ import annotations

import enum
from typing import Any, Optional

__version__ = "1.0.0"


class Tri(enum.Enum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"

    def __bool__(self):
        raise TypeError(
            "Tri must not be used in a boolean context — that implicit "
            "coercion is exactly the bug this class exists to prevent. "
            "Compare explicitly against Tri.TRUE / Tri.FALSE / Tri.UNKNOWN.")

    @property
    def known(self) -> bool:
        return self is not Tri.UNKNOWN


_TRUE_WORDS = {"true", "1", "yes", "on", "ro", "read-only", "readonly",
               "up", "active", "ok", "present"}
_FALSE_WORDS = {"false", "0", "no", "off", "rw", "read-write",
                "down", "inactive", "absent"}


def tri(value: Any) -> Tri:
    """Map any reported value onto three states. Never guesses."""
    if value is None:
        return Tri.UNKNOWN
    if isinstance(value, Tri):
        return value
    if isinstance(value, bool):
        return Tri.TRUE if value else Tri.FALSE
    if isinstance(value, (int, float)):
        return Tri.TRUE if value else Tri.FALSE
    if isinstance(value, str):
        v = value.strip().lower()
        if v in _TRUE_WORDS:
            return Tri.TRUE
        if v in _FALSE_WORDS:
            return Tri.FALSE
        return Tri.UNKNOWN
    return Tri.UNKNOWN


# --------------------------------------------------------------- outcomes
class Outcome(enum.Enum):
    PASS = "PASS"        # value known and healthy
    FAIL = "FAIL"        # value known and faulty
    WARN = "WARN"        # known but degraded, or unknown for too long
    UNKNOWN = "UNKNOWN"  # not reported, inside grace — no assertion made
    SKIP = "SKIP"        # not applicable to this hardware


class Result:
    """The outcome of evaluating one monitored value, and why."""

    __slots__ = ("subsystem", "outcome", "detail", "state", "value")

    def __init__(self, subsystem: str, outcome: Outcome, detail: str = "",
                 state: Optional[Tri] = None, value: Any = None):
        self.subsystem = subsystem
        self.outcome = outcome
        self.detail = detail
        self.state = state
        self.value = value

    @property
    def ok(self) -> bool:
        return self.outcome is not Outcome.FAIL

    def as_dict(self) -> dict:
        # `if self.state` would coerce Tri to bool — the very bug this module
        # exists to prevent, and Tri.__bool__ raises to catch it. Test for
        # None explicitly.
        return {"subsystem": self.subsystem, "outcome": self.outcome.value,
                "detail": self.detail,
                "state": self.state.value if self.state is not None else None,
                "value": self.value}

    def __repr__(self):
        return f"Result({self.subsystem}, {self.outcome.value}, {self.detail!r})"


# --------------------------------------------------------------- evaluators
def evaluate_boolean(subsystem: str, value: Any, *,
                     fail_on: Tri = Tri.TRUE,
                     unknown_age_seconds: Optional[float] = None,
                     unknown_grace_seconds: float = 900.0,
                     applicable: bool = True,
                     skip_reason: str = "",
                     label: Optional[str] = None) -> Result:
    """Evaluate an optional boolean without ever guessing.

    fail_on               which concrete state constitutes a fault
    unknown_age_seconds   how long the value has been missing, if known
    applicable            False -> SKIP (hardware genuinely lacks this)

    NEVER returns FAIL for an UNKNOWN value. That is the entire point.
    """
    name = label or subsystem
    if not applicable:
        return Result(subsystem, Outcome.SKIP,
                      skip_reason or f"{name} not applicable to this hardware",
                      Tri.UNKNOWN, value)

    state = tri(value)
    if state is Tri.UNKNOWN:
        if (unknown_age_seconds is not None
                and unknown_age_seconds > unknown_grace_seconds):
            return Result(subsystem, Outcome.WARN,
                          f"{name} not reported for {unknown_age_seconds:.0f}s "
                          f"— cannot evaluate. Reporting gap, NOT a confirmed "
                          f"fault.", state, value)
        return Result(subsystem, Outcome.UNKNOWN,
                      f"{name} not reported; no assertion made", state, value)

    if state is fail_on:
        return Result(subsystem, Outcome.FAIL, f"{name} is {state.value}",
                      state, value)
    return Result(subsystem, Outcome.PASS, f"{name} is {state.value}",
                  state, value)


def evaluate_threshold(subsystem: str, value: Any, *,
                       warn_above: Optional[float] = None,
                       fail_above: Optional[float] = None,
                       warn_below: Optional[float] = None,
                       fail_below: Optional[float] = None,
                       unit: str = "",
                       applicable: bool = True,
                       skip_reason: str = "",
                       label: Optional[str] = None) -> Result:
    """Evaluate an optional numeric value against thresholds.

    A missing or unparseable number is UNKNOWN — never silently treated as 0,
    which would make an absent temperature read as 'nice and cool'.
    """
    name = label or subsystem
    if not applicable:
        return Result(subsystem, Outcome.SKIP,
                      skip_reason or f"{name} not available on this hardware",
                      Tri.UNKNOWN, value)
    if value is None:
        return Result(subsystem, Outcome.UNKNOWN,
                      f"{name} not reported; no assertion made",
                      Tri.UNKNOWN, value)
    try:
        v = float(value)
    except (TypeError, ValueError):
        return Result(subsystem, Outcome.UNKNOWN,
                      f"{name} unparseable ({value!r}); no assertion made",
                      Tri.UNKNOWN, value)

    txt = f"{v:g}{unit}"
    if fail_above is not None and v > fail_above:
        return Result(subsystem, Outcome.FAIL,
                      f"{name} {txt} exceeds {fail_above:g}{unit}", Tri.TRUE, v)
    if fail_below is not None and v < fail_below:
        return Result(subsystem, Outcome.FAIL,
                      f"{name} {txt} below {fail_below:g}{unit}", Tri.TRUE, v)
    if warn_above is not None and v > warn_above:
        return Result(subsystem, Outcome.WARN,
                      f"{name} {txt} above {warn_above:g}{unit}", Tri.FALSE, v)
    if warn_below is not None and v < warn_below:
        return Result(subsystem, Outcome.WARN,
                      f"{name} {txt} below {warn_below:g}{unit}", Tri.FALSE, v)
    return Result(subsystem, Outcome.PASS, f"{name} {txt}", Tri.FALSE, v)


def evaluate_liveness(subsystem: str, age_seconds: Any, *,
                      ever_seen: Any = None,
                      warn_age: float = 180.0,
                      fail_age: float = 600.0,
                      registered_age_seconds: Optional[float] = None,
                      first_contact_grace: float = 180.0,
                      label: Optional[str] = None) -> Result:
    """Liveness that distinguishes 'never seen' from 'seen, then lost'.

    Those are different faults. Treating 'never seen' as healthy is precisely
    what let N001 sit at ever_seen=false / missed_beats=0 while it was dead.
    """
    name = label or subsystem
    seen = tri(ever_seen) if ever_seen is not None else Tri.UNKNOWN

    if seen is Tri.FALSE or age_seconds is None:
        if (registered_age_seconds is not None
                and registered_age_seconds > first_contact_grace):
            return Result(subsystem, Outcome.FAIL,
                          f"{name}: registered but has NEVER reported — "
                          f"liveness monitoring is not functioning for it",
                          Tri.UNKNOWN, None)
        if registered_age_seconds is None and seen is Tri.FALSE:
            return Result(subsystem, Outcome.FAIL,
                          f"{name}: has NEVER reported", Tri.UNKNOWN, None)
        return Result(subsystem, Outcome.UNKNOWN,
                      f"{name}: awaiting first report", Tri.UNKNOWN, None)

    try:
        age = float(age_seconds)
    except (TypeError, ValueError):
        return Result(subsystem, Outcome.UNKNOWN,
                      f"{name}: age unparseable", Tri.UNKNOWN, age_seconds)

    # A small negative age is clock skew between node and server, not a fault.
    age = max(0.0, age)
    if age > fail_age:
        return Result(subsystem, Outcome.FAIL,
                      f"{name}: {age:.0f}s since last report", Tri.TRUE, age)
    if age > warn_age:
        return Result(subsystem, Outcome.WARN,
                      f"{name}: {age:.0f}s since last report", Tri.FALSE, age)
    return Result(subsystem, Outcome.PASS, f"{name}: {age:.0f}s ago",
                  Tri.FALSE, age)


def worst(results) -> Outcome:
    """Aggregate. FAIL dominates, then WARN, then UNKNOWN, then PASS."""
    for o in (Outcome.FAIL, Outcome.WARN, Outcome.UNKNOWN, Outcome.PASS,
              Outcome.SKIP):
        if any(r.outcome is o for r in results):
            return o
    return Outcome.PASS
