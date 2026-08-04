from collections import defaultdict
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import lifecycle, scope
from app.db.database import get_db
from app.db.models import Building, Deployment, EnergyReading, Node
from app.services import deployment_scope
from app.services import energy_aggregate as agg
from app.services.cost_engine import estimate_reading_cost
from app.services.platform_settings import get_thresholds

router = APIRouter()
LOCAL_TZ = ZoneInfo("America/Mexico_City")


def _utc_naive(dt):
    return dt.astimezone(UTC).replace(tzinfo=None)


def _local_now():
    return datetime.now(LOCAL_TZ)


def _today_start_utc():
    now = _local_now()
    return _utc_naive(datetime.combine(now.date(), time.min, tzinfo=LOCAL_TZ))


def _week_start_utc():
    now = _local_now()
    monday = now.date() - timedelta(days=now.weekday())
    return _utc_naive(datetime.combine(monday, time.min, tzinfo=LOCAL_TZ))


def _period_label():
    now = _local_now()
    monday = now.date() - timedelta(days=now.weekday())
    sunday = monday + timedelta(days=6)
    months = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
    return f"Universidad de Colima · GDMTH · Semana del {monday.day}–{sunday.day} {months[sunday.month-1]} {sunday.year}"


def _scoped_nodes(db, deployment_id=None):
    """Nodes in scope. Fleet-wide by default; one deployment's node when scoped.

    Read from the deployment row rather than from which nodes happen to have
    readings, so a deployment whose node has gone quiet still reports that node
    as offline instead of vanishing from the KPI denominator.
    """
    if deployment_id is None:
        return db.query(Node).all()
    deployment = db.query(Deployment).filter(Deployment.id == deployment_id).first()
    if deployment is None or deployment.node_id is None:
        return []
    return db.query(Node).filter(Node.id == deployment.node_id).all()


def _building_names(db):
    return {b.id: b.name for b in db.query(Building).all()}


def _cost_between(db, start, end=None):
    """Energy, cost and per-building breakdown for one window.

    Derived from the shared hourly aggregate rather than a per-reading scan.
    """
    buckets = agg.between(agg.hourly_energy(db, start=start, end=end), start, end)
    names = _building_names(db)

    building_costs = defaultdict(lambda: {"kwh": 0.0, "cost_mxn": 0.0})
    for b in buckets:
        if b.building_id is None:
            continue
        name = names.get(b.building_id)
        if not name:
            continue
        building_costs[name]["kwh"] += b.kwh
        building_costs[name]["cost_mxn"] += b.cost_mxn

    total_kwh, total_cost = agg.totals(buckets)
    return total_kwh, total_cost, building_costs


def _cost_windows(
    db,
    oldest_start,
    today_start,
    yesterday_start,
    week_start,
    previous_week_start,
    deployment_id=None,
):
    """Four overlapping windows from ONE aggregate.

    Previously this loaded every reading since the previous week start — tens of
    thousands of rows — and ran a per-reading tariff classification. It now runs
    one SQL aggregate and slices the resulting hourly buckets four ways.

    Window boundaries are local midnights, which in a whole-hour timezone land
    exactly on hour boundaries, so no bucket straddles two windows.
    """
    buckets = agg.hourly_energy(db, start=oldest_start, deployment_id=deployment_id)
    names = _building_names(db)

    result = {
        key: {
            "kwh": 0.0,
            "cost": 0.0,
            "buildings": defaultdict(lambda: {"kwh": 0.0, "cost_mxn": 0.0}),
        }
        for key in ("today", "yesterday", "week", "prev_week")
    }

    for b in buckets:
        windows = []
        if b.hour_utc >= today_start:
            windows.append("today")
        elif yesterday_start <= b.hour_utc < today_start:
            windows.append("yesterday")

        if b.hour_utc >= week_start:
            windows.append("week")
        elif previous_week_start <= b.hour_utc < week_start:
            windows.append("prev_week")

        name = names.get(b.building_id) if b.building_id is not None else None

        for window in windows:
            result[window]["kwh"] += b.kwh
            result[window]["cost"] += b.cost_mxn
            if name:
                result[window]["buildings"][name]["kwh"] += b.kwh
                result[window]["buildings"][name]["cost_mxn"] += b.cost_mxn

    return result


