"""Smart Plug (Shelly Plug US Gen4) inventory, telemetry and assignment.

Smart plugs are accessories of a deployment, not Energy Nodes. They answer a
single question during a measurement campaign: which outlet or which connected
appliance is consuming the most.

Discovery happens exclusively on the Raspberry Pis. This module never scans the
network: it only receives the inventory each Pi already discovered, through
POST /api/smart-plugs/discovery, and serves it back to the dashboard.

A plug is identified by MAC address. IPs change with DHCP and are refreshed on
every report; they are never used as identity, so a plug that reappears on a
new IP updates the stored IP instead of creating a duplicate.
"""
import logging
import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import lifecycle
from app.services import deployment_ops as ops
from app.db.database import get_db
from app.db.models import (
    Building,
    Deployment,
    Node,
    SmartPlug,
    SmartPlugReading,
)

router = APIRouter()

log = logging.getLogger(__name__)

# Plugs are polled every 15 s by the edge. Six missed cycles is a safe margin
# to call one offline without flapping on a single lost packet, and it also
# covers the case where the Raspberry itself stops reporting.
ONLINE_WINDOW_SECONDS = 90

# Guardrail for history queries so a wide range cannot exhaust memory.
MAX_HISTORY_POINTS = 5000


def normalize_mac(mac: str) -> str:
    """Canonical MAC form: uppercase, colon separated.

    Shelly reports MACs as bare hex (ACEBE6F65388); technicians type them with
    colons. Both must resolve to the same device.
    """
    cleaned = "".join(ch for ch in str(mac) if ch.isalnum()).upper()

    if len(cleaned) != 12:
        return str(mac).strip().upper()

    return ":".join(cleaned[i:i + 2] for i in range(0, 12, 2))


MAC_RE = re.compile(r"^[0-9A-F]{2}(:[0-9A-F]{2}){5}$")

# A measurement older than this is not plausible edge buffering, and one in the
# future means a bad clock. Both would corrupt history, so they are rejected
# rather than stored.
MAX_TIMESTAMP_AGE = timedelta(days=30)
MAX_TIMESTAMP_SKEW = timedelta(minutes=10)


def valid_mac(mac: str | None) -> str | None:
    """Return the canonical MAC, or None when it is not a real MAC.

    normalize_mac() is deliberately forgiving so technicians can type a MAC in
    any notation. Ingestion cannot be: a malformed MAC would create a junk plug
    row that nothing can ever match again, and plugs are never deleted.
    """
    if not mac:
        return None

    candidate = normalize_mac(mac)

    return candidate if MAC_RE.match(candidate) else None


def valid_timestamp(value: datetime, now: datetime | None = None) -> bool:
    """Reject impossible measurement timestamps (bad RTC, corrupt buffer)."""
    now = now or datetime.utcnow()

    return (now - MAX_TIMESTAMP_AGE) <= value <= (now + MAX_TIMESTAMP_SKEW)


def plug_slug(mac: str) -> str:
    """Stable, URL-safe public id derived from the permanent identity."""
    return normalize_mac(mac).replace(":", "").lower()


def is_plug_online(plug: SmartPlug) -> bool:
    """Online means the edge reported it up *and* the report is still fresh."""
    if not plug.online or not plug.last_seen:
        return False

    return plug.last_seen >= datetime.utcnow() - timedelta(seconds=ONLINE_WINDOW_SECONDS)


def energy_today_kwh(db: Session, plug: SmartPlug) -> float | None:
    """Energy consumed today, from the per-sample deltas stored in history.

    Deltas are used instead of (max - min) of the cumulative counter so a
    firmware counter reset in the middle of the day cannot produce a spike.
    """
    start_of_day = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    # Aggregated in SQL: the inventory is polled every 15 s by every open
    # dashboard, so today's samples must not be pulled into Python each time.
    total = (
        db.query(func.sum(SmartPlugReading.energy_kwh))
        .filter(
            SmartPlugReading.smart_plug_id == plug.id,
            SmartPlugReading.timestamp >= start_of_day,
        )
        .scalar()
    )

    if total is None:
        return None

    return round(total, 4)


