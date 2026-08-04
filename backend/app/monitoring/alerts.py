"""The alert lifecycle.

Turns the findings produced by the rule engine into durable alerts, and decides
when a human should be told. Four transitions exist:

``NEW``
    A fingerprint with no open alert. Row created, notification sent.
``ONGOING``
    Still present at the same severity. The row is updated; **no notification**.
    This is the mechanism that prevents Telegram flooding: a problem lasting
    six hours produces one message, not three hundred and sixty.
``ESCALATED``
    Severity increased, either because the rule says so or because the alert
    has been open long enough to cross a duration threshold. Notification sent.
``RESOLVED``
    The rule stopped emitting the finding. Row closed, recovery notification
    sent with the outage duration and, for nodes, an assessment of data loss.

Plus one timer: a long-running alert at terminal severity sends a periodic
reminder, so a week-long outage does not fall out of view after its first
message.

De-escalation is deliberately not notified. A CRITICAL that improves to WARNING
is still a problem; announcing the improvement and then announcing it again on
resolution would be noise. The severity is lowered on the row, and
``peak_severity`` preserves how bad it got.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.monitoring.config import MonitoringConfig, get_config
from app.monitoring.models import AlertEvent, MonitorAlert
from app.monitoring.rules import Finding
from app.monitoring.severity import (
    STATUS_ESCALATED,
    STATUS_NEW,
    STATUS_REMINDER,
    STATUS_RESOLVED,
    Severity,
)

log = logging.getLogger("monitoring.alerts")


@dataclass
class AlertNotification:
    """An alert transition that a human should be told about.

    Channel-agnostic on purpose: it carries the facts and the lifecycle state,
    and rendering happens in ``notifications.py``. A new channel therefore
    needs no changes here.
    """

    alert: MonitorAlert
    #: NEW | ESCALATED | RESOLVED | REMINDER
    status: str
    severity: Severity
    #: Extra facts computed at transition time (recovery details, escalation
    #: reason). Rendered under the main body.
    extra: dict[str, Any] = field(default_factory=dict)


def _new_alert_id(now: datetime) -> str:
    """Human-quotable unique id, e.g. ``ALT-20260726-9F3A``.

    Date-prefixed so an operator can tell at a glance how old an id is, with
    random suffix rather than a counter so generating one needs no lock and no
    round-trip.
    """
    return f"ALT-{now:%Y%m%d}-{secrets.token_hex(2).upper()}"


def _duration_severity(
    opened_at: datetime, now: datetime, config: MonitoringConfig
) -> Severity:
    """Severity implied purely by how long an alert has been open."""
    minutes = (now - opened_at).total_seconds() / 60.0
    escalation = config.escalation

    if minutes >= escalation.emergency_after_minutes:
        return Severity.EMERGENCY
    if minutes >= escalation.critical_after_minutes:
        return Severity.CRITICAL
    if minutes >= escalation.error_after_minutes:
        return Severity.ERROR
    if minutes >= escalation.warning_after_minutes:
        return Severity.WARNING
    return Severity.OK


def _record_event(
    session: Session,
    alert: MonitorAlert,
    event_type: str,
    *,
    from_severity: Severity | None = None,
    to_severity: Severity | None = None,
    detail: str | None = None,
    now: datetime | None = None,
) -> None:
    """Append to the immutable audit trail."""
    session.add(
        AlertEvent(
            alert_id=alert.id,
            event_type=event_type,
            occurred_at=now or datetime.utcnow(),
            from_severity=from_severity.label if from_severity else None,
            to_severity=to_severity.label if to_severity else None,
            detail=detail,
        )
    )


def _finding_context(finding: Finding) -> dict[str, Any]:
    """Diagnostic payload persisted on the alert row."""
    return {
        "summary": finding.summary,
        "suggested_causes": finding.suggested_causes,
        "suggested_commands": finding.suggested_commands,
        "suggested_actions": finding.suggested_actions,
        "related_services": finding.related_services,
        **finding.context,
    }


def _open_alerts(session: Session) -> dict[str, MonitorAlert]:
    """Every unresolved alert, keyed by fingerprint."""
    rows = (
        session.query(MonitorAlert)
        .filter(MonitorAlert.resolved_at.is_(None))
        .all()
    )
    return {row.fingerprint: row for row in rows}


def process_findings(
    session: Session,
    findings: list[Finding],
    *,
    now: datetime | None = None,
    config: MonitoringConfig | None = None,
) -> list[AlertNotification]:
    """Reconcile the current findings against the open alerts.

    Returns the transitions that warrant a notification. Does not send
    anything and does not commit: the caller owns both, so a delivery failure
    can never leave the alert state half-written.
    """
    import json

    config = config or get_config()
    now = now or datetime.utcnow()

    problems = [finding for finding in findings if finding.is_problem]
    by_fingerprint = {finding.fingerprint: finding for finding in problems}
    open_alerts = _open_alerts(session)

    notifications: list[AlertNotification] = []

    # --- Present problems: create, escalate, or quietly update ------------
    for fingerprint, finding in by_fingerprint.items():
        alert = open_alerts.get(fingerprint)

        sustain = (
            finding.sustain_seconds
            if finding.sustain_seconds is not None
            else config.policy.default_sustain_seconds
        )

        if alert is None:
            alert = MonitorAlert(
                alert_id=_new_alert_id(now),
                fingerprint=fingerprint,
                rule_id=finding.rule_id,
                subsystem=finding.subsystem,
                severity=finding.severity.label,
                initial_severity=finding.severity.label,
                peak_severity=finding.severity.label,
                status="open",
                title=finding.title,
                summary=finding.summary,
                node_code=finding.node_code,
                node_id=finding.node_id,
                campus=finding.campus,
                building=finding.building,
                deployment=finding.deployment,
                hostname=finding.hostname,
                metric=finding.metric,
                current_value=finding.current_value,
                expected_value=finding.expected_value,
                created_at=now,
                last_seen_at=now,
                occurrence_count=1,
                context=json.dumps(_finding_context(finding), ensure_ascii=False),
            )
            session.add(alert)
            session.flush()  # assign alert.id for the event row

            _record_event(
                session,
                alert,
                "created",
                to_severity=finding.severity,
                detail=finding.summary,
                now=now,
            )

            # The alert exists and is visible in the API and the report from
            # this moment. Notification waits until the condition has proved it
            # is not a transient, and report-only rules never notify at all.
            if finding.notify and sustain <= 0:
                mark_notified(alert, now)
                notifications.append(
                    AlertNotification(
                        alert=alert, status=STATUS_NEW, severity=finding.severity
                    )
                )
            continue

        # Existing alert: refresh the observed values regardless of transition,
        # so the alert always shows the *current* reading rather than the one
        # from when it opened.
        previous = Severity.parse(alert.severity)
        alert.last_seen_at = now
        alert.occurrence_count += 1
        alert.current_value = finding.current_value
        alert.expected_value = finding.expected_value
        alert.title = finding.title
        alert.summary = finding.summary
        alert.context = json.dumps(_finding_context(finding), ensure_ascii=False)

        # A pending alert that has now proved itself: this is its first
        # notification, so it goes out as NEW rather than as an escalation.
        if finding.notify and alert.notification_count == 0:
            if (now - alert.created_at).total_seconds() >= sustain:
                _record_event(
                    session,
                    alert,
                    "sustained",
                    to_severity=previous,
                    detail=f"condition held for {sustain}s",
                    now=now,
                )
                mark_notified(alert, now)
                notifications.append(
                    AlertNotification(
                        alert=alert, status=STATUS_NEW, severity=previous
                    )
                )
            continue

        # Never-notified alerts (report-only, or still inside their sustain
        # window) must not escalate or remind — there is no conversation to
        # escalate.
        if not finding.notify or alert.notification_count == 0:
            continue

        # The louder of what the rule says and what the duration implies,
        # capped where the rule declares the condition to be a persistent state
        # rather than an incident.
        by_duration = _duration_severity(alert.created_at, now, config)
        target = max(finding.severity, by_duration)
        if finding.max_severity is not None:
            target = min(target, finding.max_severity)

        if target > previous:
            alert.severity = target.label
            alert.escalated_at = now
            if target > Severity.parse(alert.peak_severity):
                alert.peak_severity = target.label

            reason = (
                "duration threshold reached"
                if by_duration > finding.severity
                else "underlying condition worsened"
            )
            _record_event(
                session,
                alert,
                "escalated",
                from_severity=previous,
                to_severity=target,
                detail=reason,
                now=now,
            )
            mark_notified(alert, now)
            notifications.append(
                AlertNotification(
                    alert=alert,
                    status=STATUS_ESCALATED,
                    severity=target,
                    extra={
                        "escalation_reason": reason,
                        "previous_severity": previous.label,
                        "open_for_seconds": (now - alert.created_at).total_seconds(),
                    },
                )
            )
            continue

        if target < previous:
            # Improved but not resolved. Recorded, not announced.
            alert.severity = target.label
            _record_event(
                session,
                alert,
                "de-escalated",
                from_severity=previous,
                to_severity=target,
                now=now,
            )
            continue

        # Unchanged. Send a reminder only if one is due.
        #
        # A capped finding is a persistent *state* (a node awaiting
        # commissioning, a node in standby), not an incident. Reminding about
        # it every hour for days is exactly the noise the cap exists to avoid;
        # the hourly status report already lists it among the open alerts.
        interval = config.escalation.reminder_every_minutes
        if finding.max_severity is not None and target >= finding.max_severity:
            interval = 0

        if interval > 0 and previous.is_actionable:
            last = alert.last_notified_at or alert.created_at
            if (now - last) >= timedelta(minutes=interval):
                _record_event(
                    session,
                    alert,
                    "reminded",
                    to_severity=previous,
                    detail=f"still open after {(now - alert.created_at).total_seconds() / 60:.0f} min",
                    now=now,
                )
                mark_notified(alert, now)
                notifications.append(
                    AlertNotification(
                        alert=alert,
                        status=STATUS_REMINDER,
                        severity=previous,
                        extra={
                            "open_for_seconds": (now - alert.created_at).total_seconds()
                        },
                    )
                )

    # --- Absent problems: resolve ----------------------------------------
    for fingerprint, alert in open_alerts.items():
        if fingerprint in by_fingerprint:
            continue

        # A deliberate lifecycle change closes its alerts immediately and says
        # why. Waiting out the hysteresis window would be wrong here: the
        # condition did not "go away", the operator declared that it is no
        # longer being watched, and an alert left hanging for fifteen minutes
        # after that invites the reader to go looking for a fault.
        lifecycle_reason = _lifecycle_closure_reason(session, alert)

        if lifecycle_reason is None:
            # Hysteresis. A value oscillating across its threshold would
            # otherwise produce an endless open/resolve stream — two messages
            # per cycle, and the single largest source of noise in the first
            # production run. The alert stays open until the condition has been
            # absent for a while.
            absent_for = (now - alert.last_seen_at).total_seconds()
            if absent_for < config.policy.resolve_after_seconds:
                continue

        severity = Severity.parse(alert.severity)
        alert.resolved_at = now
        alert.status = "resolved"
        alert.duration_seconds = (now - alert.created_at).total_seconds()

        extra: dict[str, Any] = {
            "duration_seconds": alert.duration_seconds,
            "peak_severity": alert.peak_severity,
            "occurrences": alert.occurrence_count,
        }
        if lifecycle_reason:
            extra["resolution_reason"] = lifecycle_reason

        # Node alerts get a recovery assessment: how long it was gone, what it
        # looks like now, and whether data was lost.
        if alert.node_code:
            extra.update(_node_recovery_extra(session, alert.node_code, config))

        _record_event(
            session,
            alert,
            "resolved",
            from_severity=severity,
            detail=(
                lifecycle_reason
                or f"resolved after {alert.duration_seconds:.0f}s"
            ),
            now=now,
        )

        # Only announce a recovery for something that was announced in the
        # first place. A report-only alert, or one that resolved inside its
        # sustain window, produced no message — so "✅ RESOLVED" would be the
        # first and only thing the reader ever saw about it.
        if alert.notification_count > 0:
            notifications.append(
                AlertNotification(
                    alert=alert,
                    status=STATUS_RESOLVED,
                    severity=severity,
                    extra=extra,
                )
            )

    return notifications



def _lifecycle_closure_reason(session: Session, alert: MonitorAlert) -> str | None:
    """Why this alert is being closed by a lifecycle change, if it is.

    Returns a sentence for the audit trail and the recovery message when the
    alert belongs to a node the platform has stopped monitoring, and ``None``
    when the alert is resolving for the ordinary reason (the condition went
    away). Distinguishing the two matters: "the fault cleared" and "we stopped
    watching" look identical in an alert list otherwise.
    """
    if not alert.node_code:
        return None

    try:
        from app.db import commissioning
        from app.db.models import Node

        node = session.query(Node).filter(Node.code == alert.node_code).first()
        if node is None:
            return None

        state = commissioning.get(session, node.commission_state)
        if state is None or state.is_monitored:
            return None

        return (
            f"node lifecycle changed to '{state.code}' "
            f"({state.label}); heartbeat no longer expected, "
            "so this condition is no longer monitored"
        )
    except Exception:  # noqa: BLE001 - never block a resolution on this
        log.exception("Could not determine lifecycle closure reason for %s", alert.node_code)
        return None


def _node_recovery_extra(
    session: Session, node_code: str, config: MonitoringConfig
) -> dict[str, Any]:
    """Recovery facts for a node alert, if the node reports heartbeats.

    Imported lazily and guarded: a failure to enrich a recovery message must
    never prevent the recovery message from being sent.
    """
    try:
        from app.monitoring.heartbeat import recovery_details
        from app.monitoring.models import NodeHeartbeat, NodeHeartbeatLatest

        latest = (
            session.query(NodeHeartbeatLatest)
            .filter(NodeHeartbeatLatest.node_code == node_code)
            .first()
        )
        if latest is None:
            return {}

        beat = (
            session.get(NodeHeartbeat, latest.heartbeat_id)
            if latest.heartbeat_id
            else None
        )
        return recovery_details(
            {"latest": latest, "heartbeat": beat, "offline_since": latest.offline_since},
            config,
        )
    except Exception:  # noqa: BLE001
        log.exception("Could not build recovery details for %s", node_code)
        return {}


def mark_notified(alert: MonitorAlert, now: datetime | None = None) -> None:
    """Record that this alert has been announced.

    Called by :func:`process_findings`, which is the component that decides to
    announce. It deliberately does **not** live in ``enqueue``: the alert
    engine reads this counter on the next tick to know whether a problem has
    already been reported, and making that depend on a later subsystem meant a
    deferred or suppressed delivery caused the alert to re-announce on every
    single tick.
    """
    alert.last_notified_at = now or datetime.utcnow()
    alert.notification_count += 1


def acknowledge(
    session: Session, alert_id: str, by: str | None = None, now: datetime | None = None
) -> MonitorAlert | None:
    """Acknowledge an open alert.

    An acknowledged alert stops sending reminders but stays open and keeps
    escalating if it worsens: acknowledgement means "I know", not "it is
    handled".
    """
    now = now or datetime.utcnow()
    alert = (
        session.query(MonitorAlert).filter(MonitorAlert.alert_id == alert_id).first()
    )
    if alert is None or alert.resolved_at is not None:
        return None

    alert.status = "acknowledged"
    alert.acknowledged_at = now
    alert.acknowledged_by = by
    # Push the reminder clock forward so acknowledgement actually silences it.
    alert.last_notified_at = now
    _record_event(session, alert, "acknowledged", detail=by, now=now)
    return alert


def open_alert_summary(session: Session) -> dict[str, int]:
    """Count of open alerts by severity, for the status report."""
    counts = {level.label: 0 for level in Severity if level is not Severity.OK}
    for alert in (
        session.query(MonitorAlert).filter(MonitorAlert.resolved_at.is_(None)).all()
    ):
        label = Severity.parse(alert.severity).label
        counts[label] = counts.get(label, 0) + 1
    return counts


__all__ = [
    "AlertNotification",
    "process_findings",
    "mark_notified",
    "acknowledge",
    "open_alert_summary",
]
