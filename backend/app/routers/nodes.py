from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import commissioning
from app.services import deployment_ops as ops
from app.db.database import get_db
from app.db.models import Node, Deployment

router = APIRouter()

ONLINE_WINDOW_SECONDS = 120


def is_node_online(node: Node):
    if not node.last_sync:
        return False
    return node.last_sync >= datetime.utcnow() - timedelta(seconds=ONLINE_WINDOW_SECONDS)


def _node_payload(db: Session, node: Node) -> dict:
    """A node's identity, health and — explicitly — where it is deployed.

    There is deliberately no `building` field. A node does not belong to a
    building: a deployment does, and a reading does. This used to return
    `deployment.building.name` for the newest deployment row by id, regardless
    of lifecycle state, so a node whose last campaign ended still appeared to
    live in that building and a node with a merely *planned* campaign appeared
    to live in one it had never visited.

    Two explicit questions replace it, and a caller must choose which it means:

        current_deployment          where the node is deployed right now, or
                                    null — never a fallback to history
        last_completed_deployment   where it was deployed most recently,
                                    named as historical
    """
    online = is_node_online(node)
    state = commissioning.get(db, node.commission_state)

    current = ops.current_deployment(db, node.id)
    previous = ops.last_completed_deployment(db, node.id)

    return {
        "id": node.code,
        "name": node.name,

        # Identity and authorization — independent of connectivity.
        "commission_state": node.commission_state,
        "commission_label": state.label if state else node.commission_state,
        "may_upload": state.may_upload if state else False,
        "is_monitored": state.is_monitored if state else False,
        "hardware_kind": node.hardware_kind,
        "measurement_context": node.measurement_context,

        # Runtime health — derived, never stored as an authority.
        "status": "online" if online else "offline",
        "online": online,
        "last_sync": node.last_sync.isoformat() if node.last_sync else None,
        "buffer_pending": node.buffer_pending,
        "samples": node.samples,
        "ip": node.ip_address,

        # Location, stated explicitly. `current_deployment` is null whenever the
        # node is not actually deployed; it never falls back to the last one.
        "current_deployment": ops.deployment_summary(db, current),
        "last_completed_deployment": ops.deployment_summary(db, previous),
        "is_deployed": current is not None,
    }


@router.get("")
def list_nodes(db: Session = Depends(get_db)):
    """Every node the platform knows about, with its state.

    Existence is identity, not connectivity. This used to `continue` past any
    node that had not synced recently, so a node that lost power vanished from
    the API entirely rather than being reported as offline — conflating "does
    this node exist" with "is it reachable" (ADR-0001).
    """
    nodes = db.query(Node).order_by(Node.code.asc()).all()
    return [_node_payload(db, node) for node in nodes]


@router.get("/online")
def online_nodes(db: Session = Depends(get_db)):
    """Only nodes currently reachable. The filter belongs here, not in list_nodes."""
    nodes = db.query(Node).order_by(Node.code.asc()).all()
    return [_node_payload(db, node) for node in nodes if is_node_online(node)]


@router.get("/commission-states")
def commission_states(db: Session = Depends(get_db)):
    """The canonical node states, so no client needs to restate them."""
    return {
        "states": [
            {
                "code": s.code,
                "label": s.label,
                "may_upload": s.may_upload,
                "is_monitored": s.is_monitored,
                "is_terminal": s.is_terminal,
                "description": s.description,
            }
            for s in commissioning.all_states(db)
        ]
    }


# ---------------------------------------------------------------- lifecycle
#
# M7 defined node commission states but gave them no write path, so the only
# way to change one was raw SQL against the database. These endpoints close
# that gap, using app.db.commissioning.transition, which validates the move
# against node_commission_transitions and records it in node_commission_events.


class CommissionTransition(BaseModel):
    """Request to move a node to a different commission state."""

    to_state: str
    #: Why. Recorded in the audit trail; a state change with no explanation is
    #: worthless six months later.
    reason: str | None = None
    actor: str | None = None


@router.get("/{code}/commission-history")
def commission_history(code: str, db: Session = Depends(get_db)):
    """Commission-state history for one node, oldest first."""
    node = db.query(Node).filter(Node.code == code).first()
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")

    return {
        "node_code": node.code,
        "current_state": node.commission_state,
        "legal_transitions": list(
            commissioning.legal_transitions_from(db, node.commission_state)
        ),
        "history": commissioning.history(db, node.id),
    }


@router.post("/{code}/commission-state")
def set_commission_state(
    code: str, payload: CommissionTransition, db: Session = Depends(get_db)
):
    """Transition a node to a new commission state.

    The supported way to change ``commission_state``. An illegal move is
    rejected with 409 and changes nothing; the legal moves from the node's
    current state are returned in the error so a caller can correct itself.
    """
    node = db.query(Node).filter(Node.code == code).first()
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")

    previous = node.commission_state
    try:
        result = commissioning.transition(
            db, node, payload.to_state, reason=payload.reason, actor=payload.actor
        )
    except commissioning.IllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    db.commit()

    before = commissioning.get(db, previous)
    after = commissioning.get(db, node.commission_state)

    return {
        "node_code": node.code,
        "changed": result is not None,
        "previous_state": previous,
        "current_state": node.commission_state,
        # The flags are what actually drive monitoring behaviour, so they are
        # returned explicitly rather than left for the caller to look up.
        "flags": {
            "may_upload": {
                "before": before.may_upload if before else None,
                "after": after.may_upload if after else None,
            },
            "is_monitored": {
                "before": before.is_monitored if before else None,
                "after": after.is_monitored if after else None,
            },
        },
        "legal_transitions": list(
            commissioning.legal_transitions_from(db, node.commission_state)
        ),
    }


class NodeRatings(BaseModel):
    """Physical ratings of the measurement hardware attached to a node.

    Every field optional and nullable. Send only what is known; omitted fields
    are left unchanged, and an explicit null clears a value.
    """

    ct_max_current_a: float | None = None
    nominal_voltage_v: float | None = None
    phase_count: int | None = None
    warning_current_a: float | None = None
    critical_current_a: float | None = None
    emergency_current_a: float | None = None
    sustained_seconds: int | None = None


@router.get("/{code}/ratings")
def get_node_ratings(code: str, db: Session = Depends(get_db)):
    """Physical ratings recorded for this node."""
    node = db.query(Node).filter(Node.code == code).first()
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")

    return {
        "node_code": node.code,
        "ratings": {
            field: getattr(node, field) for field in NodeRatings.model_fields
        },
    }


@router.put("/{code}/ratings")
def set_node_ratings(
    code: str, payload: NodeRatings, db: Session = Depends(get_db)
):
    """Record the physical ratings of a node's measurement hardware.

    Only fields present in the request body are written, so a partial update
    cannot silently erase a rating entered earlier.
    """
    node = db.query(Node).filter(Node.code == code).first()
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")

    provided = payload.model_dump(exclude_unset=True)
    for field, value in provided.items():
        if value is not None and value <= 0:
            raise HTTPException(
                status_code=422, detail=f"{field} must be positive, got {value}"
            )
        setattr(node, field, value)

    db.commit()
    return {
        "node_code": node.code,
        "updated": sorted(provided),
        "ratings": {
            field: getattr(node, field) for field in NodeRatings.model_fields
        },
    }