def serialize_plug(db: Session, plug: SmartPlug, include_energy_today: bool = True) -> dict:
    """Shape expected by the Smart Plugs page and the dashboard widget."""
    online = is_plug_online(plug)

    # The label the technician typed wins for display; the resolved relation is
    # the fallback so a plug assigned by id still shows a name.
    building = plug.building_label or (plug.building.name if plug.building else None)

    if plug.deployment_label:
        deployment = plug.deployment_label
    elif plug.deployment:
        deployment = f"{plug.deployment.start_date} → {plug.deployment.end_date}"
    else:
        deployment = None

    return {
        "id": plug_slug(plug.mac),
        "mac": plug.mac,
        "model": plug.model,

        "ip": plug.ip_address,
        "hostname": plug.hostname,
        "serial": plug.serial,
        "firmware": plug.firmware,
        "rssi": plug.rssi,
        "temperature_c": plug.temperature_c,

        "node": plug.node.code if plug.node else None,
        "building": building,
        "deployment": deployment,
        "friendly_name": plug.friendly_name,
        "outlet_location": plug.outlet_location,

        "online": online,
        "last_seen": plug.last_seen.isoformat() if plug.last_seen else None,

        # The node allowed to report this plug, and when it claimed it.
        "owner_claimed_at": plug.owner_claimed_at.isoformat() if plug.owner_claimed_at else None,

        # Stale telemetry is hidden rather than shown as if it were current.
        "power_w": plug.power_w if online else None,
        "voltage_v": plug.voltage_v if online else None,
        "current_a": plug.current_a if online else None,
        "power_factor": plug.power_factor if online else None,
        "energy_today_kwh": energy_today_kwh(db, plug) if include_energy_today else None,
    }


def resolve_plug(db: Session, plug_id: str) -> SmartPlug:
    """Look a plug up by public slug, MAC in any notation, or numeric id."""
    candidate = normalize_mac(plug_id)

    plug = db.query(SmartPlug).filter(SmartPlug.mac == candidate).first()

    if not plug and str(plug_id).isdigit():
        plug = db.query(SmartPlug).filter(SmartPlug.id == int(plug_id)).first()

    if not plug:
        raise HTTPException(status_code=404, detail="Smart plug not found")

    return plug


@router.get("")
def list_smart_plugs(db: Session = Depends(get_db), deployment_id: int | None = None):
    """Full inventory: assigned and unassigned, online and offline.

    Offline plugs are returned on purpose. A plug that disappears keeps its
    assignment and its history; the UI shows it as offline with its last seen.

    ``deployment_id`` returns only the plugs assigned to that deployment.
    Omitting it returns the whole inventory, unchanged for existing callers.
    Note that an unassigned plug belongs to no deployment and is therefore
    absent from every scoped result — that is the assignment being missing, not
    the plug being filtered out incorrectly.
    """
    query = db.query(SmartPlug)
    if deployment_id is not None:
        query = query.filter(SmartPlug.deployment_id == deployment_id)
    plugs = query.order_by(SmartPlug.id).all()

    return [serialize_plug(db, plug) for plug in plugs]


@router.get("/live")
def live_smart_plugs(db: Session = Depends(get_db)):
    """Only plugs currently responding, ranked by instantaneous power.

    This is the campaign view: the top entry is the outlet consuming the most.
    """
    plugs = db.query(SmartPlug).all()

    live = [serialize_plug(db, plug) for plug in plugs]
    live = [item for item in live if item["online"]]
    live.sort(key=lambda item: item["power_w"] or 0, reverse=True)

    return {
        "count": len(live),
        "total_power_w": round(sum(item["power_w"] or 0 for item in live), 2),
        "highest_consumer": live[0] if live else None,
        "smart_plugs": live,
    }


@router.get("/{plug_id}")
def get_smart_plug(plug_id: str, db: Session = Depends(get_db)):
    plug = resolve_plug(db, plug_id)

    detail = serialize_plug(db, plug)

    detail["energy_total_kwh"] = plug.energy_total_kwh
    detail["created_at"] = plug.created_at.isoformat() if plug.created_at else None
    detail["updated_at"] = plug.updated_at.isoformat() if plug.updated_at else None
    detail["samples"] = (
        db.query(SmartPlugReading)
        .filter(SmartPlugReading.smart_plug_id == plug.id)
        .count()
    )

    return detail


