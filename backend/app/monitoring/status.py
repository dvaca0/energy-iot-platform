"""The periodic status report and the live status snapshot.

Two consumers, one body of logic:

* :func:`build_status` produces a structured snapshot, returned by the API and
  used by the frontend.
* :func:`render_report` turns that snapshot into the hourly Telegram message.

The report is written to be *scanned*, not read. A per-node line leads with a
single health glyph so the eye finds the broken node before reading any
numbers, and sections are ordered by how likely they are to matter: what is
broken, then the fleet, then the aggregates.

Values that could not be collected are shown as ``—`` rather than as zero. A
node reporting 0 °C and a node reporting nothing are different situations, and
conflating them in a health report is how a monitoring system starts lying.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.monitoring import lifecycle
from app.monitoring.alerts import open_alert_summary
from app.monitoring.channels import OutboundMessage
from app.monitoring.channels.telegram import escape
from app.monitoring.config import MonitoringConfig, get_config
from app.monitoring.models import MonitorAlert, NotificationOutbox
from app.monitoring.notifications import humanize_duration, local_time
from app.monitoring.rules import Finding
from app.monitoring.severity import Severity

log = logging.getLogger("monitoring.status")

DASH = "—"


def _fmt(value: Any, suffix: str = "", decimals: int = 1) -> str:
    """Format a value, distinguishing "missing" from "zero"."""
    if value is None:
        return DASH
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        if isinstance(value, float):
            return f"{value:.{decimals}f}{suffix}"
        return f"{value}{suffix}"
    return f"{value}{suffix}"


def _health_glyph(severity: Severity) -> str:
    return severity.emoji if severity is not Severity.OK else "✅"


def build_status(
    session: Session,
    *,
    server: dict[str, Any] | None = None,
    nodes: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    findings: list[Finding] | None = None,
    config: MonitoringConfig | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Assemble the full platform status snapshot.

    Accepts the already-collected tick data when called from the scheduler, and
    collects it on demand when called from the API, so an operator refreshing
    the status page never has to wait for the next scheduled tick.
    """
    config = config or get_config()
    now = now or datetime.utcnow()

    if server is None or nodes is None or metrics is None:
        from app.monitoring.health import collect_server_snapshot
        from app.monitoring.heartbeat import collect_node_state
        from app.monitoring.metrics import collect_metrics

        server = server if server is not None else collect_server_snapshot(config)
        nodes = nodes if nodes is not None else collect_node_state(session, config, now)
        lifecycle.annotate(session, nodes, config, now)
        metrics = metrics if metrics is not None else collect_metrics(session, config, now)

    open_alerts = (
        session.query(MonitorAlert)
        .filter(MonitorAlert.resolved_at.is_(None))
        .order_by(MonitorAlert.severity.desc(), MonitorAlert.created_at.asc())
        .all()
    )
    overall = Severity.OK
    for alert in open_alerts:
        overall = max(overall, Severity.parse(alert.severity))

    # --- Server -----------------------------------------------------------
    disks = server.get("disks") or {}
    root = disks.get("/") or next(iter(disks.values()), {})
    database = server.get("database") or {}
    api = server.get("api") or {}

    server_block = {
        "hostname": server.get("hostname"),
        "cpu_percent": (server.get("cpu") or {}).get("percent"),
        "memory_percent": (server.get("memory") or {}).get("percent"),
        "swap_percent": (server.get("memory") or {}).get("swap_percent"),
        "disk_percent": root.get("percent"),
        "disk_free_gb": root.get("free_gb"),
        "load_1": (server.get("load") or {}).get("load_1"),
        "load_5": (server.get("load") or {}).get("load_5"),
        "temperature_c": (server.get("temperature") or {}).get("celsius"),
        "uptime_seconds": (server.get("uptime") or {}).get("uptime_seconds"),
        "services": server.get("services") or {},
        "api_ok": api.get("ok"),
        "api_latency_seconds": api.get("latency_seconds"),
        "internet_ok": (server.get("internet") or {}).get("ok"),
        "dns_ok": (server.get("dns") or {}).get("ok"),
        "time_synchronized": (server.get("time_sync") or {}).get("synchronized"),
        "tailscale": server.get("tailscale") or {},
        "reboot_required": (server.get("reboot") or {}).get("required"),
    }

    # --- Nodes ------------------------------------------------------------
    node_blocks: list[dict[str, Any]] = []
    latest_readings = metrics.get("latest_readings") or {}

    for code in sorted(nodes):
        state = nodes[code]
        beat = state.get("heartbeat")
        reading = latest_readings.get(state.get("node_id"))

        missed = state.get("missed_beats") or 0
        if state.get("unregistered") or not state.get("ever_seen"):
            node_severity = Severity.WARNING
        elif missed >= config.heartbeat.missed_critical:
            node_severity = Severity.CRITICAL
        elif missed >= config.heartbeat.missed_error:
            node_severity = Severity.ERROR
        elif missed >= config.heartbeat.missed_warning:
            node_severity = Severity.WARNING
        else:
            node_severity = Severity.OK

        node_blocks.append(
            {
                "code": code,
                "name": state.get("name"),
                "lifecycle": state.get("lifecycle"),
                "lifecycle_reason": state.get("lifecycle_reason"),
                "severity": node_severity.label,
                "glyph": _health_glyph(node_severity),
                "registered": not state.get("unregistered", False),
                "ever_seen": state.get("ever_seen"),
                "heartbeat_age_seconds": state.get("heartbeat_age_seconds"),
                "missed_beats": missed,
                "campus": state.get("campus"),
                "building": state.get("building"),
                "deployment": state.get("deployment_label"),
                "deployment_status": state.get("deployment_status"),
                "last_reading_at": (
                    state["last_reading_at"].isoformat() if state.get("last_reading_at") else None
                ),
                "reading_age_seconds": state.get("reading_age_seconds"),
                "last_sync": (state["last_sync"].isoformat() if state.get("last_sync") else None),
                # Node telemetry, present only once the heartbeat agent is deployed.
                "cpu_percent": beat.cpu_percent if beat else None,
                "memory_percent": beat.memory_percent if beat else None,
                "disk_percent": beat.disk_percent if beat else None,
                "temperature_c": beat.cpu_temperature_c if beat else None,
                "uptime_seconds": beat.uptime_seconds if beat else None,
                "collector_status": beat.collector_status if beat else None,
                "buffered_readings": beat.buffered_readings if beat else None,
                "pending_sync": beat.pending_sync if beat else None,
                "sqlite_size_mb": beat.sqlite_size_mb if beat else None,
                "ethernet_up": beat.ethernet_up if beat else None,
                "wifi_up": beat.wifi_up if beat else None,
                "access_point_active": beat.access_point_active if beat else None,
                "tailscale_up": beat.tailscale_up if beat else None,
                "internet_ok": beat.internet_ok if beat else None,
                "latency_ms": beat.latency_ms if beat else None,
                "shelly": (
                    f"{beat.shelly_reachable}/{beat.shelly_total}"
                    if beat and beat.shelly_total is not None
                    else None
                ),
                "ads_ok": beat.ads_ok if beat else None,
                "software_version": beat.software_version if beat else None,
                "collector_version": beat.collector_version if beat else None,
                "git_commit": beat.git_commit if beat else None,
                # Electrical, from the newest stored reading.
                "voltage": reading.voltage if reading else None,
                "current": reading.current if reading else None,
                "power_kw": reading.power_kw if reading else None,
                "power_factor": reading.power_factor if reading else None,
                "frequency_hz": reading.frequency_hz if reading else None,
            }
        )

    # --- Electrical aggregate ----------------------------------------------
    readings = [r for r in latest_readings.values() if r is not None]
    powers = [r.power_kw for r in readings if r.power_kw is not None]
    currents = [r.current for r in readings if r.current is not None]
    voltages = [r.voltage for r in readings if r.voltage is not None]
    factors = [r.power_factor for r in readings if r.power_factor is not None]

    electrical_block = {
        "total_power_kw": round(sum(powers), 3) if powers else None,
        "highest_demand_kw": round(max(powers), 3) if powers else None,
        "highest_current_a": round(max(currents), 2) if currents else None,
        "highest_voltage_v": round(max(voltages), 1) if voltages else None,
        "worst_power_factor": round(min(factors), 3) if factors else None,
        "nodes_measuring": len(readings),
    }

    # --- Alerts -----------------------------------------------------------
    day_start = now - timedelta(days=1)
    resolved_today = (
        session.query(func.count(MonitorAlert.id))
        .filter(MonitorAlert.resolved_at >= day_start)
        .scalar()
        or 0
    )
    pending_notifications = (
        session.query(func.count(NotificationOutbox.id))
        .filter(NotificationOutbox.status == "pending")
        .scalar()
        or 0
    )

    alert_block = {
        "overall_severity": overall.label,
        "overall_glyph": _health_glyph(overall),
        "open_by_severity": open_alert_summary(session),
        "open_total": len(open_alerts),
        "resolved_last_24h": resolved_today,
        "pending_notifications": pending_notifications,
        "open": [
            {
                "alert_id": alert.alert_id,
                "severity": alert.severity,
                "title": alert.title,
                "subsystem": alert.subsystem,
                "node_code": alert.node_code,
                "current_value": alert.current_value,
                "open_for_seconds": (now - alert.created_at).total_seconds(),
                "created_at": alert.created_at.isoformat(),
            }
            for alert in open_alerts
        ],
    }

    # --- Database ----------------------------------------------------------
    database_block = {
        "engine": "SQLite (WAL)",
        "size_mb": database.get("db_mb"),
        "wal_mb": database.get("wal_mb"),
        "query_seconds": database.get("query_seconds"),
        "integrity_ok": database.get("integrity_ok"),
        "readings_last_24h": metrics.get("readings_today"),
        "readings_total": metrics.get("readings_total"),
        "nodes": metrics.get("node_count"),
        "buildings": metrics.get("building_count"),
        "campuses": metrics.get("campus_count"),
        "deployments": metrics.get("deployment_count"),
        "active_deployments": metrics.get("active_deployment_count"),
        "smart_plugs": metrics.get("plug_count"),
        "smart_plugs_online": metrics.get("plug_online"),
    }

    # --- Capability gaps ---------------------------------------------------
    gaps = [
        {
            "rule_id": finding.rule_id,
            "title": finding.title,
            "reason": finding.unavailable_reason,
        }
        for finding in (findings or [])
        if finding.unavailable
    ]

    return {
        "generated_at": now.isoformat(),
        "generated_at_local": local_time(now, config),
        "timezone": config.timezone,
        "deployment": config.deployment_name,
        "overall": overall.label,
        "server": server_block,
        "nodes": node_blocks,
        "electrical": electrical_block,
        "alerts": alert_block,
        "database": database_block,
        "unavailable_checks": gaps,
    }


