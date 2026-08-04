from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import lifecycle
from app.db.database import get_db
from app.db.models import (
    Building,
    Campus,
    Deployment,
    ElectricalPanel,
    Node,
    OrganizationalUnit,
)
from app.services import deployment_ops as ops
from app.services import deployment_scope
from app.services.deployment_ops import LifecycleError

router = APIRouter()


def _lifecycle_error(exc: LifecycleError) -> HTTPException:
    """Turn a business-rule violation into a 409 that names the rule."""
    return HTTPException(status_code=409, detail={"error": exc.code, "message": exc.message})


class DeploymentCreate(BaseModel):
    node_id: str
    campus_id: int
    organizational_unit_id: int | None = None
    custom_unit_name: str | None = None
    custom_unit_type: str | None = "manual"
    building_name: str
    electrical_panel: str
    start_date: str
    end_date: str
    notes: str | None = None
    #: Whether to start measuring immediately. Defaults to True so the existing
    #: technician form behaves exactly as before — but the deployment now walks
    #: planned -> installing -> active through validated transitions rather than
    #: being inserted straight into 'active'. Pass False to plan ahead.
    activate: bool = True


class DeploymentPlanEdit(BaseModel):
    """Planning information. Editable only before measurement begins."""

    start_date: str | None = None
    end_date: str | None = None
    notes: str | None = None


class SupersedeRequest(BaseModel):
    #: The deployment to finish as part of activating this one. Naming it is
    #: required — the system never closes a campaign the operator did not name.
    supersede_deployment_id: int | None = None


@router.get("")
def list_deployments(db: Session = Depends(get_db)):
    # Listed newest-first for display. That ordering is presentation only and
    # must never be read as "which one is current" — see current_by_node below.
    deployments = db.query(Deployment).order_by(Deployment.id.desc()).all()

    # Which deployment each node is ACTUALLY on, from the lifecycle rather than
    # from row order. Previously this was "highest id wins", so a completed
    # campaign was flagged current whenever it happened to be the newest row.
    current_by_node = {}
    for node_id in {d.node_id for d in deployments}:
        current = ops.current_deployment(db, node_id)
        if current is not None:
            current_by_node[node_id] = current.id

    online_limit = datetime.utcnow() - timedelta(seconds=120)

    # Observed telemetry, in one grouped query rather than a MAX() per row.
    # This is deliberately NOT the lifecycle status: a deployment can be
    # administratively `completed` and still be ingesting, which is exactly the
    # case for deployment 5. See app/services/deployment_scope.py.
    now = datetime.utcnow()
    latest_reading = deployment_scope.last_reading_by_deployment(db)

    result = []

    for deployment in deployments:
        # Runtime connectivity. Reported as its own field — it is a property of
        # the node, not of the campaign, and must never overwrite the lifecycle
        # (ADR-0001). Before M7 this value *replaced* `status`, so a completed
        # campaign on a live node reported as active.
        node_online = bool(deployment.node.last_sync and deployment.node.last_sync >= online_limit)
        state = lifecycle.get(db, deployment.status)

        result.append(
            {
                "id": deployment.id,
                "node_id": deployment.node.code,
                "node_name": deployment.node.name,
                "building_name": deployment.building.name,
                "building_is_placeholder": deployment.building.is_placeholder,
                "campus": deployment.building.campus.name,
                "delegation": deployment.building.campus.delegation.name,
                "organizational_unit": deployment.building.organizational_unit.name,
                "electrical_panel": deployment.electrical_panel.name,
                # The stored lifecycle, authoritative and unmodified.
                "status": deployment.status,
                "status_label": state.label if state else deployment.status,
                # What the operator may do next. Verbs, not state names — a client
                # renders buttons from this and never needs to know the machine.
                "available_actions": ops.available_actions(db, deployment),
                # Runtime health, kept strictly separate from the lifecycle above.
                "node_online": node_online,
                "node_commission_state": deployment.node.commission_state,
                "is_current_for_node": current_by_node.get(deployment.node_id) == deployment.id,
                # Observed measurement state, also strictly separate from `status`.
                # `telemetry_state` answers "is this deployment producing data right
                # now"; `status` answers "what did an operator declare". The
                # dashboard groups and badges on the former, so a completed-but-
                # live campaign is not mislabelled as archived.
                "telemetry_state": deployment_scope.telemetry_state(
                    latest_reading.get(deployment.id), now
                ),
                "last_reading_at": (
                    latest_reading[deployment.id].isoformat()
                    if deployment.id in latest_reading
                    else None
                ),
                # The plan, as scheduled by a human.
                "start_date": deployment.start_date,
                "end_date": deployment.end_date,
                # What actually happened. Business names: `activated_at` and
                # `closed_at` are storage, and an operator should never have to
                # think about them.
                "measuring_since": (
                    deployment.activated_at.isoformat() if deployment.activated_at else None
                ),
                "measuring_until": (
                    deployment.closed_at.isoformat() if deployment.closed_at else None
                ),
                "reading_count": ops.attributed_reading_count(db, deployment.id),
                "notes": deployment.notes,
            }
        )

    return result