@router.get("/{plug_id}/history")
def get_smart_plug_history(
    plug_id: str,
    hours: int = Query(24, ge=1, le=24 * 90),
    limit: int = Query(1000, ge=1, le=MAX_HISTORY_POINTS),
    db: Session = Depends(get_db),
):
    """Measurement history of a single plug, oldest first for charting."""
    plug = resolve_plug(db, plug_id)

    since = datetime.utcnow() - timedelta(hours=hours)

    readings = (
        db.query(SmartPlugReading)
        .filter(
            SmartPlugReading.smart_plug_id == plug.id,
            SmartPlugReading.timestamp >= since,
        )
        .order_by(SmartPlugReading.timestamp.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "timestamp": reading.timestamp.isoformat(),
            "power_w": reading.power_w,
            "voltage_v": reading.voltage_v,
            "current_a": reading.current_a,
            "power_factor": reading.power_factor,
            "energy_kwh": reading.energy_kwh,
            "temperature_c": reading.temperature_c,
        }
        for reading in reversed(readings)
    ]


class AssignPayload(BaseModel):
    friendly_name: str | None = None
    building: str | None = None
    deployment: str | None = None
    outlet_location: str | None = None


@router.post("/{plug_id}/assign")
def assign_smart_plug(plug_id: str, payload: AssignPayload, db: Session = Depends(get_db)):
    """Attach a plug to a building and deployment.

    The UI sends free text. The text is stored verbatim for display and, when
    it matches an existing record, also resolved to a real foreign key so plug
    history can be correlated with the deployment it belongs to.
    """
    plug = resolve_plug(db, plug_id)

    if payload.friendly_name is not None:
        plug.friendly_name = payload.friendly_name.strip() or None

    if payload.outlet_location is not None:
        plug.outlet_location = payload.outlet_location.strip() or None

    if payload.building is not None:
        label = payload.building.strip()
        plug.building_label = label or None
        plug.building_id = None

        if label:
            building = (
                db.query(Building)
                .filter((Building.name == label) | (Building.code == label))
                .first()
            )
            if building:
                plug.building_id = building.id

    if payload.deployment is not None:
        label = payload.deployment.strip()
        plug.deployment_label = label or None

        # Prefer the deployment of the resolved building; otherwise fall back to
        # the deployment of the Raspberry that discovered the plug.
        deployment = None

        if plug.building_id:
            # The deployment currently measuring this building, if any — an
            # activated campaign that has not closed. "Newest row for this
            # building" would have attached the plug to a campaign that ended
            # months ago.
            deployment = (
                db.query(Deployment)
                .filter(
                    Deployment.building_id == plug.building_id,
                    Deployment.activated_at.isnot(None),
                    Deployment.closed_at.is_(None),
                )
                .order_by(Deployment.activated_at.desc())
                .first()
            )

        if not deployment and plug.node_id:
            # The plug inherits its owning node's CURRENT deployment, not the
            # node's newest deployment row. A node with no live campaign gives
            # the plug no deployment context, which is the truth.
            deployment = ops.current_deployment(db, plug.node_id)

        plug.deployment_id = deployment.id if deployment else None

        if deployment and not plug.building_id:
            plug.building_id = deployment.building_id

    plug.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(plug)

    return serialize_plug(db, plug)


class PlugMeasurement(BaseModel):
    captured_at: str

    power_w: float | None = None
    voltage_v: float | None = None
    current_a: float | None = None
    power_factor: float | None = None

    energy_total_kwh: float | None = None
    energy_kwh: float | None = None

    temperature_c: float | None = None
    rssi: float | None = None


class DiscoveredPlug(BaseModel):
    mac: str

    model: str | None = None
    ip: str | None = None
    hostname: str | None = None
    serial: str | None = None
    firmware: str | None = None
    rssi: float | None = None
    temperature_c: float | None = None

    online: bool = True
    last_seen: str | None = None

    measurements: list[PlugMeasurement] = []


class DiscoveryPayload(BaseModel):
    """Inventory report from one Raspberry Pi.

    node_id is the Node code (for example N001) so the edge does not need to
    know database ids, matching the existing measurement ingestion contract.
    """
    node_id: str
    plugs: list[DiscoveredPlug] = []


def parse_edge_timestamp(value: str | None) -> datetime:
    if not value:
        return datetime.utcnow()

    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.utcnow()

    # History is stored in naive UTC, consistent with energy_readings.
    if parsed.tzinfo:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)

    return parsed


