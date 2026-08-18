from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import EnergyReading
from app.services import ingest_gate
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

    # ---- per-phase detail from the meter (M15) ----
    #
    # Every field here names its unit, and that is load-bearing rather than
    # decorative: this route receives values ALREADY in platform units, while
    # /api/v1/measurements/batch receives device units (watts, volt-amperes,
    # watt-hours) and converts them. A field called `phase_a_power_kw` cannot be
    # mistaken for watts, which is what keeps a value from being divided by a
    # thousand twice. See app/services/units for the full rule.
    phase_a_power_kw: float | None = None
    phase_b_power_kw: float | None = None
    phase_c_power_kw: float | None = None

    phase_a_apparent_kva: float | None = None
    phase_b_apparent_kva: float | None = None
    phase_c_apparent_kva: float | None = None

    phase_a_power_factor: float | None = None
    phase_b_power_factor: float | None = None
    phase_c_power_factor: float | None = None

    phase_a_frequency_hz: float | None = None
    phase_b_frequency_hz: float | None = None
    phase_c_frequency_hz: float | None = None

    apparent_kva: float | None = None
    #: Amperes. Stays None when the installation has no neutral CT.
    neutral_current: float | None = None

    #: Cumulative registers, kWh. Reconciliation only (ADR-0007).
    phase_a_energy_imported_kwh: float | None = None
    phase_b_energy_imported_kwh: float | None = None
    phase_c_energy_imported_kwh: float | None = None
    phase_a_energy_returned_kwh: float | None = None
    phase_b_energy_returned_kwh: float | None = None
    phase_c_energy_returned_kwh: float | None = None
    meter_energy_returned_kwh: float | None = None


def _parse_captured_at(value: str | None) -> datetime | None:
    """Parse the node's declared capture instant, or None.

    Never falls back to "now": upload time must not influence attribution
    (ADR-0004). An unparseable timestamp yields None, and the resolver reports
    it as missing rather than guessing.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


@router.post("")
def create_reading(payload: ReadingCreate, request: Request, db: Session = Depends(get_db)):
    """Ingest one reading — authenticate, authorize, classify, attribute.

    Every decision is delegated to :mod:`app.services.ingest_gate` so this path
    and the batch path answer the same questions identically. This endpoint
    previously picked ``order_by(Deployment.id.desc()).first()`` — the newest
    deployment — which attributed idle readings to a campaign that closed days
    earlier, and to that campaign's building.
    """
    captured_at = _parse_captured_at(payload.timestamp)

    decision = ingest_gate.admit(
        db,
        request,
        payload.node_id,
        captured_at,
        endpoint="/api/readings",
    )
    node = decision.node
    timestamp = captured_at or datetime.utcnow()

    if payload.timestamp:
        timestamp = datetime.fromisoformat(payload.timestamp.replace("Z", "+00:00"))
    else:
        timestamp = datetime.utcnow()

    reading = EnergyReading(
        node_id=node.id,
        # NULL when no operational deployment covers captured_at. A reading is
        # stored unattributed rather than attached to the nearest campaign.
        building_id=decision.building_id,
        deployment_id=decision.deployment_id,
        context=decision.context,
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
        # Already in platform units on this route — no conversion here, by
        # design. Converting again is the failure app/services/units documents.
        phase_a_power_kw=payload.phase_a_power_kw,
        phase_b_power_kw=payload.phase_b_power_kw,
        phase_c_power_kw=payload.phase_c_power_kw,
        phase_a_apparent_kva=payload.phase_a_apparent_kva,
        phase_b_apparent_kva=payload.phase_b_apparent_kva,
        phase_c_apparent_kva=payload.phase_c_apparent_kva,
        phase_a_power_factor=payload.phase_a_power_factor,
        phase_b_power_factor=payload.phase_b_power_factor,
        phase_c_power_factor=payload.phase_c_power_factor,
        phase_a_frequency_hz=payload.phase_a_frequency_hz,
        phase_b_frequency_hz=payload.phase_b_frequency_hz,
        phase_c_frequency_hz=payload.phase_c_frequency_hz,
        apparent_kva=payload.apparent_kva,
        neutral_current=payload.neutral_current,
        phase_a_energy_imported_kwh=payload.phase_a_energy_imported_kwh,
        phase_b_energy_imported_kwh=payload.phase_b_energy_imported_kwh,
        phase_c_energy_imported_kwh=payload.phase_c_energy_imported_kwh,
        phase_a_energy_returned_kwh=payload.phase_a_energy_returned_kwh,
        phase_b_energy_returned_kwh=payload.phase_b_energy_returned_kwh,
        phase_c_energy_returned_kwh=payload.phase_c_energy_returned_kwh,
        meter_energy_returned_kwh=payload.meter_energy_returned_kwh,
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
