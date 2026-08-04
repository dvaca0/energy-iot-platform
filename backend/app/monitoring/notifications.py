"""Rendering and delivery of notifications.

Three concerns, in order:

**Rendering.** An alert is turned into text carrying enough detail to diagnose
the problem without opening an SSH session — what broke, where, since when, the
current and expected values, likely causes, the commands to run, and the alert
id to quote.

**Queueing.** Every message is written to ``monitor_notification_outbox``
*before* any delivery is attempted. This is what makes "never silently discard
an alert" true rather than aspirational: if the process dies mid-send, if
Telegram is down, if DNS fails, the row survives and is retried on the next
tick. A message is only marked delivered when a channel confirms it.

**Delivery policy.** Rate limiting and quiet hours are applied here, at enqueue
time, not inside a channel — so the policy is identical for every channel that
is ever added.

Suppression is never silent. A message dropped by the rate limiter is recorded
as ``failed`` with the reason, so an operator can see that it happened.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.monitoring.alerts import AlertNotification
from app.monitoring.channels import NotificationChannel, OutboundMessage, build_channels
from app.monitoring.channels.telegram import escape
from app.monitoring.config import MonitoringConfig, get_config
from app.monitoring.models import AlertEvent, MonitorAlert, NotificationOutbox
from app.monitoring.severity import (
    STATUS_ESCALATED,
    STATUS_NEW,
    STATUS_REMINDER,
    STATUS_RESOLVED,
    Severity,
)

log = logging.getLogger("monitoring.notifications")


# --------------------------------------------------------------------------
# Formatting helpers
# --------------------------------------------------------------------------

def local_time(moment: datetime, config: MonitoringConfig) -> str:
    """Render a stored UTC timestamp in the configured timezone.

    The timezone is shown explicitly. An alert that says "18 minutes ago" is
    only actionable if the reader knows which clock it refers to, and the
    server runs UTC while the campus does not.
    """
    try:
        zone = ZoneInfo(config.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return moment.strftime("%Y-%m-%d %H:%M:%S UTC")

    aware = moment.replace(tzinfo=ZoneInfo("UTC")).astimezone(zone)
    return aware.strftime("%Y-%m-%d %H:%M:%S %Z")


def humanize_duration(seconds: float | None) -> str:
    """Render a duration the way an operator reads it."""
    if seconds is None:
        return "unknown"
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec}s" if sec else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h" if hours else f"{days}d"


def _line(label: str, value: Any) -> str | None:
    """One ``label: value`` line, or nothing when the value is absent."""
    if value is None or value == "" or value == []:
        return None
    return f"<b>{escape(label)}:</b> {escape(value)}"


# --------------------------------------------------------------------------
# Alert rendering
# --------------------------------------------------------------------------

def render_alert(
    notification: AlertNotification, config: MonitoringConfig | None = None
) -> OutboundMessage:
    """Render an alert transition into a message.

    Structure is fixed so the reader learns where to look: headline, location,
    what happened, the numbers, timing, then diagnosis. Empty sections are
    omitted rather than shown blank — an alert padded with "N/A" is harder to
    scan, not more informative.
    """
    config = config or get_config()
    alert = notification.alert
    severity = notification.severity
    status = notification.status
    extra = notification.extra
    context = alert.context_data()

    lines: list[str] = []

    # --- Headline ---------------------------------------------------------
    if status == STATUS_RESOLVED:
        lines.append(f"✅ <b>RESOLVED</b> — was {escape(alert.peak_severity)}")
    else:
        marker = {
            STATUS_NEW: "",
            STATUS_ESCALATED: " — ESCALATED",
            STATUS_REMINDER: " — STILL OPEN",
        }.get(status, "")
        lines.append(f"{severity.emoji} <b>{severity.label}{escape(marker)}</b>")

    lines.append(f"<b>{escape(alert.title)}</b>")
    lines.append("")

    # --- Where ------------------------------------------------------------
    location = [
        _line("Node", alert.node_code),
        _line("Hostname", alert.hostname),
        _line("Campus", alert.campus),
        _line("Building", alert.building),
        _line("Deployment", alert.deployment),
        _line("Subsystem", alert.subsystem),
    ]
    location = [line for line in location if line]
    if location:
        lines.extend(location)
        lines.append("")

    # --- What -------------------------------------------------------------
    if alert.summary:
        lines.append(escape(alert.summary))
        lines.append("")

    measurements = [
        _line("Metric", alert.metric),
        _line("Current", alert.current_value),
        _line("Expected", alert.expected_value),
    ]
    measurements = [line for line in measurements if line]
    if measurements:
        lines.extend(measurements)
        lines.append("")

    # --- When -------------------------------------------------------------
    lines.append(_line("Detected", local_time(alert.created_at, config)) or "")
    if status == STATUS_RESOLVED and alert.resolved_at:
        lines.append(_line("Resolved", local_time(alert.resolved_at, config)) or "")
        lines.append(
            _line("Total duration", humanize_duration(alert.duration_seconds)) or ""
        )
    else:
        open_for = (datetime.utcnow() - alert.created_at).total_seconds()
        lines.append(_line("Open for", humanize_duration(open_for)) or "")

    if status == STATUS_ESCALATED and extra.get("escalation_reason"):
        lines.append(
            _line(
                "Escalated",
                f"{extra.get('previous_severity')} → {severity.label} "
                f"({extra['escalation_reason']})",
            )
            or ""
        )

    if alert.occurrence_count > 1:
        lines.append(_line("Observed", f"{alert.occurrence_count} consecutive checks") or "")

    lines.append("")

    # --- Recovery detail --------------------------------------------------
    if status == STATUS_RESOLVED:
        recovery = [
            _line("Closed because", extra.get("resolution_reason")),
            _line("Offline for", humanize_duration(extra.get("offline_seconds")))
            if extra.get("offline_seconds") is not None
            else None,
            _line("Likely cause", extra.get("estimated_cause")),
            _line("Buffered readings", extra.get("buffered_readings")),
            _line("Pending sync", extra.get("pending_sync")),
            _line("Data loss", extra.get("data_loss")),
        ]
        recovery = [line for line in recovery if line]
        if recovery:
            lines.append("<b>Recovery</b>")
            lines.extend(recovery)

        health = extra.get("current_health") or {}
        readable = {
            "cpu_percent": "CPU",
            "memory_percent": "Memory",
            "disk_percent": "Disk",
            "temperature_c": "Temperature",
            "collector_status": "Collector",
        }
        health_lines = [
            _line(readable[key], value)
            for key, value in health.items()
            if key in readable and value is not None
        ]
        health_lines = [line for line in health_lines if line]
        if health_lines:
            lines.append("")
            lines.append("<b>Current health</b>")
            lines.extend(health_lines)
        lines.append("")

    # --- Diagnosis --------------------------------------------------------
    else:
        causes = context.get("suggested_causes") or []
        if causes:
            lines.append("<b>Possible causes</b>")
            lines.extend(f"• {escape(cause)}" for cause in causes[:5])
            lines.append("")

        commands = context.get("suggested_commands") or []
        if commands:
            lines.append("<b>Check first</b>")
            lines.extend(f"<code>{escape(command)}</code>" for command in commands[:5])
            lines.append("")

        actions = context.get("suggested_actions") or []
        if actions:
            lines.append("<b>Suggested action</b>")
            lines.extend(f"• {escape(action)}" for action in actions[:4])
            lines.append("")

    # --- Footer -----------------------------------------------------------
    lines.append(f"<i>{escape(alert.alert_id)} · {escape(config.deployment_name)}</i>")

    body = "\n".join(line for line in lines if line is not None)

    return OutboundMessage(
        body=body,
        html_body=body,
        severity=severity,
        subject=f"[{severity.label}] {alert.title}",
        kind="recovery" if status == STATUS_RESOLVED else "alert",
    )


# --------------------------------------------------------------------------
# Delivery policy
# --------------------------------------------------------------------------

def in_quiet_hours(now: datetime, config: MonitoringConfig) -> bool:
    """Whether the local time falls inside the configured quiet window.

    Handles a window that wraps midnight (22:00 → 07:00), which is the usual
    case and the one a naive comparison gets wrong.
    """
    quiet = config.quiet_hours
    if not quiet.enabled:
        return False

    try:
        zone = ZoneInfo(config.timezone)
        hour = now.replace(tzinfo=ZoneInfo("UTC")).astimezone(zone).hour
    except (ZoneInfoNotFoundError, ValueError):
        hour = now.hour

    start, end = quiet.start_hour, quiet.end_hour
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def _suppressed_reason(
    session: Session, severity: Severity, now: datetime, config: MonitoringConfig
) -> str | None:
    """Why this message must not be sent, or ``None`` to send it."""
    if in_quiet_hours(now, config):
        threshold = Severity.parse(config.quiet_hours.suppress_at_or_below)
        if severity <= threshold and not severity.breaks_quiet_hours:
            return f"quiet hours ({config.quiet_hours.start_hour}:00–{config.quiet_hours.end_hour}:00)"

    # Rate limit counts what was actually sent in the last hour. EMERGENCY is
    # exempt: a cap that silences the worst possible alert is a cap that has
    # failed at its job.
    if severity is not Severity.EMERGENCY:
        # The session runs with autoflush disabled, and a single tick enqueues
        # several messages before committing. Without an explicit flush those
        # rows are invisible here and a burst inside one transaction would slip
        # past the cap entirely.
        session.flush()
        window = now - timedelta(hours=1)
        sent = (
            session.query(NotificationOutbox)
            .filter(
                NotificationOutbox.created_at >= window,
                NotificationOutbox.status != "failed",
            )
            .count()
        )
        if sent >= config.notifications.max_messages_per_hour:
            return f"rate limit ({config.notifications.max_messages_per_hour}/hour) reached"

    return None


def enqueue(
    session: Session,
    message: OutboundMessage,
    *,
    channels: list[NotificationChannel] | None = None,
    alert: MonitorAlert | None = None,
    dedupe_key: str | None = None,
    now: datetime | None = None,
    config: MonitoringConfig | None = None,
    bypass_policy: bool = False,
) -> list[NotificationOutbox]:
    """Queue a message for every configured channel.

    Returns the created rows. Does not send and does not commit — the caller
    owns the transaction, so the alert state and its queued notification are
    written atomically.
    """
    config = config or get_config()
    now = now or datetime.utcnow()
    channels = channels if channels is not None else build_channels(config)

    reason = None if bypass_policy else _suppressed_reason(session, message.severity, now, config)

    rows: list[NotificationOutbox] = []
    for channel in channels:
        if not channel.is_configured():
            continue

        key = dedupe_key
        if key:
            key = f"{channel.name}:{hashlib.sha1(key.encode()).hexdigest()[:16]}"
            existing = (
                session.query(NotificationOutbox)
                .filter(NotificationOutbox.dedupe_key == key)
                .first()
            )
            if existing is not None:
                continue

        row = NotificationOutbox(
            channel=channel.name,
            recipient=channel.recipient,
            status="failed" if reason else "pending",
            severity=message.severity.label,
            kind=message.kind,
            subject=message.subject,
            body=message.html_body or message.body,
            alert_ref=alert.id if alert is not None else None,
            created_at=now,
            next_attempt_at=None if reason else now,
            last_error=f"suppressed: {reason}" if reason else None,
            dedupe_key=key,
        )
        session.add(row)
        rows.append(row)

    if reason:
        log.info("Notification suppressed: %s", reason)

    # The announced-state counter is owned by the alert engine, not by
    # delivery. See alerts.mark_notified.
    return rows


def _backoff_delay(attempts: int, config: MonitoringConfig) -> int:
    """Seconds to wait before the next attempt.

    The final value repeats, so a long outage settles into a steady retry
    cadence rather than growing without bound.
    """
    schedule = config.notifications.retry_backoff_seconds
    if not schedule:
        return 60
    index = min(attempts, len(schedule) - 1)
    return schedule[index]


def dispatch_pending(
    session: Session,
    *,
    channels: list[NotificationChannel] | None = None,
    limit: int = 50,
    now: datetime | None = None,
    config: MonitoringConfig | None = None,
) -> dict[str, int]:
    """Attempt delivery of due outbox rows.

    Ordered oldest-first so a backlog drains in the order events happened —
    receiving a recovery before the outage it resolves would be actively
    misleading.

    Returns counts of delivered, retried and failed rows.
    """
    config = config or get_config()
    now = now or datetime.utcnow()
    channels = channels if channels is not None else build_channels(config)
    by_name = {channel.name: channel for channel in channels}

    due = (
        session.query(NotificationOutbox)
        .filter(
            NotificationOutbox.status == "pending",
            (NotificationOutbox.next_attempt_at.is_(None))
            | (NotificationOutbox.next_attempt_at <= now),
        )
        .order_by(NotificationOutbox.created_at.asc())
        .limit(limit)
        .all()
    )

    counts = {"delivered": 0, "retried": 0, "failed": 0}

    for row in due:
        channel = by_name.get(row.channel)
        if channel is None:
            row.status = "failed"
            row.last_error = f"channel '{row.channel}' is no longer registered"
            counts["failed"] += 1
            continue

        if not channel.is_configured():
            # Not a delivery failure: leave it pending so it goes out once the
            # channel is configured, rather than burning a retry attempt.
            row.next_attempt_at = now + timedelta(seconds=_backoff_delay(row.attempts, config))
            row.last_error = "channel not configured yet"
            continue

        message = OutboundMessage(
            body=row.body,
            html_body=row.body,
            severity=Severity.parse(row.severity),
            subject=row.subject,
            kind=row.kind or "alert",
        )

        row.attempts += 1
        try:
            result = channel.send(message)
        except Exception as exc:  # noqa: BLE001 - a channel must not break the drain
            log.exception("Channel %s raised", channel.name)
            from app.monitoring.channels.base import DeliveryResult

            result = DeliveryResult.retry(f"channel raised {type(exc).__name__}: {exc}")

        if result.ok:
            row.status = "delivered"
            row.delivered_at = now
            row.last_error = None
            counts["delivered"] += 1
            _log_alert_event(session, row, "notified", result.detail, now)
            continue

        row.last_error = result.detail

        if not result.retryable or row.attempts >= config.notifications.max_attempts:
            row.status = "failed"
            counts["failed"] += 1
            log.error(
                "Notification %s permanently failed after %d attempt(s): %s",
                row.id,
                row.attempts,
                result.detail,
            )
            _log_alert_event(session, row, "notify_failed", result.detail, now)
        else:
            row.next_attempt_at = now + timedelta(
                seconds=_backoff_delay(row.attempts, config)
            )
            counts["retried"] += 1
            log.warning(
                "Notification %s attempt %d failed (%s), retrying at %s",
                row.id,
                row.attempts,
                result.detail,
                row.next_attempt_at,
            )

    return counts


def _log_alert_event(
    session: Session,
    row: NotificationOutbox,
    event_type: str,
    detail: str | None,
    now: datetime,
) -> None:
    """Mirror a delivery outcome onto the alert's audit trail."""
    if row.alert_ref is None:
        return
    session.add(
        AlertEvent(
            alert_id=row.alert_ref,
            event_type=event_type,
            occurred_at=now,
            detail=f"[{row.channel}] {detail or ''}".strip(),
        )
    )


def pending_count(session: Session) -> int:
    """Number of notifications still awaiting delivery."""
    return (
        session.query(NotificationOutbox)
        .filter(NotificationOutbox.status == "pending")
        .count()
    )


def notify_alerts(
    session: Session,
    notifications: list[AlertNotification],
    *,
    now: datetime | None = None,
    config: MonitoringConfig | None = None,
) -> int:
    """Render and queue every alert transition. Returns rows queued."""
    config = config or get_config()
    now = now or datetime.utcnow()
    channels = build_channels(config)

    queued = 0
    for notification in notifications:
        message = render_alert(notification, config)
        rows = enqueue(
            session,
            message,
            channels=channels,
            alert=notification.alert,
            # One notification per alert per transition, so a retry loop in the
            # scheduler cannot queue the same transition twice.
            dedupe_key=(
                f"{notification.alert.alert_id}:{notification.status}:"
                f"{notification.severity.label}:{int(now.timestamp()) // 60}"
            ),
            now=now,
            config=config,
        )
        queued += len(rows)

    return queued


__all__ = [
    "render_alert",
    "enqueue",
    "dispatch_pending",
    "notify_alerts",
    "pending_count",
    "in_quiet_hours",
    "humanize_duration",
    "local_time",
]
