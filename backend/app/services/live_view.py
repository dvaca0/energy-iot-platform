"""The technical live view: what each node is measuring, and its recent history.

This service backs the *Monitoreo en Vivo* page, whose audience is a technician
standing next to a panel — not an analyst. Two questions have to be answerable
in seconds: *what is this node reading right now*, and *what has it been doing
for the last few minutes*.

Three rules shape everything here.

**Only measured quantities appear.** Every field returned is a column that a
collector actually wrote. Nothing is derived to fill a hole, and nothing is
defaulted to zero to make a chart look continuous: a quantity a node does not
report comes back as ``null`` and the interface says so. The list of quantities
a node genuinely reports is computed from its own newest reading
(:func:`_available_metrics`) rather than assumed from its hardware family, so a
node whose meter stops publishing a field stops advertising it.

**Instantaneous and historical are separate requests.** The snapshot is small
and cheap enough to poll every few seconds; the window is large and is either
fetched incrementally (``since``) or refreshed slowly. Merging them would mean
re-downloading the window on every tick, which is what made the old dashboard
endpoints slow.

**Downsampling is declared, never silent.** Above one hour the points returned
are bucket means, and the response says the bucket width, the aggregation and
how many raw samples each point covers. A technician reading 60 A must be able
to tell whether that is a measurement or an average of twenty.

Energy is *not* recomputed here. ``energy_readings.energy_kwh`` has carried two
different meanings over the platform's life, and the only component allowed to
resolve that is :mod:`app.services.energy_aggregate` (ADR-0007). This module
asks it for the per-reading value and sums those.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import scope
from app.db.models import Deployment, EnergyReading, Node
from app.monitoring.config import get_config
from app.monitoring.models import NodeHeartbeat, NodeHeartbeatLatest
from app.services import energy_aggregate as agg
from app.services.platform_settings import get_thresholds

LOCAL_TZ = ZoneInfo("America/Mexico_City")

#: Windows the page offers, in seconds. ``deployment`` is not a fixed span —
#: its bounds come from the deployment itself, so it carries 0 here and is
#: resolved in :func:`_window`.
RANGES: dict[str, int] = {
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "6h": 21600,
    "24h": 86400,
    "7d": 604800,
    "deployment": 0,
}

#: Bucket widths the adaptive range may choose from, smallest first. A fixed
#: ladder rather than an arbitrary divisor so two windows of similar length
#: bucket identically and a technician comparing them is comparing like with
#: like.
ADAPTIVE_STEPS: tuple[int, ...] = (60, 300, 900, 1800, 3600)

#: Points the adaptive range aims for. Below this a chart wastes resolution it
#: could have had; above it the line stops being readable and the payload stops
#: being cheap.
ADAPTIVE_TARGET_POINTS = 900

#: Bucket width per range, in seconds. ``0`` means every stored sample is
#: returned untouched.
#:
#: The nodes sample at 15 s (``POLL_INTERVAL``), so an hour is 240 points — well
#: inside what a line chart draws comfortably, and raw data is always preferable
#: for diagnosis. Six and twenty-four hours would be 1,440 and 5,760 points per
#: series per node, so those two are bucketed down to 360 and 288.
RESOLUTION: dict[str, int] = {
    "5m": 0,
    "15m": 0,
    "30m": 0,
    "1h": 0,
    "6h": 60,
    "24h": 300,
    # Seven days is 40,320 samples per node at the 15 s cadence. 900 s buckets
    # bring that to ~672, which draws cleanly and still resolves a half-hour
    # excursion — and the min/max carried on current and power mean a shorter
    # transient is not erased, only summarised.
    "7d": 900,
    # Resolved per request from the deployment's own length.
    "deployment": -1,
}

#: Reading columns exposed as time series, in response-key order. The key is
#: what the payload uses; the attribute is the stored column. Nothing outside
#: this list exists on ``energy_readings`` — see the module docstring.
SERIES_FIELDS: tuple[tuple[str, str], ...] = (
    # --- per-phase, measured directly by the meter ---
    ("va", "phase_a_voltage"),
    ("vb", "phase_b_voltage"),
    ("vc", "phase_c_voltage"),
    ("ia", "phase_a_current"),
    ("ib", "phase_b_current"),
    ("ic", "phase_c_current"),
    ("pa", "phase_a_power_kw"),
    ("pb", "phase_b_power_kw"),
    ("pc", "phase_c_power_kw"),
    ("sa", "phase_a_apparent_kva"),
    ("sb", "phase_b_apparent_kva"),
    ("sc", "phase_c_apparent_kva"),
    ("pfa", "phase_a_power_factor"),
    ("pfb", "phase_b_power_factor"),
    ("pfc", "phase_c_power_factor"),
    ("fa", "phase_a_frequency_hz"),
    ("fb", "phase_b_frequency_hz"),
    ("fc", "phase_c_frequency_hz"),
    # --- totals ---
    ("v", "voltage"),
    ("i", "current"),
    ("kw", "power_kw"),
    ("kva", "apparent_kva"),
    ("pf", "power_factor"),
    ("hz", "frequency_hz"),
    ("nc", "neutral_current"),
    # --- cumulative meter registers, reconciliation only (ADR-0007) ---
    ("imp_a", "phase_a_energy_imported_kwh"),
    ("imp_b", "phase_b_energy_imported_kwh"),
    ("imp_c", "phase_c_energy_imported_kwh"),
    ("imp_t", "meter_energy_kwh"),
    ("ret_a", "phase_a_energy_returned_kwh"),
    ("ret_b", "phase_b_energy_returned_kwh"),
    ("ret_c", "phase_c_energy_returned_kwh"),
    ("ret_t", "meter_energy_returned_kwh"),
)

#: Decimal places each series carries in the payload.
#:
#: These are not display choices — the interface formats separately. They match
#: the resolution the instrument actually publishes (the Shelly Pro 3EM reports
#: 0.1 V and 1 mA), plus enough headroom that a bucket mean is not degraded.
#: Averaging produces repeating decimals, and serialising all seventeen of them
#: doubled the payload while adding no information a technician can use.
PRECISION: dict[str, int] = {
    "va": 2,
    "vb": 2,
    "vc": 2,
    "ia": 3,
    "ib": 3,
    "ic": 3,
    # The meter publishes per-phase power to 0.1 W (4632.3 W in the capture);
    # 5 decimal places in kW is 0.01 W, comfortably finer than the instrument.
    "pa": 5,
    "pb": 5,
    "pc": 5,
    "sa": 5,
    "sb": 5,
    "sc": 5,
    # Published at 2 decimals (0.99, 0.87). 4 leaves room for a bucket mean
    # without pretending to precision the device does not have.
    "pfa": 4,
    "pfb": 4,
    "pfc": 4,
    "fa": 3,
    "fb": 3,
    "fc": 3,
    "v": 2,
    "i": 3,
    "kw": 5,
    "kva": 5,
    "pf": 4,
    "hz": 3,
    "nc": 3,
    # Lifetime registers reach millions of watt-hours (total_act was
    # 5,310,919.91 Wh). 3 decimals in kWh keeps the watt-hour digit, which is
    # what makes the register reconcilable against a bill.
    "imp_a": 3,
    "imp_b": 3,
    "imp_c": 3,
    "imp_t": 3,
    "ret_a": 3,
    "ret_b": 3,
    "ret_c": 3,
    "ret_t": 3,
    "kwh": 6,
}


def _round(key: str, value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, PRECISION.get(key.removesuffix("_min").removesuffix("_max"), 4))


#: Fields whose extremes matter for diagnosis, and which therefore keep a
#: min/max alongside the mean when a window is bucketed. Averaging a current
#: spike away is exactly the failure a technician is looking for.
EXTREMA_FIELDS: tuple[str, ...] = ("i", "ia", "ib", "ic", "kw", "pa", "pb", "pc")

#: Metric identifiers the interface asks about. Grouped, because "does this node
#: report per-phase current" is one question, not three.
METRIC_GROUPS: dict[str, tuple[str, ...]] = {
    "phase_voltage": ("phase_a_voltage", "phase_b_voltage", "phase_c_voltage"),
    "phase_current": ("phase_a_current", "phase_b_current", "phase_c_current"),
    "phase_power": ("phase_a_power_kw", "phase_b_power_kw", "phase_c_power_kw"),
    "phase_apparent": (
        "phase_a_apparent_kva",
        "phase_b_apparent_kva",
        "phase_c_apparent_kva",
    ),
    "phase_power_factor": (
        "phase_a_power_factor",
        "phase_b_power_factor",
        "phase_c_power_factor",
    ),
    "phase_frequency": (
        "phase_a_frequency_hz",
        "phase_b_frequency_hz",
        "phase_c_frequency_hz",
    ),
    "voltage": ("voltage",),
    "current": ("current",),
    "power_kw": ("power_kw",),
    "apparent_kva": ("apparent_kva",),
    "power_factor": ("power_factor",),
    "frequency_hz": ("frequency_hz",),
    "neutral_current": ("neutral_current",),
    "energy_imported": (
        "meter_energy_kwh",
        "phase_a_energy_imported_kwh",
        "phase_b_energy_imported_kwh",
        "phase_c_energy_imported_kwh",
    ),
    "energy_returned": (
        "meter_energy_returned_kwh",
        "phase_a_energy_returned_kwh",
        "phase_b_energy_returned_kwh",
        "phase_c_energy_returned_kwh",
    ),
}


def _local_day_start() -> datetime:
    """Start of the current local day, as a naive UTC instant."""
    local_now = datetime.now(LOCAL_TZ)
    local_start = datetime.combine(local_now.date(), time.min, tzinfo=LOCAL_TZ)
    return local_start.astimezone(UTC).replace(tzinfo=None)


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment is not None else None


def _age(moment: datetime | None, now: datetime) -> float | None:
    if moment is None:
        return None
    return round((now - moment).total_seconds(), 3)


def parse_range(value: str | None) -> tuple[str, int, int]:
    """Validate a range key, returning ``(key, seconds, bucket_seconds)``.

    An unknown key falls back to the default rather than raising: the page is a
    diagnostic tool, and a bad querystring should not leave a technician with an
    error instead of data.
    """
    key = value if value in RANGES else "15m"
    return key, RANGES[key], RESOLUTION[key]


def parse_since(value: str | None) -> datetime | None:
    """Parse the client's ``since`` watermark into a naive UTC instant."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _requested_nodes(db: Session, node_ids: str | None) -> list[Node]:
    """Resolve ``?node_ids=N001,N002`` to node rows, preserving code order.

    Every registered node is returned when nothing is asked for. Unlike
    ``/api/metrics/live``, a node that has gone quiet is *not* dropped — a
    silent node is the most important thing this page has to show.
    """
    query = db.query(Node)
    if node_ids:
        codes = [code.strip() for code in node_ids.split(",") if code.strip()]
        if codes:
            query = query.filter(Node.code.in_(codes))
    return query.order_by(Node.code.asc()).all()


