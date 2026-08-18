"""Node heartbeat ingestion, liveness tracking and node health rules.

Why heartbeats exist separately from measurements
-------------------------------------------------
Before this module, node liveness was inferred from ``nodes.last_sync``, a
single column written by *three* different endpoints. That conflates two
genuinely different questions:

* *Is the node alive?* — the machine boots, the collector runs, the network works.
* *Is the node measuring?* — the sensors respond and produce plausible values.

A node whose CT clamp fell off keeps syncing happily. A node whose collector
died stops syncing but the machine is fine. Treating both as one signal means
every failure looks identical and the first diagnostic question — *what
actually broke?* — cannot be answered from the alert.

Heartbeats are recorded with their own timestamp in their own table, so the two
signals are independent and their combination is diagnostic:

===================  ==================  ==========================================
Heartbeat            Measurements        Interpretation
===================  ==================  ==========================================
present              flowing             healthy
present              stale               sensor or collector fault — machine is fine
absent               flowing             clock or heartbeat agent fault (rare)
absent               stale               node or network is down
===================  ==================  ==========================================

Missed-beat accounting
----------------------
``received_at`` is the server's clock, never the node's: a node with a wrong
clock must not be able to make itself look alive. Miss counting is derived from
elapsed time rather than incremented per tick, so it is correct regardless of
how often the scheduler runs and survives a monitoring restart without
resetting an escalating outage.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import Deployment, EnergyReading, Node
from app.monitoring.config import MonitoringConfig
from app.monitoring.lifecycle import policy_for
from app.monitoring.models import NodeHeartbeat, NodeHeartbeatLatest
from app.monitoring.rules import Finding, RuleContext, Subsystem, rule
from app.monitoring.severity import Severity

log = logging.getLogger("monitoring.heartbeat")


# --------------------------------------------------------------------------
# Wire format
# --------------------------------------------------------------------------


class HeartbeatPayload(BaseModel):
    """Health report sent by a node.

    **Every field except ``node_id`` is optional, by design.** The fleet is
    upgraded one Pi at a time and the existing collectors already post a
    minimal ``{"node_id": "..."}`` body to ``/api/edge/heartbeat``. Making any
    health field mandatory would reject those nodes and turn a monitoring
    rollout into an outage. Missing fields are recorded as unknown and the
    rules that need them simply do not fire.

    Unknown extra fields are accepted and preserved in ``raw_payload``, so a
    node running newer firmware than the server can send new telemetry without
    a coordinated deployment.
    """

    model_config = {"extra": "allow"}

    #: Node code as registered in the platform (N001, N002...).
    node_id: str

    #: The node's own clock at send time, ISO 8601. Used only for drift.
    timestamp: str | None = None

    hostname: str | None = None
    software_version: str | None = None
    collector_version: str | None = None
    config_version: str | None = None
    git_commit: str | None = None

    uptime_seconds: float | None = None
    boot_time: str | None = None

    cpu_percent: float | None = None
    cpu_temperature_c: float | None = None
    memory_percent: float | None = None
    swap_percent: float | None = None
    disk_percent: float | None = None
    disk_free_mb: float | None = None
    load_1: float | None = None
    load_5: float | None = None
    load_15: float | None = None
    filesystem_readonly: bool | None = None

    undervoltage: bool | None = None
    throttled: bool | None = None
    throttle_flags: str | None = None

    ip_address: str | None = None
    ethernet_up: bool | None = None
    wifi_up: bool | None = None
    wifi_ssid: str | None = None
    wifi_signal_dbm: float | None = None
    access_point_active: bool | None = None
    tailscale_up: bool | None = None
    internet_ok: bool | None = None
    latency_ms: float | None = None

    sqlite_size_mb: float | None = None
    sqlite_wal_mb: float | None = None
    buffered_readings: int | None = None
    pending_sync: int | None = None
    last_sync_at: str | None = None
    last_measurement_at: str | None = None

    collector_status: str | None = None
    collector_pid: int | None = None
    collector_restarts: int | None = None

    ads_ok: bool | None = None
    gpio_ok: bool | None = None
    spi_ok: bool | None = None
    shelly_reachable: int | None = None
    #: The MEASURING DEVICE's internal temperature (Shelly.GetStatus
    #: "temperature:0".tC), distinct from cpu_temperature_c which is the Pi's.
    #: Optional: a node whose collector does not publish it leaves it NULL, and
    #: NULL renders as "no disponible" rather than as a fault.
    meter_temperature_c: float | None = None
    shelly_total: int | None = None
    sensors_connected: int | None = None

    local_alerts: list[str] = Field(default_factory=list)


def _parse_dt(value: str | None) -> datetime | None:
    """Parse an ISO timestamp into naive UTC, tolerating offsets and ``Z``.

    The whole schema stores naive UTC. An aware value is converted; a malformed
    value yields ``None`` rather than raising, because a node with a broken
    clock must still be able to report that it is alive.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def record_heartbeat(
    session: Session,
    payload: HeartbeatPayload,
    *,
    source_ip: str | None = None,
    auth_subject: str | None = None,
    auth_status: str | None = None,
    now: datetime | None = None,
) -> NodeHeartbeat:
    """Persist one heartbeat and refresh the node's liveness state.

    Accepts heartbeats from node codes that are not registered in ``nodes``:
    an unknown node is a security finding, and dropping it would remove the
    only evidence. ``node_id`` is left NULL in that case.

    Does not commit — the caller owns the transaction.
    """
    now = now or datetime.utcnow()

    node = session.query(Node).filter(Node.code == payload.node_id).first()
    reported_at = _parse_dt(payload.timestamp)

    drift: float | None = None
    if reported_at is not None:
        drift = round((reported_at - now).total_seconds(), 2)

    raw = payload.model_dump(mode="json")

    beat = NodeHeartbeat(
        node_code=payload.node_id,
        node_id=node.id if node else None,
        received_at=now,
        reported_at=reported_at,
        clock_drift_seconds=drift,
        hostname=payload.hostname,
        software_version=payload.software_version,
        collector_version=payload.collector_version,
        config_version=payload.config_version,
        git_commit=payload.git_commit,
        uptime_seconds=payload.uptime_seconds,
        boot_time=_parse_dt(payload.boot_time),
        cpu_percent=payload.cpu_percent,
        cpu_temperature_c=payload.cpu_temperature_c,
        memory_percent=payload.memory_percent,
        swap_percent=payload.swap_percent,
        disk_percent=payload.disk_percent,
        disk_free_mb=payload.disk_free_mb,
        load_1=payload.load_1,
        load_5=payload.load_5,
        load_15=payload.load_15,
        filesystem_readonly=payload.filesystem_readonly,
        undervoltage=payload.undervoltage,
        throttled=payload.throttled,
        throttle_flags=payload.throttle_flags,
        ip_address=payload.ip_address,
        ethernet_up=payload.ethernet_up,
        wifi_up=payload.wifi_up,
        wifi_ssid=payload.wifi_ssid,
        wifi_signal_dbm=payload.wifi_signal_dbm,
        access_point_active=payload.access_point_active,
        tailscale_up=payload.tailscale_up,
        internet_ok=payload.internet_ok,
        latency_ms=payload.latency_ms,
        sqlite_size_mb=payload.sqlite_size_mb,
        sqlite_wal_mb=payload.sqlite_wal_mb,
        buffered_readings=payload.buffered_readings,
        pending_sync=payload.pending_sync,
        last_sync_at=_parse_dt(payload.last_sync_at),
        last_measurement_at=_parse_dt(payload.last_measurement_at),
        collector_status=payload.collector_status,
        collector_pid=payload.collector_pid,
        collector_restarts=payload.collector_restarts,
        ads_ok=payload.ads_ok,
        gpio_ok=payload.gpio_ok,
        spi_ok=payload.spi_ok,
        shelly_reachable=payload.shelly_reachable,
        meter_temperature_c=payload.meter_temperature_c,
        shelly_total=payload.shelly_total,
        sensors_connected=payload.sensors_connected,
        local_alerts=json.dumps(payload.local_alerts) if payload.local_alerts else None,
        raw_payload=json.dumps(raw, ensure_ascii=False),
        source_ip=source_ip,
        auth_subject=auth_subject,
        auth_status=auth_status,
    )
    session.add(beat)
    session.flush()  # assign beat.id for the latest-state reference

    latest = (
        session.query(NodeHeartbeatLatest)
        .filter(NodeHeartbeatLatest.node_code == payload.node_id)
        .first()
    )
    if latest is None:
        latest = NodeHeartbeatLatest(node_code=payload.node_id)
        session.add(latest)

    if node is not None:
        # Liveness is a property of *contact*, not of a successful upload.
        #
        # `nodes.last_sync` is what every API caller means by "online"
        # (`nodes.is_node_online`, `dashboard.online_nodes`, `metrics/live`,
        # `infra`, `deployments.node_online`). Until now only three routes wrote
        # it: the two ingest paths — both behind `authorize()`, so a node that
        # may not upload can never refresh it — and the unauthenticated legacy
        # `/api/edge/heartbeat`.
        #
        # That made "alive" reachable only by uploading or by an unauthenticated
        # side door. N001/N002 took the side door and looked online while every
        # reading they sent was refused; N003 had neither and looked dead while
        # sampling every 15 seconds. Refreshing liveness from the canonical
        # authenticated heartbeat decouples the two, so the four states stay
        # independent: alive / authorized to upload / measuring / deployed.
        #
        # Writing it here is gated by the same admission decision as the beat
        # itself (`node_auth.enforcement_applies_to`, applied in the router
        # before this is reached), so an unauthenticated node cannot refresh its
        # own liveness under enforcement.
        node.last_sync = now

    latest.node_id = node.id if node else None
    latest.heartbeat_id = beat.id
    latest.received_at = now
    latest.missed_beats = 0
    latest.last_healthy_at = now
    latest.offline_since = None
    latest.online = True
    latest.ever_seen = True
    latest.updated_at = now

    if payload.buffered_readings is not None:
        latest.last_buffered_readings = payload.buffered_readings
    if payload.software_version:
        latest.last_software_version = payload.software_version
    if payload.ip_address:
        latest.last_ip_address = payload.ip_address

    return beat


