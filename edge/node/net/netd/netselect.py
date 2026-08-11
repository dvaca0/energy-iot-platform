"""Which known network should we try next, and why.

PURE. No I/O, no radio, no clock: time and scan results arrive as arguments,
so every rule below is unit-testable without hardware. This is the same
discipline the evaluator and state machine already follow.

THE STRATEGY (agreed 2026-08-11)

    1. Try the most recently successful network first. A node that worked on
       "Lab-AP" ten minutes ago should go back to "Lab-AP", regardless of what
       the configured priorities say - the world told us that one works.
    2. Then follow configured priorities.
    3. Skip networks that have been failing, with exponential backoff, so a
       network with a changed password does not soak up every attempt.
    4. Never join an unknown or open network unless explicitly allowed.

WHY NOT JUST ITERATE THE LIST
    A plain ordered walk retries the same broken network at the top of the
    list forever, and forgets that the one at the bottom worked five minutes
    ago. Health is what makes the difference between a list and a strategy.

WHAT THIS MODULE DOES NOT DO
    It does not connect. It ranks. The caller applies the ranking, which on
    these nodes means mapping it onto NetworkManager autoconnect priorities,
    because NetworkManager is already the roaming engine and a second one
    would fight it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

BASELINE = "baseline"
OPERATOR = "operator"


@dataclass(frozen=True)
class KnownNetwork:
    """One entry of the effective whitelist.

    NEVER carries a passphrase. Credentials live in the 0600 secrets store,
    because this object is built from git-managed config and is logged,
    rendered in the portal and returned over the control socket.
    """

    ssid: str
    priority: int = 0
    source: str = BASELINE           # baseline (git) | operator (portal)
    hidden: bool = False
    open: bool = False               # network has no passphrase
    notes: str = ""

    def redacted(self) -> dict:
        return {"ssid": self.ssid, "priority": self.priority,
                "source": self.source, "hidden": self.hidden,
                "open": self.open, "notes": self.notes}


@dataclass
class NetHealth:
    """What we have learned about one network by trying it."""

    ssid: str
    last_success: Optional[float] = None
    last_failure: Optional[float] = None
    last_attempt: Optional[float] = None
    consecutive_failures: int = 0
    last_signal: Optional[int] = None      # dBm or percent, as reported
    last_error: str = ""

    def as_dict(self) -> dict:
        return {"ssid": self.ssid, "last_success": self.last_success,
                "last_failure": self.last_failure,
                "last_attempt": self.last_attempt,
                "consecutive_failures": self.consecutive_failures,
                "last_signal": self.last_signal, "last_error": self.last_error}

    @classmethod
    def from_dict(cls, d: dict) -> "NetHealth":
        return cls(
            ssid=str(d.get("ssid", "")),
            last_success=d.get("last_success"),
            last_failure=d.get("last_failure"),
            last_attempt=d.get("last_attempt"),
            consecutive_failures=int(d.get("consecutive_failures") or 0),
            last_signal=d.get("last_signal"),
            last_error=str(d.get("last_error") or ""),
        )


@dataclass(frozen=True)
class SelectionPolicy:
    backoff_initial: int = 15
    backoff_max: int = 300
    #: A success older than this no longer earns the "try me first" slot; the
    #: node has probably been moved.
    recent_success_window: int = 86400
    #: Open networks are refused unless this is explicitly turned on.
    allow_open: bool = False


@dataclass(frozen=True)
class Candidate:
    network: KnownNetwork
    reason: str
    signal: Optional[int] = None
    eligible: bool = True
    retry_after: Optional[float] = None


def backoff_seconds(failures: int, policy: SelectionPolicy) -> int:
    """Exponential, capped. Zero failures means no wait at all."""
    if failures <= 0:
        return 0
    delay = policy.backoff_initial * (2 ** (failures - 1))
    return int(min(delay, policy.backoff_max))


def retry_after(health: Optional[NetHealth], policy: SelectionPolicy) -> Optional[float]:
    """The instant this network may be tried again, or None if it may now."""
    if health is None or health.consecutive_failures <= 0:
        return None
    base = health.last_failure or health.last_attempt
    if base is None:
        return None
    return base + backoff_seconds(health.consecutive_failures, policy)


def in_backoff(health: Optional[NetHealth], now: float,
               policy: SelectionPolicy) -> bool:
    ra = retry_after(health, policy)
    return ra is not None and now < ra


def most_recently_successful(
    known: Sequence[KnownNetwork],
    health: Dict[str, NetHealth],
    now: float,
    policy: SelectionPolicy,
) -> Optional[str]:
    """The SSID that worked most recently, within the recency window."""
    best_ssid, best_at = None, None
    for net in known:
        h = health.get(net.ssid)
        if h is None or h.last_success is None:
            continue
        if now - h.last_success > policy.recent_success_window:
            continue
        if best_at is None or h.last_success > best_at:
            best_ssid, best_at = net.ssid, h.last_success
    return best_ssid


def rank(
    known: Sequence[KnownNetwork],
    health: Dict[str, NetHealth],
    visible: Optional[Dict[str, int]] = None,
    now: float = 0.0,
    policy: Optional[SelectionPolicy] = None,
) -> List[Candidate]:
    """Order the whitelist into the sequence we should actually try.

    `visible` maps SSID -> signal for networks the last scan saw. Pass None
    when no scan is available, in which case visibility is not used as a
    filter - refusing to try anything because a scan failed would be a way to
    stay offline.

    Returns every known network, eligible ones first in try-order, so the
    caller can also show an operator *why* something is being skipped.
    """
    policy = policy or SelectionPolicy()
    preferred = most_recently_successful(known, health, now, policy)

    eligible: List[Candidate] = []
    deferred: List[Candidate] = []

    for net in known:
        h = health.get(net.ssid)
        sig = visible.get(net.ssid) if visible is not None else None

        # Rule 4: never join an open network unless explicitly allowed.
        if net.open and not policy.allow_open:
            deferred.append(Candidate(
                net, "open network - refused by policy", sig, eligible=False))
            continue

        # Not in range. Hidden networks never appear in a scan, so they are
        # always considered reachable.
        if visible is not None and not net.hidden and net.ssid not in visible:
            deferred.append(Candidate(net, "not in range", sig, eligible=False))
            continue

        # Rule 3: skip a network that is backing off.
        if in_backoff(h, now, policy):
            ra = retry_after(h, policy)
            deferred.append(Candidate(
                net,
                f"backing off after {h.consecutive_failures} failure(s), "
                f"retry in {int(ra - now)}s",
                sig, eligible=False, retry_after=ra))
            continue

        if net.ssid == preferred:
            reason = "most recently successful"
        elif h is not None and h.consecutive_failures:
            reason = (f"priority {net.priority}, "
                      f"{h.consecutive_failures} recent failure(s)")
        else:
            reason = f"priority {net.priority}"
        eligible.append(Candidate(net, reason, sig))

    def sort_key(c: Candidate):
        h = health.get(c.network.ssid)
        return (
            0 if c.network.ssid == preferred else 1,      # rule 1
            -c.network.priority,                          # rule 2
            -(h.last_success or 0) if h else 0,           # then recency
            c.network.ssid.lower(),                       # stable tie-break
        )

    eligible.sort(key=sort_key)
    deferred.sort(key=lambda c: (-c.network.priority, c.network.ssid.lower()))
    return eligible + deferred


def next_to_try(
    known: Sequence[KnownNetwork],
    health: Dict[str, NetHealth],
    visible: Optional[Dict[str, int]] = None,
    now: float = 0.0,
    policy: Optional[SelectionPolicy] = None,
) -> Optional[KnownNetwork]:
    for c in rank(known, health, visible, now, policy):
        if c.eligible:
            return c.network
    return None


def should_raise_ap(
    known: Sequence[KnownNetwork],
    health: Dict[str, NetHealth],
    visible: Optional[Dict[str, int]] = None,
    now: float = 0.0,
    policy: Optional[SelectionPolicy] = None,
) -> bool:
    """The AP goes up only when NO known network is worth trying right now.

    Backing off still counts as "worth trying later", so a node does not raise
    the AP the moment one network fails once - it raises it when there is
    genuinely nothing left to attempt.
    """
    return next_to_try(known, health, visible, now, policy) is None


# ------------------------------------------------------------------ recording


def record_success(health: Dict[str, NetHealth], ssid: str, now: float,
                   signal: Optional[int] = None) -> NetHealth:
    h = health.get(ssid) or NetHealth(ssid=ssid)
    h.last_success = now
    h.last_attempt = now
    h.consecutive_failures = 0        # a success clears the backoff entirely
    h.last_error = ""
    if signal is not None:
        h.last_signal = signal
    health[ssid] = h
    return h


def record_failure(health: Dict[str, NetHealth], ssid: str, now: float,
                   error: str = "", signal: Optional[int] = None) -> NetHealth:
    h = health.get(ssid) or NetHealth(ssid=ssid)
    h.last_failure = now
    h.last_attempt = now
    h.consecutive_failures += 1
    h.last_error = error[:200]
    if signal is not None:
        h.last_signal = signal
    health[ssid] = h
    return h


def merge_whitelist(baseline: Sequence[KnownNetwork],
                    operator: Sequence[KnownNetwork],
                    suppressed: Sequence[str] = ()) -> List[KnownNetwork]:
    """The effective whitelist: git baseline plus operator additions.

    An operator entry for the same SSID overrides the baseline, because the
    person standing at the node knows something git does not. A deployment
    from git therefore can never delete an operator network - it only ever
    contributes baseline entries, and this merge keeps operator ones on top.

    `suppressed` lets an operator forget a BASELINE network without git
    reinstating it on the next deploy.
    """
    out: Dict[str, KnownNetwork] = {}
    for net in baseline:
        out[net.ssid] = net
    for net in operator:
        out[net.ssid] = net
    for ssid in suppressed:
        out.pop(ssid, None)
    return sorted(out.values(), key=lambda n: (-n.priority, n.ssid.lower()))