def _available_metrics(reading: EnergyReading | None) -> list[str]:
    """Which metric groups this node actually reports, from its own last sample.

    Derived from the data rather than from ``nodes.hardware_kind`` on purpose. A
    node is not "a Shelly node, therefore it has power factor" — it either sent
    one or it did not, and the interface must say "no disponible" in the second
    case instead of drawing a zero.
    """
    if reading is None:
        return []
    return [
        name
        for name, columns in METRIC_GROUPS.items()
        if any(getattr(reading, column, None) is not None for column in columns)
    ]


def _latest_heartbeats(db: Session, nodes: list[Node]) -> dict[str, NodeHeartbeat]:
    """Newest heartbeat row per node code, via the maintained pointer table."""
    codes = [node.code for node in nodes]
    if not codes:
        return {}

    pointers = db.query(NodeHeartbeatLatest).filter(NodeHeartbeatLatest.node_code.in_(codes)).all()
    beats: dict[str, NodeHeartbeat] = {}
    for pointer in pointers:
        if not pointer.heartbeat_id:
            continue
        beat = db.get(NodeHeartbeat, pointer.heartbeat_id)
        if beat is not None:
            beats[pointer.node_code] = beat
    return beats


def _latest_readings(
    db: Session, nodes: list[Node], contexts: str | None
) -> dict[int, EnergyReading]:
    """Newest reading per node — one indexed seek each.

    Deliberately a query per node rather than a single grouped aggregate. The
    fleet is a handful of nodes, and ``ORDER BY timestamp DESC LIMIT 1`` under
    ``idx_readings_node_timestamp`` is an index seek, while
    ``MAX(timestamp) GROUP BY node_id`` scans every row the node ever wrote.
    Measured on the live database at 314k readings: 203 ms for the aggregate
    against 3 ms for these seeks — the difference between a snapshot that can
    be polled every few seconds and one that cannot.
    """
    latest: dict[int, EnergyReading] = {}
    for node in nodes:
        reading = (
            scope.production_readings(db, contexts)
            .filter(EnergyReading.node_id == node.id)
            .order_by(EnergyReading.timestamp.desc())
            .first()
        )
        if reading is not None:
            latest[node.id] = reading
    return latest


