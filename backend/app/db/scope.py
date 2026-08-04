"""Query scoping for production analytics.

One helper, applied at every analytics call site, so that excluding bench and
laboratory data is structural rather than something each query has to remember.
A call site that forgets a filter is how contamination got in; a call site that
forgets to *use this module* is a much more visible omission.

Two independent exclusions, matching the two axes in ADR-0003 and ADR-0006:

  measurement context   Is this a real production measurement, or bench,
                        laboratory, calibration or simulation work?
                        Read from `measurement_contexts.counts_in_analytics`.

  building metadata     Is the building a real site, or a development
                        placeholder? Read from `buildings.is_placeholder`.

Neither list is restated here. Adding a seventh context, or flagging another
building as a placeholder, changes behaviour everywhere without touching this
file — the same property the deployment lifecycle has in `lifecycle.py`.

Nothing is deleted or hidden: excluded data stays queryable through the explicit
``contexts=`` argument, which is what the ``?context=`` API parameter passes.
"""
from __future__ import annotations

from threading import Lock

from sqlalchemy import text
from sqlalchemy.orm import Query, Session

from app.db.models import Building, EnergyReading

_lock = Lock()
_analytic_contexts: tuple[str, ...] | None = None
_all_contexts: tuple[str, ...] | None = None


def refresh() -> None:
    """Drop the cache. Call after a migration changes measurement_contexts."""
    global _analytic_contexts, _all_contexts
    with _lock:
        _analytic_contexts = None
        _all_contexts = None


def analytic_contexts(db: Session) -> tuple[str, ...]:
    """Contexts that count toward production KPIs, cost, AI and anomalies."""
    global _analytic_contexts
    if _analytic_contexts is not None:
        return _analytic_contexts
    with _lock:
        rows = db.execute(
            text(
                "SELECT code FROM measurement_contexts "
                " WHERE counts_in_analytics = 1 ORDER BY sort_order"
            )
        ).fetchall()
        _analytic_contexts = tuple(r[0] for r in rows)
        return _analytic_contexts


def all_contexts(db: Session) -> tuple[str, ...]:
    global _all_contexts
    if _all_contexts is not None:
        return _all_contexts
    with _lock:
        rows = db.execute(
            text("SELECT code FROM measurement_contexts ORDER BY sort_order")
        ).fetchall()
        _all_contexts = tuple(r[0] for r in rows)
        return _all_contexts


def resolve_contexts(db: Session, requested: str | list[str] | None) -> tuple[str, ...]:
    """Turn an API ``?context=`` value into a validated tuple.

    ``None`` means the production default. ``"all"`` means every context.
    Anything else is validated against the canonical list, so a typo returns
    nothing rather than silently falling back to everything.
    """
    if requested is None:
        return analytic_contexts(db)

    if isinstance(requested, str):
        requested = [part.strip() for part in requested.split(",") if part.strip()]

    if any(part.lower() == "all" for part in requested):
        return all_contexts(db)

    known = set(all_contexts(db))
    return tuple(part for part in requested if part in known)


# ------------------------------------------------------------------ queries
def production_readings(db: Session, contexts: str | list[str] | None = None) -> Query:
    """Base query for analytics. Production contexts only unless told otherwise."""
    return db.query(EnergyReading).filter(
        EnergyReading.context.in_(resolve_contexts(db, contexts))
    )


def scope_readings(query: Query, db: Session, contexts: str | list[str] | None = None) -> Query:
    """Apply the context filter to a query that is already built."""
    return query.filter(EnergyReading.context.in_(resolve_contexts(db, contexts)))


def placeholder_building_ids(db: Session) -> tuple[int, ...]:
    rows = db.query(Building.id).filter(Building.is_placeholder.is_(True)).all()
    return tuple(r[0] for r in rows)


def real_buildings(db: Session) -> Query:
    """Buildings that represent a real site, for building-level analytics."""
    return db.query(Building).filter(Building.is_placeholder.is_(False))


def exclude_placeholder_buildings(query: Query, db: Session) -> Query:
    """Drop readings attributed to a placeholder building.

    Used only for *building-level* breakdowns. Fleet-level energy totals keep
    counting these readings — they are real measurements, and it is the site
    label that is unreliable, not the measurement (ADR-0006).
    """
    placeholders = placeholder_building_ids(db)
    if not placeholders:
        return query
    return query.filter(
        (EnergyReading.building_id.is_(None))
        | (~EnergyReading.building_id.in_(placeholders))
    )
