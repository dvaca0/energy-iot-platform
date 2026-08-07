from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import EnergyReading, Node
from app.monitoring.config import get_config
from app.services import ingest_gate

router = APIRouter(tags=["Edge"])


class Measurement(BaseModel):
    captured_at: str

    voltage_a: float | None = None
    current_a: float | None = None
    active_power_a: float | None = None
    apparent_power_a: float | None = None
    power_factor_a: float | None = None
    frequency_a: float | None = None

    voltage_b: float | None = None
    current_b: float | None = None
    active_power_b: float | None = None
    apparent_power_b: float | None = None
    power_factor_b: float | None = None
    frequency_b: float | None = None

    voltage_c: float | None = None
    current_c: float | None = None
    active_power_c: float | None = None
    apparent_power_c: float | None = None
    power_factor_c: float | None = None
    frequency_c: float | None = None

    total_active_power: float | None = None
    total_apparent_power: float | None = None
    total_current: float | None = None

    temperature_c: float | None = None
    uptime_s: int | None = None

    errors_a: str | None = None
    errors_b: str | None = None
    errors_c: str | None = None


class BatchPayload(BaseModel):
    device_id: str
    measurements: list[Measurement]


@router.post("/api/v1/measurements/batch")
def ingest_batch(payload: BatchPayload, request: Request, db: Session = Depends(get_db)):
    """Ingest a batch — each measurement attributed on its own captured_at.

    Attribution is per-measurement, not per-batch: a batch may legitimately
    straddle a deployment handover (deployment 4 handed to 6 one 15-second
    sample apart), so a single decision for the whole batch would misattribute
    everything on one side of the boundary.

    Authentication and authorization happen once for the batch, because they are
    properties of the sender rather than of a measurement.
    """
    node, _authenticated = ingest_gate.authenticate_node(
        db,
        request,
        payload.device_id,
        endpoint="/api/v1/measurements/batch",
        enforcing=get_config().node_auth.enforcing,
    )
    ingest_gate.authorize(db, node, endpoint="/api/v1/measurements/batch")

    inserted = 0

    for m in payload.measurements:

        ts = datetime.fromisoformat(m.captured_at.replace("Z", "+00:00"))
        if ts.tzinfo is not None:
            ts = ts.astimezone(UTC).replace(tzinfo=None)

        # Resolved per measurement from its own captured_at.
        decision = ingest_gate.classify(db, node, ts)

        reading = EnergyReading(
            node_id=node.id,
            building_id=decision.building_id,
            deployment_id=decision.deployment_id,
            context=decision.context,
            timestamp=ts,
            voltage=((m.voltage_a or 0) + (m.voltage_b or 0) + (m.voltage_c or 0)) / 3,
            current=m.total_current,
            power_kw=(m.total_active_power or 0) / 1000.0,
            energy_kwh=None,
            power_factor=(
                (m.power_factor_a or 0) + (m.power_factor_b or 0) + (m.power_factor_c or 0)
            )
            / 3,
            frequency_hz=((m.frequency_a or 0) + (m.frequency_b or 0) + (m.frequency_c or 0)) / 3,
            phase_a_voltage=m.voltage_a,
            phase_b_voltage=m.voltage_b,
            phase_c_voltage=m.voltage_c,
            phase_a_current=m.current_a,
            phase_b_current=m.current_b,
            phase_c_current=m.current_c,
        )

        db.add(reading)
        inserted += 1

    node.samples += inserted
    node.last_sync = datetime.utcnow()

    db.commit()

    return {
        "status": "ok",
        "inserted": inserted,
    }


class HeartbeatPayload(BaseModel):
    node_id: str


@router.post("/api/edge/heartbeat")
def heartbeat(payload: HeartbeatPayload, db: Session = Depends(get_db)):
    node = db.query(Node).filter(Node.code == payload.node_id).first()

    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    node.last_sync = datetime.utcnow()
    db.commit()

    return {"status": "ok", "last_sync": node.last_sync.isoformat()}
