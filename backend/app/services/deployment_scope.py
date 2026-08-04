"""Deployment scoping and telemetry state for the Executive Dashboard.

Two questions the dashboard asks that nothing else answered:

  which readings belong to this deployment?   ``scope_readings`` / the
                                              ``deployment_id`` argument
                                              threaded through
                                              ``energy_aggregate``

  is this deployment still measuring?         ``telemetry_state``

**Telemetry state is not lifecycle state.** ``deployments.status`` and
``deployment_statuses`` are an administrative lifecycle — planned, installing,
active, completed, cancelled — owned by ``app.db.lifecycle`` and used for
attribution and alerting policy. It records what an operator declared. It does
not, and is not meant to, track whether hardware is currently sending data:
deployment 5 is ``completed`` and has been ingesting continuously.

The dashboard needs the second, observed fact, so this module derives it from
the readings themselves and gives it a separate name. Nothing here writes to or
reinterprets ``status``; callers that need the administrative view keep asking
``lifecycle``. Conflating the two is what would make a genuinely archived
deployment look live, or hide an active one behind a stale label.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Query, Session

from app.db.models import Deployment, EnergyReading

#: A deployment counts as measuring if a reading landed within this window.
#: Chosen by the platform owner: nodes report on a 15 s–1 min cadence, so five
#: minutes is several missed samples — long enough not to flicker on one late
#: batch, short enough that "ACTIVE" means now rather than earlier today.
TELEMETRY_ACTIVE_WINDOW = timedelta(minutes=5)

ACTIVE = "active"
ARCHIVED = "archived"


def scope_readings(query: Query, deployment_id: int | None) -> Query:
    """Restrict a reading query to one deployment. ``None`` leaves it alone."""
    if deployment_id is None:
        return query
    return query.filter(EnergyReading.deployment_id == deployment_id)


def exists(db: Session, deployment_id: int) -> bool:
    return db.query(Deployment.id).filter(Deployment.id == deployment_id).first() is not None


def last_reading_at(db: Session, deployment_id: int) -> datetime | None:
    """Timestamp of the most recent reading this deployment owns."""
    return (
        db.query(func.max(EnergyReading.timestamp))
        .filter(EnergyReading.deployment_id == deployment_id)
        .scalar()
    )


def last_reading_by_deployment(db: Session) -> dict[int, datetime]:
    """``{deployment id: latest reading timestamp}`` in one query.

    The selector needs this for every deployment at once; asking per row would
    put a MAX() scan behind each entry in the list.
    """
    rows = (
        db.query(EnergyReading.deployment_id, func.max(EnergyReading.timestamp))
        .filter(EnergyReading.deployment_id.isnot(None))
        .group_by(EnergyReading.deployment_id)
        .all()
    )
    out: dict[int, datetime] = {}
    for deployment_id, latest in rows:
        if latest is None:
            continue
        out[deployment_id] = latest if isinstance(latest, datetime) else datetime.fromisoformat(latest)
    return out


def telemetry_state(latest: datetime | None, now: datetime | None = None) -> str:
    """ACTIVE if a reading arrived inside the window, else ARCHIVED.

    ``latest`` is a naive UTC timestamp, matching how readings are stored.
    """
    if latest is None:
        return ARCHIVED
    reference = now or datetime.utcnow()
    return ACTIVE if (reference - latest) <= TELEMETRY_ACTIVE_WINDOW else ARCHIVED


def measuring_window(db: Session, deployment_id: int) -> tuple[datetime | None, datetime | None]:
    """First and last reading this deployment owns.

    The anomaly engine evaluates "since deployment start", and the start that
    matters is the first reading actually attributed — not ``start_date``, which
    is a planning field and for deployment 4 covers a quarter of its own rows.
    """
    row = (
        db.query(func.min(EnergyReading.timestamp), func.max(EnergyReading.timestamp))
        .filter(EnergyReading.deployment_id == deployment_id)
        .first()
    )
    if not row:
        return None, None

    def _dt(value):
        if value is None or isinstance(value, datetime):
            return value
        return datetime.fromisoformat(value)

    return _dt(row[0]), _dt(row[1])


def default_deployment_id(db: Session, now: datetime | None = None) -> int | None:
    """The deployment the dashboard should open on.

    Priority set by the platform owner:

      1. one that is still producing telemetry (a reading inside the window),
      2. otherwise the one with the newest data,
      3. otherwise none, and the dashboard shows its empty state.

    Rule 2 is "newest data", not "newest id" or "most recently closed": with
    every deployment marked completed, the one worth opening on is the one that
    measured last.
    """
    latest_by_deployment = last_reading_by_deployment(db)
    if not latest_by_deployment:
        # No deployment owns a reading. Fall back to the highest id so the
        # selector still opens on something if deployments exist at all.
        row = db.query(Deployment.id).order_by(Deployment.id.desc()).first()
        return row[0] if row else None

    reference = now or datetime.utcnow()
    live = [
        deployment_id
        for deployment_id, latest in latest_by_deployment.items()
        if telemetry_state(latest, reference) == ACTIVE
    ]
    if live:
        return max(live, key=lambda d: latest_by_deployment[d])

    return max(latest_by_deployment, key=lambda d: latest_by_deployment[d])