@router.post("/discovery")
def report_discovery(payload: DiscoveryPayload, db: Session = Depends(get_db)):
    """Receive the plug inventory and buffered measurements from a Raspberry.

    Upsert is keyed on MAC, so a plug rediscovered on a different IP updates in
    place. Nothing is ever deleted here: plugs absent from a report keep their
    row, their assignment and their history.
    """
    node = db.query(Node).filter(Node.code == payload.node_id).first()

    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    # The plug's deployment context defaults to the Raspberry's own deployment.
    node_deployment = (
        db.query(Deployment)
        .filter(
            Deployment.node_id == node.id,
            Deployment.status.in_(lifecycle.attributing_statuses(db)),
        )
        .order_by(Deployment.activated_at.desc().nullslast(), Deployment.id.desc())
        .first()
    )

    created = 0
    updated = 0
    inserted_readings = 0
    duplicate_readings = 0

    rejected_malformed: list[str] = []
    rejected_duplicate: list[str] = []
    rejected_not_owner: list[str] = []
    rejected_timestamps = 0

    seen_macs: set[str] = set()

    for reported in payload.plugs:
        mac = valid_mac(reported.mac)

        if not mac:
            rejected_malformed.append(str(reported.mac)[:32])
            log.warning(
                "smart-plug report from %s rejected: malformed MAC %r",
                payload.node_id, str(reported.mac)[:32],
            )
            continue

        # One physical plug may not appear twice in a single report: the second
        # entry would overwrite the first and its measurements would be
        # attributed ambiguously.
        if mac in seen_macs:
            rejected_duplicate.append(mac)
            log.warning(
                "smart-plug report from %s rejected: duplicate MAC %s in payload",
                payload.node_id, mac,
            )
            continue

        seen_macs.add(mac)

        plug = db.query(SmartPlug).filter(SmartPlug.mac == mac).first()

        if not plug:
            # First node to report a plug claims ownership of it.
            plug = SmartPlug(mac=mac)
            plug.node_id = node.id
            plug.owner_claimed_at = datetime.utcnow()
            db.add(plug)
            db.flush()  # assigns plug.id for the readings below
            created += 1
            log.info("smart-plug %s claimed by node %s", mac, node.code)
        elif plug.node_id is None:
            # Pre-existing row with no owner: the first reporter adopts it.
            plug.node_id = node.id
            plug.owner_claimed_at = datetime.utcnow()
            updated += 1
            log.info("smart-plug %s adopted by node %s", mac, node.code)
        elif plug.node_id != node.id:
            # Not the owner. Rejected rather than accepted as the latest
            # writer: two nodes on one subnet see the same plugs, and
            # last-writer-wins would flip ownership every cycle and split the
            # plug's history. Transfer is explicit, via /transfer.
            owner = db.query(Node).filter(Node.id == plug.node_id).first()
            rejected_not_owner.append(mac)
            log.warning(
                "smart-plug report from %s rejected: %s is owned by %s",
                payload.node_id, mac, owner.code if owner else plug.node_id,
            )
            continue
        else:
            updated += 1

        if reported.model:
            plug.model = reported.model

        # Volatile fields: always refreshed, IP included.
        if reported.ip:
            plug.ip_address = reported.ip
        if reported.hostname:
            plug.hostname = reported.hostname
        if reported.serial:
            plug.serial = reported.serial
        if reported.firmware:
            plug.firmware = reported.firmware
        if reported.rssi is not None:
            plug.rssi = reported.rssi
        if reported.temperature_c is not None:
            plug.temperature_c = reported.temperature_c

        plug.node_id = node.id
        plug.online = bool(reported.online)

        # An offline plug keeps its previous last_seen: that is the whole point
        # of the field. Only a responding plug refreshes it.
        if reported.online:
            plug.last_seen = parse_edge_timestamp(reported.last_seen)

        # Inherit context from the Raspberry only while unassigned, so a manual
        # assignment is never overwritten by the edge.
        if node_deployment and plug.deployment_id is None and plug.building_label is None:
            plug.deployment_id = node_deployment.id
            plug.building_id = node_deployment.building_id

        plug.updated_at = datetime.utcnow()

        previous_total = plug.energy_total_kwh

        for measurement in sorted(reported.measurements, key=lambda m: m.captured_at):
            timestamp = parse_edge_timestamp(measurement.captured_at)

            if not valid_timestamp(timestamp):
                rejected_timestamps += 1
                log.warning(
                    "smart-plug measurement from %s for %s rejected: "
                    "implausible timestamp %s",
                    payload.node_id, mac, timestamp.isoformat(),
                )
                continue

            exists = (
                db.query(SmartPlugReading)
                .filter(
                    SmartPlugReading.smart_plug_id == plug.id,
                    SmartPlugReading.timestamp == timestamp,
                )
                .first()
            )

            if exists:
                duplicate_readings += 1
                continue

            # Prefer the delta the edge computed; otherwise derive it from the
            # cumulative counter, ignoring decreases (counter reset).
            delta = measurement.energy_kwh

            if delta is None and measurement.energy_total_kwh is not None:
                if previous_total is not None and measurement.energy_total_kwh >= previous_total:
                    delta = round(measurement.energy_total_kwh - previous_total, 6)
                else:
                    delta = 0.0

            db.add(
                SmartPlugReading(
                    smart_plug_id=plug.id,
                    node_id=node.id,
                    building_id=plug.building_id,
                    deployment_id=plug.deployment_id,
                    timestamp=timestamp,
                    power_w=measurement.power_w,
                    voltage_v=measurement.voltage_v,
                    current_a=measurement.current_a,
                    power_factor=measurement.power_factor,
                    energy_total_kwh=measurement.energy_total_kwh,
                    energy_kwh=delta,
                    temperature_c=measurement.temperature_c,
                    rssi=measurement.rssi,
                )
            )

            inserted_readings += 1

            if measurement.energy_total_kwh is not None:
                previous_total = measurement.energy_total_kwh

        # Latest sample becomes the live snapshot shown by the dashboard.
        if reported.measurements:
            latest = max(reported.measurements, key=lambda m: m.captured_at)

            plug.power_w = latest.power_w
            plug.voltage_v = latest.voltage_v
            plug.current_a = latest.current_a
            plug.power_factor = latest.power_factor

            if latest.energy_total_kwh is not None:
                plug.energy_total_kwh = latest.energy_total_kwh

    db.commit()

    if rejected_malformed or rejected_duplicate or rejected_not_owner or rejected_timestamps:
        log.warning(
            "smart-plug report from %s: %d malformed, %d duplicate, "
            "%d not-owned, %d bad timestamp(s)",
            payload.node_id, len(rejected_malformed), len(rejected_duplicate),
            len(rejected_not_owner), rejected_timestamps,
        )

    return {
        "status": "ok",
        "node": node.code,
        "plugs_created": created,
        "plugs_updated": updated,
        "readings_inserted": inserted_readings,
        "readings_duplicated": duplicate_readings,
        "online_window_seconds": ONLINE_WINDOW_SECONDS,
        # Reported back so the edge can log why a plug it sees is not appearing.
        "rejected_malformed_mac": rejected_malformed,
        "rejected_duplicate_mac": rejected_duplicate,
        "rejected_not_owner": rejected_not_owner,
        "rejected_timestamps": rejected_timestamps,
    }


class OwnershipTransfer(BaseModel):
    node_id: str


@router.post("/{plug_id}/transfer")
def transfer_ownership(
    plug_id: str, payload: OwnershipTransfer, db: Session = Depends(get_db)
):
    """Move a plug to a different owner node, explicitly.

    Ownership is never reassigned automatically: a plug seen by two Raspberry
    Pis stays with the node that claimed it until someone moves it here. The
    plug's history, assignment and deployment context are untouched — only the
    node allowed to report it changes.
    """
    plug = resolve_plug(db, plug_id)

    node = db.query(Node).filter(Node.code == payload.node_id).first()

    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    previous = db.query(Node).filter(Node.id == plug.node_id).first()

    plug.node_id = node.id
    plug.owner_claimed_at = datetime.utcnow()
    plug.updated_at = datetime.utcnow()
    db.commit()

    log.info(
        "smart-plug %s ownership transferred from %s to %s",
        plug.mac, previous.code if previous else None, node.code,
    )

    return {
        "status": "ok",
        "mac": plug.mac,
        "previous_owner": previous.code if previous else None,
        "owner": node.code,
        "owner_claimed_at": plug.owner_claimed_at.isoformat(),
    }
