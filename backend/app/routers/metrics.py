from app.services.platform_settings import get_thresholds
from datetime import datetime, time, timedelta, timezone
from collections import defaultdict
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import scope
from app.db.database import get_db
from app.db.models import EnergyReading, Node, TariffPeriod, Campus, Building
from app.services.cost_engine import estimate_reading_cost
from app.services import energy_aggregate as agg

router = APIRouter()

LOCAL_TZ = ZoneInfo("America/Mexico_City")


def to_local_time(timestamp):
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(LOCAL_TZ)


def today_start():
    local_now = datetime.now(LOCAL_TZ)
    local_start = datetime.combine(local_now.date(), time.min, tzinfo=LOCAL_TZ)
    return local_start.astimezone(timezone.utc).replace(tzinfo=None)


def get_period_for_hour(db: Session, hour: int):
    return (
        db.query(TariffPeriod)
        .filter(
            TariffPeriod.start_hour <= hour,
            TariffPeriod.end_hour > hour,
            TariffPeriod.is_active == True,
        )
        .first()
    )


@router.get("/live")
def live_metrics(db: Session = Depends(get_db)):
    nodes = db.query(Node).all()
    result = []
    start = today_start()
    now = datetime.utcnow()
    today_buckets = agg.hourly_energy(db, start=start)

    for node in nodes:
        latest = (
            scope.production_readings(db)
            .filter(EnergyReading.node_id == node.id)
            .order_by(EnergyReading.timestamp.desc())
            .first()
        )

        rpi_recent = node.last_sync is not None and node.last_sync >= now - timedelta(seconds=300)
        shelly_recent = latest is not None and latest.timestamp >= now - timedelta(seconds=300)

        if not rpi_recent and not shelly_recent:
            continue

        # Today's energy for this node, from the canonical service. This used to
        # be `latest.energy_kwh - first_today.energy_kwh`, which is the counter
        # rule applied to whatever the column happened to hold (ADR-0007).
        energy_today = agg.totals(
            [b for b in today_buckets if b.node_id == node.id]
        )[0]

        current_cost = estimate_reading_cost(db, latest.timestamp, energy_today) if latest else None

        result.append({
            "node_id": node.code,
            "status": "online" if rpi_recent else "offline",
            "rpi_status": "ok" if rpi_recent else "offline",
            "shelly_status": "ok" if shelly_recent else "offline",
            "last_sync": node.last_sync.isoformat() if node.last_sync else None,
            "latest_reading": latest.timestamp.isoformat() if latest else None,
            "buffer_pending": node.buffer_pending,
            "samples": node.samples,
            # The building that produced the most recent reading — a property
            # of the reading, not of the node (ADR-0001). Named accordingly so
            # no consumer can read it as "the node's building".
            "last_reading_building": latest.building.name if latest and latest.building else None,
            "voltage": latest.voltage if latest else None,
            "current": latest.current if latest else None,
            "power_kw": latest.power_kw if latest else None,
            "power_factor": latest.power_factor if latest else None,
            "frequency_hz": latest.frequency_hz if latest else None,
            "energy_today_kwh": round(energy_today, 4),
            # The device's own cumulative register, the canonical field for it
            # (ADR-0007). Null until a collector reports one; it is deliberately
            # not energy_kwh, which no longer holds a lifetime count.
            "lifetime_energy_kwh": latest.meter_energy_kwh if latest else None,
            "estimated_cost_today_mxn": round(current_cost["cost_mxn"], 4) if current_cost else 0,
            "tariff_period": current_cost["period_name"] if current_cost else None,
        })

    return result


@router.get("/hourly")
def hourly_metrics(db: Session = Depends(get_db), deployment_id: int | None = None):
    """Energy and cost per local hour of the current day.

    One SQL aggregate instead of a scan-and-loop over every reading. The tariff
    period is constant within a local hour, so it is classified once per bucket;
    the result is identical to the old per-reading classification.

    ``deployment_id`` narrows the result to one deployment; omitting it keeps
    the fleet-wide behaviour.
    """
    buckets = agg.hourly_energy(db, start=today_start(), deployment_id=deployment_id)
    grouped = agg.by_local_hour_of_day(buckets)

    result = []
    for hour in range(24):
        rows = grouped.get(hour, [])
        kwh, cost = agg.totals(rows)
        result.append({
            "hour": f"{hour:02d}:00",
            "kwh": round(kwh, 4),
            "cost_mxn": round(cost, 4),
            "tariff_period": rows[0].period if rows else "base",
        })
    return result


@router.get("/tariffs")
def tariff_metrics(db: Session = Depends(get_db), deployment_id: int | None = None):
    hourly = hourly_metrics(db, deployment_id=deployment_id)
    totals = defaultdict(lambda: {"kwh": 0, "cost_mxn": 0})

    for row in hourly:
        period = row["tariff_period"] or "unknown"
        totals[period]["kwh"] += row["kwh"]
        totals[period]["cost_mxn"] += row["cost_mxn"]

    total_cost = sum(v["cost_mxn"] for v in totals.values()) or 1

    return [
        {
            "period": period,
            "kwh": round(values["kwh"], 4),
            "cost_mxn": round(values["cost_mxn"], 4),
            "share_pct": round((values["cost_mxn"] / total_cost) * 100, 2),
        }
        for period, values in totals.items()
    ]


