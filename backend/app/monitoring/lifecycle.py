"""Monitoring policy derived from the platform's own lifecycle model.

**This module deliberately defines no lifecycle states of its own.** The
platform already owns that model, in two reference tables that carry explicit
semantics:

``node_commission_states`` — what the *node* is
    ``registered``      may_upload=0, is_monitored=0 — "silence is expected, so no alarm"
    ``commissioned``    may_upload=1, is_monitored=1 — "Silence is an alarm"
    ``suspended``       may_upload=0, is_monitored=1 — "still physically installed, so still monitored"
    ``decommissioned``  may_upload=0, is_monitored=0 — "silence is expected"

``deployment_statuses`` — what the *campaign* is
    ``planned``     is_operational=0, allows_attribution=0
    ``installing``  is_operational=1, allows_attribution=0
    ``active``      is_operational=1, allows_attribution=1
    ``completed``   is_operational=0, allows_attribution=1
    ``cancelled``   is_operational=0, allows_attribution=0

Those flags answer the alerting question directly, so this module only maps
them onto "which categories of rule may run":

===================  ======================================================
Flag                 Meaning for monitoring
===================  ======================================================
``is_monitored``     Alert about this node at all. False means the operator
                     has said the node is not in service; silence is the
                     expected state and must not page anyone.
``may_upload``       The node is expected to be talking to us. False means
                     missing heartbeats and missing data are intended.
``is_operational``   The deployment expects live measurement. False means
                     electrical thresholds are meaningless — the CT may be
                     clamped to nothing, or the panel de-energised.
===================  ======================================================

Why this matters: measured over the first three days of production traffic,
**1,288 of 1,312 alert messages (98%) came from nodes with no operational
deployment.** Reading these flags instead of ignoring them is the single
largest reduction in noise available.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.monitoring.config import MonitoringConfig

log = logging.getLogger("monitoring.lifecycle")


@dataclass(frozen=True)
class CommissionState:
    """A row of ``node_commission_states``."""

    code: str
    label: str
    may_upload: bool
    is_monitored: bool
    is_terminal: bool
    description: str = ""


@dataclass(frozen=True)
class MonitoringPolicy:
    """Which categories of rule may run for a given node right now.

    A rule asks the policy rather than deciding for itself, so "should this
    node be alerting at all?" is answered in exactly one place.
    """

    #: Electrical thresholds: current, voltage, PF, imbalance, spikes, reverse.
    electrical: bool
    #: Sensor and bus availability (ADS, SPI, GPIO), collector state.
    sensors: bool
    #: "Not measuring" / "never recorded anything" checks.
    measurement_freshness: bool
    #: Missed heartbeats are evaluated.
    heartbeat: bool
    #: Machine health: disk, temperature, filesystem, undervoltage.
    node_hardware: bool

    #: Human-readable justification, shown in the status report so a silenced
    #: node is never a mystery.
    rationale: str
    #: Missed heartbeats reach a channel rather than only the hourly report.
    #: A commissioned node with no campaign running is idle equipment: its
    #: silence is worth recording, but it is not worth waking anyone for.
    heartbeat_pages: bool = False
    #: The states this was derived from, for the API and for debugging.
    commission_state: str = "unknown"
    deployment_status: str | None = None


#: Nothing alerts. The safe default whenever classification is unavailable:
#: a bug in this module should produce silence, never a false page.
SILENT = MonitoringPolicy(
    electrical=False,
    sensors=False,
    measurement_freshness=False,
    heartbeat=False,
    node_hardware=False,
    heartbeat_pages=False,
    rationale="lifecycle unknown — alerting suppressed",
)


_commission_cache: dict[str, CommissionState] | None = None
_operational_cache: frozenset[str] | None = None


def refresh() -> None:
    """Drop the cached reference data. Called when the tables change."""
    global _commission_cache, _operational_cache
    _commission_cache = None
    _operational_cache = None


def commission_states(session: Session) -> dict[str, CommissionState]:
    """Load ``node_commission_states``, cached.

    Reference data that changes only through a migration, read on every tick —
    so it is cached for the process lifetime. Falls back to an empty mapping
    if the table does not exist, which keeps monitoring importable against an
    older database (and, per :data:`SILENT`, silent rather than noisy).
    """
    global _commission_cache
    if _commission_cache is not None:
        return _commission_cache

    try:
        rows = session.execute(
            text(
                "SELECT code, label, may_upload, is_monitored, is_terminal, "
                "COALESCE(description,'') FROM node_commission_states"
            )
        ).all()
    except Exception:
        log.warning("node_commission_states unavailable; monitoring policy will be silent")
        _commission_cache = {}
        return _commission_cache

    _commission_cache = {
        row[0]: CommissionState(
            code=row[0],
            label=row[1],
            may_upload=bool(row[2]),
            is_monitored=bool(row[3]),
            is_terminal=bool(row[4]),
            description=row[5],
        )
        for row in rows
    }
    return _commission_cache


def operational_statuses(session: Session) -> frozenset[str]:
    """Deployment statuses in which the node is expected to be measuring.

    Delegates to ``app.db.lifecycle``, which owns this definition, rather than
    hard-coding ``("active", "installing")`` — the whole point of the reference
    table is that this list lives in one place.
    """
    global _operational_cache
    if _operational_cache is not None:
        return _operational_cache

    try:
        from app.db import lifecycle as db_lifecycle

        _operational_cache = frozenset(db_lifecycle.operational_statuses(session))
    except Exception:
        log.warning("deployment_statuses unavailable; treating no deployment as operational")
        _operational_cache = frozenset()
    return _operational_cache


def _deployment_in_window(deployment: Any, now: datetime) -> bool:
    """Whether today falls inside the deployment's date range.

    ``end_date`` NULL means open-ended. Dates are stored ``YYYY-MM-DD`` and the
    schema enforces that with a CHECK, so lexical comparison is chronological
    and no parsing is needed.
    """
    if deployment is None:
        return False
    today = now.strftime("%Y-%m-%d")
    if deployment.start_date and today < deployment.start_date:
        return False
    if deployment.end_date and today > deployment.end_date:
        return False
    return True


def classify(
    session: Session, state: dict[str, Any], config: MonitoringConfig, now: datetime
) -> MonitoringPolicy:
    """Derive the monitoring policy for one node.

    An operator override in ``config.node_lifecycle`` (values: the commission
    state codes, or ``maintenance`` to silence everything) always wins, so a
    node can be muted for a day without a database change.
    """
    code = state.get("code")
    node = state.get("node")

    commission = getattr(node, "commission_state", None) or "unknown"

    override = (config.node_lifecycle or {}).get(code)
    if override:
        override = str(override).lower()
        if override == "maintenance":
            return MonitoringPolicy(
                False,
                False,
                False,
                False,
                False,
                rationale="under maintenance — alerting suppressed by configuration",
                commission_state=commission,
            )
        commission = override

    states = commission_states(session)
    info = states.get(commission)

    if info is None:
        # Unknown state: monitor the machine only. Better to under-report than
        # to invent a policy for a state this code has never seen.
        return MonitoringPolicy(
            False,
            False,
            False,
            False,
            True,
            rationale=f"unrecognised commission state {commission!r} — hardware only",
            commission_state=commission,
        )

    if not info.is_monitored:
        return MonitoringPolicy(
            False,
            False,
            False,
            False,
            False,
            rationale=f"{info.label.lower()} — {info.description or 'silence is expected'}",
            commission_state=commission,
        )

    # The node is in service. Is a campaign actually running on it?
    deployment = state.get("deployment")
    status = getattr(deployment, "status", None)
    operational = (
        deployment is not None
        and status in operational_statuses(session)
        and _deployment_in_window(deployment, now)
    )

    if not info.may_upload:
        # Suspended: still installed and still worth watching as hardware, but
        # its silence is deliberate, so absent data must not alarm.
        return MonitoringPolicy(
            electrical=False,
            sensors=False,
            measurement_freshness=False,
            heartbeat=False,
            node_hardware=True,
            rationale=f"{info.label.lower()} — uploads revoked, silence is expected",
            commission_state=commission,
            deployment_status=status,
        )

    if operational:
        return MonitoringPolicy(
            electrical=True,
            sensors=True,
            measurement_freshness=True,
            heartbeat=True,
            node_hardware=True,
            heartbeat_pages=True,
            rationale=f"deployment {status} — full monitoring",
            commission_state=commission,
            deployment_status=status,
        )

    # Commissioned, expected to be reachable, but no campaign is running.
    # Watch the machine and its liveness; say nothing about electricity,
    # because there is nothing it is supposed to be measuring.
    return MonitoringPolicy(
        electrical=False,
        sensors=False,
        measurement_freshness=False,
        heartbeat=True,
        node_hardware=True,
        # Recorded and shown in the hourly report, but it does not page: idle
        # equipment going quiet is information, not an incident.
        heartbeat_pages=False,
        rationale=(
            "commissioned, no operational deployment"
            + (f" (latest: {status})" if status else "")
            + " — electrical alerting suppressed"
        ),
        commission_state=commission,
        deployment_status=status,
    )


def annotate(
    session: Session,
    nodes: dict[str, dict[str, Any]],
    config: MonitoringConfig,
    now: datetime,
) -> None:
    """Attach the policy to every node state, in place, once per tick."""
    for state in nodes.values():
        policy = classify(session, state, config, now)
        state["policy"] = policy
        state["lifecycle"] = policy.commission_state
        state["lifecycle_reason"] = policy.rationale


def policy_for(state: dict[str, Any]) -> MonitoringPolicy:
    """Policy for an annotated node state, defaulting to silence."""
    policy = state.get("policy")
    return policy if isinstance(policy, MonitoringPolicy) else SILENT


__all__ = [
    "SILENT",
    "CommissionState",
    "MonitoringPolicy",
    "annotate",
    "classify",
    "commission_states",
    "operational_statuses",
    "policy_for",
    "refresh",
]