def _estimate_potential_savings(db, today_cost, projected_month, latest_by_node):
    """
    Conservative monthly savings estimate from real readings.
    It does not invent recommendations; it estimates value only when real conditions exist.
    """
    thresholds = get_thresholds()
    min_pf = float(thresholds.get("minPowerFactor", 0.90))
    night_kw_threshold = float(thresholds.get("nightPowerKw", 5))
    demand_spike_pct = float(thresholds.get("demandSpike", 25))

    monthly_savings = 0.0
    active_recommendations = []

    # 1) Low power factor opportunity.
    # Conservative assumption: improving PF avoids roughly 2–6% operational/capacity losses.
    low_pf_nodes = [
        r for r in latest_by_node.values() if r.power_factor is not None and r.power_factor < min_pf
    ]

    if projected_month > 0 and low_pf_nodes:
        worst_pf = min(float(r.power_factor) for r in low_pf_nodes)
        severity = min(max((min_pf - worst_pf) / max(min_pf, 0.01), 0), 0.25)
        pf_savings = projected_month * min(0.06, max(0.02, severity * 0.25))
        monthly_savings += pf_savings
        active_recommendations.append(
            {
                "category": "Power Factor",
                "title": "Corrección de factor de potencia",
                "estimated_savings_mxn_month": round(pf_savings, 2),
                "reason": f"Factor de potencia mínimo detectado {worst_pf:.2f}, debajo del umbral {min_pf:.2f}.",
            }
        )

    # 2) Night consumption opportunity.
    # Estimate cost of excess kWh between 00:00 and 06:00 today, then project monthly.
    today_start = _today_start_utc()

    # Only local 00:00-06:00 matters here. The window is bounded in SQL rather
    # than by scanning the whole day and discarding most of it: the local offset
    # is a whole number of hours, so the night band is exactly the first six
    # hours after local midnight.
    night_end = today_start + timedelta(hours=6)
    night_readings = (
        scope.production_readings(db)
        .filter(
            EnergyReading.timestamp >= today_start,
            EnergyReading.timestamp < night_end,
            EnergyReading.power_kw > night_kw_threshold,
        )
        .all()
    )

    # Energy per reading from the canonical service (ADR-0007). This was an
    # inline `energy_kwh - previous`, a second interpretation of the column that
    # disagreed with the KPIs on this same page.
    energy_by_id = agg.energy_by_reading_id(db, start=today_start, end=night_end)
    excess_night_cost_today = 0.0

    for r in night_readings:
        delta_kwh = energy_by_id.get(r.id, 0.0)
        power_kw = float(r.power_kw or 0)

        if delta_kwh > 0:
            excess_ratio = min((power_kw - night_kw_threshold) / max(power_kw, 0.01), 1)
            excess_kwh = delta_kwh * excess_ratio
            excess_night_cost_today += estimate_reading_cost(db, r.timestamp, excess_kwh)[
                "cost_mxn"
            ]

    if excess_night_cost_today > 0:
        night_savings = excess_night_cost_today * 30
        monthly_savings += night_savings
        active_recommendations.append(
            {
                "category": "Night Consumption",
                "title": "Reducir carga nocturna no esencial",
                "estimated_savings_mxn_month": round(night_savings, 2),
                "reason": f"Consumo nocturno por encima de {night_kw_threshold:.1f} kW detectado hoy.",
            }
        )

    # 3) Demand spike opportunity.
    # If current load is above recent average by configured threshold, estimate small demand-control opportunity.
    for node_id, latest in latest_by_node.items():
        if latest.power_kw is None:
            continue

        start = datetime.utcnow() - timedelta(hours=2)
        readings = (
            scope.production_readings(db)
            .filter(
                EnergyReading.node_id == node_id,
                EnergyReading.timestamp >= start,
                EnergyReading.power_kw.isnot(None),
            )
            .all()
        )

        powers = [float(r.power_kw) for r in readings if r.power_kw is not None]
        if len(powers) >= 10:
            avg_power = sum(powers) / len(powers)
            limit = avg_power * (1 + demand_spike_pct / 100)

            if avg_power > 0 and float(latest.power_kw) > limit and projected_month > 0:
                spike_savings = projected_month * 0.015
                monthly_savings += spike_savings
                active_recommendations.append(
                    {
                        "category": "Demand Spike",
                        "title": "Control de picos de demanda",
                        "estimated_savings_mxn_month": round(spike_savings, 2),
                        "reason": f"Potencia actual {latest.power_kw:.2f} kW sobre promedio reciente {avg_power:.2f} kW.",
                    }
                )
                break

    return round(monthly_savings, 2), active_recommendations