def _open_deployments(db: Session) -> dict[int, Deployment]:
    """The deployment each node is currently on — activated and not yet closed."""
    return {
        deployment.node_id: deployment
        for deployment in db.query(Deployment).all()
        if deployment.activated_at is not None and deployment.closed_at is None
    }


def alert_limits() -> dict[str, Any]:
    """The platform's own electrical limits, published so the page reuses them.

    The interface must not carry a second copy of these numbers. Every value
    here comes from :mod:`app.monitoring.config`, which is the same source the
    alerting rules resolve against, so a badge on this page and a Telegram alert
    agree by construction.
    """
    electrical = get_config().electrical
    thresholds = get_thresholds()
    return {
        "nominal_voltage": electrical.nominal_voltage,
        "voltage_deviation_warning_pct": electrical.voltage_deviation_warning,
        "voltage_deviation_critical_pct": electrical.voltage_deviation_critical,
        "missing_phase_voltage": electrical.missing_phase_voltage,
        "nominal_frequency_hz": electrical.nominal_frequency_hz,
        "frequency_deviation_warning_hz": electrical.frequency_deviation_warning,
        "frequency_deviation_critical_hz": electrical.frequency_deviation_critical,
        "power_factor_warning": electrical.power_factor_warning,
        "power_factor_critical": electrical.power_factor_critical,
        "current_warning_a": electrical.current_warning,
        "current_critical_a": electrical.current_critical,
        "voltage_imbalance_warning_pct": electrical.voltage_imbalance_warning,
        "voltage_imbalance_critical_pct": electrical.voltage_imbalance_critical,
        "current_imbalance_warning_pct": electrical.current_imbalance_warning,
        "current_imbalance_critical_pct": electrical.current_imbalance_critical,
        # Below this current the phase spread is ADC noise, not imbalance. The
        # rules guard on it and so must any badge derived from the same idea.
        "imbalance_min_current_a": electrical.imbalance_min_current_a,
        # Seconds without a heartbeat or a reading before the node reads stale.
        # Same constant /api/metrics/live uses for rpi_status / shelly_status.
        "node_offline_timeout_s": float(thresholds.get("nodeOfflineTimeout", 300)),
    }


# --------------------------------------------------------------------------
# Snapshot
# --------------------------------------------------------------------------


