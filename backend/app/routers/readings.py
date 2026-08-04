from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import lifecycle
from app.db.database import get_db
from app.db.models import Deployment, EnergyReading, Node
from app.services.cost_engine import estimate_reading_cost

router = APIRouter()


class ReadingCreate(BaseModel):
    node_id: str
    timestamp: str | None = None

    voltage: float | None = None
    current: float | None = None
    power_kw: float | None = None
    #: LEGACY. Accepted so existing collectors keep working unchanged; its
    #: meaning is resolved per era (ADR-0007). New collectors should send the
    #: canonical fields below instead.
    energy_kwh: float | None = None

    # ---- canonical measurement contract (ADR-0007) ----
    #: Energy for this sample's interval. What analytics consumes.
    interval_energy_kwh: float | None = None
    #: Seconds this sample covers.
    interval_seconds: float | None = None
    #: The device's cumulative register, if it has one. Reconciliation only.
    meter_energy_kwh: float | None = None
    #: measured | counter_delta | power_integral
    energy_source: str | None = None
    power_factor: float | None = None
    frequency_hz: float | None = None

    phase_a_voltage: float | None = None
    phase_b_voltage: float | None = None
    phase_c_voltage: float | None = None

    phase_a_current: float | None = None
    phase_b_current: float | None = None
    phase_c_current: float | None = None


@router.post("")
def create_reading(payload: ReadingCreate, db: Session = Depends(get_db)):
    node = db.query(Node).filter(Node.code == payload.node_id).first()

    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    deployment = (
        db.query(Deployment)
        .filter(
            Deployment.node_id == node.id,
            Deployment.status.in_(lifecycle.attributing_statuses(db)),
        )
        .order_by(Deployment.id.desc())
        .first()
    )

    if not deployment:
        raise HTTPException(status_code=400, detail="Node has no active deployment")

    if payload.timestamp:
        timestamp = datetime.fromisoformat(payload.timestamp.replace("Z", "+00:00"))
    else:
        timestamp = datetime.utcnow()

    reading = EnergyReading(
        node_id=node.id,
        building_id=deployment.building_id,
        deployment_id=deployment.id,
        timestamp=timestamp,
        voltage=payload.voltage,
        current=payload.current,
        power_kw=payload.power_kw,
        energy_kwh=payload.energy_kwh,
        interval_energy_kwh=payload.interval_energy_kwh,
        interval_seconds=payload.interval_seconds,
        meter_energy_kwh=payload.meter_energy_kwh,
        energy_source=payload.energy_source,
        power_factor=payload.power_factor,
        frequency_hz=payload.frequency_hz,
        phase_a_voltage=payload.phase_a_voltage,
        phase_b_voltage=payload.phase_b_voltage,
        phase_c_voltage=payload.phase_c_voltage,
        phase_a_current=payload.phase_a_current,
        phase_b_current=payload.phase_b_current,
        phase_c_current=payload.phase_c_current,
    )

    db.add(reading)

    node.samples += 1
    node.last_sync = datetime.utcnow()

    db.commit()
    db.refresh(reading)

    cost = estimate_reading_cost(db, reading.timestamp, reading.energy_kwh)

    return {
        "id": reading.id,
        "node_id": node.code,
        "building_id": reading.building_id,
        "deployment_id": reading.deployment_id,
        "timestamp": reading.timestamp.isoformat(),
        "power_kw": reading.power_kw,
        "energy_kwh": reading.energy_kwh,
        "tariff_period": cost["period_name"],
        "price_per_kwh_mxn": cost["price_per_kwh_mxn"],
        "estimated_cost_mxn": cost["cost_mxn"],
    }


@router.get("/latest")
def latest_readings(db: Session = Depends(get_db)):
    readings = db.query(EnergyReading).order_by(EnergyReading.timestamp.desc()).limit(20).all()

    return [
        {
            "id": reading.id,
            # Read from the reading's own node, not through its deployment: an
            # unattributed reading still has a node (ADR-0004).
            "node_id": reading.node.code if reading.node else None,
            "building_id": reading.building_id,
            "deployment_id": reading.deployment_id,
            "timestamp": reading.timestamp.isoformat(),
            "voltage": reading.voltage,
            "current": reading.current,
            "power_kw": reading.power_kw,
            "energy_kwh": reading.energy_kwh,
            "power_factor": reading.power_factor,
            "frequency_hz": reading.frequency_hz,
            "cost": estimate_reading_cost(db, reading.timestamp, reading.energy_kwh),
            "phase_a_voltage": reading.phase_a_voltage,
            "phase_b_voltage": reading.phase_b_voltage,
            "phase_c_voltage": reading.phase_c_voltage,
            "phase_a_current": reading.phase_a_current,
            "phase_b_current": reading.phase_b_current,
            "phase_c_current": reading.phase_c_current,
        }
        for reading in readings
    ]
