from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.services.anomaly_engine import ACTIVE, detect_all_anomalies

router = APIRouter()


@router.get("")
def list_anomalies(
    db: Session = Depends(get_db),
    deployment_id: int | None = None,
    include_resolved: bool = False,
):
    """Anomaly findings, each carrying an ACTIVE or RESOLVED status.

    ``deployment_id`` scopes both the nodes and the readings evaluated.

    ``include_resolved`` defaults to **false** so that a client which knows
    nothing about statuses — the production dashboard until it is promoted —
    receives only conditions that are true right now. Returning recovered
    findings to such a client would render them as though they were live, which
    is the defect this work exists to remove. Clients that display recovery
    history opt in explicitly.

    ``count`` counts ACTIVE findings only, in both modes.
    """
    anomalies = detect_all_anomalies(db, deployment_id=deployment_id)
    active = [a for a in anomalies if a.get("status") == ACTIVE]
    resolved = [a for a in anomalies if a.get("status") != ACTIVE]

    return {
        "count": len(active),
        "active_count": len(active),
        "resolved_count": len(resolved),
        "anomalies": anomalies if include_resolved else active,
    }