def snapshot(db: Session, node_ids: str | None = None, contexts: str | None = "all") -> dict:
    """Instantaneous state of each node: last reading, freshness and health.

    Contexts default to *all*, not to the production set. This view answers
    "what is the hardware doing", and a node measuring under
    ``infrastructure_validation`` is still measuring — hiding it would make a
    working node look dead. The context each reading was stored under is
    returned alongside it so nothing is silently mixed.
    """
    now = datetime.utcnow()
    nodes = _requested_nodes(db, node_ids)
    readings = _latest_readings(db, nodes, contexts)
    beats = _latest_heartbeats(db, nodes)
    deployments = _open_deployments(db)
    offline_after = float(get_thresholds().get("nodeOfflineTimeout", 300))

    today_buckets = agg.hourly_energy(db, start=_local_day_start(), contexts=contexts)
    energy_today: dict[int, float] = {}
    for bucket in today_buckets:
        energy_today[bucket.node_id] = energy_today.get(bucket.node_id, 0.0) + bucket.kwh

    payload = []
    for node in nodes:
        reading = readings.get(node.id)
        beat = beats.get(node.code)
        deployment = deployments.get(node.id)

        reading_age = _age(reading.timestamp if reading else None, now)
        sync_age = _age(node.last_sync, now)

        rpi_ok = sync_age is not None and sync_age <= offline_after
        shelly_ok = reading_age is not None and reading_age <= offline_after

        payload.append(
            {
                "node_id": node.code,
                "name": node.name,
                # Declared by the operator, never inferred. Drives the honest
                # degradation in the interface for non-Shelly hardware.
                "hardware_kind": node.hardware_kind,
                "measurement_context": node.measurement_context,
                "commission_state": node.commission_state,
                "status": "online" if rpi_ok else "offline",
                "rpi_status": "ok" if rpi_ok else "offline",
                "shelly_status": "ok" if shelly_ok else "offline",
                "last_sync": _iso(node.last_sync),
                "last_sync_age_seconds": sync_age,
                # A property of the reading, not of the node (ADR-0001).
                "last_reading_building": (
                    reading.building.name if reading and reading.building else None
                ),
                "deployment": (
                    {
                        "id": deployment.id,
                        "status": deployment.status,
                        "building": deployment.building.name if deployment.building else None,
                    }
                    if deployment is not None
                    else None
                ),
                "reading": (
                    {
                        "timestamp": _iso(reading.timestamp),
                        "age_seconds": reading_age,
                        "context": reading.context,
                        "phase_a_voltage": reading.phase_a_voltage,
                        "phase_b_voltage": reading.phase_b_voltage,
                        "phase_c_voltage": reading.phase_c_voltage,
                        "phase_a_current": reading.phase_a_current,
                        "phase_b_current": reading.phase_b_current,
                        "phase_c_current": reading.phase_c_current,
                        # The meter's own per-phase figures (M15). NULL on every
                        # reading stored before the collector was updated.
                        "phase_a_power_kw": reading.phase_a_power_kw,
                        "phase_b_power_kw": reading.phase_b_power_kw,
                        "phase_c_power_kw": reading.phase_c_power_kw,
                        "phase_a_apparent_kva": reading.phase_a_apparent_kva,
                        "phase_b_apparent_kva": reading.phase_b_apparent_kva,
                        "phase_c_apparent_kva": reading.phase_c_apparent_kva,
                        "phase_a_power_factor": reading.phase_a_power_factor,
                        "phase_b_power_factor": reading.phase_b_power_factor,
                        "phase_c_power_factor": reading.phase_c_power_factor,
                        "phase_a_frequency_hz": reading.phase_a_frequency_hz,
                        "phase_b_frequency_hz": reading.phase_b_frequency_hz,
                        "phase_c_frequency_hz": reading.phase_c_frequency_hz,
                        # Averaged across energised phases by the collector, and
                        # summed across them respectively — named so no reader
                        # mistakes one for a single-phase measurement.
                        "voltage_avg": reading.voltage,
                        "current_total": reading.current,
                        "power_kw": reading.power_kw,
                        "apparent_kva": reading.apparent_kva,
                        "power_factor": reading.power_factor,
                        "frequency_hz": reading.frequency_hz,
                        # NULL where no neutral CT is installed. Not zero.
                        "neutral_current": reading.neutral_current,
                        # The device's own cumulative registers. Reconciliation
                        # only — no analytic differences these (ADR-0007).
                        "meter_energy_kwh": reading.meter_energy_kwh,
                        "meter_energy_returned_kwh": reading.meter_energy_returned_kwh,
                        "phase_a_energy_imported_kwh": reading.phase_a_energy_imported_kwh,
                        "phase_b_energy_imported_kwh": reading.phase_b_energy_imported_kwh,
                        "phase_c_energy_imported_kwh": reading.phase_c_energy_imported_kwh,
                        "phase_a_energy_returned_kwh": reading.phase_a_energy_returned_kwh,
                        "phase_b_energy_returned_kwh": reading.phase_b_energy_returned_kwh,
                        "phase_c_energy_returned_kwh": reading.phase_c_energy_returned_kwh,
                    }
                    if reading is not None
                    else None
                ),
                "energy_today_kwh": round(energy_today.get(node.id, 0.0), 4),
                "available_metrics": _available_metrics(reading),
                "health": _health(beat, now),
            }
        )

    return {
        "generated_at": _iso(now),
        "limits": alert_limits(),
        "nodes": payload,
    }


