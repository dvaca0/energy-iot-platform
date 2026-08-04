"""Deployment lifecycle operations.

The API's job is to let an operator perform *actions*; this module is where an
action becomes a transition. Nothing here writes a status directly — every
change goes through `_transition`, which validates against
`deployment_status_transitions` and applies the business rules that the database
triggers exist to backstop.

Operators never supply `activated_at` or `closed_at`. They are written here, by
the transition that causes them, from the server clock. That is the whole point
of the planning/operational split: a schedule is typed by a human, an
operational fact is recorded by the system.

Errors raise `LifecycleError` carrying a sentence that names the business rule
that failed. The triggers in M12 remain the last line of defence, but a
constraint message should never reach an operator — if one does, a rule is
missing here.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.db import commissioning, lifecycle
from app.db.models import Deployment, EnergyReading, Node


class LifecycleError(Exception):
    """A lifecycle rule was violated. Carries an operator-readable explanation."""

    def __init__(self, message: str, *, code: str = "lifecycle_violation"):
        super().__init__(message)
        self.message = message
        self.code = code


# Operator-facing verbs, mapped to the transition each performs. The API renders
# `available_actions` from this, so a UI never needs to know state names.
ACTIONS: dict[str, tuple[str, str]] = {
    # action: (from_status, to_status)
    "begin_installation": ("planned", "installing"),
    "activate": ("installing", "active"),
    "complete": ("active", "completed"),
}

ACTION_LABELS = {
    "begin_installation": "Begin installation",
    "activate": "Start measuring",
    "complete": "Finish measuring",
    "cancel": "Cancel",
    "edit": "Edit planning information",
}


def attributed_reading_count(db: Session, deployment_id: int) -> int:
    return (
        db.query(EnergyReading)
        .filter(EnergyReading.deployment_id == deployment_id)
        .count()
    )


def available_actions(db: Session, deployment: Deployment) -> list[str]:
    """What the operator may do next. Verbs, not state names."""
    actions: list[str] = []
    for action, (frm, to) in ACTIONS.items():
        if deployment.status == frm and lifecycle.can_transition(db, frm, to):
            actions.append(action)

    if lifecycle.can_transition(db, deployment.status, "cancelled"):
        # Rule 8: a campaign that produced data happened; it is completed, not
        # cancelled. Hiding the action is friendlier than offering it and then
        # refusing.
        if attributed_reading_count(db, deployment.id) == 0:
            actions.append("cancel")

    state = lifecycle.get(db, deployment.status)
    if state and not state.is_terminal and deployment.activated_at is None:
        actions.append("edit")

    return actions


# --------------------------------------------------------------- validation
def _require_no_live_deployment(db: Session, node: Node, exclude_id: int | None = None):
    """At most one deployment per node may be installing or active."""
    exclusive = [s.code for s in lifecycle.all_statuses(db) if s.is_operational]
    query = db.query(Deployment).filter(
        Deployment.node_id == node.id,
        Deployment.status.in_(exclusive),
    )
    if exclude_id is not None:
        query = query.filter(Deployment.id != exclude_id)

    other = query.first()
    if other is not None:
        since = other.activated_at or "not yet started"
        raise LifecycleError(
            f"Cannot proceed: deployment {other.id} is already {other.status} on node "
            f"{node.code} (since {since}). Finish it first, or supersede it explicitly.",
            code="node_already_live",
        )


def _require_commissioned(db: Session, node: Node):
    if not commissioning.may_upload(db, node.commission_state):
        state = commissioning.get(db, node.commission_state)
        label = state.label if state else node.commission_state
        raise LifecycleError(
            f"Cannot start measuring: node {node.code} is {label}, which is not "
            f"permitted to upload readings. Commission it first.",
            code="node_not_commissioned",
        )


def _require_no_backdating(db: Session, node: Node, at: datetime):
    """Rule 6: activation may not reach back over readings already stored.

    Those readings carry the attribution they were stamped with and are
    immutable, so a window that retroactively covers them would claim instants
    it can never actually own.
    """
    latest = (
        db.query(EnergyReading.timestamp)
        .filter(EnergyReading.node_id == node.id)
        .order_by(EnergyReading.timestamp.desc())
        .first()
    )
    if latest and latest[0] and at < latest[0]:
        raise LifecycleError(
            f"Cannot start measuring at {at}: node {node.code} already has readings "
            f"up to {latest[0]}. Activation cannot reach back over stored readings.",
            code="backdated_activation",
        )


def _require_legal(db: Session, deployment: Deployment, to_status: str, *, action: str):
    """Is this move permitted at all?

    Checked before any other guard. "You cannot do this from this state" is more
    fundamental than "the node is not commissioned" — reporting the latter for
    an illegal transition sends the operator to fix the wrong thing.
    """
    if not lifecycle.can_transition(db, deployment.status, to_status):
        legal = lifecycle.legal_transitions_from(db, deployment.status)
        allowed = ", ".join(legal) if legal else "nothing — this is a final state"
        raise LifecycleError(
            f"Cannot {ACTION_LABELS.get(action, action).lower()} a deployment that is "
            f"'{deployment.status}'. From '{deployment.status}' it may become: {allowed}.",
            code="illegal_transition",
        )


def _transition(db: Session, deployment: Deployment, to_status: str, *, action: str):
    _require_legal(db, deployment, to_status, action=action)
    deployment.status = to_status


# --------------------------------------------------------------- operations
def begin_installation(db: Session, deployment: Deployment) -> Deployment:
    """planned -> installing. Claims the node exclusively; writes no timestamp."""
    _require_legal(db, deployment, "installing", action="begin_installation")
    _require_no_live_deployment(db, deployment.node, exclude_id=deployment.id)
    _transition(db, deployment, "installing", action="begin_installation")
    return deployment


def activate(db: Session, deployment: Deployment, *, at: datetime | None = None) -> Deployment:
    """installing -> active. Attribution begins here, and only here.

    `at` exists for the create-and-activate path so both transitions share one
    instant. It is never operator-supplied.
    """
    _require_legal(db, deployment, "active", action="activate")

    node = deployment.node
    moment = at or datetime.utcnow()

    _require_commissioned(db, node)
    _require_no_live_deployment(db, node, exclude_id=deployment.id)
    _require_no_backdating(db, node, moment)

    _transition(db, deployment, "active", action="activate")
    deployment.activated_at = moment
    return deployment


def complete(db: Session, deployment: Deployment, *, at: datetime | None = None) -> Deployment:
    """active -> completed. Closes the window; the campaign keeps its readings."""
    _require_legal(db, deployment, "completed", action="complete")
    # Defence in depth. Unreachable through the normal flow: only an `active`
    # deployment may be completed, and R2 (M12 trigger) guarantees an active
    # deployment has activated_at. Kept so a future path that bypasses the
    # transition table cannot produce a terminal deployment with no window.
    if deployment.activated_at is None:
        raise LifecycleError(
            "Cannot finish measuring: this deployment has never been activated.",
            code="never_activated",
        )
    _transition(db, deployment, "completed", action="complete")
    deployment.closed_at = at or datetime.utcnow()
    return deployment


def cancel(db: Session, deployment: Deployment, *, at: datetime | None = None) -> Deployment:
    """-> cancelled. Only while nothing was measured (Rule 8)."""
    attributed = attributed_reading_count(db, deployment.id)
    if attributed:
        raise LifecycleError(
            f"Cannot cancel: {attributed:,} readings are attributed to this deployment. "
            "A campaign that produced measurements happened — finish it instead.",
            code="has_attributed_readings",
        )
    _transition(db, deployment, "cancelled", action="cancel")
    if deployment.activated_at is not None:
        deployment.closed_at = at or datetime.utcnow()
    return deployment


def supersede_and_activate(
    db: Session, incoming: Deployment, previous: Deployment, *, at: datetime | None = None
) -> tuple[Deployment, Deployment]:
    """Close one campaign and start the next, in a single transaction.

    The alternative designs were rejected during review: closing the previous
    deployment automatically would write an end time the operator never chose,
    and a two-call confirmation flow cannot be atomic from the client's side.
    Here the operator names both deployments and the system supplies one instant
    for the handover, so the windows meet exactly and cannot overlap.
    """
    moment = at or datetime.utcnow()

    if previous.node_id != incoming.node_id:
        raise LifecycleError(
            f"Cannot supersede: deployment {previous.id} is on node "
            f"{previous.node.code}, not {incoming.node.code}.",
            code="node_mismatch",
        )
    if previous.id == incoming.id:
        raise LifecycleError(
            "Cannot supersede a deployment with itself.", code="node_mismatch"
        )

    # Close first, so the exclusivity check inside activate() sees a free node.
    complete(db, previous, at=moment)

    # The operator's action is "hand over to this campaign". Whatever
    # transitions that requires are performed here, atomically — a handover
    # should not fail because the incoming campaign was still a plan.
    if incoming.status == lifecycle.initial_status(db):
        begin_installation(db, incoming)

    # One microsecond later, so the windows are adjacent and provably disjoint
    # rather than sharing an instant. Both bounds are inclusive, so touching
    # windows would overlap.
    activate(db, incoming, at=moment + timedelta(microseconds=1))
    return previous, incoming


# ------------------------------------------------- node deployment context
#
# A node does not belong to a building. A deployment belongs to a building, and
# a reading belongs to a building; a node belongs to neither.
#
# These two functions are the only sanctioned way to answer "where is this
# node?", and they answer two *different* questions that the old
# `node.building` field silently conflated. Anything that needs a node's
# location asks one of them explicitly, so the caller has to choose which
# question it means.


def current_deployment(db: Session, node_id: int) -> Deployment | None:
    """Where this node is deployed RIGHT NOW, or None.

    "Right now" means a deployment that has actually been activated and has not
    been closed — never "the newest row", which is what
    `ORDER BY id DESC LIMIT 1` returned regardless of lifecycle state. A node
    whose last campaign finished is deployed nowhere, and this returns None for
    it rather than pointing at history.

    Derived from the lifecycle table: operational statuses that have an
    activation instant. It cannot return two, because the partial unique index
    from M12 permits only one live deployment per node.
    """
    operational = [s.code for s in lifecycle.all_statuses(db) if s.is_operational]
    if not operational:
        return None
    return (
        db.query(Deployment)
        .filter(
            Deployment.node_id == node_id,
            Deployment.status.in_(operational),
            Deployment.activated_at.isnot(None),
        )
        .order_by(Deployment.activated_at.desc())
        .first()
    )


def last_completed_deployment(db: Session, node_id: int) -> Deployment | None:
    """Where this node was deployed most recently, historically.

    Explicitly historical. Never a substitute for `current_deployment`, and
    never surfaced through a generic "building" property.
    """
    terminal = [
        s.code for s in lifecycle.all_statuses(db)
        if s.is_terminal and s.allows_attribution
    ]
    if not terminal:
        return None
    return (
        db.query(Deployment)
        .filter(
            Deployment.node_id == node_id,
            Deployment.status.in_(terminal),
            Deployment.closed_at.isnot(None),
        )
        .order_by(Deployment.closed_at.desc())
        .first()
    )


def deployment_summary(db: Session, deployment: Deployment | None) -> dict | None:
    """Serialise a deployment as a node's location. None stays None."""
    if deployment is None:
        return None
    state = lifecycle.get(db, deployment.status)
    return {
        "deployment_id": deployment.id,
        "building_id": deployment.building_id,
        "building_name": deployment.building.name if deployment.building else None,
        "building_is_placeholder": (
            deployment.building.is_placeholder if deployment.building else None
        ),
        "electrical_panel": (
            deployment.electrical_panel.name if deployment.electrical_panel else None
        ),
        "status": deployment.status,
        "status_label": state.label if state else deployment.status,
        "activated_at": deployment.activated_at.isoformat() if deployment.activated_at else None,
        "closed_at": deployment.closed_at.isoformat() if deployment.closed_at else None,
        "planned_start": deployment.start_date,
        "planned_end": deployment.end_date,
    }
