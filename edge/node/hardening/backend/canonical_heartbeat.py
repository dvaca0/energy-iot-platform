"""Backend fix: ONE heartbeat ingest path.

DEPLOYMENT BLOCKED — no SSH access to the backend host. Written against the
live API contract (/openapi.json) and black-box probing on 2026-08-03. Never
executed against the running service.

BEFORE
    POST /api/edge/heartbeat        -> updates last_sync only  (collector)
    POST /api/monitoring/heartbeat  -> feeds monitoring store   (nobody)
    Result: N001 held at ever_seen=false / heartbeat_age=null forever, so
    node.heartbeat_lost could never fire. 43h37m outage, nobody told.

AFTER
    Both URLs funnel into ingest_heartbeat(). One store, one truth.
    /api/edge/heartbeat is retained ONLY as a compatibility alias so older
    collectors keep working during rollout; it is not a second concept.

INTEGRATION
    The backend source is not available to me, so this is a drop-in module
    plus a specification rather than a diff. Wire it as:

        from canonical_heartbeat import ingest_heartbeat, HeartbeatPayload

        @router.post("/api/monitoring/heartbeat")
        async def monitoring_heartbeat(p: HeartbeatPayload, db=Depends(get_db)):
            return ingest_heartbeat(db, p.model_dump(), source="monitoring")

        @router.post("/api/edge/heartbeat")   # compatibility alias
        async def edge_heartbeat(p: dict, db=Depends(get_db)):
            return ingest_heartbeat(db, p, source="edge")

    `db` needs: upsert_node_last_sync(), insert_monitoring_heartbeat(),
    touch_node_seen(). Names will differ in your tree; the contract is what
    matters. Run migrations/001 first.
"""

from __future__ import annotations

import datetime
from typing import Any, Optional

# Fields the monitoring store must persist. `filesystem_readonly` was in the
# API schema but was NEVER STORED, which is half of the false-positive bug:
# the rule could only ever read NULL. See monitoring_rules_fix.py.
MONITORING_FIELDS = (
    "hostname", "software_version", "collector_version", "config_version",
    "git_commit", "uptime_seconds", "boot_time", "cpu_percent",
    "cpu_temperature_c", "memory_percent", "swap_percent", "disk_percent",
    "disk_free_mb", "load_1", "load_5", "load_15",
    "filesystem_readonly",                      # <-- was dropped before
    "undervoltage", "throttled", "throttle_flags",
    "ip_address", "ethernet_up", "wifi_up", "wifi_ssid", "wifi_signal_dbm",
    "access_point_active", "tailscale_up", "internet_ok", "latency_ms",
    "sqlite_size_mb", "sqlite_wal_mb", "buffered_readings", "pending_sync",
    "last_sync_at", "last_measurement_at", "collector_status",
    "collector_pid", "collector_restarts", "ads_ok", "gpio_ok", "spi_ok",
    "shelly_reachable", "shelly_total", "sensors_connected", "local_alerts",
)

# Legacy edge payload -> canonical field names.
LEGACY_ALIASES = {"buffer_pending": "buffered_readings"}


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


def _parse_ts(value: Any) -> Optional[datetime.datetime]:
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def normalise(payload: dict) -> dict:
    """Accept either payload shape and emit the canonical one."""
    out = dict(payload or {})
    for old, new in LEGACY_ALIASES.items():
        if old in out and new not in out:
            out[new] = out.pop(old)
    return out


def clock_drift_seconds(payload: dict, now: Optional[datetime.datetime] = None):
    """Node-reported time minus server time.

    Nodes MUST send UTC. A node sending local time produced a bogus -21602s
    (-6h, CST) CRITICAL on its first heartbeat; the node side is fixed, and
    this stays as the server-side check.
    """
    t = _parse_ts(payload.get("timestamp"))
    if t is None:
        return None
    if t.tzinfo is not None:
        t = t.astimezone(datetime.timezone.utc).replace(tzinfo=None)
    return (t - (now or _utcnow())).total_seconds()


def ingest_heartbeat(db, payload: dict, source: str = "monitoring") -> dict:
    """THE single ingest path. Both URLs call this.

    Updates BOTH stores unconditionally, which is the whole point: whichever
    URL a node uses, monitoring sees it AND last_sync advances.
    """
    p = normalise(payload)
    node_id = p.get("node_id")
    if not node_id:
        raise ValueError("node_id is required")

    now = _utcnow()
    record = {k: p.get(k) for k in MONITORING_FIELDS}
    record["node_id"] = node_id
    record["received_at"] = now
    record["source"] = source
    record["clock_drift_seconds"] = clock_drift_seconds(p, now)

    # 1. monitoring store — arms node.heartbeat_lost / node.power / node.*
    db.insert_monitoring_heartbeat(record)

    # 2. node registry — drives /api/nodes status and the dashboards.
    #    Previously ONLY the edge path did this, which is why a node posting
    #    to the monitoring path alone showed as stale.
    db.upsert_node_last_sync(node_id, now,
                             buffer_pending=record.get("buffered_readings"))

    # 3. first-contact marker so 'never seen' is distinguishable from 'seen,
    #    then lost'. Those are different faults and need different alerts.
    db.touch_node_seen(node_id, now)

    return {"node_id": node_id, "received_at": now.isoformat(),
            "last_sync": now.isoformat(), "source": source,
            "clock_drift_seconds": record["clock_drift_seconds"]}