def _health(beat: NodeHeartbeat | None, now: datetime) -> dict | None:
    """Node condition from its newest heartbeat, or ``None`` if it never sent one.

    Returning ``None`` rather than a dictionary of nulls is deliberate: "this
    node has no heartbeat agent" and "this node reported 0 % CPU" are different
    facts and the interface renders them differently.
    """
    if beat is None:
        return None
    return {
        "reported_at": _iso(beat.reported_at),
        "received_at": _iso(beat.received_at),
        "age_seconds": _age(beat.received_at, now),
        "clock_drift_seconds": beat.clock_drift_seconds,
        "collector_status": beat.collector_status,
        "collector_restarts": beat.collector_restarts,
        # Rows written but not yet accepted by the backend. This is the number a
        # technician watches: a buffer that only grows means uploads are being
        # refused, not that the node is dead.
        "buffered_readings": beat.buffered_readings,
        "pending_sync": beat.pending_sync,
        "last_measurement_at": _iso(beat.last_measurement_at),
        "cpu_percent": beat.cpu_percent,
        "cpu_temperature_c": beat.cpu_temperature_c,
        "memory_percent": beat.memory_percent,
        "disk_percent": beat.disk_percent,
        "disk_free_mb": beat.disk_free_mb,
        "uptime_seconds": beat.uptime_seconds,
        "undervoltage": beat.undervoltage,
        "throttled": beat.throttled,
        "throttle_flags": beat.throttle_flags,
        "filesystem_readonly": beat.filesystem_readonly,
        "ethernet_up": beat.ethernet_up,
        "wifi_up": beat.wifi_up,
        "sqlite_size_mb": beat.sqlite_size_mb,
        "software_version": beat.software_version,
        # Present only on nodes whose collector probes them; null elsewhere and
        # rendered as "no disponible", never as a failure.
        "ads_ok": beat.ads_ok,
        "shelly_reachable": beat.shelly_reachable,
        # The METER's temperature, not the Pi's (cpu_temperature_c above).
        # Health telemetry, deliberately never an energy_readings column.
        "meter_temperature_c": beat.meter_temperature_c,
        # Free-text notices the node raised about itself (UPS state, throttle
        # flags, retained rows). Stored as a JSON string; decoded here so the
        # interface never parses a column format.
        "local_alerts": _decode_alerts(beat.local_alerts),
    }


