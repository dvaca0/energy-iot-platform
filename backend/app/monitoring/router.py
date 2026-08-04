"""HTTP API for the monitoring system.

Mounted at ``/api/monitoring``. Three audiences:

* **Nodes** post heartbeats to ``/heartbeat``.
* **The frontend** reads status, alerts and history.
* **An operator** runs self-tests and acknowledges alerts.

The heartbeat endpoint deliberately accepts more than it requires: any node
code, registered or not, and any subset of the health fields. Rejecting an
unexpected payload would turn a monitoring rollout into an ingestion outage,
and would discard the very evidence needed to diagnose a misconfigured node.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.monitoring import history
from app.monitoring.alerts import acknowledge
from app.monitoring.channels import build_channels
from app.monitoring.channels.telegram import TelegramChannel
from app.monitoring.config import config_as_dict, get_config
from app.monitoring.heartbeat import HeartbeatPayload, record_heartbeat
from app.monitoring.notifications import dispatch_pending, enqueue, pending_count
from app.monitoring.rules import registered_rules
from app.monitoring.scheduler import watchdog_status
from app.monitoring.status import build_status

log = logging.getLogger("monitoring.router")

router = APIRouter()


# --------------------------------------------------------------------------
# Node ingestion
# --------------------------------------------------------------------------

@router.post("/heartbeat")
def post_heartbeat(
    payload: HeartbeatPayload,
    request: Request,
    db: Session = Depends(get_db),
):
    """Accept a node heartbeat.

    Returns the interval the node should use, so the cadence can be retuned
    centrally without redeploying every Pi.
    """
    config = get_config()

    source_ip = request.client.host if request.client else None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        source_ip = forwarded.split(",")[0].strip()

    beat = record_heartbeat(db, payload, source_ip=source_ip)
    db.commit()

    return {
        "status": "ok",
        "received_at": beat.received_at.isoformat(),
        "node_code": beat.node_code,
        "registered": beat.node_id is not None,
        "next_interval_seconds": config.heartbeat.interval_seconds,
        "clock_drift_seconds": beat.clock_drift_seconds,
    }


# --------------------------------------------------------------------------
# Status
# --------------------------------------------------------------------------

@router.get("/status")
def get_status(db: Session = Depends(get_db)):
    """Full platform status snapshot, collected on demand."""
    return build_status(db)


@router.get("/health")
def monitoring_health(db: Session = Depends(get_db)):
    """Whether the monitoring system itself is working.

    Checked separately from platform health: a green platform status means
    nothing if the thing reporting it stopped running an hour ago.
    """
    watchdog = watchdog_status()
    return {
        "scheduler": watchdog,
        "pending_notifications": pending_count(db),
        "channels": [channel.describe() for channel in build_channels()],
        "rules_registered": len(registered_rules()),
        "healthy": bool(watchdog.get("running")),
    }


# --------------------------------------------------------------------------
# Alerts
# --------------------------------------------------------------------------

@router.get("/alerts")
def list_alerts(
    status: str | None = Query(None, pattern="^(open|resolved|acknowledged|all)$"),
    severity: str | None = None,
    subsystem: str | None = None,
    node_code: str | None = None,
    hours: int | None = Query(None, ge=1, le=8760),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Filtered alert list, newest first."""
    since = datetime.utcnow() - timedelta(hours=hours) if hours else None
    return history.list_alerts(
        db,
        status=status,
        severity=severity,
        subsystem=subsystem,
        node_code=node_code,
        since=since,
        limit=limit,
        offset=offset,
    )


@router.get("/alerts/statistics")
def alert_statistics(
    days: int = Query(7, ge=1, le=365), db: Session = Depends(get_db)
):
    """Aggregate alert counts, for a dashboard."""
    return history.statistics(db, days=days)


@router.get("/alerts/{alert_id}")
def get_alert(alert_id: str, db: Session = Depends(get_db)):
    """One alert with its event timeline and delivery record."""
    alert = history.get_alert(db, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert["recurrence"] = history.recurrence(db, alert["fingerprint"])
    return alert


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(
    alert_id: str, by: str | None = None, db: Session = Depends(get_db)
):
    """Acknowledge an alert: stops reminders, keeps it open."""
    alert = acknowledge(db, alert_id, by=by)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found or already resolved")
    db.commit()
    return {"status": "acknowledged", "alert_id": alert_id, "by": by}


# --------------------------------------------------------------------------
# Nodes
# --------------------------------------------------------------------------

@router.get("/nodes/{node_code}/heartbeats")
def node_heartbeats(
    node_code: str,
    hours: int = Query(24, ge=1, le=720),
    db: Session = Depends(get_db),
):
    """Recent heartbeat history for one node."""
    return {
        "node_code": node_code,
        "hours": hours,
        "heartbeats": history.node_heartbeat_history(db, node_code, hours=hours),
    }


# --------------------------------------------------------------------------
# Configuration and diagnostics
# --------------------------------------------------------------------------

@router.get("/config")
def get_monitoring_config():
    """Effective configuration, with secrets redacted."""
    return config_as_dict()


@router.get("/rules")
def list_rules():
    """Every registered rule, so coverage is inspectable."""
    config = get_config()
    disabled = set(config.disabled_rules)
    return {
        "count": len(registered_rules()),
        "rules": [
            {
                "rule_id": rule.rule_id,
                "subsystem": rule.subsystem,
                "description": rule.description,
                "enabled": rule.rule_id not in disabled and rule.enabled_by_default,
            }
            for rule in sorted(registered_rules().values(), key=lambda r: r.rule_id)
        ],
    }


@router.get("/channels")
def list_channels():
    """Configured notification channels."""
    return {"channels": [channel.describe() for channel in build_channels()]}


@router.post("/test-notification")
def test_notification(db: Session = Depends(get_db)):
    """Send a test message through every configured channel.

    Queued through the normal outbox and delivered immediately, so this
    exercises the real delivery path rather than a shortcut that could succeed
    while the real path is broken.
    """
    from app.monitoring.channels import OutboundMessage
    from app.monitoring.severity import Severity

    config = get_config()
    now = datetime.utcnow()

    body = (
        "ℹ️ <b>INFO</b>\n"
        "<b>Monitoring test notification</b>\n\n"
        f"<b>Deployment:</b> {config.deployment_name}\n"
        f"<b>Sent:</b> {now.isoformat()}Z\n\n"
        "If you are reading this, alert delivery works end to end."
    )

    rows = enqueue(
        db,
        OutboundMessage(
            body=body,
            html_body=body,
            severity=Severity.INFO,
            subject="Monitoring test",
            kind="selftest",
        ),
        now=now,
        bypass_policy=True,
    )
    db.commit()

    result = dispatch_pending(db, now=now)
    db.commit()

    return {"queued": len(rows), "delivery": result}


@router.get("/telegram/verify")
def verify_telegram():
    """Verify the Telegram token and report the bot identity."""
    channel = TelegramChannel(get_config().telegram)
    return channel.verify()


@router.get("/telegram/discover-chat")
def discover_chat():
    """Find the chat id after someone messages the bot."""
    channel = TelegramChannel(get_config().telegram)
    return channel.discover_chat_id()


__all__ = ["router"]