def render_report(
    status: dict[str, Any], config: MonitoringConfig | None = None
) -> OutboundMessage:
    """Render the status snapshot into the periodic report message."""
    config = config or get_config()
    overall = Severity.parse(status.get("overall"), Severity.OK)

    lines: list[str] = []
    lines.append(f"{_health_glyph(overall)} <b>PLATFORM STATUS — {escape(overall.label)}</b>")
    lines.append(f"<i>{escape(status.get('generated_at_local'))}</i>")
    lines.append("")

    # --- Alert summary first: it is the reason to read the rest ------------
    alerts = status.get("alerts") or {}
    open_by = alerts.get("open_by_severity") or {}
    if alerts.get("open_total"):
        lines.append("<b>OPEN ALERTS</b>")
        for level in ("EMERGENCY", "CRITICAL", "ERROR", "WARNING", "INFO"):
            count = open_by.get(level, 0)
            if count:
                lines.append(f"{Severity.parse(level).emoji} {escape(level)}: {count}")
        for alert in (alerts.get("open") or [])[:8]:
            lines.append(
                f"• <code>{escape(alert['alert_id'])}</code> {escape(alert['title'])} "
                f"({humanize_duration(alert['open_for_seconds'])})"
            )
        lines.append("")
    else:
        lines.append("<b>OPEN ALERTS</b>")
        lines.append("None. All checks passing.")
        lines.append("")

    # --- Server -----------------------------------------------------------
    server = status.get("server") or {}
    lines.append("<b>SERVER</b>")
    lines.append(f"Host: {escape(server.get('hostname') or DASH)}")
    lines.append(
        f"CPU {_fmt(server.get('cpu_percent'), '%')} · "
        f"RAM {_fmt(server.get('memory_percent'), '%')} · "
        f"Disk {_fmt(server.get('disk_percent'), '%')} "
        f"({_fmt(server.get('disk_free_gb'), ' GB free')})"
    )
    lines.append(
        f"Load {_fmt(server.get('load_1'), '', 2)} / {_fmt(server.get('load_5'), '', 2)} · "
        f"Temp {_fmt(server.get('temperature_c'), ' °C')} · "
        f"Up {humanize_duration(server.get('uptime_seconds'))}"
    )
    api_state = "ok" if server.get("api_ok") else "DOWN"
    lines.append(
        f"API {escape(api_state)} ({_fmt(server.get('api_latency_seconds'), 's', 3)}) · "
        f"Internet {_fmt(server.get('internet_ok'))} · "
        f"DNS {_fmt(server.get('dns_ok'))} · "
        f"NTP {_fmt(server.get('time_synchronized'))}"
    )
    for unit, state in (server.get("services") or {}).items():
        glyph = "✅" if state.get("ok") else "❌"
        short = unit.replace("energy-platform-", "").replace(".service", "")
        lines.append(f"{glyph} {escape(short)}: {escape(state.get('active'))}")
    lines.append("")

    # --- Database ----------------------------------------------------------
    database = status.get("database") or {}
    lines.append("<b>DATABASE</b>")
    lines.append(
        f"{escape(database.get('engine'))} · {_fmt(database.get('size_mb'), ' MB')} "
        f"(WAL {_fmt(database.get('wal_mb'), ' MB')})"
    )
    lines.append(
        f"Readings 24h: {_fmt(database.get('readings_last_24h'))} · "
        f"total {_fmt(database.get('readings_total'))}"
    )
    lines.append(
        f"Nodes {_fmt(database.get('nodes'))} · "
        f"Buildings {_fmt(database.get('buildings'))} · "
        f"Campuses {_fmt(database.get('campuses'))} · "
        f"Deployments {_fmt(database.get('deployments'))} "
        f"({_fmt(database.get('active_deployments'))} active)"
    )
    lines.append(
        f"Smart plugs: {_fmt(database.get('smart_plugs_online'))}/"
        f"{_fmt(database.get('smart_plugs'))} online"
    )
    lines.append("")

    # --- Nodes -------------------------------------------------------------
    lines.append("<b>NODES</b>")
    for node in status.get("nodes") or []:
        header = f"{node['glyph']} <b>{escape(node['code'])}</b>"
        if node.get("lifecycle"):
            header += f" · <i>{escape(node['lifecycle'])}</i>"
        if node.get("building"):
            header += f" · {escape(node['building'])}"
        lines.append(header)

        # Why a node is or is not being alerted on must never be a mystery.
        if node.get("lifecycle_reason") and "full monitoring" not in node["lifecycle_reason"]:
            lines.append(f"   <i>{escape(node.get('lifecycle_reason') or '')}</i>")

        if not node.get("registered"):
            lines.append("   unregistered node reporting heartbeats")
            continue

        if not node.get("ever_seen"):
            hb = "no heartbeat agent yet"
        else:
            hb = f"beat {humanize_duration(node.get('heartbeat_age_seconds'))} ago"
            if node.get("missed_beats"):
                hb += f" ({node['missed_beats']} missed)"
        reading_age = node.get("reading_age_seconds")
        measurement = (
            f"reading {humanize_duration(reading_age)} ago"
            if reading_age is not None
            else "no readings"
        )
        lines.append(f"   {escape(hb)} · {escape(measurement)}")

        # Electrical line, only when there is something to show.
        if node.get("voltage") is not None or node.get("power_kw") is not None:
            lines.append(
                f"   {_fmt(node.get('voltage'), ' V')} · "
                f"{_fmt(node.get('current'), ' A')} · "
                f"{_fmt(node.get('power_kw'), ' kW', 3)} · "
                f"PF {_fmt(node.get('power_factor'), '', 2)} · "
                f"{_fmt(node.get('frequency_hz'), ' Hz', 2)}"
            )

        # Node telemetry appears once the heartbeat agent is deployed.
        if node.get("cpu_percent") is not None or node.get("temperature_c") is not None:
            lines.append(
                f"   CPU {_fmt(node.get('cpu_percent'), '%')} · "
                f"RAM {_fmt(node.get('memory_percent'), '%')} · "
                f"Disk {_fmt(node.get('disk_percent'), '%')} · "
                f"{_fmt(node.get('temperature_c'), ' °C')}"
            )
            lines.append(
                f"   Collector {escape(node.get('collector_status') or DASH)} · "
                f"buffer {_fmt(node.get('buffered_readings'))} · "
                f"Shelly {escape(node.get('shelly') or DASH)} · "
                f"v{escape(node.get('software_version') or DASH)}"
            )
    lines.append("")

    # --- Electrical --------------------------------------------------------
    electrical = status.get("electrical") or {}
    lines.append("<b>ELECTRICAL</b>")
    lines.append(
        f"Total monitored: {_fmt(electrical.get('total_power_kw'), ' kW', 3)} "
        f"across {_fmt(electrical.get('nodes_measuring'))} node(s)"
    )
    lines.append(
        f"Peak demand {_fmt(electrical.get('highest_demand_kw'), ' kW', 3)} · "
        f"peak current {_fmt(electrical.get('highest_current_a'), ' A', 2)} · "
        f"worst PF {_fmt(electrical.get('worst_power_factor'), '', 2)}"
    )
    lines.append("")

    # --- Capability gaps ---------------------------------------------------
    gaps = status.get("unavailable_checks") or []
    if gaps:
        lines.append("<b>CHECKS WITHOUT A DATA SOURCE</b>")
        for gap in gaps[:8]:
            lines.append(f"• {escape(gap['title'])}: {escape(gap['reason'])}")
        lines.append("")

    pending = alerts.get("pending_notifications") or 0
    if pending:
        lines.append(f"<i>{pending} notification(s) queued for delivery</i>")

    lines.append(f"<i>{escape(config.deployment_name)}</i>")

    body = "\n".join(lines)
    return OutboundMessage(
        body=body,
        html_body=body,
        severity=Severity.INFO,
        subject=f"Platform status — {overall.label}",
        kind="report",
    )


__all__ = ["build_status", "render_report"]
