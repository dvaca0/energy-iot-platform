"""Monitoring persistence model.

Six new tables, all prefixed so they can never collide with the operational
schema. **No existing table is modified.** The monitoring system reads
``nodes``, ``deployments``, ``energy_readings``, ``smart_plugs`` and
``smart_plug_readings``; it writes only to its own tables.

Timestamps follow the convention already established by ``app/db/models.py``:
naive ``datetime`` in UTC. Mixing timezone-aware values in would break every
comparison against ``EnergyReading.timestamp``, so localisation happens only at
presentation time.

Design note on heartbeats
-------------------------
A node heartbeat carries around fifty fields. Rather than fifty columns that
are half-null for any given firmware version, the fields the rule engine
actually evaluates are real columns (indexed, queryable, cheap), and the
complete payload is retained verbatim in ``raw_payload``. That keeps rules fast
while preserving everything for forensics and for the "what changed?" question,
and it lets a node send new fields before the server knows about them.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class NodeHeartbeat(Base):
    """One heartbeat received from a Raspberry Pi node.

    This is the health of the *node*, deliberately distinct from
    ``nodes.last_sync``, which the ingest endpoints also write. Keeping them
    separate is what makes "alive but not measuring" detectable: a node can be
    heartbeating normally while its sensor path is dead, and the platform could
    not previously tell those apart.
    """

    __tablename__ = "monitor_node_heartbeats"
    __table_args__ = (
        Index("ix_monitor_hb_node_received", "node_code", "received_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    #: Node code (N001...), not the database id: the node knows its code, and
    #: an unknown code must still be recordable so unregistered nodes can be
    #: reported as a security finding rather than dropped.
    node_code: Mapped[str] = mapped_column(String, index=True)
    node_id: Mapped[int | None] = mapped_column(ForeignKey("nodes.id"), nullable=True)

    #: When the server accepted the beat. Authoritative for liveness, because
    #: it cannot be affected by a node with a wrong clock.
    received_at: Mapped[datetime] = mapped_column(
        DateTime, index=True, default=datetime.utcnow
    )
    #: The node's own view of when it sent the beat. Compared against
    #: received_at to detect clock drift.
    reported_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    clock_drift_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Identity and versioning -------------------------------------------
    hostname: Mapped[str | None] = mapped_column(String, nullable=True)
    software_version: Mapped[str | None] = mapped_column(String, nullable=True)
    collector_version: Mapped[str | None] = mapped_column(String, nullable=True)
    config_version: Mapped[str | None] = mapped_column(String, nullable=True)
    git_commit: Mapped[str | None] = mapped_column(String, nullable=True)

    # --- Uptime ------------------------------------------------------------
    uptime_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    boot_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # --- Resources ---------------------------------------------------------
    cpu_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    cpu_temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    memory_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    swap_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    disk_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    disk_free_mb: Mapped[float | None] = mapped_column(Float, nullable=True)
    load_1: Mapped[float | None] = mapped_column(Float, nullable=True)
    load_5: Mapped[float | None] = mapped_column(Float, nullable=True)
    load_15: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: True when the root filesystem is mounted read-only, which on a Pi almost
    #: always means SD card failure and silently stops all buffering.
    filesystem_readonly: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # --- Raspberry Pi power health -----------------------------------------
    #: From `vcgencmd get_throttled`. Undervoltage corrupts SD cards and
    #: produces impossible ADC readings, so it explains sensor faults.
    undervoltage: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    throttled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    throttle_flags: Mapped[str | None] = mapped_column(String, nullable=True)

    # --- Network -----------------------------------------------------------
    ip_address: Mapped[str | None] = mapped_column(String, nullable=True)
    ethernet_up: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    wifi_up: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    wifi_ssid: Mapped[str | None] = mapped_column(String, nullable=True)
    wifi_signal_dbm: Mapped[float | None] = mapped_column(Float, nullable=True)
    access_point_active: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    tailscale_up: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    internet_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Local storage and sync queue --------------------------------------
    sqlite_size_mb: Mapped[float | None] = mapped_column(Float, nullable=True)
    sqlite_wal_mb: Mapped[float | None] = mapped_column(Float, nullable=True)
    buffered_readings: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pending_sync: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_measurement_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # --- Collector ---------------------------------------------------------
    collector_status: Mapped[str | None] = mapped_column(String, nullable=True)
    collector_pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    collector_restarts: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- Sensors -----------------------------------------------------------
    ads_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    gpio_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    spi_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    shelly_reachable: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shelly_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sensors_connected: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: Alerts the node raised locally, JSON list. A node can detect faults the
    #: server cannot see (a sensor that reads zero, a failed I2C probe).
    local_alerts: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Complete payload as received, for fields not modelled above.
    raw_payload: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Source address, used to detect a node reporting from an unexpected
    #: network and to correlate with the backend access log.
    source_ip: Mapped[str | None] = mapped_column(String, nullable=True)

    def payload(self) -> dict[str, Any]:
        """Decoded raw payload, or an empty dict if absent or malformed."""
        if not self.raw_payload:
            return {}
        try:
            return json.loads(self.raw_payload)
        except ValueError:
            return {}


class NodeHeartbeatLatest(Base):
    """Current heartbeat state per node, one row each.

    Denormalised on purpose. Every rule evaluation and every status report
    needs "the newest beat for each node"; against a growing history table that
    is a correlated subquery per node on every tick. Here it is a single scan
    of a table whose row count equals the fleet size.

    It also holds the miss-tracking state, which has nowhere else to live: the
    consecutive-miss counter must survive a monitoring restart, otherwise a
    restart would reset an escalating outage back to healthy.
    """

    __tablename__ = "monitor_node_heartbeat_latest"

    node_code: Mapped[str] = mapped_column(String, primary_key=True)
    node_id: Mapped[int | None] = mapped_column(ForeignKey("nodes.id"), nullable=True)

    heartbeat_id: Mapped[int | None] = mapped_column(
        ForeignKey("monitor_node_heartbeats.id"), nullable=True
    )
    received_at: Mapped[datetime | None] = mapped_column(DateTime, index=True, nullable=True)

    #: Consecutive expected-but-absent beats. Reset to 0 on any beat.
    missed_beats: Mapped[int] = mapped_column(Integer, default=0)
    #: When the node was last considered healthy, used to compute outage length.
    last_healthy_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: Set when an outage begins, cleared on recovery.
    offline_since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: Whether the node is currently considered online by the heartbeat monitor.
    online: Mapped[bool] = mapped_column(Boolean, default=False)
    #: True once the node has ever sent a heartbeat, so "never seen" can be
    #: distinguished from "was here and vanished".
    ever_seen: Mapped[bool] = mapped_column(Boolean, default=False)

    #: Snapshot of the last known good values, so a recovery message can report
    #: what the node looked like before it disappeared.
    last_buffered_readings: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_software_version: Mapped[str | None] = mapped_column(String, nullable=True)
    last_ip_address: Mapped[str | None] = mapped_column(String, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ServerHeartbeat(Base):
    """The server's own periodic health snapshot.

    Written every minute by the monitoring scheduler. Its absence is itself a
    signal: a gap in this table means monitoring was not running, which is how
    the system detects that it died while nobody was looking.
    """

    __tablename__ = "monitor_server_heartbeats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime, index=True, default=datetime.utcnow
    )

    cpu_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    memory_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    swap_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    disk_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    disk_free_gb: Mapped[float | None] = mapped_column(Float, nullable=True)
    load_1: Mapped[float | None] = mapped_column(Float, nullable=True)
    load_5: Mapped[float | None] = mapped_column(Float, nullable=True)
    load_15: Mapped[float | None] = mapped_column(Float, nullable=True)
    iowait_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    uptime_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    db_size_mb: Mapped[float | None] = mapped_column(Float, nullable=True)
    db_wal_mb: Mapped[float | None] = mapped_column(Float, nullable=True)
    db_query_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    api_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    api_latency_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    internet_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    dns_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    time_synchronized: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    reboot_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    #: Full probe output including anything without a dedicated column
    #: (service states, mounts, port list, package counts).
    raw_payload: Mapped[str | None] = mapped_column(Text, nullable=True)

    def payload(self) -> dict[str, Any]:
        """Decoded raw payload, or an empty dict if absent or malformed."""
        if not self.raw_payload:
            return {}
        try:
            return json.loads(self.raw_payload)
        except ValueError:
            return {}


class MonitorAlert(Base):
    """An alert, from first detection to resolution.

    One row per *problem*, not per notification. A problem that persists for
    three hours is a single row whose severity escalates and whose
    ``last_seen_at`` advances — this is what stops Telegram being flooded.

    The ``fingerprint`` is the deduplication key: a stable identifier for
    "this exact problem on this exact target". Two evaluations producing the
    same fingerprint update one row.
    """

    __tablename__ = "monitor_alerts"
    __table_args__ = (
        # At most one open alert per distinct problem. Resolved rows are
        # excluded from the constraint by including resolved_at, so history is
        # retained while a new occurrence can open a fresh row.
        UniqueConstraint("fingerprint", "resolved_at", name="uq_monitor_alert_open"),
        Index("ix_monitor_alerts_state", "status", "severity"),
        Index("ix_monitor_alerts_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    #: Human-facing unique identifier, e.g. ``ALT-20260726-4F2A``. Quoted in
    #: notifications so an operator can refer to an alert unambiguously.
    alert_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    #: Deduplication key. Stable for the lifetime of a problem.
    fingerprint: Mapped[str] = mapped_column(String, index=True)

    #: Identifier of the rule that raised it, e.g. ``node.heartbeat_lost``.
    rule_id: Mapped[str] = mapped_column(String, index=True)
    subsystem: Mapped[str] = mapped_column(String, index=True)

    severity: Mapped[str] = mapped_column(String, index=True)
    #: Severity at first detection, retained so escalation is visible.
    initial_severity: Mapped[str] = mapped_column(String)
    #: Highest severity ever reached.
    peak_severity: Mapped[str] = mapped_column(String)

    #: open | acknowledged | resolved
    status: Mapped[str] = mapped_column(String, default="open", index=True)

    title: Mapped[str] = mapped_column(String)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Where ------------------------------------------------------------
    node_code: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    node_id: Mapped[int | None] = mapped_column(ForeignKey("nodes.id"), nullable=True)
    campus: Mapped[str | None] = mapped_column(String, nullable=True)
    building: Mapped[str | None] = mapped_column(String, nullable=True)
    deployment: Mapped[str | None] = mapped_column(String, nullable=True)
    hostname: Mapped[str | None] = mapped_column(String, nullable=True)

    # --- What -------------------------------------------------------------
    metric: Mapped[str | None] = mapped_column(String, nullable=True)
    current_value: Mapped[str | None] = mapped_column(String, nullable=True)
    expected_value: Mapped[str | None] = mapped_column(String, nullable=True)

    # --- When -------------------------------------------------------------
    created_at: Mapped[datetime] = mapped_column(
        DateTime, index=True, default=datetime.utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String, nullable=True)
    #: NULL while open. Part of the uniqueness constraint above.
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: Seconds between created_at and resolved_at, denormalised for reporting.
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)

    #: When the last reminder for a long-running alert was sent.
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    notification_count: Mapped[int] = mapped_column(Integer, default=0)
    #: How many evaluations have seen this problem still present.
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)

    #: Diagnostic context: suggested causes, commands, related services and any
    #: rule-specific detail. JSON object.
    context: Mapped[str | None] = mapped_column(Text, nullable=True)

    def context_data(self) -> dict[str, Any]:
        """Decoded context, or an empty dict if absent or malformed."""
        if not self.context:
            return {}
        try:
            return json.loads(self.context)
        except ValueError:
            return {}


class AlertEvent(Base):
    """Append-only audit trail of everything that happened to an alert.

    Separate from ``monitor_alerts`` because that table holds current state and
    is updated in place. Answering "how long has this existed and what changed
    along the way?" requires the immutable sequence, not the latest snapshot.
    """

    __tablename__ = "monitor_alert_events"
    __table_args__ = (Index("ix_monitor_events_alert", "alert_id", "occurred_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("monitor_alerts.id"), index=True)

    #: created | escalated | de-escalated | reminded | acknowledged | resolved
    #: | notified | notify_failed
    event_type: Mapped[str] = mapped_column(String, index=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime, index=True, default=datetime.utcnow
    )

    from_severity: Mapped[str | None] = mapped_column(String, nullable=True)
    to_severity: Mapped[str | None] = mapped_column(String, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class NotificationOutbox(Base):
    """Durable queue of outbound notifications.

    Every notification is written here *before* any delivery attempt, and the
    row is only marked delivered once a channel confirms. If Telegram is
    unreachable, if the process is killed mid-send, or if the network is down,
    the message survives and is retried. Nothing is ever discarded silently —
    exhausted messages are marked ``failed`` and retained.
    """

    __tablename__ = "monitor_notification_outbox"
    __table_args__ = (
        Index("ix_monitor_outbox_pending", "status", "next_attempt_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    #: Channel name as registered in the dispatcher, e.g. ``telegram``.
    channel: Mapped[str] = mapped_column(String, index=True)
    #: Channel-specific destination. For Telegram, the chat id.
    recipient: Mapped[str | None] = mapped_column(String, nullable=True)

    #: pending | delivered | failed
    status: Mapped[str] = mapped_column(String, default="pending", index=True)
    severity: Mapped[str | None] = mapped_column(String, nullable=True)
    #: alert | report | selftest | recovery
    kind: Mapped[str] = mapped_column(String, default="alert")

    subject: Mapped[str | None] = mapped_column(String, nullable=True)
    body: Mapped[str] = mapped_column(Text)

    #: Link back to the alert, when the notification is about one.
    alert_ref: Mapped[int | None] = mapped_column(
        ForeignKey("monitor_alerts.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, index=True, default=datetime.utcnow
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Idempotency key. Prevents a retry storm from queueing duplicates of the
    #: same logical message.
    dedupe_key: Mapped[str | None] = mapped_column(String, index=True, nullable=True)


#: Every monitoring table, in dependency order. Used by
#: :func:`app.monitoring.storage.create_tables` to create exactly these and
#: nothing else — never a blanket ``Base.metadata.create_all()``, which would
#: also touch the operational schema.
MONITORING_TABLES = [
    NodeHeartbeat.__table__,
    NodeHeartbeatLatest.__table__,
    ServerHeartbeat.__table__,
    MonitorAlert.__table__,
    AlertEvent.__table__,
    NotificationOutbox.__table__,
]


__all__ = [
    "NodeHeartbeat",
    "NodeHeartbeatLatest",
    "ServerHeartbeat",
    "MonitorAlert",
    "AlertEvent",
    "NotificationOutbox",
    "MONITORING_TABLES",
]
