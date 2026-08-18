"""The single gate every measurement passes through — ADR-0002 + ADR-0004.

Four questions, asked in order, never conflated. Before this module each ingest
endpoint answered them ad hoc, and two of them answered none:

1. **Authentication — which physical node sent this?**
   A bearer credential resolved against ``nodes.auth_token_hash``. Never the
   source address: three nodes here share two NAT addresses, and on 2026-08-06
   two different producers published as N001 from one of them.

2. **Authorization — may this node upload?**
   ``node_commission_states.may_upload``. ADR-0002 chose 403 for a node that may
   not: it buffers locally and retries, so refusing loses nothing. See
   :func:`authorize` for why that decision was kept.

3. **Context — what kind of measurement is this?**
   ``nodes.measurement_context``. Declared by the operator, never inferred from
   the data. A powered node with no campaign declares
   ``infrastructure_validation``: real measurements, retained, never counted.

4. **Attribution — which operational deployment covers ``captured_at``?**
   Delegated to :mod:`app.services.attribution`, which matches on
   ``activated_at``/``closed_at`` and returns nothing when nothing covers.

The bug this replaces
---------------------
Both ingest paths selected a deployment with
``order_by(Deployment.id.desc()).first()`` — **the newest deployment wins**.
That is how, with zero operational deployments, N001's readings were still
being attributed to deployment 6 (closed 2026-08-03) and building 9, and
stored as ``production``. Newest is not the same as *covering*, and on a node
that has finished a campaign it is never the same.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db import commissioning, node_auth
from app.db.models import Node
from app.services import attribution

log = logging.getLogger("ingest.gate")


@dataclass(frozen=True)
class IngestDecision:
    """Everything an ingest endpoint needs, already decided."""

    node: Node
    #: Whether a credential was presented and matched this node.
    authenticated: bool
    #: Whether the node's commission state permits uploading.
    authorized: bool
    #: Declared measurement context for this node.
    context: str

    #: Attribution, resolved from captured_at. NULL when nothing covers it.
    deployment_id: int | None
    building_id: int | None
    electrical_panel_id: int | None
    #: Why the resolver decided what it did — stored for auditability.
    reason: str

    @property
    def attributed(self) -> bool:
        return self.deployment_id is not None


def authenticate_node(
    db: Session, request, claimed_code: str, *, endpoint: str
) -> tuple[Node, bool]:
    """Resolve the sender to a node, or refuse.

    Returns ``(node, authenticated)``. Raises 401 when a credential is required
    and absent or unknown, 403 when a credential authenticates as a *different*
    node than the one claimed — impersonation is always refused, in either mode,
    because storing a payload known to be mislabelled corrupts the record used
    to detect the problem.

    Whether a credential is *required* is asked of
    :func:`node_auth.enforcement_applies_to`, never computed here. This function
    used to take an ``enforcing: bool`` that callers filled in with
    ``get_config().node_auth.enforcing`` — the mode alone, with
    ``exempt_nodes`` dropped on the floor. Taking the node code and asking the
    policy removes the parameter that made the divergence expressible.
    """
    source_ip = node_auth.client_ip(request)
    user_agent = request.headers.get("user-agent")
    result = node_auth.authenticate(db, node_auth.extract_token(request.headers))

    if result.authenticated and result.subject != claimed_code:
        node_auth.record_violation(
            db,
            violation="subject_mismatch",
            claimed_node=claimed_code,
            auth_subject=result.subject,
            source_ip=source_ip,
            user_agent=user_agent,
            endpoint=endpoint,
            detail=f"credential for {result.subject} claimed {claimed_code}",
        )
        db.commit()
        raise HTTPException(
            status_code=403,
            detail=(
                f"credential authenticates as {result.subject}, " f"cannot upload as {claimed_code}"
            ),
        )

    if not result.authenticated:
        enforcing = node_auth.enforcement_applies_to(claimed_code)
        node_auth.record_violation(
            db,
            violation=result.violation or "unauthenticated",
            claimed_node=claimed_code,
            source_ip=source_ip,
            user_agent=user_agent,
            endpoint=endpoint,
            detail="enforcing" if enforcing else "permissive",
        )
        if enforcing:
            db.commit()
            raise HTTPException(
                status_code=401,
                detail=(
                    "node credential required (ADR-0002); " "present Authorization: Bearer <token>"
                ),
            )

    node = db.query(Node).filter(Node.code == claimed_code).first()
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")

    return node, result.authenticated


def authorize(db: Session, node: Node, *, endpoint: str) -> bool:
    """Decide whether this node may upload, and act on it — ADR-0002 step 2.

    **Policy A: refuse with 403.** Chosen over "accept and store as diagnostic"
    for three reasons specific to this platform:

    *The edge already retains it.* The collector buffers into its own SQLite and
    marks rows by ``sync_status``; a refused upload is kept on the node, not
    lost. Storing it server-side too would duplicate the retention without
    adding a capability.

    *ADR-0002 already decided this*, and consistency across ingest paths matters
    more than a marginal gain — the whole class of bug being fixed here came
    from endpoints answering the same question differently.

    *An unauthorized node is a statement of intent.* ``registered`` means "not
    in service"; ``suspended`` means "uploads deliberately revoked, possibly for
    theft or fault". Accepting writes from either would make the state
    meaningless.

    Diagnostics are not lost by this choice: an **authorized** node with no
    deployment still uploads, and its readings are retained under a
    non-production context with NULL attribution. That is the case the physical
    context describes, and it is served.

    The refusal is recorded, never silent.
    """
    if commissioning.may_upload(db, node.commission_state):
        return True

    state = commissioning.get(db, node.commission_state)
    node_auth.record_violation(
        db,
        violation="not_authorized",
        claimed_node=node.code,
        auth_subject=node.code,
        endpoint=endpoint,
        detail=f"commission_state={node.commission_state} may_upload=0",
    )
    db.commit()
    raise HTTPException(
        status_code=403,
        detail=(
            f"node {node.code} is '{node.commission_state}'"
            f"{f' ({state.label})' if state else ''} and may not upload "
            "(ADR-0002 step 2). Readings remain buffered on the node; "
            "commission it to resume ingestion."
        ),
    )


def classify(db: Session, node: Node, captured_at: datetime | None) -> IngestDecision:
    """Resolve context and attribution for one measurement — ADR-0004.

    Attribution is decided by ``captured_at`` against operational windows, not
    by which deployment happens to be newest. When nothing covers the instant,
    every attribution field is NULL and the reason says why. The measured values
    are stored regardless: a reading that cannot be attributed is stored
    unattributed, never refused.
    """
    # load_state uses raw DBAPI-style `conn.execute("SELECT ...")`, so it needs
    # the driver connection, not the SQLAlchemy one. Taken from the *current*
    # session so the snapshot sees this transaction's view rather than a second
    # connection's.
    state = attribution.load_state(db.connection().connection.driver_connection)
    decision = attribution.resolve(state, node.id, captured_at)

    return IngestDecision(
        node=node,
        authenticated=True,
        authorized=True,
        context=decision.context,
        deployment_id=decision.deployment_id,
        building_id=decision.building_id,
        electrical_panel_id=decision.electrical_panel_id,
        reason=decision.reason,
    )


def admit(
    db: Session,
    request,
    claimed_code: str,
    captured_at: datetime | None,
    *,
    endpoint: str,
) -> IngestDecision:
    """Run the whole gate: authenticate, authorize, classify, attribute.

    The only entry point ingest endpoints should use, so all four questions are
    answered the same way everywhere.
    """
    node, authenticated = authenticate_node(db, request, claimed_code, endpoint=endpoint)
    authorize(db, node, endpoint=endpoint)
    decision = classify(db, node, captured_at)

    if not decision.attributed:
        log.debug(
            "unattributed reading from %s at %s: %s",
            claimed_code,
            captured_at,
            decision.reason,
        )

    return IngestDecision(
        node=node,
        authenticated=authenticated,
        authorized=True,
        context=decision.context,
        deployment_id=decision.deployment_id,
        building_id=decision.building_id,
        electrical_panel_id=decision.electrical_panel_id,
        reason=decision.reason,
    )


__all__ = ["IngestDecision", "admit", "authenticate_node", "authorize", "classify"]
