"""The single authoritative definition of deployment lifecycle.

Every part of the backend that needs to know what a deployment status means asks
this module. Nothing hard-codes a status string, a list of "active-ish" statuses,
or a transition rule — those literals are what let the dashboard, the deployment
API, the ingest path and the alerting subsystem drift apart in the first place.

The values themselves live in the database (`deployment_statuses`,
`deployment_status_transitions`), not in this file. That is deliberate: adding a
lifecycle state should be one INSERT, with no schema change, no constraint
rewrite and no code change. Callers ask questions about *semantics* —

    attributing_statuses(db)      which statuses may own a reading
    operational_statuses(db)      which statuses expect the node to be measuring
    is_terminal(db, code)         may this still change
    can_transition(db, a, b)      is this move legal

— rather than comparing against literals, so a sixth state introduced later is
picked up automatically by every caller that already asks the right question.

The tables are read once and cached; they change only by migration. Call
`refresh()` after any deliberate change within a running process.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class DeploymentStatus:
    code: str
    label: str
    sort_order: int
    is_terminal: bool
    allows_attribution: bool
    is_operational: bool
    description: str | None


_lock = Lock()
_statuses: dict[str, DeploymentStatus] | None = None
_transitions: set[tuple[str, str]] | None = None


def refresh() -> None:
    """Drop the cache. Call after a migration changes the lifecycle tables."""
    global _statuses, _transitions
    with _lock:
        _statuses = None
        _transitions = None


def _load(db: Session) -> tuple[dict[str, DeploymentStatus], set[tuple[str, str]]]:
    global _statuses, _transitions
    if _statuses is not None and _transitions is not None:
        return _statuses, _transitions

    with _lock:
        if _statuses is not None and _transitions is not None:
            return _statuses, _transitions

        rows = db.execute(
            text(
                "SELECT code, label, sort_order, is_terminal, allows_attribution, "
                "       is_operational, description "
                "  FROM deployment_statuses ORDER BY sort_order"
            )
        ).fetchall()

        statuses = {
            row[0]: DeploymentStatus(
                code=row[0],
                label=row[1],
                sort_order=row[2],
                is_terminal=bool(row[3]),
                allows_attribution=bool(row[4]),
                is_operational=bool(row[5]),
                description=row[6],
            )
            for row in rows
        }

        transitions = {
            (row[0], row[1])
            for row in db.execute(
                text("SELECT from_code, to_code FROM deployment_status_transitions")
            ).fetchall()
        }

        _statuses, _transitions = statuses, transitions
        return statuses, transitions


# ----------------------------------------------------------------- accessors
def all_statuses(db: Session) -> list[DeploymentStatus]:
    statuses, _ = _load(db)
    return sorted(statuses.values(), key=lambda s: s.sort_order)


def get(db: Session, code: str) -> DeploymentStatus | None:
    statuses, _ = _load(db)
    return statuses.get(code)


def is_legal(db: Session, code: str) -> bool:
    statuses, _ = _load(db)
    return code in statuses


def attributing_statuses(db: Session) -> tuple[str, ...]:
    """Statuses whose deployment may own a reading.

    Replaces the hard-coded ``["active", "completed"]`` that appeared in the
    ingest routers. Same values today, but now derived from the one definition —
    and M8 removes the need for it in the ingest path entirely.
    """
    statuses, _ = _load(db)
    return tuple(s.code for s in sorted(statuses.values(), key=lambda s: s.sort_order)
                 if s.allows_attribution)


def operational_statuses(db: Session) -> tuple[str, ...]:
    """Statuses in which the node is expected to be measuring."""
    statuses, _ = _load(db)
    return tuple(s.code for s in sorted(statuses.values(), key=lambda s: s.sort_order)
                 if s.is_operational)


def terminal_statuses(db: Session) -> tuple[str, ...]:
    statuses, _ = _load(db)
    return tuple(s.code for s in sorted(statuses.values(), key=lambda s: s.sort_order)
                 if s.is_terminal)


def is_terminal(db: Session, code: str) -> bool:
    status = get(db, code)
    return bool(status and status.is_terminal)


def can_transition(db: Session, from_code: str, to_code: str) -> bool:
    _, transitions = _load(db)
    return (from_code, to_code) in transitions


def legal_transitions_from(db: Session, from_code: str) -> tuple[str, ...]:
    _, transitions = _load(db)
    return tuple(sorted(to for frm, to in transitions if frm == from_code))


def initial_status(db: Session) -> str:
    """The status a newly created deployment starts in.

    Defined as the first non-terminal status by sort order, so introducing a
    stage before `planned` needs no code change here.
    """
    for status in all_statuses(db):
        if not status.is_terminal:
            return status.code
    raise RuntimeError("no non-terminal deployment status is defined")
