from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import lifecycle
from app.db.database import get_db
from app.db.models import Deployment, EnergyReading, Node

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
def ingest_batch(payload: BatchPayload, db: Session = Depends(get_db)):

    node = db.query(Node).filter(Node.code == payload.device_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    deployment = (
        db.query(Deployment)
        .filter(
            Deployment.node_id == node.id,
            # Which statuses may own a reading is defined once, in the
            # deployment_statuses table — not restated here (ADR-0001).
            Deployment.status.in_(lifecycle.attributing_statuses(db)),
        )
        .order_by(Deployment.id.desc())
        .first()
    )

    if not deployment:
        raise HTTPException(status_code=400, detail="Node has no active deployment")

    inserted = 0

    for m in payload.measurements:

        ts = datetime.fromisoformat(m.captured_at.replace("Z", "+00:00"))

        reading = EnergyReading(
            node_id=node.id,
            building_id=deployment.building_id,
            deployment_id=deployment.id,
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
