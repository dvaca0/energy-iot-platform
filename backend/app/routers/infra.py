from datetime import datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import EnergyReading, Node
from app.services import deployment_ops as ops

router = APIRouter()


@router.get("")
def infrastructure_status(db: Session = Depends(get_db)):
    now = datetime.utcnow()
    online_limit = now - timedelta(seconds=300)

    nodes = db.query(Node).all()
    readings_total = db.query(EnergyReading).count()

    node_items = []
    total_buffer = 0
    total_samples = 0
    online_count = 0
    latest_sync = None

    for node in nodes:
        latest = (
            db.query(EnergyReading)
            .filter(EnergyReading.node_id == node.id)
            .order_by(EnergyReading.timestamp.desc())
            .first()
        )

        online = node.last_sync is not None and node.last_sync >= online_limit
        if online:
            online_count += 1

        total_buffer += node.buffer_pending or 0
        total_samples += node.samples or 0

        if node.last_sync and (latest_sync is None or node.last_sync > latest_sync):
            latest_sync = node.last_sync

        node_items.append(
            {
                "id": node.code,
                "name": node.name,
                "status": "online" if online else "offline",
                "ip": node.ip_address,
                "last_sync": node.last_sync.isoformat() if node.last_sync else None,
                "buffer_pending": node.buffer_pending or 0,
                "samples": node.samples or 0,
                # Where the node is deployed, stated explicitly. Infrastructure
                # needs to distinguish "deployed here now" from "was last deployed
                # here", so both are returned and neither is called "building".
                "current_deployment": ops.deployment_summary(
                    db, ops.current_deployment(db, node.id)
                ),
                "last_completed_deployment": ops.deployment_summary(
                    db, ops.last_completed_deployment(db, node.id)
                ),
                # The building that produced this node's most recent reading. A
                # property of the READING, named so that nobody mistakes it for a
                # property of the node.
                "last_reading_building": (
                    latest.building.name if latest and latest.building else None
                ),
                "rpi_status": "OK" if online else "Offline",
                "shelly_status": "OK" if latest and latest.timestamp >= online_limit else "Offline",
                "voltage": latest.voltage if latest else None,
                "current": latest.current if latest else None,
                "power_kw": latest.power_kw if latest else None,
                "power_factor": latest.power_factor if latest else None,
                "frequency_hz": latest.frequency_hz if latest else None,
                "latest_reading": latest.timestamp.isoformat() if latest else None,
            }
        )

    return {
        "summary": {
            "online_nodes": online_count,
            "total_nodes": len(nodes),
            "total_samples": total_samples,
            "total_readings": readings_total,
            "buffer_pending": total_buffer,
            "latest_sync": latest_sync.isoformat() if latest_sync else None,
        },
        "services": [
            {"name": "API Backend (FastAPI)", "status": "OK", "detail": "Online"},
            {
                "name": "Base de Datos PostgreSQL",
                "status": "OK",
                "detail": f"{readings_total} lecturas",
            },
            {
                "name": "Servicio de Sincronía",
                "status": "OK" if online_count > 0 else "Offline",
                "detail": f"{online_count}/{len(nodes)} nodos activos",
            },
            {
                "name": "Tailscale VPN",
                "status": "OK" if online_count > 0 else "Sin datos",
                "detail": "Conectividad edge",
            },
        ],
        "nodes": node_items,
    }