# --------------------------------------------------------------------------
# Liveness state
# --------------------------------------------------------------------------


def _missed_beats(age_seconds: float, config: MonitoringConfig) -> int:
    """Number of expected heartbeats that did not arrive.

    Derived from elapsed time rather than counted per tick, so the value does
    not depend on scheduler cadence and is unaffected by a monitoring restart.
    Within the grace window the node is merely late, not missing.
    """
    interval = max(1, config.heartbeat.interval_seconds)
    grace = interval * config.heartbeat.grace_multiplier
    if age_seconds <= grace:
        return 0
    return int(age_seconds // interval)


def _severity_for_misses(missed: int, config: MonitoringConfig) -> Severity:
    """Map a missed-beat count onto the configured escalation ladder."""
    heartbeat = config.heartbeat
    if missed >= heartbeat.missed_emergency:
        return Severity.EMERGENCY
    if missed >= heartbeat.missed_critical:
        return Severity.CRITICAL
    if missed >= heartbeat.missed_error:
        return Severity.ERROR
    if missed >= heartbeat.missed_warning:
        return Severity.WARNING
    return Severity.OK


def collect_node_state(
    session: Session, config: MonitoringConfig, now: datetime
) -> dict[str, dict[str, Any]]:
    """Build the per-node view used by every node rule.

    Combines three sources: the registered node row, its newest heartbeat, and
    its newest stored measurement. Also updates the persisted miss counter, so
    the state survives restarts.

    Nodes are keyed by code. A node that has never sent a heartbeat is included
    with ``ever_seen`` false, so "never reported" is distinguishable from
    "stopped reporting" — the two need different alerts and different advice.
    """
    state: dict[str, dict[str, Any]] = {}

    nodes = session.query(Node).all()
    latest_rows = {row.node_code: row for row in session.query(NodeHeartbeatLatest).all()}

    # Newest measurement per node: one grouped aggregate rather than a
    # correlated subquery per node on every tick.
    newest_reading: dict[int, datetime] = {}
    for node_id, newest in (
        session.query(EnergyReading.node_id, func.max(EnergyReading.timestamp))
        .group_by(EnergyReading.node_id)
        .all()
    ):
        if newest is not None:
            newest_reading[node_id] = newest

    # Deployment context for the "where" block of an alert.
    #
    # The deployment a node is CURRENTLY on — activated and not yet closed —
    # not merely its newest row. An alert that named the building from a
    # finished campaign was telling the operator to check a panel the node had
    # already left.
    deployments: dict[int, Deployment] = {}
    for deployment in session.query(Deployment).all():
        if deployment.activated_at is not None and deployment.closed_at is None:
            deployments[deployment.node_id] = deployment

    known_codes = set()

    for node in nodes:
        known_codes.add(node.code)
        latest = latest_rows.get(node.code)
        beat: NodeHeartbeat | None = None
        if latest is not None and latest.heartbeat_id:
            beat = session.get(NodeHeartbeat, latest.heartbeat_id)

        age = None
        missed = 0
        if latest is not None and latest.received_at is not None:
            age = (now - latest.received_at).total_seconds()
            missed = _missed_beats(age, config)

            # Persist the derived counter and the outage start.
            if missed != latest.missed_beats:
                latest.missed_beats = missed
            if missed > 0 and latest.offline_since is None:
                latest.offline_since = latest.received_at
            if missed == 0:
                latest.offline_since = None
            latest.online = missed == 0
            latest.updated_at = now

        deployment = deployments.get(node.id)
        building = deployment.building if deployment else None
        campus = building.campus if building else None

        reading_at = newest_reading.get(node.id)

        state[node.code] = {
            "node": node,
            "node_id": node.id,
            "code": node.code,
            "name": node.name,
            "latest": latest,
            "heartbeat": beat,
            "heartbeat_age_seconds": age,
            "missed_beats": missed,
            "ever_seen": bool(latest and latest.ever_seen),
            "offline_since": latest.offline_since if latest else None,
            "last_sync": node.last_sync,
            "buffer_pending": node.buffer_pending,
            "samples": node.samples,
            "deployment": deployment,
            "deployment_label": (
                f"{deployment.start_date} → {deployment.end_date} ({deployment.status})"
                if deployment
                else None
            ),
            "deployment_status": deployment.status if deployment else None,
            "building": building.name if building else None,
            "campus": campus.name if campus else None,
            "last_reading_at": reading_at,
            "reading_age_seconds": ((now - reading_at).total_seconds() if reading_at else None),
        }

    # Heartbeats from codes that are not registered nodes: kept so the security
    # rule can report them rather than losing the evidence.
    for code, latest in latest_rows.items():
        if code in known_codes:
            continue
        state[code] = {
            "node": None,
            "node_id": None,
            "code": code,
            "name": None,
            "latest": latest,
            "heartbeat": (
                session.get(NodeHeartbeat, latest.heartbeat_id) if latest.heartbeat_id else None
            ),
            "heartbeat_age_seconds": (
                (now - latest.received_at).total_seconds() if latest.received_at else None
            ),
            "missed_beats": 0,
            "ever_seen": bool(latest.ever_seen),
            "unregistered": True,
        }

    return state


def recovery_details(state: dict[str, Any], config: MonitoringConfig) -> dict[str, Any]:
    """Facts for a heartbeat-recovery message.

    Answers the questions a recovery notification must answer: how long was it
    gone, what does it look like now, is there data waiting to upload, and was
    anything lost.

    Data loss is reported as an *assessment*, not a certainty: the server can
    see that measurements are missing for the outage window, but only the node
    knows whether its local buffer still holds them. When the node reports a
    buffer, the honest answer is "buffered, replay expected".
    """
    beat: NodeHeartbeat | None = state.get("heartbeat")
    latest: NodeHeartbeatLatest | None = state.get("latest")

    details: dict[str, Any] = {}

    offline_since = state.get("offline_since") or (latest.offline_since if latest else None)
    if offline_since and latest and latest.received_at:
        outage = (latest.received_at - offline_since).total_seconds()
        details["offline_seconds"] = max(0.0, outage)

    if beat is not None:
        details["current_health"] = {
            "cpu_percent": beat.cpu_percent,
            "memory_percent": beat.memory_percent,
            "disk_percent": beat.disk_percent,
            "temperature_c": beat.cpu_temperature_c,
            "uptime_seconds": beat.uptime_seconds,
            "collector_status": beat.collector_status,
        }
        details["buffered_readings"] = beat.buffered_readings
        details["pending_sync"] = beat.pending_sync

        # A node whose uptime is shorter than the outage rebooted during it,
        # which is the most likely explanation and worth stating.
        outage = details.get("offline_seconds")
        if beat.uptime_seconds is not None and outage:
            if beat.uptime_seconds < outage:
                details["estimated_cause"] = (
                    "node rebooted during the outage "
                    f"(uptime {int(beat.uptime_seconds)}s < outage {int(outage)}s)"
                )
            else:
                details["estimated_cause"] = (
                    "node stayed up; the interruption was network or backend side"
                )

        buffered = beat.buffered_readings or 0
        if buffered > 0:
            details["data_loss"] = f"no loss expected — {buffered} readings buffered for replay"
        elif details.get("offline_seconds"):
            details["data_loss"] = "possible gap — node reports an empty buffer"

    return details


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------


def _node_location(state: dict[str, Any]) -> dict[str, Any]:
    """Location fields shared by every node finding."""
    beat: NodeHeartbeat | None = state.get("heartbeat")
    return {
        "node_code": state.get("code"),
        "node_id": state.get("node_id"),
        "campus": state.get("campus"),
        "building": state.get("building"),
        "deployment": state.get("deployment_label"),
        "hostname": beat.hostname if beat else None,
    }


_NODE_COMMANDS = [
    "systemctl status energy-collector",
    "journalctl -u energy-collector -n 100 --no-pager",
    "ping -c3 <backend-host>",
    "vcgencmd get_throttled",
]


@rule("node.heartbeat", Subsystem.NODE, "Node heartbeat liveness")
def check_heartbeat(ctx: RuleContext) -> Iterable[Finding]:
    """Missed heartbeats, escalating on the configured ladder."""
    findings: list[Finding] = []

    for code, state in ctx.nodes.items():
        if state.get("unregistered"):
            continue

        # A node is only expected to be online while it is deployed or being
        # commissioned. A node in standby, under maintenance, retired, or
        # simply switched off must not page anyone for being switched off —
        # this rule alone produced 64 messages about a node the operator had
        # deliberately powered down.
        if not policy_for(state).heartbeat:
            continue

        latest = state.get("latest")

        # A node that has never reported is a deployment gap, not an outage.
        if not state.get("ever_seen"):
            findings.append(
                Finding(
                    rule_id="node.heartbeat_never",
                    subsystem=Subsystem.NODE,
                    severity=Severity.WARNING,
                    title=f"Node {code} has never sent a heartbeat",
                    target=code,
                    summary=(
                        "The node is registered in the platform but the heartbeat agent "
                        "has never reported. Either it is not installed, or it cannot "
                        "reach the backend."
                    ),
                    metric="heartbeat",
                    current_value="never received",
                    expected_value=f"every {ctx.config.heartbeat.interval_seconds}s",
                    suggested_causes=[
                        "Heartbeat agent not installed on this node",
                        "Wrong backend URL or node code in the agent configuration",
                        "Node has never been commissioned",
                    ],
                    suggested_commands=[
                        "systemctl status energy-node-heartbeat",
                        "journalctl -u energy-node-heartbeat -n 50 --no-pager",
                    ],
                    suggested_actions=[
                        "Install or configure the heartbeat agent on this node.",
                    ],
                    # A node awaiting commissioning stays this way for days.
                    # Escalating it to EMERGENCY on a timer would devalue the
                    # level for real outages.
                    max_severity=Severity.WARNING,
                    **_node_location(state),
                )
            )
            continue

        missed = state.get("missed_beats") or 0
        severity = _severity_for_misses(missed, ctx.config)
        if severity is Severity.OK:
            continue

        age = state.get("heartbeat_age_seconds") or 0
        last_seen = latest.received_at if latest else None

        # Measurements still arriving while heartbeats stopped points at the
        # agent rather than the node, and that changes what to check first.
        reading_age = state.get("reading_age_seconds")
        still_measuring = reading_age is not None and reading_age < age

        causes = (
            [
                "Heartbeat agent stopped while the collector kept running",
                "Agent crashed or was disabled",
            ]
            if still_measuring
            else [
                "Node powered off or rebooting",
                "Network or WiFi association lost",
                "Upstream campus link down",
                "Collector host wedged",
            ]
        )

        findings.append(
            Finding(
                rule_id="node.heartbeat_lost",
                # Pages only while a campaign is running. A commissioned node
                # with no deployment that goes quiet is idle equipment being
                # switched off, which belongs in the report, not on a phone.
                notify=policy_for(state).heartbeat_pages,
                subsystem=Subsystem.NODE,
                severity=severity,
                title=f"Node {code} heartbeat lost",
                target=code,
                summary=(
                    f"{missed} consecutive heartbeats missed. "
                    + (
                        "Measurements are still arriving, so the machine is alive and "
                        "only the heartbeat agent is affected."
                        if still_measuring
                        else "No measurements either — the node or its network is down."
                    )
                ),
                metric="heartbeat_age_seconds",
                current_value=f"{int(age)}s ago ({missed} missed)",
                expected_value=f"every {ctx.config.heartbeat.interval_seconds}s",
                suggested_causes=causes,
                suggested_commands=_NODE_COMMANDS,
                suggested_actions=[
                    "Confirm power and network first; the node buffers locally, so a "
                    "short outage should replay without data loss.",
                ],
                context={
                    "missed_beats": missed,
                    "last_heartbeat": last_seen.isoformat() if last_seen else None,
                    "still_measuring": still_measuring,
                    "last_buffered_readings": latest.last_buffered_readings if latest else None,
                },
                **_node_location(state),
            )
        )

    return findings


@rule("node.resources", Subsystem.NODE, "Node CPU, memory, disk and temperature")
def check_node_resources(ctx: RuleContext) -> Iterable[Finding]:
    findings: list[Finding] = []
    thresholds = ctx.config.node

    for code, state in ctx.nodes.items():
        beat: NodeHeartbeat | None = state.get("heartbeat")
        # Stale telemetry describes the past, not the present; the heartbeat
        # rule already owns that problem.
        if beat is None or (state.get("missed_beats") or 0) > 0:
            continue
        if not policy_for(state).node_hardware:
            continue

        location = _node_location(state)

        for metric, value, warn, crit, label, unit in (
            (
                "cpu_percent",
                beat.cpu_percent,
                thresholds.cpu_warning,
                thresholds.cpu_critical,
                "CPU",
                "%",
            ),
            (
                "memory_percent",
                beat.memory_percent,
                thresholds.memory_warning,
                thresholds.memory_critical,
                "memory",
                "%",
            ),
            (
                "disk_percent",
                beat.disk_percent,
                thresholds.disk_warning,
                thresholds.disk_critical,
                "disk",
                "%",
            ),
            (
                "cpu_temperature_c",
                beat.cpu_temperature_c,
                thresholds.temperature_warning_c,
                thresholds.temperature_critical_c,
                "temperature",
                " °C",
            ),
        ):
            severity = ctx.threshold_severity(value, warn, crit)
            if severity is Severity.OK:
                continue

            findings.append(
                Finding(
                    rule_id=f"node.{metric}",
                    subsystem=Subsystem.NODE,
                    severity=severity,
                    title=f"Node {code} {label} is high",
                    target=code,
                    metric=metric,
                    current_value=f"{value:.1f}{unit}",
                    expected_value=f"< {warn:.0f}{unit}",
                    suggested_commands=["top -b -n1 | head -15", "df -h", "vcgencmd measure_temp"],
                    suggested_actions=[
                        (
                            "A Raspberry Pi throttles above 80 °C and can produce unstable "
                            "ADC readings when hot."
                            if metric == "cpu_temperature_c"
                            else "Sustained pressure here eventually stops local buffering."
                        )
                    ],
                    **location,
                )
            )

    return findings


@rule("node.power", Subsystem.NODE, "Undervoltage and CPU throttling")
def check_node_power(ctx: RuleContext) -> Iterable[Finding]:
    """Raspberry Pi power-supply health.

    Undervoltage is the single most common cause of inexplicable Pi behaviour:
    it corrupts SD cards, destabilises the ADC and produces impossible
    electrical readings. Surfacing it explains a whole class of downstream
    symptoms that otherwise look like sensor faults.
    """
    findings: list[Finding] = []

    for code, state in ctx.nodes.items():
        beat: NodeHeartbeat | None = state.get("heartbeat")
        if beat is None or (state.get("missed_beats") or 0) > 0:
            continue
        if not policy_for(state).node_hardware:
            continue

        location = _node_location(state)

        if beat.undervoltage:
            findings.append(
                Finding(
                    rule_id="node.undervoltage",
                    subsystem=Subsystem.NODE,
                    severity=Severity.ERROR,
                    title=f"Node {code} reports undervoltage",
                    target=code,
                    summary=(
                        "The Pi's power supply is dropping below spec. This corrupts SD "
                        "cards over time and can make ADC readings unreliable."
                    ),
                    metric="undervoltage",
                    current_value="detected",
                    expected_value="none",
                    suggested_causes=[
                        "Underpowered or failing PSU",
                        "Thin or long USB cable",
                        "Too much drawn from the Pi's own 5V rail",
                    ],
                    suggested_commands=["vcgencmd get_throttled", "dmesg | grep -i voltage"],
                    suggested_actions=[
                        "Replace the supply before trusting any electrical reading from "
                        "this node.",
                    ],
                    context={"throttle_flags": beat.throttle_flags},
                    **location,
                )
            )

        if beat.throttled and not beat.undervoltage:
            findings.append(
                Finding(
                    rule_id="node.throttled",
                    subsystem=Subsystem.NODE,
                    severity=Severity.WARNING,
                    title=f"Node {code} CPU is being throttled",
                    target=code,
                    metric="throttled",
                    current_value=beat.throttle_flags or "throttled",
                    expected_value="not throttled",
                    suggested_causes=["Thermal limit reached", "Sustained undervoltage"],
                    suggested_commands=["vcgencmd get_throttled", "vcgencmd measure_temp"],
                    suggested_actions=["Improve cooling or reduce load; sampling may lag."],
                    **location,
                )
            )

        # --- Read-only filesystem, tri-state and corroborated -------------
        #
        # `filesystem_readonly` is deliberately tri-state:
        #   True  -> confirmed read-only        False -> confirmed read-write
        #   None  -> unknown; the probe could not answer, which is not a fault
        #
        # A True on its own is not sufficient evidence. On 2026-08-06 this rule
        # paged 43 times because the node's probe read `/` from inside the
        # collector's own systemd mount namespace (`ProtectSystem=strict`),
        # where `/` genuinely is `ro` by design. The storage was healthy: writes
        # succeeded, SQLite committed, 0 remount-ro events, `tune2fs` clean.
        #
        # So the claim is cross-examined against the same heartbeat. A
        # filesystem that cannot be written to cannot simultaneously accept
        # buffered rows and grow its database, and a collector cannot stay
        # active while every write fails. When the payload contradicts itself
        # the honest report is "contradictory telemetry", not "the SD card
        # failed" — a claim this rule has no evidence for and must not make.
        if beat.filesystem_readonly is True:
            contradictions = []
            if beat.collector_status in ("active", "running", "ok"):
                contradictions.append(f"collector is {beat.collector_status}")
            if beat.sqlite_size_mb:
                contradictions.append(f"local database is {beat.sqlite_size_mb} MB")
            if beat.disk_free_mb:
                contradictions.append(f"{beat.disk_free_mb:.0f} MB reported free")
            if state.get("reading_age_seconds") is not None and (
                state["reading_age_seconds"] < 600
            ):
                contradictions.append("measurements still arriving")

            if contradictions:
                findings.append(
                    Finding(
                        rule_id="node.filesystem_readonly_contradiction",
                        subsystem=Subsystem.NODE,
                        severity=Severity.WARNING,
                        title=f"Node {code} reports read-only but is writing",
                        target=code,
                        summary=(
                            "The node claims its filesystem is read-only while the same "
                            "heartbeat shows it writing: "
                            + "; ".join(contradictions)
                            + ". This is a probe fault, not a storage fault. The usual "
                            "cause is reading /proc/mounts from inside a hardened "
                            "systemd mount namespace (ProtectSystem=strict), where / "
                            "really is ro for that service while the disk is fine."
                        ),
                        metric="filesystem_readonly",
                        current_value="True (contradicted by same payload)",
                        expected_value="agreement between the probe and observed writes",
                        # A probe defect is not an incident; it must not page or
                        # climb the ladder on a timer.
                        max_severity=Severity.WARNING,
                        suggested_causes=[
                            "Probe reads / from inside a service mount namespace",
                            "Probe measures the wrong path for this service",
                        ],
                        suggested_commands=[
                            "systemctl show energy-node-collector -p ProtectSystem -p ReadWritePaths",
                            "awk '$2==\"/\" {print $4}' /proc/$(systemctl show energy-node-collector -p MainPID --value)/mounts",
                            "awk '$2==\"/\" {print $4}' /proc/mounts",
                        ],
                        suggested_actions=[
                            "Probe the path the service actually writes to "
                            "(its ReadWritePaths/StateDirectory), not /.",
                        ],
                        context={"contradictions": contradictions},
                        **location,
                    )
                )
            else:
                findings.append(
                    Finding(
                        rule_id="node.filesystem_readonly",
                        subsystem=Subsystem.NODE,
                        severity=Severity.CRITICAL,
                        title=f"Node {code} filesystem is read-only",
                        target=code,
                        summary=(
                            "The node reports a read-only filesystem and nothing in the "
                            "same heartbeat contradicts it. Local buffering cannot "
                            "persist while this is true."
                        ),
                        metric="filesystem_readonly",
                        current_value="read-only (uncontradicted)",
                        expected_value="read-write",
                        # Genuine data-integrity risk: no sustain window.
                        sustain_seconds=0,
                        suggested_causes=[
                            "Kernel remounted read-only after an I/O error",
                            "Storage or SD card fault",
                            "Probe measuring a path that is legitimately read-only",
                        ],
                        # Deliberately NOT asserting SD-card failure. That claim
                        # requires ext4 / I/O / mmc / remount-ro evidence, none
                        # of which this rule can see from a heartbeat.
                        suggested_commands=[
                            "awk '$2==\"/\" {print $4}' /proc/mounts",
                            "dmesg -T | grep -iE 'ext4|I/O error|mmc|remount'",
                            "tune2fs -l $(findmnt -no SOURCE /) | grep -i 'state\\|error'",
                        ],
                        suggested_actions=[
                            "Confirm on the device before replacing hardware: check "
                            "/proc/mounts, dmesg for ext4/mmc errors, and whether a "
                            "write actually fails. Only conclude SD-card failure if "
                            "that evidence exists.",
                        ],
                        **location,
                    )
                )

    return findings


@rule("node.storage", Subsystem.NODE, "Node local buffer and SQLite size")
def check_node_storage(ctx: RuleContext) -> Iterable[Finding]:
    findings: list[Finding] = []
    thresholds = ctx.config.node

    for code, state in ctx.nodes.items():
        beat: NodeHeartbeat | None = state.get("heartbeat")
        if beat is None or (state.get("missed_beats") or 0) > 0:
            continue
        if not policy_for(state).node_hardware:
            continue

        location = _node_location(state)

        buffered = beat.buffered_readings
        if buffered is not None:
            severity = ctx.threshold_severity(
                buffered, thresholds.buffer_warning, thresholds.buffer_critical
            )
            if severity is not Severity.OK:
                findings.append(
                    Finding(
                        rule_id="node.buffer",
                        subsystem=Subsystem.NODE,
                        severity=severity,
                        title=f"Node {code} has a large unsent buffer",
                        target=code,
                        summary=(
                            "The node is collecting but not delivering. Data is safe for "
                            "now, but the buffer is bounded."
                        ),
                        metric="buffered_readings",
                        current_value=str(buffered),
                        expected_value=f"< {thresholds.buffer_warning}",
                        suggested_causes=[
                            "Backend unreachable from this node",
                            "Ingest endpoint rejecting the payload",
                            "Node has no active deployment, so readings are refused",
                        ],
                        suggested_commands=[
                            "journalctl -u energy-collector -n 100 --no-pager | grep -i 'error\\|4[0-9][0-9]'",
                            "curl -sS -m 5 <backend>/health",
                        ],
                        suggested_actions=[
                            "Check the backend response code the node is receiving — a "
                            "persistent 400 means the payload is being rejected, not lost "
                            "in transit.",
                        ],
                        **location,
                    )
                )

        severity = ctx.threshold_severity(
            beat.sqlite_size_mb,
            thresholds.sqlite_size_warning_mb,
            thresholds.sqlite_size_critical_mb,
        )
        if severity is not Severity.OK:
            findings.append(
                Finding(
                    rule_id="node.sqlite_size",
                    subsystem=Subsystem.NODE,
                    severity=severity,
                    title=f"Node {code} local database is large",
                    target=code,
                    metric="sqlite_size_mb",
                    current_value=f"{beat.sqlite_size_mb:.0f} MB",
                    expected_value=f"< {thresholds.sqlite_size_warning_mb:.0f} MB",
                    suggested_actions=[
                        "Confirm the retention window is being applied on the node."
                    ],
                    **location,
                )
            )

        severity = ctx.threshold_severity(beat.sqlite_wal_mb, thresholds.wal_size_warning_mb, None)
        if severity is not Severity.OK:
            findings.append(
                Finding(
                    rule_id="node.sqlite_wal",
                    subsystem=Subsystem.NODE,
                    severity=Severity.WARNING,
                    title=f"Node {code} WAL is not checkpointing",
                    target=code,
                    metric="sqlite_wal_mb",
                    current_value=f"{beat.sqlite_wal_mb:.0f} MB",
                    expected_value=f"< {thresholds.wal_size_warning_mb:.0f} MB",
                    suggested_causes=["A stuck reader or writer on the node's buffer database"],
                    **location,
                )
            )

    return findings


@rule("node.connectivity", Subsystem.NETWORK, "Node network state and latency")
def check_node_connectivity(ctx: RuleContext) -> Iterable[Finding]:
    findings: list[Finding] = []
    thresholds = ctx.config.node

    for code, state in ctx.nodes.items():
        beat: NodeHeartbeat | None = state.get("heartbeat")
        if beat is None or (state.get("missed_beats") or 0) > 0:
            continue
        if not policy_for(state).node_hardware:
            continue

        location = _node_location(state)

        severity = ctx.threshold_severity(
            beat.latency_ms, thresholds.latency_warning_ms, thresholds.latency_critical_ms
        )
        if severity is not Severity.OK:
            findings.append(
                Finding(
                    rule_id="node.latency",
                    subsystem=Subsystem.NETWORK,
                    severity=severity,
                    title=f"Node {code} has high latency to the backend",
                    target=code,
                    metric="latency_ms",
                    current_value=f"{beat.latency_ms:.0f} ms",
                    expected_value=f"< {thresholds.latency_warning_ms:.0f} ms",
                    suggested_causes=["Congested campus link", "Weak WiFi signal"],
                    suggested_commands=["ping -c5 <backend-host>", "iwconfig"],
                    **location,
                )
            )

        # An access point that turns itself on usually means the node failed to
        # associate and fell back to its own AP — it is a symptom of a WiFi
        # problem, and it also exposes an unexpected open network.
        if beat.access_point_active:
            findings.append(
                Finding(
                    rule_id="node.access_point",
                    subsystem=Subsystem.NETWORK,
                    severity=Severity.WARNING,
                    title=f"Node {code} has its access point active",
                    target=code,
                    summary=(
                        "The node is broadcasting its own AP, which normally means it "
                        "could not join the campus WiFi and fell back."
                    ),
                    metric="access_point",
                    current_value="active",
                    expected_value="inactive",
                    suggested_causes=["WiFi association failed", "Credentials changed"],
                    suggested_commands=["iwconfig", "systemctl status hostapd"],
                    **location,
                )
            )

        if beat.internet_ok is False:
            findings.append(
                Finding(
                    rule_id="node.internet",
                    subsystem=Subsystem.NETWORK,
                    severity=Severity.WARNING,
                    title=f"Node {code} reports no internet access",
                    target=code,
                    metric="internet",
                    current_value="unreachable",
                    expected_value="reachable",
                    suggested_actions=[
                        "The node can still reach the backend if it is on the same "
                        "network; check whether ingestion is continuing.",
                    ],
                    **location,
                )
            )

        drift = beat.clock_drift_seconds
        if drift is not None:
            severity = ctx.threshold_severity(
                abs(drift),
                thresholds.clock_drift_warning_s,
                thresholds.clock_drift_critical_s,
            )
            if severity is not Severity.OK:
                findings.append(
                    Finding(
                        rule_id="node.clock_drift",
                        subsystem=Subsystem.NODE,
                        severity=severity,
                        title=f"Node {code} clock differs from the server",
                        target=code,
                        summary=(
                            "Measurements are stored with the node's timestamp, so drift "
                            "misplaces readings on the timeline and corrupts cost "
                            "attribution by tariff period."
                        ),
                        metric="clock_drift_seconds",
                        current_value=f"{drift:+.0f}s",
                        expected_value=f"within ±{thresholds.clock_drift_warning_s:.0f}s",
                        suggested_causes=[
                            "NTP not reachable from the node",
                            "A Pi has no RTC, so it starts from a stale clock after a "
                            "power cut until NTP corrects it",
                        ],
                        suggested_commands=["timedatectl status", "chronyc tracking"],
                        **location,
                    )
                )

    return findings


@rule("node.collector", Subsystem.NODE, "Collector process and sensor availability")
def check_node_collector(ctx: RuleContext) -> Iterable[Finding]:
    findings: list[Finding] = []

    for code, state in ctx.nodes.items():
        beat: NodeHeartbeat | None = state.get("heartbeat")
        if beat is None or (state.get("missed_beats") or 0) > 0:
            continue
        # A stopped collector on an undeployed node is expected, not a fault.
        if not policy_for(state).sensors:
            continue

        location = _node_location(state)

        if beat.collector_status and beat.collector_status not in ("active", "running", "ok"):
            findings.append(
                Finding(
                    rule_id="node.collector_down",
                    subsystem=Subsystem.NODE,
                    severity=Severity.CRITICAL,
                    title=f"Node {code} collector is not running",
                    target=code,
                    summary=(
                        "The node is alive and reporting, but the process that reads the "
                        "sensors is not running. No measurements are being taken."
                    ),
                    metric="collector_status",
                    current_value=beat.collector_status,
                    expected_value="active",
                    related_services=["energy-collector"],
                    suggested_causes=[
                        "Collector crashed and exhausted its restart budget",
                        "Configuration error after an update",
                        "A sensor library failing to import",
                    ],
                    suggested_commands=[
                        "systemctl status energy-collector",
                        "journalctl -u energy-collector -n 100 --no-pager",
                    ],
                    suggested_actions=[
                        "This is data loss in progress: the node is up but measuring "
                        "nothing, and nothing is being buffered either.",
                    ],
                    context={"pid": beat.collector_pid, "restarts": beat.collector_restarts},
                    **location,
                )
            )

        for flag, name, hint in (
            (beat.ads_ok, "ADS", "I2C/ADC converter — check wiring and i2cdetect"),
            (beat.spi_ok, "SPI", "SPI bus — check that the interface is enabled"),
            (beat.gpio_ok, "GPIO", "GPIO access — check permissions and pin configuration"),
        ):
            if flag is False:
                findings.append(
                    Finding(
                        rule_id=f"node.{name.lower()}",
                        subsystem=Subsystem.NODE,
                        severity=Severity.ERROR,
                        title=f"Node {code} reports {name} unavailable",
                        target=code,
                        metric=f"{name.lower()}_ok",
                        current_value="unavailable",
                        expected_value="available",
                        suggested_causes=[hint],
                        suggested_commands=[
                            "i2cdetect -y 1",
                            "ls -l /dev/spidev*",
                            "dmesg | tail -30",
                        ],
                        suggested_actions=["Readings from this node are suspect until resolved."],
                        **location,
                    )
                )

        if (
            beat.shelly_total is not None
            and beat.shelly_reachable is not None
            and beat.shelly_total > 0
            and beat.shelly_reachable < beat.shelly_total
        ):
            missing = beat.shelly_total - beat.shelly_reachable
            findings.append(
                Finding(
                    rule_id="node.shelly_unreachable",
                    subsystem=Subsystem.SMART_PLUG,
                    severity=Severity.WARNING,
                    title=f"Node {code} cannot reach {missing} smart plug(s)",
                    target=code,
                    metric="shelly_reachable",
                    current_value=f"{beat.shelly_reachable}/{beat.shelly_total}",
                    expected_value=f"{beat.shelly_total}/{beat.shelly_total}",
                    suggested_causes=[
                        "Plug unplugged or powered off",
                        "Plug moved to a different subnet after a DHCP change",
                        "WiFi congestion",
                    ],
                    suggested_actions=[
                        "Plugs are kept, not deleted, when unreachable; they recover "
                        "automatically once they respond again.",
                    ],
                    **location,
                )
            )

    return findings


@rule("node.measurements", Subsystem.ELECTRICAL, "Measurement freshness per node")
def check_measurement_freshness(ctx: RuleContext) -> Iterable[Finding]:
    """A node that is alive but has stopped storing measurements.

    This is the case the previous alerting could not express, and the case that
    is live on this platform right now: a node heartbeating normally whose
    readings never reach the database.
    """
    findings: list[Finding] = []
    thresholds = ctx.config.node

    for code, state in ctx.nodes.items():
        if state.get("unregistered"):
            continue
        # Missing measurements only mean something when the node is supposed to
        # be measuring. Without this gate, every decommissioned or powered-down
        # node reports "alive but not measuring" forever.
        if not policy_for(state).measurement_freshness:
            continue
        # Only meaningful while the node is reachable; otherwise the heartbeat
        # rule already describes the problem.
        if (state.get("missed_beats") or 0) > 0:
            continue

        age = state.get("reading_age_seconds")
        deployment = state.get("deployment")

        if age is None:
            # Only reachable in COMMISSIONING: a deployment was started and no
            # measurement has ever arrived. Standby and offline nodes are gated
            # out upstream by the lifecycle policy, so this is unambiguously
            # "you started a campaign and it is recording nothing".
            findings.append(
                Finding(
                    rule_id="node.no_measurements",
                    subsystem=Subsystem.ELECTRICAL,
                    severity=Severity.WARNING,
                    title=f"Node {code} is deployed but has never recorded a measurement",
                    target=code,
                    summary=(
                        "A deployment is active for this node, but no reading from it "
                        "has ever reached the database. The campaign is collecting "
                        "nothing."
                    ),
                    metric="last_measurement",
                    current_value="never",
                    expected_value=f"within {thresholds.measurement_stale_warning_s}s",
                    # Half an hour of grace: commissioning a node legitimately
                    # takes time, and alerting during setup is pure noise.
                    sustain_seconds=1800,
                    suggested_causes=[
                        "Collector not started or not configured for this node code",
                        "Sensors not wired",
                        "Backend rejecting the payload — check for 4xx in its journal",
                    ],
                    suggested_commands=[
                        "journalctl -u energy-node-collector -n 50 --no-pager",
                        "curl -sS <backend>/api/nodes",
                    ],
                    suggested_actions=[
                        "Confirm the collector is running and reporting the node code "
                        "this deployment expects.",
                    ],
                    context={"has_deployment": True},
                    **_node_location(state),
                )
            )
            continue

        severity = ctx.threshold_severity(
            age,
            thresholds.measurement_stale_warning_s,
            thresholds.measurement_stale_critical_s,
        )
        if severity is Severity.OK:
            continue

        findings.append(
            Finding(
                rule_id="node.measurements_stale",
                subsystem=Subsystem.ELECTRICAL,
                severity=severity,
                title=f"Node {code} is alive but not measuring",
                target=code,
                summary=(
                    "Heartbeats are arriving normally, so the machine and its network "
                    "are fine. The measurement path specifically has stopped."
                ),
                metric="measurement_age_seconds",
                current_value=f"{int(age)}s",
                expected_value=f"< {thresholds.measurement_stale_warning_s}s",
                suggested_causes=[
                    "Collector running but sensors not responding",
                    "Ingest rejecting the payload (check for 4xx in the backend journal)",
                    "Deployment ended, so readings are refused",
                    "CT clamp or ADC disconnected",
                ],
                suggested_commands=[
                    "journalctl -u energy-platform-backend.service -n 200 --no-pager | grep -E '\"POST /api/(readings|v1)' | tail -20",
                    "systemctl status energy-collector",
                ],
                suggested_actions=[
                    "The node is up, so this is a sensor, collector or ingest-contract "
                    "problem rather than a connectivity problem.",
                ],
                context={"deployment_status": state.get("deployment_status")},
                **_node_location(state),
            )
        )

    return findings


@rule("security.unknown_node", Subsystem.SECURITY, "Heartbeats from unregistered nodes")
def check_unknown_nodes(ctx: RuleContext) -> Iterable[Finding]:
    """A node code that is not registered in the platform.

    Either a misconfigured node reporting under the wrong code — which means
    its data is being attributed wrongly or discarded — or something that
    should not be talking to this backend at all.
    """
    findings: list[Finding] = []

    for code, state in ctx.nodes.items():
        if not state.get("unregistered"):
            continue

        beat: NodeHeartbeat | None = state.get("heartbeat")
        findings.append(
            Finding(
                rule_id="security.unknown_node",
                subsystem=Subsystem.SECURITY,
                severity=Severity.WARNING,
                title=f"Heartbeat from unregistered node '{code}'",
                target=code,
                summary=(
                    "A node is reporting under a code that does not exist in the "
                    "platform. Its measurements cannot be attributed to a deployment."
                ),
                metric="node_code",
                current_value=code,
                expected_value="a registered node code",
                hostname=beat.hostname if beat else None,
                suggested_causes=[
                    "Node configured with the wrong code",
                    "A node deployed but never registered",
                    "An unauthorised device",
                ],
                suggested_commands=["curl -sS <backend>/api/nodes"],
                suggested_actions=[
                    "Register the node or correct its configuration; until then its data "
                    "is rejected.",
                ],
                context={"source_ip": beat.source_ip if beat else None},
            )
        )

    return findings


@rule(
    "security.duplicate_node_identity",
    Subsystem.SECURITY,
    "Contradictory or unauthenticated producers publishing as one node",
)
def check_duplicate_node_identity(ctx: RuleContext) -> Iterable[Finding]:
    """Detect two producers publishing under a single node code.

    Node identity is a credential, never a source address. On 2026-08-06 two
    producers published as N001 from one NAT address with the same hostname and
    the same PID in the payload; nothing in the platform could separate them,
    and they disagreed on ``filesystem_readonly``.

    Three signals, any of which is a violation:

    * **Distinct producer signatures** for one node inside the window. A node
      runs one agent; two self-declared versions means two processes.
    * **Contradictory telemetry** on a field that cannot legitimately differ
      between two reports of the same machine seconds apart.
    * **Recorded identity violations** — a rejected credential or a mismatched
      claim, which is an impersonation attempt rather than a misconfiguration.

    Deliberately not gated on lifecycle policy: an impersonation attempt against
    a decommissioned node still matters.
    """
    from sqlalchemy import text as _text

    findings: list[Finding] = []
    window_start = ctx.now - timedelta(minutes=15)

    # --- Distinct producer signatures ------------------------------------
    rows = (
        ctx.session.query(
            NodeHeartbeat.node_code,
            NodeHeartbeat.software_version,
            func.count(NodeHeartbeat.id),
            func.max(NodeHeartbeat.received_at),
        )
        .filter(NodeHeartbeat.received_at >= window_start)
        .group_by(NodeHeartbeat.node_code, NodeHeartbeat.software_version)
        .all()
    )

    by_node: dict[str, list[tuple[str | None, int, Any]]] = {}
    for code, version, count, last in rows:
        by_node.setdefault(code, []).append((version, count, last))

    for code, producers in by_node.items():
        if len(producers) < 2:
            continue
        detail = ", ".join(
            f"{ver or 'unknown'} ({n} beats, last {last})" for ver, n, last in producers
        )
        findings.append(
            Finding(
                rule_id="security.duplicate_node_identity",
                subsystem=Subsystem.SECURITY,
                severity=Severity.CRITICAL,
                title=f"Multiple producers publishing as {code}",
                target=code,
                summary=(
                    f"{len(producers)} distinct producer signatures reported as {code} "
                    "in the last 15 minutes. A node runs one agent; two signatures "
                    "means a second process is impersonating it, and its telemetry "
                    "cannot be trusted until resolved."
                ),
                metric="producer_signatures",
                current_value=detail,
                expected_value="exactly one producer",
                node_code=code,
                # Identity is not a transient. One extra beat is enough evidence.
                sustain_seconds=0,
                suggested_causes=[
                    "An old agent left in a backups/ directory being run manually",
                    "A duplicate service or timer publishing the same node code",
                    "A second host configured with the same NODE_ID",
                    "A stale container or cron job",
                ],
                suggested_commands=[
                    "curl -s localhost:8010/api/monitoring/identity/violations",
                    'sqlite3 energy_platform.db "SELECT source_ip, software_version, '
                    "auth_status, COUNT(*) FROM monitor_node_heartbeats "
                    f"WHERE node_code='{code}' AND received_at > datetime('now','-1 hour') "
                    'GROUP BY 1,2,3"',
                    "ps -eo pid,etimes,cmd | grep -iE 'agent|heartbeat'",
                ],
                suggested_actions=[
                    "Identify and stop the second producer before trusting this "
                    "node's telemetry.",
                    "Issue credentials and set node_auth.mode=enforce so an "
                    "unauthenticated producer is refused rather than recorded.",
                ],
                context={"producers": detail},
            )
        )

    # --- Recorded identity violations ------------------------------------
    try:
        violations = ctx.session.execute(
            _text(
                "SELECT claimed_node, violation, COUNT(*), MAX(occurred_at) "
                "  FROM node_identity_violations "
                " WHERE occurred_at >= :since AND violation != 'unauthenticated' "
                " GROUP BY claimed_node, violation"
            ),
            {"since": window_start.strftime("%Y-%m-%dT%H:%M:%S")},
        ).all()
    except Exception:
        violations = []

    for claimed, violation, count, last in violations:
        findings.append(
            Finding(
                rule_id="security.identity_violation",
                subsystem=Subsystem.SECURITY,
                severity=Severity.CRITICAL,
                title=f"Identity violation on {claimed}: {violation}",
                target=f"{claimed}:{violation}",
                summary=(
                    f"{count} request(s) in the last 15 minutes were refused or "
                    f"flagged as {violation!r} while claiming to be {claimed}."
                ),
                metric="identity_violation",
                current_value=f"{count} occurrence(s), last {last}",
                expected_value="none",
                node_code=claimed,
                sustain_seconds=0,
                suggested_commands=[
                    "sqlite3 energy_platform.db 'SELECT * FROM node_identity_violations "
                    "ORDER BY id DESC LIMIT 20'",
                ],
                suggested_actions=[
                    "A mismatched or unknown credential is an impersonation "
                    "attempt, not a misconfiguration. Investigate the source.",
                ],
            )
        )

    return findings


@rule(
    "security.unauthenticated_producer",
    Subsystem.SECURITY,
    "Nodes still publishing without a credential",
)
def check_unauthenticated_producers(ctx: RuleContext) -> Iterable[Finding]:
    """Report nodes whose heartbeats carry no credential.

    Exists so ``node_auth.mode = permissive`` cannot become a quiet resting
    state. Permissive is a rollout step; while any node is unauthenticated the
    endpoint can be impersonated, so this keeps saying so.

    Report-only by default: it is a standing configuration gap, not an incident.
    """
    findings: list[Finding] = []
    window_start = ctx.now - timedelta(minutes=15)

    rows = (
        ctx.session.query(NodeHeartbeat.node_code, func.count(NodeHeartbeat.id))
        .filter(
            NodeHeartbeat.received_at >= window_start,
            (NodeHeartbeat.auth_status.is_(None)) | (NodeHeartbeat.auth_status != "authenticated"),
        )
        .group_by(NodeHeartbeat.node_code)
        .all()
    )

    for code, count in rows:
        findings.append(
            Finding(
                rule_id="security.unauthenticated_producer",
                subsystem=Subsystem.SECURITY,
                severity=Severity.WARNING,
                title=f"Node {code} publishes without a credential",
                target=code,
                summary=(
                    f"{count} heartbeat(s) in the last 15 minutes carried no valid "
                    "credential. Until every node authenticates, any process can "
                    "publish telemetry as this node."
                ),
                metric="auth_status",
                current_value=f"{count} unauthenticated beat(s)",
                expected_value="authenticated",
                node_code=code,
                max_severity=Severity.WARNING,
                suggested_commands=[
                    "venv/bin/python3 -m app.db.provision_node list",
                    f"venv/bin/python3 -m app.db.provision_node issue {code}",
                ],
                suggested_actions=[
                    "Issue a credential, install it on the node, then set "
                    "node_auth.mode=enforce.",
                ],
            )
        )

    return findings


__all__ = [
    "HeartbeatPayload",
    "collect_node_state",
    "record_heartbeat",
    "recovery_details",
]
