from datetime import datetime, timedelta
import shutil
import subprocess

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import commissioning, lifecycle, scope
from app.db.database import get_db
from app.db.models import Node, EnergyReading, Deployment

router = APIRouter()

NODE_STALE_SECONDS = 180
READING_STALE_SECONDS = 180
DISK_WARNING_PCT = 80
DISK_CRITICAL_PCT = 90


def service_active(name: str):
    result = subprocess.run(
        ["systemctl", "is-active", name],
        capture_output=True,
        text=True,
        timeout=5,
    )
    return result.stdout.strip()


def alert(level, title, detail):
    return {"level": level, "title": title, "detail": detail}


@router.get("/status")
def alert_status(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    alerts = []

    backend_status = service_active("energy-platform-backend.service")
    frontend_status = service_active("energy-platform-frontend.service")

    if backend_status != "active":
        alerts.append(alert("critical", "Backend service down", backend_status))

    if frontend_status != "active":
        alerts.append(alert("critical", "Frontend service down", frontend_status))

    disk = shutil.disk_usage("/")
    disk_pct = round((disk.used / disk.total) * 100, 2)

    if disk_pct >= DISK_CRITICAL_PCT:
        alerts.append(alert("critical", "Disk space critical", f"{disk_pct}% used"))
    elif disk_pct >= DISK_WARNING_PCT:
        alerts.append(alert("warning", "Disk space warning", f"{disk_pct}% used"))

    # Alerting follows NODES, not campaigns.
    #
    # This endpoint used to iterate `Deployment.status == "active"`. Every
    # deployment in the database is completed, so it silently emitted nothing —
    # heartbeat failures, stale readings and frequency excursions all went
    # unreported. Completing a campaign could switch off monitoring for a node
    # that was still physically installed and still measuring.
    #
    # `is_monitored` comes from node_commission_states, so which states are
    # watched is data. No deployment transition can change it (ADR-0001).
    monitored = commissioning.monitored_states(db)
    monitored_nodes = (
        db.query(Node).filter(Node.commission_state.in_(monitored)).all()
    )

    # Reported for context only — never used to decide what is monitored.
    operational_deployments = (
        db.query(Deployment)
        .filter(Deployment.status.in_(lifecycle.operational_statuses(db)))
        .count()
    )

    # Which nodes have a deployment that can retain their readings at all. Used
    # to tell "installed but not yet commissioned into a campaign" apart from
    # "should be measuring and is not".
    attributing_by_node = {
        node_id: True
        for (node_id,) in db.query(Deployment.node_id)
        .filter(Deployment.status.in_(lifecycle.attributing_statuses(db)))
        .distinct()
        .all()
    }

    for node in monitored_nodes:
        if not node.last_sync:
            alerts.append(alert("critical", f"{node.code} no heartbeat", "Node has never synchronized"))
        else:
            age = (now - node.last_sync).total_seconds()
            if age > NODE_STALE_SECONDS:
                alerts.append(alert("critical", f"{node.code} heartbeat stale", f"{int(age)} seconds since last sync"))

        if node.buffer_pending and node.buffer_pending > 0:
            alerts.append(alert("warning", f"{node.code} buffer pending", f"{node.buffer_pending} samples pending"))

        latest = (
            scope.production_readings(db)
            .filter(EnergyReading.node_id == node.id)
            .order_by(EnergyReading.timestamp.desc())
            .first()
        )

        # Electrical-quality rules apply only to nodes that declare themselves
        # production. A node on the bench reads ~1e-5 A and PF 0.00 by design;
        # judging it against production thresholds produces a permanent false
        # alarm and trains the operator to ignore the panel. Liveness rules
        # above still apply to every monitored node — a bench node that stops
        # responding is still a fault (ADR-0003).
        measures_production = node.measurement_context == "production"

        if not latest:
            if not attributing_by_node.get(node.id):
                # Installed and commissioned but not attached to a campaign:
                # a commissioning gap, not an equipment fault. Matches the
                # monitoring subsystem's node.standby rule.
                alerts.append(alert(
                    "warning", f"{node.code} awaiting deployment",
                    "Commissioned but no deployment covers it, so readings are not being retained",
                ))
            elif measures_production:
                alerts.append(alert(
                    "critical", f"{node.code} no readings",
                    "No production readings for this commissioned node",
                ))
        else:
            reading_age = (now - latest.timestamp).total_seconds()
            if reading_age > READING_STALE_SECONDS:
                alerts.append(alert("critical", f"{node.code} readings stale", f"{int(reading_age)} seconds since latest reading"))

            if measures_production:
                if latest.power_factor is not None and latest.power_factor < 0.70:
                    alerts.append(alert("warning", f"{node.code} low power factor", f"PF={latest.power_factor:.2f}"))

                if latest.frequency_hz is not None and not (59.5 <= latest.frequency_hz <= 60.5):
                    alerts.append(alert("critical", f"{node.code} frequency out of range", f"{latest.frequency_hz:.2f} Hz"))

    level = "ok"
    if any(a["level"] == "critical" for a in alerts):
        level = "critical"
    elif any(a["level"] == "warning" for a in alerts):
        level = "warning"

    return {
        "status": level,
        "generated_at": now.isoformat(),
        "services": {
            "backend": backend_status,
            "frontend": frontend_status,
        },
        "disk": {
            "used_pct": disk_pct,
            "free_gb": round(disk.free / 1024 / 1024 / 1024, 2),
        },
        "monitored_nodes": len(monitored_nodes),
        "active_deployments": operational_deployments,
        "alert_count": len(alerts),
        "alerts": alerts,
    }