@router.get("/lifecycle")
def deployment_lifecycle(db: Session = Depends(get_db)):
    """The canonical lifecycle, so no client needs to restate the values."""
    return {
        "statuses": [
            {
                "code": s.code,
                "label": s.label,
                "is_terminal": s.is_terminal,
                "allows_attribution": s.allows_attribution,
                "is_operational": s.is_operational,
                "description": s.description,
                "transitions_to": list(lifecycle.legal_transitions_from(db, s.code)),
            }
            for s in lifecycle.all_statuses(db)
        ],
        "actions": [
            {
                "action": action,
                "label": ops.ACTION_LABELS[action],
                "from_status": frm,
                "to_status": to,
            }
            for action, (frm, to) in ops.ACTIONS.items()
        ]
        + [
            {
                "action": "cancel",
                "label": ops.ACTION_LABELS["cancel"],
                "from_status": None,
                "to_status": "cancelled",
            },
            {
                "action": "edit",
                "label": ops.ACTION_LABELS["edit"],
                "from_status": None,
                "to_status": None,
            },
        ],
    }


@router.post("")
def create_deployment(payload: DeploymentCreate, db: Session = Depends(get_db)):
    node = db.query(Node).filter(Node.code == payload.node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    campus = db.query(Campus).filter(Campus.id == payload.campus_id).first()
    if not campus:
        raise HTTPException(status_code=404, detail="Campus not found")

    if payload.organizational_unit_id:
        unit = (
            db.query(OrganizationalUnit)
            .filter(OrganizationalUnit.id == payload.organizational_unit_id)
            .first()
        )
        if not unit:
            raise HTTPException(status_code=404, detail="Organizational unit not found")
    else:
        if not payload.custom_unit_name:
            raise HTTPException(
                status_code=400, detail="custom_unit_name is required when no unit is selected"
            )

        unit = OrganizationalUnit(
            name=payload.custom_unit_name,
            unit_type=payload.custom_unit_type or "manual",
            campus_id=campus.id,
        )
        db.add(unit)
        db.commit()
        db.refresh(unit)

    building_code = (
        f"B-MANUAL-{unit.id}-{payload.building_name.strip().lower().replace(' ', '-')[:30]}"
    )

    building = (
        db.query(Building)
        .filter(
            Building.name == payload.building_name,
            Building.organizational_unit_id == unit.id,
        )
        .first()
    )

    if not building:
        building = Building(
            code=building_code,
            name=payload.building_name,
            campus_id=campus.id,
            organizational_unit_id=unit.id,
            is_user_defined=True,
            notes="Created from technician deployment form.",
        )
        db.add(building)
        db.commit()
        db.refresh(building)

    panel = (
        db.query(ElectricalPanel)
        .filter(
            ElectricalPanel.name == payload.electrical_panel,
            ElectricalPanel.building_id == building.id,
        )
        .first()
    )

    if not panel:
        panel = ElectricalPanel(
            name=payload.electrical_panel,
            building_id=building.id,
            notes="Created from technician deployment form.",
        )
        db.add(panel)
        db.commit()
        db.refresh(panel)

    # Every deployment is born planned. Nothing is reserved and nothing is
    # attributed until it is explicitly activated — a plan is a calendar entry.
    deployment = Deployment(
        node_id=node.id,
        building_id=building.id,
        electrical_panel_id=panel.id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        status=lifecycle.initial_status(db),
        notes=payload.notes,
    )
    db.add(deployment)
    db.flush()

    # The technician form's action is "install this and start measuring", so by
    # default the whole chain runs here — but as validated transitions, inside
    # one transaction. A failure at any step leaves no deployment behind.
    if payload.activate:
        try:
            ops.begin_installation(db, deployment)
            ops.activate(db, deployment)
        except LifecycleError as exc:
            db.rollback()
            raise _lifecycle_error(exc)

    db.commit()
    db.refresh(deployment)

    return {
        "id": deployment.id,
        "node_id": node.code,
        "building_name": building.name,
        "campus": campus.name,
        "organizational_unit": unit.name,
        "electrical_panel": panel.name,
        "status": deployment.status,
        "available_actions": ops.available_actions(db, deployment),
        "measuring_since": deployment.activated_at.isoformat() if deployment.activated_at else None,
    }


def _get(db: Session, deployment_id: int) -> Deployment:
    deployment = db.query(Deployment).filter(Deployment.id == deployment_id).first()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")
    return deployment


def _summary(db: Session, deployment: Deployment) -> dict:
    return {
        "id": deployment.id,
        "node_id": deployment.node.code,
        "building_name": deployment.building.name,
        "electrical_panel": deployment.electrical_panel.name,
        "status": deployment.status,
        "available_actions": ops.available_actions(db, deployment),
        "measuring_since": deployment.activated_at.isoformat() if deployment.activated_at else None,
        "measuring_until": deployment.closed_at.isoformat() if deployment.closed_at else None,
        "reading_count": ops.attributed_reading_count(db, deployment.id),
    }


@router.get("/{deployment_id}")
def get_deployment(deployment_id: int, db: Session = Depends(get_db)):
    return _summary(db, _get(db, deployment_id))


@router.patch("/{deployment_id}")
def edit_plan(deployment_id: int, payload: DeploymentPlanEdit, db: Session = Depends(get_db)):
    """Correct the planning information.

    Only while the deployment has never measured. Once activation has happened
    the schedule becomes part of the campaign's historical record, and the
    fields that define attribution are frozen outright (M12 trigger).
    """
    deployment = _get(db, deployment_id)

    if deployment.activated_at is not None:
        raise _lifecycle_error(
            LifecycleError(
                f"Cannot edit the plan: this deployment started measuring on "
                f"{deployment.activated_at}. Create a new deployment instead.",
                code="already_activated",
            )
        )

    state = lifecycle.get(db, deployment.status)
    if state and state.is_terminal:
        raise _lifecycle_error(
            LifecycleError(
                f"Cannot edit the plan: this deployment is {state.label.lower()} and is "
                "part of the historical record.",
                code="terminal_state",
            )
        )

    for field in ("start_date", "end_date", "notes"):
        value = getattr(payload, field)
        if value is not None:
            setattr(deployment, field, value)

    db.commit()
    db.refresh(deployment)
    return _summary(db, deployment)


@router.post("/{deployment_id}/begin-installation")
def begin_installation(deployment_id: int, db: Session = Depends(get_db)):
    """The technician is on site. Claims the node; measures nothing yet."""
    deployment = _get(db, deployment_id)
    try:
        ops.begin_installation(db, deployment)
        db.commit()
    except LifecycleError as exc:
        db.rollback()
        raise _lifecycle_error(exc)
    db.refresh(deployment)
    return _summary(db, deployment)


@router.post("/{deployment_id}/activate")
def activate_deployment(
    deployment_id: int,
    payload: SupersedeRequest | None = None,
    db: Session = Depends(get_db),
):
    """Start measuring. Attribution begins here, and only here.

    If another campaign is already running on this node the request is refused,
    naming it. To hand over, name it explicitly via `supersede_deployment_id`:
    both the close and the activation then happen in one transaction, one
    microsecond apart, so the windows are adjacent and provably disjoint.
    """
    deployment = _get(db, deployment_id)
    supersede_id = payload.supersede_deployment_id if payload else None

    try:
        if supersede_id is not None:
            previous = _get(db, supersede_id)
            ops.supersede_and_activate(db, deployment, previous)
        else:
            ops.activate(db, deployment)
        db.commit()
    except LifecycleError as exc:
        db.rollback()
        raise _lifecycle_error(exc)

    db.refresh(deployment)
    return _summary(db, deployment)


@router.post("/{deployment_id}/complete")
def complete_deployment(
    deployment_id: int,
    dry_run: bool = False,
    db: Session = Depends(get_db),
):
    """Finish measuring. The campaign keeps every reading it took."""
    deployment = _get(db, deployment_id)
    node = deployment.node

    if dry_run:
        return {
            "ok": "complete" in ops.available_actions(db, deployment),
            "dry_run": True,
            "deployment_id": deployment.id,
            "node_id": node.code,
            "building": deployment.building.name,
            "reading_count": ops.attributed_reading_count(db, deployment.id),
            "buffer_pending": node.buffer_pending,
            "action": "Deployment can be completed safely",
        }

    try:
        ops.complete(db, deployment)
        # The node is free for its next campaign. Its commission state is
        # untouched: finishing a campaign says nothing about whether the node is
        # authorised (ADR-0001).
        node.buffer_pending = 0
        db.commit()
    except LifecycleError as exc:
        db.rollback()
        raise _lifecycle_error(exc)

    db.refresh(deployment)
    return _summary(db, deployment)


@router.post("/{deployment_id}/cancel")
def cancel_deployment(deployment_id: int, db: Session = Depends(get_db)):
    """Call off a campaign. Refused once anything has been measured."""
    deployment = _get(db, deployment_id)
    try:
        ops.cancel(db, deployment)
        db.commit()
    except LifecycleError as exc:
        db.rollback()
        raise _lifecycle_error(exc)
    db.refresh(deployment)
    return _summary(db, deployment)


@router.post("/{deployment_id}/finish")
def finish_deployment(
    deployment_id: int,
    dry_run: bool = True,
    db: Session = Depends(get_db),
):
    """Compatibility alias for /complete.

    Kept because the existing frontend calls it with `dry_run=true` first and
    reads `ok`, `reason`, `reading_count` and `buffer_pending`. The behaviour is
    the same as before with one correction: completing now records when
    measurement actually stopped, which the old implementation never did — the
    omission that let deployment 4 become a completed campaign claiming every
    future instant.
    """
    deployment = _get(db, deployment_id)
    node = deployment.node

    if "complete" not in ops.available_actions(db, deployment):
        legal = lifecycle.legal_transitions_from(db, deployment.status)
        return {
            "ok": False,
            "dry_run": dry_run,
            "reason": (
                "This deployment has never been activated"
                if deployment.activated_at is None
                else f"Cannot complete a deployment that is '{deployment.status}'"
            ),
            "deployment_id": deployment.id,
            "status": deployment.status,
            "legal_transitions": list(legal),
        }

    if node.buffer_pending and node.buffer_pending > 0:
        return {
            "ok": False,
            "dry_run": dry_run,
            "reason": "Node still has pending buffered samples",
            "deployment_id": deployment.id,
            "node_id": node.code,
            "buffer_pending": node.buffer_pending,
        }

    result = {
        "ok": True,
        "dry_run": dry_run,
        "deployment_id": deployment.id,
        "node_id": node.code,
        "building": deployment.building.name,
        "reading_count": ops.attributed_reading_count(db, deployment.id),
        "buffer_pending": node.buffer_pending,
        "action": "Deployment can be completed safely" if dry_run else "Deployment completed",
    }

    if dry_run:
        return result

    try:
        ops.complete(db, deployment)
        node.buffer_pending = 0
        db.commit()
    except LifecycleError as exc:
        db.rollback()
        raise _lifecycle_error(exc)

    db.refresh(deployment)
    result["deployment_status"] = deployment.status
    result["node_status"] = node.status
    result["measuring_until"] = deployment.closed_at.isoformat() if deployment.closed_at else None
    return result


# ----------------------------------------------------------------- ratings
#
# Physical limits of the installation this campaign measures (M8). These take
# precedence over the node's own ratings in the alert threshold resolver
# (app/monitoring/thresholds.py), because the panel changes between campaigns
# while the clamp travels with the Pi.


class DeploymentRatings(BaseModel):
    """Physical ratings of the panel this deployment measures.

    Every field is optional and nullable. Send only what is known: an omitted
    field is left unchanged, and the threshold resolver falls through to the
    next source for anything still NULL. A guessed rating is worse than an
    absent one, because it looks authoritative.
    """

    #: Main breaker rating in amperes — the best single value to provide. It is
    #: what protects the conductor, so it defines the real limit.
    panel_main_breaker_a: float | None = None
    #: CT/clamp measurement ceiling for this installation, if different from
    #: the node's own clamp.
    ct_max_current_a: float | None = None
    nominal_voltage_v: float | None = None
    phase_count: int | None = None
    #: Explicit alert levels. Setting any of these overrides every derivation.
    warning_current_a: float | None = None
    critical_current_a: float | None = None
    emergency_current_a: float | None = None
    #: Seconds a breach must persist before anyone is notified.
    sustained_seconds: int | None = None


@router.get("/{deployment_id}/ratings")
def get_deployment_ratings(deployment_id: int, db: Session = Depends(get_db)):
    """Ratings recorded for this deployment, and the limits they resolve to."""
    deployment = db.query(Deployment).filter(Deployment.id == deployment_id).first()
    if deployment is None:
        raise HTTPException(status_code=404, detail="Deployment not found")

    from app.monitoring.config import get_config
    from app.monitoring.thresholds import describe, resolve_current_thresholds

    resolved = resolve_current_thresholds(deployment.node, deployment, get_config())

    return {
        "deployment_id": deployment.id,
        "node_code": deployment.node.code if deployment.node else None,
        "ratings": {field: getattr(deployment, field) for field in DeploymentRatings.model_fields},
        "applies": describe(deployment.node, deployment),
        "resolved_thresholds": {
            "warning_a": resolved.warning,
            "critical_a": resolved.critical,
            "emergency_a": resolved.emergency,
            "physical_ceiling_a": resolved.physical_ceiling,
            "sustained_seconds": resolved.sustained_seconds,
            "source": resolved.source,
        },
    }


@router.put("/{deployment_id}/ratings")
def set_deployment_ratings(
    deployment_id: int, payload: DeploymentRatings, db: Session = Depends(get_db)
):
    """Record the physical ratings of the panel this deployment measures.

    Only fields present in the body are written, so a partial update cannot
    silently erase a rating entered earlier.
    """
    deployment = db.query(Deployment).filter(Deployment.id == deployment_id).first()
    if deployment is None:
        raise HTTPException(status_code=404, detail="Deployment not found")

    provided = payload.model_dump(exclude_unset=True)
    for field, value in provided.items():
        if value is not None and value <= 0:
            raise HTTPException(status_code=422, detail=f"{field} must be positive, got {value}")
        setattr(deployment, field, value)

    db.commit()
    return get_deployment_ratings(deployment_id, db)
