"""The single authoritative definition of node commissioning state.

The counterpart to `lifecycle.py`, and deliberately the same shape: the values
live in `node_commission_states`, and callers ask about *semantics* rather than
comparing against literals —

    uploading_states(db)    which states may write readings
    monitored_states(db)    which states must raise an alarm when silent
    may_upload(db, code)
    is_monitored(db, code)

Two separations this makes possible, both of which the audit found broken:

Identity is not connectivity. A node exists because it has a row, not because
it synced recently. `/api/nodes` used to drop offline nodes entirely, so a node
that lost power ceased to exist as far as the API was concerned.

Alerting follows nodes, not campaigns. The legacy alert endpoint iterated active
deployments; with every deployment completed it emitted nothing at all, silently.
Monitoring now follows `is_monitored`, which no deployment transition can change.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class CommissionState:
    code: str
    label: str
    sort_order: int
    may_upload: bool
    is_monitored: bool
    is_terminal: bool
    description: str | None


_lock = Lock()
_states: dict[str, CommissionState] | None = None
_transitions: set[tuple[str, str]] | None = None


class IllegalTransition(ValueError):
    """A commission-state move that the lifecycle model does not permit."""


def refresh() -> None:
    global _states, _transitions
    with _lock:
        _states = None
        _transitions = None


def _load(db: Session) -> dict[str, CommissionState]:
    global _states
    if _states is not None:
        return _states
    with _lock:
        rows = db.execute(
            text(
                "SELECT code, label, sort_order, may_upload, is_monitored, "
                "       is_terminal, description "
                "  FROM node_commission_states ORDER BY sort_order"
            )
        ).fetchall()
        _states = {
            r[0]: CommissionState(
                code=r[0], label=r[1], sort_order=r[2],
                may_upload=bool(r[3]), is_monitored=bool(r[4]),
                is_terminal=bool(r[5]), description=r[6],
            )
            for r in rows
        }
        return _states


def all_states(db: Session) -> list[CommissionState]:
    return sorted(_load(db).values(), key=lambda s: s.sort_order)


def get(db: Session, code: str) -> CommissionState | None:
    return _load(db).get(code)


def uploading_states(db: Session) -> tuple[str, ...]:
    """States permitted to write readings (ADR-0002 step 2)."""
    return tuple(s.code for s in all_states(db) if s.may_upload)


def monitored_states(db: Session) -> tuple[str, ...]:
    """States whose silence is an alarm rather than an expectation."""
    return tuple(s.code for s in all_states(db) if s.is_monitored)


def may_upload(db: Session, code: str) -> bool:
    state = get(db, code)
    return bool(state and state.may_upload)


def is_monitored(db: Session, code: str) -> bool:
    state = get(db, code)
    return bool(state and state.is_monitored)


# --------------------------------------------------------------- transitions
#
# M7 defined the states but not the moves between them, so `commission_state`
# had no legal-transition rule, no audit trail and no write path in the
# application — the only way to change it was raw SQL. M8 adds
# `node_commission_transitions` and `node_commission_events`; this is the code
# that uses them, mirroring `lifecycle.can_transition` for deployments so both
# lifecycles behave the same way.


def _load_transitions(db: Session) -> set[tuple[str, str]]:
    global _transitions
    if _transitions is not None:
        return _transitions
    with _lock:
        rows = db.execute(
            text("SELECT from_code, to_code FROM node_commission_transitions")
        ).fetchall()
        _transitions = {(r[0], r[1]) for r in rows}
        return _transitions


def can_transition(db: Session, from_code: str, to_code: str) -> bool:
    """Whether this move is permitted by the lifecycle model.

    A move to the state a node is already in is legal and is a no-op, so
    re-running an operational script cannot fail halfway.
    """
    if from_code == to_code:
        return True
    return (from_code, to_code) in _load_transitions(db)


def legal_transitions_from(db: Session, from_code: str) -> tuple[str, ...]:
    """Every state reachable from ``from_code``, for an API or a UI menu."""
    return tuple(
        sorted(to for (frm, to) in _load_transitions(db) if frm == from_code)
    )


def transition(
    db: Session,
    node,
    to_code: str,
    *,
    reason: str | None = None,
    actor: str | None = None,
):
    """Move a node to a new commission state, with an audit record.

    The only supported way to change ``Node.commission_state``. Validates the
    target exists and the move is legal, writes a ``node_commission_events``
    row, then updates the node — in that order, inside the caller's
    transaction, so an illegal move changes nothing.

    Does not commit: the caller owns the transaction boundary.

    Raises :class:`IllegalTransition` for an unknown or forbidden target.
    """
    target = get(db, to_code)
    if target is None:
        raise IllegalTransition(
            f"unknown commission state {to_code!r}; "
            f"known: {sorted(s.code for s in all_states(db))}"
        )

    current = node.commission_state
    if not can_transition(db, current, to_code):
        raise IllegalTransition(
            f"{node.code}: {current} -> {to_code} is not a legal transition; "
            f"from {current} you may move to "
            f"{list(legal_transitions_from(db, current)) or 'nothing (terminal state)'}"
        )

    if current == to_code:
        return None  # no-op, nothing to record

    db.execute(
        text(
            "INSERT INTO node_commission_events "
            "  (node_id, node_code, from_state, to_state, reason, actor) "
            "VALUES (:node_id, :node_code, :from_state, :to_state, :reason, :actor)"
        ),
        {
            "node_id": node.id,
            "node_code": node.code,
            "from_state": current,
            "to_state": to_code,
            "reason": reason,
            "actor": actor,
        },
    )
    node.commission_state = to_code
    if to_code == "commissioned" and getattr(node, "commissioned_at", None) is None:
        from datetime import datetime

        node.commissioned_at = datetime.utcnow()

    return {
        "node_code": node.code,
        "from_state": current,
        "to_state": to_code,
        "reason": reason,
        "actor": actor,
    }


def history(db: Session, node_id: int) -> list[dict]:
    """Commission-state history for a node, oldest first."""
    rows = db.execute(
        text(
            "SELECT from_state, to_state, reason, actor, occurred_at "
            "  FROM node_commission_events WHERE node_id = :node_id "
            " ORDER BY occurred_at, id"
        ),
        {"node_id": node_id},
    ).fetchall()
    return [
        {
            "from_state": r[0],
            "to_state": r[1],
            "reason": r[2],
            "actor": r[3],
            "occurred_at": r[4],
        }
        for r in rows
    ]