@router.get("/summary")
def dashboard_summary(db: Session = Depends(get_db), deployment_id: int | None = None):
    """Executive KPIs.

    ``deployment_id`` scopes every energy and cost figure, plus the node set, to
    one deployment. Omitting it keeps the fleet-wide behaviour this endpoint has
    always had, so existing callers are unaffected.
    """
    nodes = _scoped_nodes(db, deployment_id)
    now = datetime.utcnow()
    today_start = _today_start_utc()
    yesterday_start = today_start - timedelta(days=1)
    week_start = _week_start_utc()
    previous_week_start = week_start - timedelta(days=7)

    online_nodes = sum(
        1 for node in nodes if node.last_sync and node.last_sync >= now - timedelta(seconds=120)
    )

    # Deployment lifecycle, counted from the Deployment table — not inferred
    # from node connectivity. Before M7 this KPI was literally
    # `active_deployments = online_nodes`, so the dashboard reported a node
    # count under a deployment label (ADR-0001).
    #
    # "Active" here means operationally running, read from
    # deployment_statuses.is_operational rather than compared against a literal,
    # so a lifecycle state added later is classified without touching this code.
    status_counts = dict(
        db.query(Deployment.status, func.count(Deployment.id)).group_by(Deployment.status).all()
    )
    operational = set(lifecycle.operational_statuses(db))
    active_deployments = sum(n for code, n in status_counts.items() if code in operational)
    total_deployments = sum(status_counts.values())

    latest_by_node = {}
    for node in nodes:
        latest = (
            deployment_scope.scope_readings(scope.production_readings(db), deployment_id)
            .filter(EnergyReading.node_id == node.id)
            .order_by(EnergyReading.timestamp.desc())
            .first()
        )
        if latest:
            latest_by_node[node.id] = latest

    total_power_kw = round(sum((r.power_kw or 0) for r in latest_by_node.values()), 3)

    windows = _cost_windows(
        db=db,
        oldest_start=previous_week_start,
        today_start=today_start,
        yesterday_start=yesterday_start,
        week_start=week_start,
        previous_week_start=previous_week_start,
        deployment_id=deployment_id,
    )

    today_kwh = windows["today"]["kwh"]
    today_cost = windows["today"]["cost"]
    yesterday_kwh = windows["yesterday"]["kwh"]
    yesterday_cost = windows["yesterday"]["cost"]
    week_kwh = windows["week"]["kwh"]
    week_cost = windows["week"]["cost"]
    week_buildings = windows["week"]["buildings"]
    prev_week_kwh = windows["prev_week"]["kwh"]
    prev_week_cost = windows["prev_week"]["cost"]

    days_elapsed = max(
        1,
        (_local_now().date() - (_local_now().date() - timedelta(days=_local_now().weekday()))).days
        + 1,
    )
    projected_month = (
        (today_cost / max(1, (_local_now().hour + 1))) * 24 * 30 if today_cost > 0 else 0
    )

    daily_comparison_pct = None
    if yesterday_cost > 0:
        daily_comparison_pct = round(((today_cost - yesterday_cost) / yesterday_cost) * 100, 2)

    week_comparison_pct = None
    if prev_week_cost > 0:
        week_comparison_pct = round(((week_cost - prev_week_cost) / prev_week_cost) * 100, 2)

    has_daily_comparison = daily_comparison_pct is not None and abs(daily_comparison_pct) <= 500
    has_week_comparison = week_comparison_pct is not None and abs(week_comparison_pct) <= 500

    most_expensive_building = None
    if week_buildings:
        name, values = max(week_buildings.items(), key=lambda item: item[1]["cost_mxn"])
        most_expensive_building = {
            "name": name,
            "kwh_week": round(values["kwh"], 4),
            "cost_week_mxn": round(values["cost_mxn"], 2),
        }

    potential_savings, savings_recommendations = _estimate_potential_savings(
        db=db,
        today_cost=today_cost,
        projected_month=projected_month,
        latest_by_node=latest_by_node,
    )

    return {
        "period_label": _period_label(),
        "estimated_cost_today_mxn": round(today_cost, 2),
        "estimated_cost_week_mxn": round(week_cost, 2),
        "projected_monthly_cost_mxn": round(projected_month, 2),
        "potential_savings_mxn_month": potential_savings,
        "savings_recommendations": savings_recommendations,
        "most_expensive_building": most_expensive_building,
        "online_nodes": online_nodes,
        "total_nodes": len(nodes),
        # Now a genuine deployment count. Key retained so the existing frontend
        # bundle keeps working without a rebuild.
        "active_deployments": active_deployments,
        "total_deployments": total_deployments,
        "deployments_by_status": status_counts,
        "total_power_kw": total_power_kw,
        "energy_today_kwh": round(today_kwh, 3),
        "energy_week_kwh": round(week_kwh, 3),
        "yesterday_cost_mxn": round(yesterday_cost, 2),
        "has_previous_day_data": has_daily_comparison,
        "daily_comparison_pct": daily_comparison_pct if has_daily_comparison else None,
        "daily_comparison_label": (
            "Histórico insuficiente"
            if not has_daily_comparison
            else f"{daily_comparison_pct:+.2f}% vs día anterior"
        ),
        "has_previous_week_data": has_week_comparison,
        "week_comparison_pct": week_comparison_pct if has_week_comparison else None,
        "comparison_label": (
            "Histórico insuficiente"
            if not has_week_comparison
            else f"{week_comparison_pct:+.2f}% vs semana anterior"
        ),
    }
