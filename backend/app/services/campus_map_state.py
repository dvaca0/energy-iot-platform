"""What colour a building gets on the Campus Map, and why.

Kept apart from the router so the decision is a pure function of four facts and
can be tested without a database. Every one of those facts already has an owner
elsewhere in the platform; nothing here re-derives them:

  administrative state   ``deployments.status``, owned by ``app.db.lifecycle``
  observed state         a reading inside the telemetry window, owned by
                         ``app.services.deployment_scope``
  alert state            the highest open severity on the measuring node, owned
                         by ``app.monitoring``
  history                whether the building has ever owned a reading

**Consumption magnitude is not one of them.** A building drawing 400 kW because
it runs a chiller is not in a worse state than one drawing 4 kW, and colouring
it red would train an operator to ignore red. Magnitude gets its own map modes
(POWER, ENERGY, COST) with a graduated scale; STATUS is about whether the
measurement chain is healthy.

**An active deployment is not a claim that the building is live.** Deployment 7
can be ``active`` while its node has been silent for a day — the administrative
record says an operator declared a campaign, not that data is arriving. That is
why ``ACTIVE_STALE`` exists as a state of its own instead of being folded into
either ``ACTIVE_HEALTHY`` (which would show a day-old number as current) or
``HISTORICAL`` (which would hide a campaign that is supposed to be running and
therefore hide the fault).
"""

from __future__ import annotations

from datetime import datetime

from app.monitoring.severity import Severity

#: A physical footprint OSM knows about that Energy IQ has no building for.
#: Never produced here — the router assigns it to unassociated features.
UNREGISTERED = "unregistered"

#: An Energy IQ building that has never had a deployment or a reading.
REGISTERED = "registered"

#: Has measured in the past; nothing is running now.
HISTORICAL = "historical"

#: A deployment is administratively active but no reading has arrived inside
#: the telemetry window. The campaign is declared, the data is not current.
ACTIVE_STALE = "active_stale"

#: Active, fresh, and no open alert above INFO on the measuring node.
ACTIVE_HEALTHY = "active_healthy"

#: Active and fresh, with an open WARNING- or ERROR-level alert.
ACTIVE_WARNING = "active_warning"

#: Active and fresh, with an open CRITICAL- or EMERGENCY-level alert.
ACTIVE_CRITICAL = "active_critical"

#: Ordered worst-first. Used when one footprint holds several Energy IQ
#: buildings and the polygon can only carry one colour: the most urgent state
#: wins, because a healthy neighbour must never mask a critical one.
SEVERITY_ORDER = (
    ACTIVE_CRITICAL,
    ACTIVE_WARNING,
    ACTIVE_STALE,
    ACTIVE_HEALTHY,
    HISTORICAL,
    REGISTERED,
    UNREGISTERED,
)


def derive_status(
    *,
    has_active_deployment: bool,
    telemetry_live: bool,
    max_open_severity: Severity | None,
    has_history: bool,
) -> str:
    """The STATUS-mode state of one Energy IQ building.

    ``max_open_severity`` is the highest severity among *open* alerts on the
    node measuring this building, or ``None`` when it has none. It is consulted
    only for a live building: an alert raised against a node whose campaign
    ended months ago says nothing about the building today.
    """
    if not has_active_deployment:
        return HISTORICAL if has_history else REGISTERED
    if not telemetry_live:
        return ACTIVE_STALE
    if max_open_severity is not None:
        if max_open_severity >= Severity.CRITICAL:
            return ACTIVE_CRITICAL
        if max_open_severity >= Severity.WARNING:
            return ACTIVE_WARNING
    return ACTIVE_HEALTHY


def worst(statuses: list[str]) -> str:
    """The most urgent of several states, for a shared footprint."""
    for candidate in SEVERITY_ORDER:
        if candidate in statuses:
            return candidate
    return UNREGISTERED


def freshness(last_reading_at: datetime | None, window_seconds: int, now: datetime) -> dict:
    """Age of the newest reading, in the form the interface needs to be honest.

    ``is_live`` is the same five-minute question ``deployment_scope`` asks; it
    is repeated here against an explicit window so the caller passes the shared
    constant in rather than this module inventing a second threshold.
    """
    if last_reading_at is None:
        return {
            "last_reading_at": None,
            "age_seconds": None,
            "is_live": False,
            "window_seconds": window_seconds,
        }
    age = max(0.0, (now - last_reading_at).total_seconds())
    return {
        "last_reading_at": last_reading_at.isoformat(),
        "age_seconds": round(age, 1),
        "is_live": age <= window_seconds,
        "window_seconds": window_seconds,
    }