def _decode_alerts(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return [raw]
    return [str(item) for item in decoded] if isinstance(decoded, list) else [str(decoded)]


# --------------------------------------------------------------------------
# History
# --------------------------------------------------------------------------


@dataclass
class _Bucket:
    """Accumulator for one downsampled point."""

    stamp: datetime
    sums: dict[str, float]
    counts: dict[str, int]
    lows: dict[str, float]
    highs: dict[str, float]
    kwh: float
    samples: int


@dataclass(frozen=True)
class Window:
    """The span a request covers, how it will be bucketed, and what it scopes to."""

    key: str
    start: datetime
    end: datetime
    bucket_seconds: int
    #: Populated only for the deployment range, so the interface can name what
    #: it is looking at instead of showing a bare date span.
    deployments: list[dict]
    #: Set only for the deployment range. When present the query is scoped to
    #: **this deployment's readings**, not to a node set and a time span — the
    #: two are different questions, and only the first survives a node being
    #: redeployed to another building mid-window.
    deployment_id: int | None = None


def _adaptive_bucket(span_seconds: float) -> int:
    """Smallest ladder step that keeps a window under the point target.

    Falls through to the largest step rather than inventing a bigger one: a
    46-day deployment at 3600 s is ~1,100 points, slightly over target and still
    perfectly readable, whereas a 7200 s bucket nobody else uses would make that
    chart incomparable with every other view on the page.
    """
    for step in ADAPTIVE_STEPS:
        if span_seconds / step <= ADAPTIVE_TARGET_POINTS:
            return step
    return ADAPTIVE_STEPS[-1]


def _deployment_nodes(db: Session, deployment_id: int) -> list[Node]:
    """Nodes that actually produced readings for this deployment.

    Discovered from the readings rather than read off the deployment row. They
    normally agree, but attribution is resolved per measurement from its own
    ``captured_at``, so a handover can legitimately leave rows from two nodes
    inside one campaign — and the chart should show whatever is really there.

    The deployment's declared node is always included, so a campaign with no
    readings yet still renders its node rather than an empty page.
    """
    node_ids = {
        row[0]
        for row in db.query(EnergyReading.node_id)
        .filter(EnergyReading.deployment_id == deployment_id)
        .distinct()
        .all()
        if row[0] is not None
    }
    deployment = db.get(Deployment, deployment_id)
    if deployment is not None:
        node_ids.add(deployment.node_id)
    if not node_ids:
        return []
    return db.query(Node).filter(Node.id.in_(node_ids)).order_by(Node.code.asc()).all()


def _reading_census(db: Session, deployment: Deployment) -> tuple[int, int]:
    """``(readings inside the declared window, readings outside it)``.

    Both numbers are shown because they can disagree, and when they do the
    disagreement is the finding rather than a rendering problem.

    Deployment 5 is the live example: it declares 2026-06-14 → 06-21, and all
    4,499 readings carrying its id are stamped 2026-07-26 → 08-06 — entirely
    outside its own window. Charting it yields an empty axis, which looks like a
    broken page unless the interface can say *why*. Deployment 4 has the milder
    form of the same defect: it declares a window N001 has measured well past.

    Nothing is corrected here. Attribution is written once at ingest from each
    measurement's own ``captured_at`` and is never recomputed on read (ADR-0004);
    widening a window to make a chart look better would be exactly the silent
    retroactive attribution the platform forbids.
    """
    start, end = deployment.activated_at, deployment.closed_at
    base = db.query(EnergyReading).filter(EnergyReading.deployment_id == deployment.id)
    total = base.count()
    inside = base
    if start is not None:
        inside = inside.filter(EnergyReading.timestamp >= start)
    if end is not None:
        inside = inside.filter(EnergyReading.timestamp <= end)
    within = inside.count()
    return within, total - within


def _describe(deployment: Deployment, db: Session | None = None) -> dict:
    described = {
        "deployment_id": deployment.id,
        "node_id": deployment.node.code if deployment.node else None,
        "building": deployment.building.name if deployment.building else None,
        "status": deployment.status,
        "activated_at": _iso(deployment.activated_at),
        "closed_at": _iso(deployment.closed_at),
    }
    if db is not None:
        within, outside = _reading_census(db, deployment)
        described["readings_in_window"] = within
        described["readings_outside_window"] = outside
    return described


def list_deployments(db: Session) -> list[dict]:
    """Activated deployments, newest first — the range selector's options.

    Only activated ones: a planned deployment has no readings and no bounds, so
    offering it would produce an empty chart with an undefined axis.
    """
    rows = (
        db.query(Deployment)
        .filter(Deployment.activated_at.isnot(None))
        .order_by(Deployment.activated_at.desc())
        .all()
    )
    return [_describe(row, db) for row in rows]


def _deployment_window(db: Session, deployment_id: int | None, now: datetime) -> Window:
    """Bounds and scope for one campaign.

    A deployment is not "a node over a date range". It is a body of readings
    that carry its ``deployment_id``, and that distinction is the whole reason
    this range exists separately from the chronological ones:

    * A node can be redeployed mid-window. Scoping by node and date would pull
      in readings that belong to the *next* campaign, in a different building.
    * A campaign's readings are what its report, its CSV export and its cost
      attribution already use. Charting anything else would put a fourth
      definition of "this deployment's data" beside the three that agree.

    So the filter is ``deployment_id = N`` and the window is that deployment's
    own ``activated_at`` → ``closed_at`` (or now, while it is open). The nodes
    shown are whichever nodes actually produced those readings, discovered from
    the data rather than assumed from the deployment row.

    An earlier version took the union of every selected node's most recent
    campaign. With N003's June campaign and N001's August one selected together
    that produced a 65-day axis on which each node occupied a different sixth —
    technically honest, practically unreadable, and not what the range is for.
    Cross-node comparison belongs on the chronological ranges.
    """
    chosen = None
    if deployment_id is not None:
        chosen = (
            db.query(Deployment)
            .filter(Deployment.id == deployment_id, Deployment.activated_at.isnot(None))
            .first()
        )
    if chosen is None:
        # No deployment asked for, or an unknown one: fall back to the newest
        # activated campaign so the range is usable on first click, and say
        # which one was picked rather than silently choosing.
        chosen = (
            db.query(Deployment)
            .filter(Deployment.activated_at.isnot(None))
            .order_by(Deployment.activated_at.desc())
            .first()
        )

    if chosen is None:
        # Nothing has ever been deployed. Fall back to a recent window rather
        # than an empty chart with no axis at all.
        start = now - timedelta(seconds=RANGES["24h"])
        return Window("deployment", start, now, RESOLUTION["24h"], [])

    start = chosen.activated_at
    end = chosen.closed_at or now
    if end <= start:
        end = now

    return Window(
        key="deployment",
        start=start,
        end=end,
        bucket_seconds=_adaptive_bucket((end - start).total_seconds()),
        deployments=[_describe(chosen, db)],
        deployment_id=chosen.id,
    )


def _window(db: Session, range_key: str | None, deployment_id: int | None, now: datetime) -> Window:
    """Turn a range key into concrete bounds, a bucket width and a scope."""
    key, seconds, bucket_seconds = parse_range(range_key)
    if key == "deployment":
        return _deployment_window(db, deployment_id, now)
    return Window(key, now - timedelta(seconds=seconds), now, bucket_seconds, [])


def history(
    db: Session,
    node_ids: str | None = None,
    range_key: str | None = "15m",
    since: str | None = None,
    contexts: str | None = "all",
    deployment_id: int | None = None,
) -> dict:
    """Time series for the selected nodes over the selected window.

    ``since`` requests only the samples newer than a watermark the client
    already holds. It is honoured for raw ranges only: a bucketed point changes
    as its bucket fills, so serving an incremental slice of one would hand the
    client half-finished averages it could never correct. Bucketed ranges always
    return the whole window, and the caller is expected to refresh them slowly.
    """
    now = datetime.utcnow()
    window = _window(db, range_key, deployment_id, now)
    key, bucket_seconds = window.key, window.bucket_seconds
    window_start = window.start

    watermark = parse_since(since) if bucket_seconds == 0 else None
    incremental = watermark is not None and watermark > window_start
    query_start = watermark if incremental else window_start

    if window.deployment_id is not None:
        # The deployment defines its own scope. Node selection is ignored here
        # on purpose — asking for "deployment 4, but only N002" is asking for
        # readings that do not exist, and answering it with an empty chart would
        # look like a fault rather than a category error.
        nodes = _deployment_nodes(db, window.deployment_id)
    else:
        nodes = _requested_nodes(db, node_ids)

    by_id = {node.id: node for node in nodes}

    series: dict[int, list[dict]] = {node.id: [] for node in nodes}
    total_points = 0

    if (by_id or window.deployment_id is not None) and bucket_seconds > 0:
        for node_id, points in _bucketed_from_sql(
            db,
            list(by_id),
            window_start,
            window.end,
            bucket_seconds,
            contexts,
            deployment_id=window.deployment_id,
        ).items():
            if node_id in series:
                series[node_id] = points
                total_points += len(points)
    elif by_id:
        columns = [EnergyReading.id, EnergyReading.node_id, EnergyReading.timestamp] + [
            getattr(EnergyReading, column) for _, column in SERIES_FIELDS
        ]
        rows = (
            scope.production_readings(db, contexts)
            .with_entities(*columns)
            .filter(
                EnergyReading.node_id.in_(list(by_id)),
                (
                    EnergyReading.timestamp > query_start
                    if incremental
                    else EnergyReading.timestamp >= query_start
                ),
                # A closed deployment ends; without this bound its chart would
                # trail off into whatever the node measured afterwards, under a
                # different campaign and possibly a different building.
                EnergyReading.timestamp <= window.end,
            )
            .order_by(EnergyReading.node_id.asc(), EnergyReading.timestamp.asc())
            .all()
        )

        # Canonical per-reading energy. Asked for, never recomputed here — the
        # column it comes from has meant two different things (ADR-0007) and
        # only energy_aggregate knows which era each row belongs to.
        energy = agg.energy_by_reading_id(db, start=query_start, end=window.end, contexts=contexts)

        for node_id, points in _assemble(rows, energy, bucket_seconds).items():
            if node_id in series:
                series[node_id] = points
                total_points += len(points)

    return {
        "range": key,
        "start": _iso(query_start if incremental else window_start),
        "end": _iso(window.end),
        "window_start": _iso(window_start),
        "incremental": incremental,
        "resolution_seconds": bucket_seconds,
        "aggregation": (
            "raw — every stored sample"
            if bucket_seconds == 0
            else (
                f"mean over {bucket_seconds} s buckets; "
                f"min/max kept for {', '.join(EXTREMA_FIELDS)}; energy summed"
            )
        ),
        # Present only for the deployment range: which campaign each node's
        # points belong to, so the axis is identified rather than merely dated.
        "deployments": window.deployments,
        #: Which deployment the readings were scoped to, when scoped at all.
        "deployment_id": window.deployment_id,
        "point_count": total_points,
        "series": [
            {
                "node_id": by_id[node_id].code,
                "hardware_kind": by_id[node_id].hardware_kind,
                "points": points,
            }
            for node_id, points in series.items()
        ],
    }


def _bucketed_sql(node_ids: list[int], contexts_count: int, by_deployment: bool) -> str:
    """Build the grouped aggregate, generated from SERIES_FIELDS so it cannot drift.

    Bucketing in SQLite rather than in Python is not a micro-optimisation. A
    seven-day window is ~36,000 readings; materialising them as Python tuples
    and folding 33 fields over each cost 1.2 s of a **single-worker** backend,
    which is long enough to stall the 3 s snapshot poll queued behind it. The
    grouped query returns ~600 rows instead.

    SQLite's ``AVG``, ``MIN`` and ``MAX`` skip NULLs natively, which is exactly
    the semantics required: a field nobody reported inside a bucket yields NULL,
    never 0. ``COUNT(*)`` counts readings, not non-null values, so ``n`` still
    means "samples behind this point".
    """
    columns = [
        "node_id",
        "CAST(strftime('%s', timestamp) / :bucket AS INTEGER) AS bucket",
        "COUNT(*) AS n",
    ]
    columns += [f"AVG({column}) AS {key}" for key, column in SERIES_FIELDS]
    by_key = dict(SERIES_FIELDS)
    for key in EXTREMA_FIELDS:
        columns.append(f"MIN({by_key[key]}) AS {key}_min")
        columns.append(f"MAX({by_key[key]}) AS {key}_max")

    contexts = ", ".join(f":ctx{i}" for i in range(contexts_count))
    # Two different questions, two different filters. Scoping a deployment by
    # node and date would include readings the *next* campaign owns, in another
    # building, the moment a node is redeployed inside the window.
    if by_deployment:
        scope_clause = "deployment_id = :deployment_id"
    else:
        scope_clause = "node_id IN (" + ", ".join(f":node{i}" for i in range(len(node_ids))) + ")"
    return (
        f"SELECT {', '.join(columns)} FROM energy_readings "
        f"WHERE context IN ({contexts}) AND {scope_clause} "
        "AND timestamp >= :start AND timestamp <= :end "
        "GROUP BY node_id, bucket ORDER BY node_id, bucket"
    )


def _bucketed_from_sql(
    db: Session,
    node_ids: list[int],
    start: datetime,
    end: datetime,
    bucket_seconds: int,
    contexts: str | None,
    deployment_id: int | None = None,
) -> dict[int, list[dict]]:
    """Aggregate a window in the database and shape the rows into points.

    Scoped either to a node set over a time span (the chronological ranges) or
    to one deployment's readings (the deployment range). The energy service is
    scoped the same way, so the two halves of a point describe the same rows.
    """
    resolved = scope.resolve_contexts(db, contexts)
    by_deployment = deployment_id is not None
    if not resolved or (not node_ids and not by_deployment):
        return {}

    binds: dict[str, Any] = {
        "bucket": int(bucket_seconds),
        "start": start.strftime("%Y-%m-%d %H:%M:%S.%f"),
        "end": end.strftime("%Y-%m-%d %H:%M:%S.%f"),
    }
    for index, code in enumerate(resolved):
        binds[f"ctx{index}"] = code
    if by_deployment:
        binds["deployment_id"] = int(deployment_id)
    else:
        for index, node_id in enumerate(node_ids):
            binds[f"node{index}"] = node_id

    # Interval energy for the same buckets, from the canonical service. Asked
    # for, never recomputed here (ADR-0007), and keyed on the identical bucket
    # arithmetic so an energy bucket and a current bucket describe one instant.
    energy = agg.bucketed_energy(
        db,
        bucket_seconds,
        start=start,
        end=end,
        contexts=contexts,
        deployment_id=deployment_id,
    )

    out: dict[int, list[dict]] = {}
    for row in db.execute(text(_bucketed_sql(node_ids, len(resolved), by_deployment)), binds):
        mapping = row._mapping
        index = mapping["bucket"]
        point: dict[str, Any] = {
            "t": datetime.utcfromtimestamp(index * bucket_seconds).isoformat(),
            "n": mapping["n"],
        }
        for key, _ in SERIES_FIELDS:
            value = mapping[key]
            # Omitted, not nulled: absence and null mean the same thing to the
            # client, and twenty-two of these are empty on every reading stored
            # before M15.
            if value is not None:
                point[key] = _round(key, value)
        for key in EXTREMA_FIELDS:
            low, high = mapping[f"{key}_min"], mapping[f"{key}_max"]
            if low is not None:
                point[f"{key}_min"] = _round(key, low)
            if high is not None:
                point[f"{key}_max"] = _round(key, high)
        point["kwh"] = _round("kwh", energy.get((mapping["node_id"], index), 0.0))
        out.setdefault(mapping["node_id"], []).append(point)
    return out


def _assemble(rows, energy: dict[int, float], bucket_seconds: int) -> dict[int, list[dict]]:
    """Turn reading rows into per-node point lists, bucketing when asked to.

    Retained for the raw path and for :func:`_bucketed_points`, which is now
    exercised only by the tests that pin the Python and SQL aggregations against
    each other.
    """
    if bucket_seconds == 0:
        return _raw_points(rows, energy)
    return _bucketed_points(rows, energy, bucket_seconds)


def _raw_points(rows, energy: dict[int, float]) -> dict[int, list[dict]]:
    """One point per stored sample.

    A key whose value is NULL is **omitted** rather than serialised as
    ``"pa": null``. Absence and null mean the same thing to every consumer — the
    quantity was not measured at that instant — and the client already reads a
    missing key as null.

    This matters because of when the fields arrived. Thirty-three series are
    declared, and twenty-two of them are NULL on all 315,000 readings stored
    before M15, because the collector was discarding them. Serialising those
    nulls would have tripled a one-hour payload to carry no information at all;
    omitting them keeps historical windows exactly as cheap as they were and
    lets the payload grow only as real measurements arrive.
    """
    out: dict[int, list[dict]] = {}
    for row in rows:
        point: dict[str, Any] = {"t": row.timestamp.isoformat()}
        for index, (key, _) in enumerate(SERIES_FIELDS):
            # Offset by three: id, node_id and timestamp lead the row.
            value = _round(key, row[index + 3])
            if value is not None:
                point[key] = value
        point["kwh"] = _round("kwh", energy.get(row.id, 0.0))
        out.setdefault(row.node_id, []).append(point)
    return out


def _bucketed_points(rows, energy: dict[int, float], width: int) -> dict[int, list[dict]]:
    """Mean per bucket, skipping nulls per field so a gap never reads as zero."""
    buckets: dict[int, dict[int, _Bucket]] = {}

    for row in rows:
        epoch = int(row.timestamp.replace(tzinfo=UTC).timestamp())
        index = epoch // width
        per_node = buckets.setdefault(row.node_id, {})
        bucket = per_node.get(index)
        if bucket is None:
            bucket = _Bucket(
                stamp=datetime.utcfromtimestamp(index * width),
                sums={},
                counts={},
                lows={},
                highs={},
                kwh=0.0,
                samples=0,
            )
            per_node[index] = bucket

        bucket.samples += 1
        bucket.kwh += energy.get(row.id, 0.0)
        for offset, (key, _) in enumerate(SERIES_FIELDS):
            value = row[offset + 3]
            if value is None:
                continue
            bucket.sums[key] = bucket.sums.get(key, 0.0) + value
            bucket.counts[key] = bucket.counts.get(key, 0) + 1
            if key in EXTREMA_FIELDS:
                low = bucket.lows.get(key)
                high = bucket.highs.get(key)
                bucket.lows[key] = value if low is None else min(low, value)
                bucket.highs[key] = value if high is None else max(high, value)

    out: dict[int, list[dict]] = {}
    for node_id, per_node in buckets.items():
        points = []
        for index in sorted(per_node):
            bucket = per_node[index]
            point: dict[str, Any] = {"t": bucket.stamp.isoformat(), "n": bucket.samples}
            for key, _ in SERIES_FIELDS:
                count = bucket.counts.get(key, 0)
                # A field nobody reported in this bucket is omitted, never
                # averaged as zero. Emitting 0 would draw a line through a gap,
                # which is the single most misleading thing a monitoring chart
                # can do; omitting it leaves the gap visible as a gap.
                if count:
                    point[key] = _round(key, bucket.sums[key] / count)
            for key in EXTREMA_FIELDS:
                low = bucket.lows.get(key)
                high = bucket.highs.get(key)
                if low is not None:
                    point[f"{key}_min"] = _round(key, low)
                if high is not None:
                    point[f"{key}_max"] = _round(key, high)
            point["kwh"] = _round("kwh", bucket.kwh)
            points.append(point)
        out[node_id] = points
    return out
