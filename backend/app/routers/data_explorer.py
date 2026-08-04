from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from collections import defaultdict
import builtins

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import scope
from app.db.database import get_db
from app.db.models import EnergyReading, Building
from app.services.cost_engine import estimate_reading_cost
from app.services import energy_aggregate as agg

router = APIRouter()

LOCAL_TZ = ZoneInfo("America/Mexico_City")


def range_start(range_value: str | None):
    now = datetime.utcnow()
    if range_value == "1h":
        return now - timedelta(hours=1)
    if range_value == "24h":
        return now - timedelta(hours=24)
    if range_value == "7d":
        return now - timedelta(days=7)
    if range_value == "30d":
        return now - timedelta(days=30)
    return None


def to_local(ts: datetime):
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(LOCAL_TZ)


def bucket_label(ts: datetime, range_value: str):
    ts = to_local(ts)

    if range_value == "1h":
        minute = (ts.minute // 5) * 5
        return ts.replace(minute=minute, second=0, microsecond=0).strftime("%H:%M")
    if range_value == "24h":
        minute = 0 if ts.minute < 30 else 30
        return ts.replace(minute=minute, second=0, microsecond=0).strftime("%H:%M")
    if range_value == "7d":
        hour = (ts.hour // 6) * 6
        return ts.replace(hour=hour, minute=0, second=0, microsecond=0).strftime("%d/%m %Hh")
    return ts.strftime("%d/%m")


def bucket_start(ts: datetime, range_value: str):
    ts = to_local(ts)

    if range_value == "1h":
        minute = (ts.minute // 5) * 5
        return ts.replace(minute=minute, second=0, microsecond=0)

    if range_value == "24h":
        minute = 0 if ts.minute < 30 else 30
        return ts.replace(minute=minute, second=0, microsecond=0)

    if range_value == "7d":
        hour = (ts.hour // 6) * 6
        return ts.replace(hour=hour, minute=0, second=0, microsecond=0)

    return ts.replace(hour=0, minute=0, second=0, microsecond=0)


def period_label(period):
    if period == "intermediate":
        return "Intermedia"
    if period == "peak":
        return "Punta"
    return "Base"


@router.get("/options")
def data_explorer_options(db: Session = Depends(get_db)):
    buildings = (
        db.query(Building)
        .join(EnergyReading, EnergyReading.building_id == Building.id)
        .filter(EnergyReading.context.in_(scope.analytic_contexts(db)))
        .distinct()
        .order_by(Building.name.asc())
        .all()
    )

    return {
        "buildings": [
            {"id": building.id, "name": building.name, "is_placeholder": building.is_placeholder}
            for building in buildings
        ],
        "contexts": [
            {"code": code, "default": code in scope.analytic_contexts(db)}
            for code in scope.all_contexts(db)
        ],
        "ranges": [
            {"id": "1h", "label": "Última hora"},
            {"id": "24h", "label": "Últimas 24 horas"},
            {"id": "7d", "label": "Últimos 7 días"},
            {"id": "30d", "label": "Últimos 30 días"},
            {"id": "all", "label": "Todo el despliegue"},
        ],
    }


@router.get("")
def data_explorer(
    range: str = Query("24h"),
    building_ids: str | None = Query(None),
    context: str | None = Query(
        None,
        description=(
            "Measurement contexts to include, comma separated (e.g. 'bench,laboratory'), "
            "or 'all'. Defaults to production contexts only. Bench and laboratory data "
            "is never deleted — this is how you reach it."
        ),
    ),
    db: Session = Depends(get_db),
):
    start = range_start(range)

    selected_ids = []
    if building_ids:
        selected_ids = [
            int(value)
            for value in building_ids.split(",")
            if value.strip().isdigit()
        ]

    query = scope.production_readings(db, context).filter(
        EnergyReading.energy_kwh.isnot(None)
    )

    if start:
        query = query.filter(EnergyReading.timestamp >= start)

    if selected_ids:
        query = query.filter(EnergyReading.building_id.in_(selected_ids))

    readings = (
        query
        .order_by(EnergyReading.timestamp.desc())
        .limit(100000)
        .all()
    )
    readings = list(reversed(readings))

    buildings_by_id = {
        building.id: building.name
        for building in db.query(Building).all()
    }

    selected_buildings = sorted({
        r.building_id for r in readings if r.building_id is not None
    })

    bucketed = defaultdict(lambda: defaultdict(lambda: {
        "power_values": [],
        "energy_delta": 0,
        "cost_mxn": 0,
        "current_values": [],
        "voltage_values": [],
        "pf_values": [],
        "freq_values": [],
    }))

    heatmap = defaultdict(lambda: defaultdict(lambda: {"kwh": 0, "cost_mxn": 0}))
    tariff_totals = defaultdict(lambda: {"kwh": 0, "cost_mxn": 0})
    bucket_labels = {}

    # Canonical interval energy per reading (ADR-0007). The explorer used to
    # difference energy_kwh itself, so it disagreed with every other view.
    energy_by_id = agg.energy_by_reading_id(db, start=start, contexts=context)

    recent = []

    total_kwh = 0
    total_cost = 0
    pf_values = []
    current_values = []
    voltage_values = []

    for reading in readings:
        building_name = buildings_by_id.get(reading.building_id, "Sin edificio")
        bucket_dt = bucket_start(reading.timestamp, range)
        key = bucket_dt.isoformat()
        bucket_labels.setdefault(key, bucket_label(bucket_dt, range))

        delta_kwh = energy_by_id.get(reading.id, 0.0)

        cost_info = estimate_reading_cost(db, reading.timestamp, delta_kwh)
        cost_mxn = float(cost_info.get("cost_mxn", 0) or 0)
        tariff_period = cost_info.get("period_name", "base") or "base"

        row = bucketed[key][building_name]
        row["power_values"].append(float(reading.power_kw or 0))
        row["energy_delta"] += delta_kwh
        row["cost_mxn"] += cost_mxn
        row["current_values"].append(float(reading.current or 0))
        row["voltage_values"].append(float(reading.voltage or 0))
        row["pf_values"].append(float(reading.power_factor or 0))
        row["freq_values"].append(float(reading.frequency_hz or 0))

        hour = to_local(reading.timestamp).strftime("%H")
        heatmap[building_name][hour]["kwh"] += delta_kwh
        heatmap[building_name][hour]["cost_mxn"] += cost_mxn

        tariff_totals[tariff_period]["kwh"] += delta_kwh
        tariff_totals[tariff_period]["cost_mxn"] += cost_mxn

        total_kwh += delta_kwh
        total_cost += cost_mxn

        if reading.power_factor is not None:
            pf_values.append(float(reading.power_factor))
        if reading.current is not None:
            current_values.append(float(reading.current))
        if reading.voltage is not None:
            voltage_values.append(float(reading.voltage))

        recent.append({
            "timestamp": to_local(reading.timestamp).isoformat(),
            "building": building_name,
            "node": str(reading.node_id),
            "power_kw": round(float(reading.power_kw or 0), 4),
            "voltage": round(float(reading.voltage or 0), 3),
            "current": round(float(reading.current or 0), 3),
            "power_factor": round(float(reading.power_factor or 0), 4),
            "frequency_hz": round(float(reading.frequency_hz or 0), 3),
            "energy_kwh": round(delta_kwh, 5),
            "tariff_period": period_label(tariff_period),
            "cost_mxn": round(cost_mxn, 4),
        })


    def avg(values):
        return round(sum(values) / len(values), 4) if values else 0

    series = []
    cumulative_by_building = defaultdict(float)

    for time_key in sorted(bucketed.keys()):
        row = {"time": bucket_labels.get(time_key, time_key)}

        for building_name, values in bucketed[time_key].items():
            cumulative_by_building[building_name] += values["energy_delta"]

            row[f"{building_name}_power_kw"] = avg(values["power_values"])
            row[f"{building_name}_energy_kwh"] = round(cumulative_by_building[building_name], 4)
            row[f"{building_name}_cost_mxn"] = round(values["cost_mxn"], 4)
            row[f"{building_name}_current_a"] = avg(values["current_values"])
            row[f"{building_name}_voltage"] = avg(values["voltage_values"])
            row[f"{building_name}_power_factor"] = avg(values["pf_values"])
            row[f"{building_name}_frequency_hz"] = avg(values["freq_values"])

        series.append(row)

    tariff_total_cost = sum(v["cost_mxn"] for v in tariff_totals.values()) or 1

    return {
        "range": range,
        "buildings": [
            {"id": building_id, "name": buildings_by_id.get(building_id, "Sin edificio")}
            for building_id in selected_buildings
        ],
        "series": series,
        "tariffDistribution": [
            {
                "period": period_label(period),
                "kwh": round(values["kwh"], 4),
                "cost_mxn": round(values["cost_mxn"], 4),
                "share_pct": round((values["cost_mxn"] / tariff_total_cost) * 100, 2),
            }
            for period, values in tariff_totals.items()
        ],
        "heatmap": [
            {
                "building": building,
                "hours": [
                    {
                        "hour": f"{hour:02d}",
                        "kwh": round(values.get(f"{hour:02d}", {}).get("kwh", 0), 4),
                        "cost_mxn": round(values.get(f"{hour:02d}", {}).get("cost_mxn", 0), 4),
                    }
                    for hour in builtins.range(24)
                ],
            }
            for building, values in heatmap.items()
        ],
        "recentReadings": list(reversed(recent[-80:])),
        "summary": {
            "total_kwh": round(total_kwh, 4),
            "total_cost_mxn": round(total_cost, 4),
            "avg_power_factor": avg(pf_values),
            "max_current_a": round(max(current_values), 3) if current_values else 0,
            "min_voltage": round(min(voltage_values), 3) if voltage_values else 0,
            "reading_count": len(readings),
        },
    }