@router.get("/daily")
def daily_metrics(db: Session = Depends(get_db), deployment_id: int | None = None):
    """Energy and cost per local day, over the last 7 days.

    The delta carried across local midnight is now attributed to the day of the
    later reading. Previously the "previous reading" was reset at each midnight,
    so that consumption was dropped entirely — 0.15% of a 7-day window,
    belonging to no day at all. Daily totals now reconcile exactly with the
    weekly and monthly figures, which never had the reset.
    """
    end = datetime.utcnow()
    buckets = agg.hourly_energy(db, start=end - timedelta(days=7), deployment_id=deployment_id)

    result = []
    for day, rows in sorted(agg.by_local_date(buckets).items()):
        kwh, cost = agg.totals(rows)
        result.append({
            "day": day,
            "kwh": round(kwh, 4),
            "cost_mxn": round(cost, 4),
        })
    return result


@router.get("/buildings")
def building_metrics(db: Session = Depends(get_db), deployment_id: int | None = None):
    """Energy and cost per building for the current day."""
    buckets = agg.hourly_energy(db, start=today_start(), deployment_id=deployment_id)
    names = {b.id: b.name for b in db.query(Building).all()}

    result = []
    for building_id, rows in agg.by_building(buckets).items():
        kwh, cost = agg.totals(rows)
        result.append({
            "building_id": building_id,
            # Unattributed readings have no building; name them explicitly
            # rather than dropping the energy.
            "building_name": names.get(building_id, "Sin edificio"),
            "kwh": round(kwh, 4),
            "cost_mxn": round(cost, 4),
        })

    result.sort(key=lambda r: r["kwh"], reverse=True)
    return result


@router.get("/campuses")
def campus_metrics(db: Session = Depends(get_db)):
    start = today_start()
    now = datetime.utcnow()

    buildings = db.query(Building).all()
    today_by_building = agg.by_building(agg.hourly_energy(db, start=start))

    building_data = []
    campus_totals = defaultdict(lambda: {
        "power_kw": 0,
        "energy_today_kwh": 0,
        "cost_today_mxn": 0,
        "monitored_buildings": 0,
        "total_buildings": 0,
    })

    for building in buildings:
        latest = (
            scope.production_readings(db)
            .filter(EnergyReading.building_id == building.id)
            .order_by(EnergyReading.timestamp.desc())
            .first()
        )

        # Today's energy and cost for this building, from the canonical service.
        # Cost is summed per hourly bucket at that hour's own tariff rather than
        # charging the whole day at the latest reading's rate.
        building_buckets = today_by_building.get(building.id, [])
        energy_today, cost_today = agg.totals(building_buckets)

        campus_id = building.campus_id
        campus_totals[campus_id]["total_buildings"] += 1

        if latest:
            campus_totals[campus_id]["monitored_buildings"] += 1
            campus_totals[campus_id]["power_kw"] += latest.power_kw or 0
            campus_totals[campus_id]["energy_today_kwh"] += energy_today
            campus_totals[campus_id]["cost_today_mxn"] += cost_today

        anomaly = False
        if latest:
            anomaly = (
                (latest.power_factor is not None and latest.power_factor < float(get_thresholds().get('minPowerFactor', 0.90)))
                or (latest.current is not None and latest.current > float(get_thresholds().get('maxCurrent', 200)))
            )

        building_data.append({
            "id": building.id,
            "name": building.name,
            "campus_id": building.campus_id,
            "campus": building.campus.name,
            "delegation": building.campus.delegation.name,
            "organizational_unit": building.organizational_unit.name,
            "status": "monitored" if latest else "no_data",
            "power_kw": round(latest.power_kw or 0, 3) if latest else 0,
            "energy_today_kwh": round(energy_today, 4),
            "cost_today_mxn": round(cost_today, 4),
            "anomaly": anomaly,
            "last_reading": latest.timestamp.isoformat() if latest else None,
        })

    campuses = []
    for campus in db.query(Campus).all():
        totals = campus_totals[campus.id]
        campuses.append({
            "id": campus.id,
            "name": campus.name,
            "delegation": campus.delegation.name,
            "status": "active" if totals["monitored_buildings"] > 0 else "inactive",
            "monitored_buildings": totals["monitored_buildings"],
            "total_buildings": totals["total_buildings"],
            "power_kw": round(totals["power_kw"], 3),
            "energy_today_kwh": round(totals["energy_today_kwh"], 4),
            "cost_today_mxn": round(totals["cost_today_mxn"], 4),
        })

    return {
        "campuses": campuses,
        "buildings": building_data,
    }
