"""Alert history queries.

The read side of the alert store, kept separate from ``alerts.py`` so the
lifecycle logic is not mixed with presentation queries. This is what the future
Alerts page in the frontend will consume.

Every function takes an explicit session and returns plain dictionaries, so the
API layer never touches ORM objects and cannot accidentally trigger lazy loads
after the session has closed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.monitoring.models import AlertEvent, MonitorAlert, NotificationOutbox
from app.monitoring.severity import Severity


def _serialize(alert: MonitorAlert, now: datetime) -> dict[str, Any]:
    """Alert row as a plain dictionary."""
    open_seconds = ((alert.resolved_at or now) - alert.created_at).total_seconds()

    return {
        "id": alert.id,
        "alert_id": alert.alert_id,
        "fingerprint": alert.fingerprint,
        "rule_id": alert.rule_id,
        "subsystem": alert.subsystem,
        "severity": alert.severity,
        "initial_severity": alert.initial_severity,
        "peak_severity": alert.peak_severity,
        "status": alert.status,
        "title": alert.title,
        "summary": alert.summary,
        "node_code": alert.node_code,
        "campus": alert.campus,
        "building": alert.building,
        "deployment": alert.deployment,
        "hostname": alert.hostname,
        "metric": alert.metric,
        "current_value": alert.current_value,
        "expected_value": alert.expected_value,
        "created_at": alert.created_at.isoformat(),
        "last_seen_at": alert.last_seen_at.isoformat(),
        "escalated_at": alert.escalated_at.isoformat() if alert.escalated_at else None,
        "acknowledged_at": (alert.acknowledged_at.isoformat() if alert.acknowledged_at else None),
        "acknowledged_by": alert.acknowledged_by,
        "resolved_at": alert.resolved_at.isoformat() if alert.resolved_at else None,
        "duration_seconds": alert.duration_seconds if alert.resolved_at else open_seconds,
        "is_open": alert.resolved_at is None,
        "occurrence_count": alert.occurrence_count,
        "notification_count": alert.notification_count,
        "context": alert.context_data(),
    }


def list_alerts(
    session: Session,
    *,
    status: str | None = None,
    severity: str | None = None,
    subsystem: str | None = None,
    node_code: str | None = None,
    since: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    """Filtered, paginated alert list, newest first.

    ``status`` accepts ``open``, ``resolved``, ``acknowledged`` or ``all``.
    Defaults to everything, because an alerts page that hides resolved history
    cannot answer "has this happened before?".
    """
    now = datetime.utcnow()
    query = session.query(MonitorAlert)

    if status == "open":
        query = query.filter(MonitorAlert.resolved_at.is_(None))
    elif status == "resolved":
        query = query.filter(MonitorAlert.resolved_at.isnot(None))
    elif status == "acknowledged":
        query = query.filter(MonitorAlert.status == "acknowledged")

    if severity:
        query = query.filter(MonitorAlert.severity == severity.upper())
    if subsystem:
        query = query.filter(MonitorAlert.subsystem == subsystem)
    if node_code:
        query = query.filter(MonitorAlert.node_code == node_code)
    if since:
        query = query.filter(MonitorAlert.created_at >= since)

    total = query.count()
    rows = (
        query.order_by(MonitorAlert.created_at.desc())
        .offset(max(0, offset))
        .limit(max(1, min(limit, 500)))
        .all()
    )

    return {
        "total": total,
        "count": len(rows),
        "offset": offset,
        "alerts": [_serialize(alert, now) for alert in rows],
    }


def get_alert(session: Session, alert_id: str) -> dict[str, Any] | None:
    """One alert with its full event timeline and delivery record."""
    alert = session.query(MonitorAlert).filter(MonitorAlert.alert_id == alert_id).first()
    if alert is None:
        return None

    now = datetime.utcnow()
    data = _serialize(alert, now)

    data["events"] = [
        {
            "event_type": event.event_type,
            "occurred_at": event.occurred_at.isoformat(),
            "from_severity": event.from_severity,
            "to_severity": event.to_severity,
            "detail": event.detail,
        }
        for event in (
            session.query(AlertEvent)
            .filter(AlertEvent.alert_id == alert.id)
            .order_by(AlertEvent.occurred_at.asc())
            .all()
        )
    ]

    data["notifications"] = [
        {
            "channel": row.channel,
            "status": row.status,
            "attempts": row.attempts,
            "created_at": row.created_at.isoformat(),
            "delivered_at": row.delivered_at.isoformat() if row.delivered_at else None,
            "last_error": row.last_error,
        }
        for row in (
            session.query(NotificationOutbox)
            .filter(NotificationOutbox.alert_ref == alert.id)
            .order_by(NotificationOutbox.created_at.asc())
            .all()
        )
    ]

    return data


def recurrence(session: Session, fingerprint: str, *, days: int = 30) -> dict[str, Any]:
    """How often this exact problem has occurred recently.

    Answers "has this happened before?" — the question that separates a one-off
    from a pattern, and the one that decides whether to restart a service or
    investigate why it keeps dying.
    """
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        session.query(MonitorAlert)
        .filter(
            MonitorAlert.fingerprint == fingerprint,
            MonitorAlert.created_at >= since,
        )
        .order_by(MonitorAlert.created_at.desc())
        .all()
    )

    durations = [row.duration_seconds for row in rows if row.duration_seconds]

    return {
        "fingerprint": fingerprint,
        "window_days": days,
        "occurrences": len(rows),
        "first_seen": rows[-1].created_at.isoformat() if rows else None,
        "last_seen": rows[0].created_at.isoformat() if rows else None,
        "mean_duration_seconds": (round(sum(durations) / len(durations), 1) if durations else None),
        "longest_duration_seconds": max(durations) if durations else None,
    }


def statistics(session: Session, *, days: int = 7) -> dict[str, Any]:
    """Aggregate alert statistics for a dashboard."""
    since = datetime.utcnow() - timedelta(days=days)

    by_severity = dict(
        session.query(MonitorAlert.severity, func.count(MonitorAlert.id))
        .filter(MonitorAlert.created_at >= since)
        .group_by(MonitorAlert.severity)
        .all()
    )
    by_subsystem = dict(
        session.query(MonitorAlert.subsystem, func.count(MonitorAlert.id))
        .filter(MonitorAlert.created_at >= since)
        .group_by(MonitorAlert.subsystem)
        .all()
    )
    by_rule = (
        session.query(MonitorAlert.rule_id, func.count(MonitorAlert.id).label("n"))
        .filter(MonitorAlert.created_at >= since)
        .group_by(MonitorAlert.rule_id)
        .order_by(func.count(MonitorAlert.id).desc())
        .limit(10)
        .all()
    )

    mean_resolution = (
        session.query(func.avg(MonitorAlert.duration_seconds))
        .filter(
            MonitorAlert.created_at >= since,
            MonitorAlert.resolved_at.isnot(None),
        )
        .scalar()
    )

    return {
        "window_days": days,
        "total": sum(by_severity.values()),
        "by_severity": {
            level.label: by_severity.get(level.label, 0)
            for level in Severity
            if level is not Severity.OK
        },
        "by_subsystem": by_subsystem,
        "noisiest_rules": [{"rule_id": rule, "count": count} for rule, count in by_rule],
        "currently_open": (
            session.query(func.count(MonitorAlert.id))
            .filter(MonitorAlert.resolved_at.is_(None))
            .scalar()
            or 0
        ),
        "mean_resolution_seconds": (round(float(mean_resolution), 1) if mean_resolution else None),
    }


def node_heartbeat_history(
    session: Session, node_code: str, *, hours: int = 24, limit: int = 500
) -> list[dict[str, Any]]:
    """Recent heartbeats for one node, for charting node health over time."""
    from app.monitoring.models import NodeHeartbeat

    since = datetime.utcnow() - timedelta(hours=hours)
    rows = (
        session.query(NodeHeartbeat)
        .filter(
            NodeHeartbeat.node_code == node_code,
            NodeHeartbeat.received_at >= since,
        )
        .order_by(NodeHeartbeat.received_at.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "received_at": row.received_at.isoformat(),
            "cpu_percent": row.cpu_percent,
            "memory_percent": row.memory_percent,
            "disk_percent": row.disk_percent,
            "temperature_c": row.cpu_temperature_c,
            "uptime_seconds": row.uptime_seconds,
            "buffered_readings": row.buffered_readings,
            "latency_ms": row.latency_ms,
            "collector_status": row.collector_status,
            "undervoltage": row.undervoltage,
            "throttled": row.throttled,
            "clock_drift_seconds": row.clock_drift_seconds,
        }
        for row in rows
    ]


__all__ = [
    "get_alert",
    "list_alerts",
    "node_heartbeat_history",
    "recurrence",
    "statistics",
]
