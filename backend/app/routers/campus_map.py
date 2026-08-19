"""The Campus Map: real building footprints with Energy IQ state on top.

Two endpoints, and a deliberate omission.

``GET /api/campus-map/campuses`` lists the campuses the map can open, straight
from the ``campuses`` table — the selector never hardcodes Campus Central, and a
campus nobody has traced yet appears with ``has_geometry: false`` rather than
being hidden.

``GET /api/campus-map/{campus_id}`` returns the campus's footprints joined to
the state of every Energy IQ building on it: which deployment is running, which
node measures it, when the last reading actually landed, and what that reading
said.

The omission: **no campus totals.** Power, energy today, cost today and the
monitored/total counts already have exactly one definition, in
``/api/metrics/campuses``, and it charges each hourly bucket at its own tariff.
Recomputing them here would create a second answer to the same question that
drifts the first time one of them is fixed. The page calls both endpoints and
merges — a round trip is cheaper than a contradiction.

Everything returned is measured. A field a node does not report comes back
``null``; nothing is defaulted to zero to make the panel look complete.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import lifecycle, scope
from app.db.database import get_db
from app.db.models import Building, Campus, Deployment, ElectricalPanel, EnergyReading, Node
from app.monitoring.models import MonitorAlert
from app.monitoring.severity import Severity

# The local-midnight boundary the rest of the platform already uses. Imported
# rather than restated: "today" must mean the same thing on the map as it does
# on the dashboard, including across a DST change.
from app.routers.metrics import today_start
from app.services import campus_geometry as geo
from app.services import campus_map_state as state
from app.services import deployment_scope
from app.services import energy_aggregate as agg

router = APIRouter()

#: Seconds. The same window ``deployment_scope`` uses to decide whether a
#: deployment is still measuring, read from that module so there is one value.
TELEMETRY_WINDOW_SECONDS = int(deployment_scope.TELEMETRY_ACTIVE_WINDOW.total_seconds())

#: Quantities the detail panel shows. Every one is a column a collector writes;
#: none is derived. Read straight off the newest reading so a node that stops
#: publishing a field stops advertising it, exactly as the live view does.
PHASE_FIELDS = ("voltage", "current", "power_kw", "apparent_kva", "power_factor", "frequency_hz")


def _reading_snapshot(reading: EnergyReading | None) -> dict | None:
    """The newest reading, as measured. ``None`` fields mean "not reported"."""
    if reading is None:
        return None

    phases = {}
    for phase in ("a", "b", "c"):
        values = {field: getattr(reading, f"phase_{phase}_{field}", None) for field in PHASE_FIELDS}
        # A phase the meter does not break out is absent, not zero. Three
        # zeroed phases would read as a de-energised panel.
        if any(value is not None for value in values.values()):
            phases[phase.upper()] = values

    return {
        "timestamp": reading.timestamp.isoformat(),
        "power_kw": reading.power_kw,
        "voltage": reading.voltage,
        "current": reading.current,
        "apparent_kva": reading.apparent_kva,
        "power_factor": reading.power_factor,
        "frequency_hz": reading.frequency_hz,
        "neutral_current": reading.neutral_current,
        "context": reading.context,
        "phases": phases or None,
    }


def _deployment_summary(
    deployment: Deployment | None,
    node: Node | None,
    panel_name: str | None,
    operational_codes: set[str],
):
    if deployment is None:
        return None
    return {
        "id": deployment.id,
        "status": deployment.status,
        "is_operational": deployment.status in operational_codes,
        "start_date": deployment.start_date,
        "end_date": deployment.end_date,
        "activated_at": deployment.activated_at.isoformat() if deployment.activated_at else None,
        "closed_at": deployment.closed_at.isoformat() if deployment.closed_at else None,
        "panel": panel_name,
        "node": (
            {
                "id": node.id,
                "code": node.code,
                "name": node.name,
                "measurement_context": node.measurement_context,
                "commission_state": node.commission_state,
            }
            if node
            else None
        ),
    }


def _open_alerts_by_node(db: Session) -> dict[int, list[MonitorAlert]]:
    rows = (
        db.query(MonitorAlert)
        .filter(MonitorAlert.status == "open", MonitorAlert.node_id.isnot(None))
        .order_by(MonitorAlert.created_at.desc())
        .all()
    )
    grouped: dict[int, list[MonitorAlert]] = {}
    for alert in rows:
        grouped.setdefault(alert.node_id, []).append(alert)
    return grouped


@router.get("/campuses")
def list_map_campuses(db: Session = Depends(get_db)):
    """Every campus in the database, with whether the map has geometry for it.

    Driven by the ``campuses`` table, not by the geometry directory: a campus
    with buildings but no traced footprints must still be selectable, because
    its summary numbers are real even when its outlines are not drawn yet.
    """
    views = geo.campus_views()
    counts = dict(
        db.query(Building.campus_id, func.count(Building.id)).group_by(Building.campus_id).all()
    )

    out = []
    for campus in db.query(Campus).order_by(Campus.name).all():
        view = views.get(campus.id)
        collection = geo.geometry(campus.id) if view and view.has_geometry else None
        out.append(
            {
                "id": campus.id,
                "name": campus.name,
                "location": campus.location,
                "delegation": campus.delegation.name if campus.delegation else None,
                "has_geometry": collection is not None,
                "footprint_count": len(collection["features"]) if collection else 0,
                "energy_iq_buildings": counts.get(campus.id, 0),
                "mapped_buildings": len(geo.features_by_building(campus.id)),
            }
        )
    return {
        "campuses": out,
        "attribution": geo.ATTRIBUTION,
        # Carried here so the platform-status page can state the freshness
        # window without asking for a campus it does not need. Same constant
        # the map itself uses, from deployment_scope — not a second definition.
        "telemetry_window_seconds": TELEMETRY_WINDOW_SECONDS,
    }


@router.get("/{campus_id}")
def campus_map(campus_id: int, db: Session = Depends(get_db)):
    """Footprints, associations and the electrical state of one campus."""
    campus = db.query(Campus).filter(Campus.id == campus_id).first()
    if campus is None:
        raise HTTPException(status_code=404, detail=f"No campus with id {campus_id}")

    now = datetime.utcnow()
    view = geo.campus_views().get(campus_id)
    collection = geo.geometry(campus_id)

    buildings = db.query(Building).filter(Building.campus_id == campus_id).all()
    building_ids = [b.id for b in buildings]
    today_by_building = agg.by_building(agg.hourly_energy(db, start=today_start()))
    alerts_by_node = _open_alerts_by_node(db)

    # Deployments for this campus's buildings, newest first, so the first hit
    # per building is the one to describe when none is operational.
    deployments = (
        db.query(Deployment)
        .filter(Deployment.building_id.in_(building_ids or [-1]))
        .order_by(Deployment.id.desc())
        .all()
    )
    panels = {
        p.id: p.name
        for p in db.query(ElectricalPanel)
        .filter(ElectricalPanel.building_id.in_(building_ids or [-1]))
        .all()
    }
    nodes = {n.id: n for n in db.query(Node).all()}
    # The statuses in which a node is expected to be measuring, read from
    # deployment_statuses rather than compared against the literal "active".
    operational_codes = set(lifecycle.operational_statuses(db))

    building_state = []
    for building in buildings:
        mine = [d for d in deployments if d.building_id == building.id]
        operational = next((d for d in mine if d.status in operational_codes), None)
        chosen = operational or (mine[0] if mine else None)

        latest = (
            scope.production_readings(db)
            .filter(EnergyReading.building_id == building.id)
            .order_by(EnergyReading.timestamp.desc())
            .first()
        )
        # Freshness is asked of the deployment that is supposed to be running.
        # Asking the building would let a closed campaign's last reading make a
        # newly activated, silent one look live.
        last_for_chosen = (
            deployment_scope.last_reading_at(db, chosen.id) if chosen is not None else None
        )
        fresh = state.freshness(last_for_chosen, TELEMETRY_WINDOW_SECONDS, now)

        node = nodes.get(chosen.node_id) if chosen else None
        open_alerts = alerts_by_node.get(node.id, []) if node and operational else []
        max_severity = max(Severity.parse(a.severity) for a in open_alerts) if open_alerts else None

        energy_today, cost_today = agg.totals(today_by_building.get(building.id, []))
        map_status = state.derive_status(
            has_active_deployment=operational is not None,
            telemetry_live=fresh["is_live"],
            max_open_severity=max_severity,
            has_history=latest is not None,
        )

        building_state.append(
            {
                "id": building.id,
                "code": building.code,
                "name": building.name,
                "campus_id": building.campus_id,
                "campus": campus.name,
                "organizational_unit": (
                    building.organizational_unit.name if building.organizational_unit else None
                ),
                "is_placeholder": building.is_placeholder,
                "map_status": map_status,
                "deployment": _deployment_summary(
                    chosen,
                    node,
                    panels.get(chosen.electrical_panel_id) if chosen else None,
                    operational_codes,
                ),
                "deployment_count": len(mine),
                "telemetry": fresh,
                "latest_reading": _reading_snapshot(latest),
                "energy_today_kwh": round(energy_today, 4),
                "cost_today_mxn": round(cost_today, 4),
                "alerts": {
                    "open_count": len(open_alerts),
                    "max_severity": max_severity.name if max_severity else None,
                    "items": [
                        {
                            "id": a.id,
                            "alert_id": a.alert_id,
                            "severity": a.severity,
                            "title": a.title,
                            "created_at": a.created_at.isoformat() if a.created_at else None,
                        }
                        for a in open_alerts[:5]
                    ],
                },
            }
        )

    by_id = {b["id"]: b for b in building_state}
    associations = geo.buildings_by_feature(campus_id)

    features = []
    for feature in (collection or {}).get("features", []):
        linked = associations.get(feature["id"], [])
        linked_ids = [
            entry["energy_iq_building_id"]
            for entry in linked
            if entry["energy_iq_building_id"] in by_id
        ]
        statuses = [by_id[bid]["map_status"] for bid in linked_ids]
        features.append(
            {
                **feature,
                "properties": {
                    **feature["properties"],
                    # Identity stays in two layers: the OSM keys above describe
                    # the physical feature, these describe what Energy IQ knows
                    # about it. Neither is derived from the other's name.
                    "energy_iq_building_ids": linked_ids,
                    "map_status": state.worst(statuses) if statuses else state.UNREGISTERED,
                    "association_confidence": (
                        linked[0].get("confidence") if linked and linked_ids else None
                    ),
                },
            }
        )

    mapped = set(geo.features_by_building(campus_id))
    return {
        "campus": {
            "id": campus.id,
            "name": campus.name,
            "location": campus.location,
            "delegation": campus.delegation.name if campus.delegation else None,
        },
        "view": {
            "has_geometry": collection is not None,
            "fallback_center": view.fallback_center if view else None,
            "fallback_zoom": view.fallback_zoom if view else None,
        },
        "geometry": (
            {"type": "FeatureCollection", "features": features} if collection is not None else None
        ),
        # The campus property outline, alongside the footprints rather than
        # among them. The page draws it faintly and fits the viewport to it, so
        # a site whose buildings OSM has not traced still shows *where it is*
        # instead of falling back to an arbitrary centre.
        "grounds": geo.grounds(campus_id),
        "buildings": building_state,
        # Registered in Energy IQ but not drawn: real data with nowhere on the
        # map to put it. The page lists these instead of losing them.
        "unmapped_building_ids": [b["id"] for b in building_state if b["id"] not in mapped],
        "orphan_associations": geo.orphans(campus_id, set(by_id)),
        "telemetry_window_seconds": TELEMETRY_WINDOW_SECONDS,
        "attribution": geo.ATTRIBUTION,
        "generated_at": now.isoformat(),
    }
