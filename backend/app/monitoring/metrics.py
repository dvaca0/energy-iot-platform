"""Electrical, smart-plug and fleet metrics, and the rules built on them.

Electrical rules evaluate the *newest stored reading* per node, plus a trailing
baseline for change detection. They deliberately do not attempt to re-derive
anomaly detection that ``app/services/anomaly_engine.py`` already owns: this
module answers "is a measured value outside its safe band right now?", which is
a threshold question, not a modelling one.

Ordering matters for diagnosis
------------------------------
Physically impossible values are checked *before* out-of-band values. A CT
clamp reading 4000 A is not an overload, it is a broken sensor, and reporting
it as an overload sends an operator to inspect a panel that is fine. The
implausible-reading rule therefore suppresses the threshold rules for the same
node in the same tick, using the shared ``scratch`` space on the context.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    Building,
    Campus,
    Deployment,
    EnergyReading,
    Node,
    SmartPlug,
)
from app.monitoring.config import MonitoringConfig
from app.monitoring.lifecycle import policy_for
from app.monitoring.rules import Finding, RuleContext, Subsystem, rule, unavailable
from app.monitoring.severity import Severity

log = logging.getLogger("monitoring.metrics")


# --------------------------------------------------------------------------
# Collection
# --------------------------------------------------------------------------


def collect_metrics(session: Session, config: MonitoringConfig, now: datetime) -> dict[str, Any]:
    """Gather electrical, plug and fleet metrics for one tick."""
    metrics: dict[str, Any] = {}

    # --- Newest reading per node -------------------------------------------
    newest_ids = session.query(func.max(EnergyReading.id)).group_by(EnergyReading.node_id).all()
    latest_readings: dict[int, EnergyReading] = {}
    ids = [row[0] for row in newest_ids if row[0] is not None]
    if ids:
        for reading in session.query(EnergyReading).filter(EnergyReading.id.in_(ids)).all():
            latest_readings[reading.node_id] = reading
    metrics["latest_readings"] = latest_readings

    # --- Trailing baseline, for spike and drop detection --------------------
    # Compared against the previous hour rather than a long window, so a real
    # change in occupancy is not permanently masked by weeks of history.
    baseline_start = now - timedelta(hours=2)
    baseline_end = now - timedelta(hours=1)
    baselines: dict[int, float] = {}
    for node_id, avg_power in (
        session.query(EnergyReading.node_id, func.avg(EnergyReading.power_kw))
        .filter(
            EnergyReading.timestamp >= baseline_start,
            EnergyReading.timestamp < baseline_end,
            EnergyReading.power_kw.isnot(None),
        )
        .group_by(EnergyReading.node_id)
        .all()
    ):
        if avg_power is not None:
            baselines[node_id] = float(avg_power)
    metrics["power_baseline"] = baselines

    # Standard deviation of the same window, so "abnormal" can be expressed
    # relative to how much this panel normally moves rather than as a flat
    # percentage. A panel that swings 30% every morning should not be
    # described as spiking when it swings 30%.
    spread: dict[int, float] = {}
    for node_id, avg_power, samples in (
        session.query(
            EnergyReading.node_id,
            func.avg(EnergyReading.power_kw),
            func.count(EnergyReading.id),
        )
        .filter(
            EnergyReading.timestamp >= baseline_start,
            EnergyReading.timestamp < baseline_end,
            EnergyReading.power_kw.isnot(None),
        )
        .group_by(EnergyReading.node_id)
        .all()
    ):
        if not avg_power or samples < 10:
            continue
        variance = (
            session.query(
                func.avg(
                    (EnergyReading.power_kw - float(avg_power))
                    * (EnergyReading.power_kw - float(avg_power))
                )
            )
            .filter(
                EnergyReading.timestamp >= baseline_start,
                EnergyReading.timestamp < baseline_end,
                EnergyReading.power_kw.isnot(None),
                EnergyReading.node_id == node_id,
            )
            .scalar()
        )
        if variance and variance > 0:
            spread[node_id] = float(variance) ** 0.5
    metrics["power_stddev"] = spread

    # Learned current baseline per node, used instead of a flat amperage
    # constant. The old 200 A default sat near the 94th percentile of N001's
    # normal operation, which is why it fired 471 times in three days.
    metrics["current_baseline"] = _current_baselines(session, config, now)

    # --- Fleet and database counts -----------------------------------------
    day_start = now - timedelta(days=1)
    metrics["readings_today"] = (
        session.query(func.count(EnergyReading.id))
        .filter(EnergyReading.timestamp >= day_start)
        .scalar()
        or 0
    )
    metrics["readings_total"] = session.query(func.count(EnergyReading.id)).scalar() or 0
    metrics["node_count"] = session.query(func.count(Node.id)).scalar() or 0
    metrics["building_count"] = session.query(func.count(Building.id)).scalar() or 0
    metrics["campus_count"] = session.query(func.count(Campus.id)).scalar() or 0
    metrics["deployment_count"] = session.query(func.count(Deployment.id)).scalar() or 0
    metrics["active_deployment_count"] = (
        session.query(func.count(Deployment.id)).filter(Deployment.status == "active").scalar() or 0
    )

    # --- Smart plugs --------------------------------------------------------
    plugs = session.query(SmartPlug).all()
    metrics["plugs"] = plugs
    metrics["plug_count"] = len(plugs)
    metrics["plug_online"] = sum(1 for plug in plugs if plug.online)

    return metrics


def _current_baselines(
    session: Session, config: MonitoringConfig, now: datetime
) -> dict[int, dict[str, Any]]:
    """Learned current envelope per node, from operational-deployment data only.

    Delegates to ``thresholds.learned_baseline``, which owns the definition of
    "clean operational data". Collected once per tick here so no rule
    recomputes it.
    """
    from app.monitoring.thresholds import learned_baseline

    out: dict[int, dict[str, Any]] = {}
    for (node_id,) in session.query(Node.id).all():
        out[node_id] = learned_baseline(session, node_id, config, now)
    return out


def _current_threshold(ctx: RuleContext, node, deployment):
    """Resolved current thresholds for one node, with provenance.

    The ordering, the physical-ceiling cap and the fallbacks all live in
    ``app/monitoring/thresholds.py``; this only supplies the collected baseline.
    """
    from app.monitoring.thresholds import resolve_current_thresholds

    baseline = (ctx.metrics.get("current_baseline") or {}).get(getattr(node, "id", None))
    return resolve_current_thresholds(node, deployment, ctx.config, baseline=baseline)


def _deviation_pct(value: float, nominal: float) -> float:
    """Absolute percentage deviation from a nominal value."""
    if nominal == 0:
        return 0.0
    return abs(value - nominal) / nominal * 100.0


def _imbalance_pct(values: list[float]) -> float | None:
    """Maximum percentage spread across phases, relative to the mean.

    Returns ``None`` when fewer than two phases carry a usable value, so a
    single-phase installation is not reported as perfectly balanced (which
    would be meaningless) nor as imbalanced (which would be wrong).
    """
    usable = [value for value in values if value is not None and value > 0]
    if len(usable) < 2:
        return None
    mean = sum(usable) / len(usable)
    if mean == 0:
        return None
    return max(abs(value - mean) for value in usable) / mean * 100.0


def _location_from_reading(
    session: Session, reading: EnergyReading, node: Node | None
) -> dict[str, Any]:
    """Location fields for an electrical finding."""
    deployment = reading.deployment
    building = deployment.building if deployment else None
    campus = building.campus if building else None
    return {
        "node_code": node.code if node else None,
        "node_id": reading.node_id,
        "campus": campus.name if campus else None,
        "building": building.name if building else None,
        "deployment": (
            f"{deployment.start_date} → {deployment.end_date} ({deployment.status})"
            if deployment
            else None
        ),
    }


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------

#: Key under which the implausible-reading rule marks nodes whose readings
#: should not be threshold-checked this tick.
_SUPPRESS_KEY = "electrical_suppressed_nodes"


def _electrical_nodes(ctx: RuleContext) -> dict[int, Any]:
    """Readings for nodes whose lifecycle permits electrical alerting.

    **The single most important gate in the alerting policy.** Electrical
    thresholds only mean something while a deployment is running: a node on a
    shelf, or one whose campaign ended, produces readings that are either
    absent, zero, or from a CT clamped to nothing. Alerting on them is noise by
    construction.

    Measured on the first production run: 98% of all alert messages came from
    nodes with no active deployment.
    """
    allowed: dict[int, Any] = {}
    suppressed: set[int] = ctx.scratch.get(_SUPPRESS_KEY, set())

    # Map node id -> lifecycle-annotated state.
    by_id = {
        state.get("node_id"): state
        for state in ctx.nodes.values()
        if state.get("node_id") is not None
    }

    for node_id, reading in (ctx.metrics.get("latest_readings") or {}).items():
        if node_id in suppressed:
            continue
        state = by_id.get(node_id)
        if state is None:
            continue
        if not policy_for(state).electrical:
            continue
        allowed[node_id] = reading

    return allowed


@rule("electrical.implausible", Subsystem.ELECTRICAL, "Physically impossible readings")
def check_implausible(ctx: RuleContext) -> Iterable[Finding]:
    """Values that cannot be real, which indicate a sensor fault.

    Runs before the threshold rules and suppresses them for the same node, so
    a broken CT is reported as a broken CT rather than as an overload.
    """
    findings: list[Finding] = []
    suppressed: set[int] = ctx.scratch.setdefault(_SUPPRESS_KEY, set())
    limits = ctx.config.electrical

    for node_id, reading in (ctx.metrics.get("latest_readings") or {}).items():
        node = ctx.session.get(Node, node_id)
        problems: list[str] = []

        for label, value, ceiling in (
            ("voltage", reading.voltage, limits.impossible_voltage_max),
            ("current", reading.current, limits.impossible_current_max),
        ):
            if value is None:
                continue
            if value < 0:
                problems.append(f"{label} is negative ({value:.2f})")
            elif value > ceiling:
                problems.append(f"{label} is {value:.1f}, above the physical ceiling {ceiling:.0f}")

        if reading.power_factor is not None and not (-1.0 <= reading.power_factor <= 1.0):
            problems.append(f"power factor is {reading.power_factor:.2f}, outside [-1, 1]")

        if not problems:
            continue

        suppressed.add(node_id)
        findings.append(
            Finding(
                rule_id="electrical.implausible",
                subsystem=Subsystem.ELECTRICAL,
                severity=Severity.ERROR,
                title=f"Node {node.code if node else node_id} is reporting impossible values",
                target=str(node.code if node else node_id),
                summary=(
                    "These values are not physically possible, so this is a measurement "
                    "fault rather than an electrical event. " + "; ".join(problems)
                ),
                metric="plausibility",
                current_value="; ".join(problems),
                expected_value="values within physical limits",
                suggested_causes=[
                    "CT clamp disconnected, reversed or on the wrong conductor",
                    "ADC reference or wiring fault",
                    "Undervoltage on the Pi destabilising the ADC",
                    "Calibration constant wrong after a configuration change",
                ],
                suggested_commands=[
                    "i2cdetect -y 1",
                    "journalctl -u energy-collector -n 100 --no-pager",
                    "vcgencmd get_throttled",
                ],
                suggested_actions=[
                    "Do not treat this as an electrical event. Inspect the sensor chain "
                    "before trusting any reading from this node.",
                ],
                **_location_from_reading(ctx.session, reading, node),
            )
        )

    return findings


@rule("electrical.voltage", Subsystem.ELECTRICAL, "Voltage band")
def check_voltage(ctx: RuleContext) -> Iterable[Finding]:
    findings: list[Finding] = []
    limits = ctx.config.electrical
    suppressed: set[int] = ctx.scratch.get(_SUPPRESS_KEY, set())

    for node_id, reading in _electrical_nodes(ctx).items():
        if reading.voltage is None:
            continue

        deviation = _deviation_pct(reading.voltage, limits.nominal_voltage)
        severity = ctx.threshold_severity(
            deviation,
            limits.voltage_deviation_warning,
            limits.voltage_deviation_critical,
        )
        if severity is Severity.OK:
            continue

        node = ctx.session.get(Node, node_id)
        high = reading.voltage > limits.nominal_voltage
        findings.append(
            Finding(
                rule_id="electrical.voltage_high" if high else "electrical.voltage_low",
                subsystem=Subsystem.ELECTRICAL,
                severity=severity,
                title=(
                    f"Node {node.code if node else node_id} voltage is "
                    + ("high" if high else "low")
                ),
                target=str(node.code if node else node_id),
                metric="voltage",
                current_value=f"{reading.voltage:.1f} V ({deviation:.1f}% from nominal)",
                expected_value=f"{limits.nominal_voltage:.0f} V ±{limits.voltage_deviation_warning:.0f}%",
                suggested_causes=(
                    ["Light loading on the transformer", "Utility regulation"]
                    if high
                    else [
                        "Heavy load on the feeder",
                        "Long or undersized conductor run",
                        "Utility supply sag",
                    ]
                ),
                suggested_actions=[
                    "Sustained deviation stresses connected equipment; correlate with "
                    "load before escalating to the utility.",
                ],
                **_location_from_reading(ctx.session, reading, node),
            )
        )

    return findings


@rule("electrical.frequency", Subsystem.ELECTRICAL, "Frequency band")
def check_frequency(ctx: RuleContext) -> Iterable[Finding]:
    findings: list[Finding] = []
    limits = ctx.config.electrical
    suppressed: set[int] = ctx.scratch.get(_SUPPRESS_KEY, set())

    for node_id, reading in _electrical_nodes(ctx).items():
        if reading.frequency_hz is None:
            continue
        # A frequency of exactly zero means the meter is not measuring, which
        # the sensor rules cover; treating it as a grid excursion would be wrong.
        if reading.frequency_hz <= 0:
            continue

        deviation = abs(reading.frequency_hz - limits.nominal_frequency_hz)
        severity = ctx.threshold_severity(
            deviation,
            limits.frequency_deviation_warning,
            limits.frequency_deviation_critical,
        )
        if severity is Severity.OK:
            continue

        node = ctx.session.get(Node, node_id)
        findings.append(
            Finding(
                rule_id="electrical.frequency",
                subsystem=Subsystem.ELECTRICAL,
                severity=severity,
                title=f"Node {node.code if node else node_id} frequency is out of band",
                target=str(node.code if node else node_id),
                metric="frequency_hz",
                current_value=f"{reading.frequency_hz:.2f} Hz",
                expected_value=(
                    f"{limits.nominal_frequency_hz:.0f} ±{limits.frequency_deviation_warning} Hz"
                ),
                suggested_causes=[
                    "Grid disturbance",
                    "Site running on a generator",
                    "Meter measurement error",
                ],
                suggested_actions=[
                    "Grid frequency rarely moves this far. Confirm the reading against a "
                    "second source before acting on it.",
                ],
                **_location_from_reading(ctx.session, reading, node),
            )
        )

    return findings


@rule("electrical.current", Subsystem.ELECTRICAL, "Current above threshold")
def check_current(ctx: RuleContext) -> Iterable[Finding]:
    findings: list[Finding] = []
    limits = ctx.config.electrical
    suppressed: set[int] = ctx.scratch.get(_SUPPRESS_KEY, set())

    for node_id, reading in _electrical_nodes(ctx).items():
        if reading.current is None:
            continue

        node = ctx.session.get(Node, node_id)
        code = node.code if node else None
        resolved = _current_threshold(ctx, node, reading.deployment)

        if not resolved.known:
            continue

        severity = ctx.threshold_severity(reading.current, resolved.warning, resolved.critical)
        # A configured emergency limit outranks the ladder: past the breaker
        # rating the protective device should already have operated.
        if resolved.emergency is not None and reading.current >= resolved.emergency:
            severity = Severity.EMERGENCY
        if severity is Severity.OK:
            continue

        warning = resolved.warning
        basis = resolved.source
        baseline = (ctx.metrics.get("current_baseline") or {}).get(node_id) or {}
        findings.append(
            Finding(
                rule_id="electrical.current",
                subsystem=Subsystem.ELECTRICAL,
                severity=severity,
                title=f"Node {code or node_id} current is high",
                target=str(code or node_id),
                summary=(
                    "Sustained current well above this panel's own normal envelope. "
                    f"Threshold basis: {basis}."
                ),
                metric="current",
                current_value=f"{reading.current:.1f} A",
                expected_value=f"< {warning:.0f} A ({basis})",
                # Half an hour by default: a panel briefly pulling high current
                # while a motor starts is not an event, half an hour there is.
                # A deployment or node may state its own requirement.
                sustain_seconds=resolved.sustained_seconds or 1800,
                suggested_causes=[
                    "Load added to the panel",
                    "Equipment fault drawing excess current",
                    "Approaching the panel or CT rating",
                ],
                suggested_actions=[
                    "Compare against the panel rating and the contracted demand.",
                    "Set an explicit rating in monitoring_config.json "
                    "(electrical.current_limit_by_node) — it is more meaningful "
                    "than a learned baseline.",
                ],
                context={
                    "baseline": baseline,
                    "threshold_basis": basis,
                    "physical_ceiling_a": resolved.physical_ceiling,
                    "warning_a": resolved.warning,
                    "critical_a": resolved.critical,
                    "emergency_a": resolved.emergency,
                },
                **_location_from_reading(ctx.session, reading, node),
            )
        )

    return findings


@rule("electrical.power_factor", Subsystem.ELECTRICAL, "Power factor")
def check_power_factor(ctx: RuleContext) -> Iterable[Finding]:
    findings: list[Finding] = []
    limits = ctx.config.electrical
    suppressed: set[int] = ctx.scratch.get(_SUPPRESS_KEY, set())

    for node_id, reading in _electrical_nodes(ctx).items():
        if reading.power_factor is None:
            continue
        # Power factor is undefined at negligible load and drifts wildly there;
        # flagging it would produce constant noise overnight.
        if reading.power_kw is not None and abs(reading.power_kw) < 0.1:
            continue

        # Lower is worse, so the comparison is inverted.
        severity = ctx.threshold_severity(
            reading.power_factor,
            limits.power_factor_warning,
            limits.power_factor_critical,
            inverted=True,
        )
        if severity is Severity.OK:
            continue

        node = ctx.session.get(Node, node_id)
        findings.append(
            Finding(
                rule_id="electrical.power_factor",
                subsystem=Subsystem.ELECTRICAL,
                severity=severity,
                title=f"Node {node.code if node else node_id} power factor is low",
                target=str(node.code if node else node_id),
                summary=(
                    "Low power factor increases billed demand without increasing useful "
                    "work, and is penalised under GDMTH."
                ),
                metric="power_factor",
                current_value=f"{reading.power_factor:.2f}",
                expected_value=f"≥ {limits.power_factor_warning:.2f}",
                suggested_causes=[
                    "Large inductive load (motors, HVAC) without correction",
                    "Capacitor bank failed or switched out",
                ],
                suggested_actions=["Review reactive compensation for this panel."],
                # A chronic condition measured continuously, not an incident
                # that worsens. EMERGENCY is reserved for a threat to the
                # installation or the platform.
                max_severity=Severity.CRITICAL,
                **_location_from_reading(ctx.session, reading, node),
            )
        )

    return findings


@rule("electrical.phases", Subsystem.ELECTRICAL, "Missing phase and imbalance")
def check_phases(ctx: RuleContext) -> Iterable[Finding]:
    """Missing phases, voltage imbalance and current imbalance.

    Imbalance is only meaningful on a genuinely three-phase installation, so
    single-phase nodes are skipped rather than reported as balanced.
    """
    findings: list[Finding] = []
    limits = ctx.config.electrical
    suppressed: set[int] = ctx.scratch.get(_SUPPRESS_KEY, set())

    for node_id, reading in _electrical_nodes(ctx).items():
        node = ctx.session.get(Node, node_id)
        location = _location_from_reading(ctx.session, reading, node)
        label = str(node.code if node else node_id)

        voltages = [
            reading.phase_a_voltage,
            reading.phase_b_voltage,
            reading.phase_c_voltage,
        ]
        currents = [
            reading.phase_a_current,
            reading.phase_b_current,
            reading.phase_c_current,
        ]

        present = [v for v in voltages if v is not None]
        if len(present) < 2:
            continue  # single-phase or unreported; nothing to compare

        # A phase that reads near zero while its siblings are energised.
        energised = [v for v in present if v >= limits.missing_phase_voltage]
        dead = [
            index
            for index, value in enumerate(voltages)
            if value is not None and value < limits.missing_phase_voltage
        ]
        if energised and dead:
            names = ", ".join("ABC"[index] for index in dead)
            findings.append(
                Finding(
                    rule_id="electrical.missing_phase",
                    subsystem=Subsystem.ELECTRICAL,
                    severity=Severity.CRITICAL,
                    title=f"Node {label} has a missing phase",
                    target=label,
                    summary=f"Phase {names} is unenergised while the others are live.",
                    metric="phase_voltage",
                    current_value=", ".join(
                        f"{'ABC'[i]}={v:.0f}V" for i, v in enumerate(voltages) if v is not None
                    ),
                    expected_value=f"all phases ≥ {limits.missing_phase_voltage:.0f} V",
                    suggested_causes=[
                        "Blown fuse or tripped single-pole breaker",
                        "Utility phase loss",
                        "Voltage lead disconnected at the meter",
                    ],
                    suggested_commands=[],
                    suggested_actions=[
                        "Three-phase equipment on this panel can be damaged by single-"
                        "phasing. Verify at the panel before assuming a sensor fault.",
                    ],
                    **location,
                )
            )
            continue

        imbalance = _imbalance_pct([v for v in voltages if v is not None])
        severity = ctx.threshold_severity(
            imbalance,
            limits.voltage_imbalance_warning,
            limits.voltage_imbalance_critical,
        )
        if severity is not Severity.OK:
            findings.append(
                Finding(
                    rule_id="electrical.voltage_imbalance",
                    subsystem=Subsystem.ELECTRICAL,
                    severity=severity,
                    title=f"Node {label} voltage imbalance",
                    target=label,
                    metric="voltage_imbalance_pct",
                    current_value=f"{imbalance:.1f}%",
                    expected_value=f"< {limits.voltage_imbalance_warning:.0f}%",
                    suggested_causes=[
                        "Uneven single-phase loading",
                        "Loose or corroded connection",
                    ],
                    suggested_actions=[
                        "Voltage imbalance causes disproportionate current imbalance in "
                        "motors and overheats them.",
                    ],
                    max_severity=Severity.CRITICAL,
                    **location,
                )
            )

        # Only evaluate imbalance under real load. At the noise floor the
        # phases read ~1e-5 A and their percentage spread is arbitrary, which
        # would otherwise report a permanent CRITICAL on every idle panel.
        measured = [c for c in currents if c is not None]
        loaded = measured and max(measured) >= limits.imbalance_min_current_a

        current_imbalance = _imbalance_pct(measured) if loaded else None
        severity = ctx.threshold_severity(
            current_imbalance,
            limits.current_imbalance_warning,
            limits.current_imbalance_critical,
        )
        if severity is not Severity.OK:
            findings.append(
                Finding(
                    rule_id="electrical.current_imbalance",
                    subsystem=Subsystem.ELECTRICAL,
                    severity=severity,
                    title=f"Node {label} current imbalance",
                    target=label,
                    metric="current_imbalance_pct",
                    current_value=f"{current_imbalance:.1f}%",
                    expected_value=f"< {limits.current_imbalance_warning:.0f}%",
                    suggested_causes=[
                        "Single-phase loads unevenly distributed across phases",
                        "A CT clamp on the wrong conductor or reversed",
                    ],
                    suggested_actions=["Rebalance single-phase loads across the three phases."],
                    max_severity=Severity.CRITICAL,
                    **location,
                )
            )

    return findings


@rule("electrical.consumption", Subsystem.ELECTRICAL, "Consumption spikes, drops and outages")
def check_consumption(ctx: RuleContext) -> Iterable[Finding]:
    """Change detection against the trailing hourly baseline."""
    findings: list[Finding] = []
    limits = ctx.config.electrical
    suppressed: set[int] = ctx.scratch.get(_SUPPRESS_KEY, set())
    baselines = ctx.metrics.get("power_baseline") or {}

    for node_id, reading in _electrical_nodes(ctx).items():
        if reading.power_kw is None:
            continue

        node = ctx.session.get(Node, node_id)
        label = str(node.code if node else node_id)
        location = _location_from_reading(ctx.session, reading, node)

        # Total loss of load on a panel that was drawing power.
        baseline = baselines.get(node_id)
        if baseline is not None and baseline > 0.2 and reading.power_kw <= 0.01:
            findings.append(
                Finding(
                    rule_id="electrical.power_loss",
                    subsystem=Subsystem.ELECTRICAL,
                    severity=Severity.CRITICAL,
                    title=f"Node {label} shows no power on a previously loaded panel",
                    target=label,
                    summary=(
                        f"Baseline was {baseline:.2f} kW an hour ago; the panel now reads " "zero."
                    ),
                    metric="power_kw",
                    current_value=f"{reading.power_kw:.3f} kW",
                    expected_value=f"~{baseline:.2f} kW",
                    suggested_causes=[
                        "Supply interruption to the panel",
                        "Main breaker tripped",
                        "CT clamp fell off the conductor",
                    ],
                    suggested_actions=[
                        "Distinguish a real outage from a sensor that stopped reading: "
                        "check whether voltage is still present.",
                    ],
                    context={"baseline_kw": baseline},
                    **location,
                )
            )
            continue

        if baseline is None or baseline <= 0.05:
            continue  # no usable baseline; change detection would be noise

        change = (reading.power_kw - baseline) / baseline * 100.0

        # Contracted demand is the case that genuinely costs money, so it is
        # evaluated first and on its own terms — a modest percentage rise that
        # threatens the contracted limit matters far more than a large one that
        # does not.
        contracted = (limits.contracted_demand_kw or {}).get(label)
        if contracted and reading.power_kw >= contracted * limits.contracted_demand_ratio:
            findings.append(
                Finding(
                    rule_id="electrical.contracted_demand",
                    subsystem=Subsystem.ELECTRICAL,
                    severity=Severity.WARNING,
                    title=f"Node {label} approaching contracted demand",
                    target=label,
                    summary=(
                        f"Drawing {reading.power_kw:.1f} kW against a contracted "
                        f"{contracted:.0f} kW. Exceeding it carries a tariff penalty."
                    ),
                    metric="power_kw",
                    current_value=f"{reading.power_kw:.2f} kW",
                    expected_value=f"< {contracted * limits.contracted_demand_ratio:.1f} kW",
                    sustain_seconds=900,
                    suggested_actions=["Shed non-essential load before the interval closes."],
                    context={"contracted_kw": contracted},
                    **location,
                )
            )

        # A spike must clear three independent bars: a large percentage, a
        # departure from this panel's own variability, and persistence. Any one
        # alone describes normal operation — loads start, air conditioning
        # cycles, people use electricity.
        stddev = (ctx.metrics.get("power_stddev") or {}).get(node_id)
        sigma_ok = (
            stddev is not None
            and stddev > 0
            and (reading.power_kw - baseline) >= limits.consumption_spike_sigma * stddev
        )

        if change >= limits.consumption_spike_pct and sigma_ok:
            findings.append(
                Finding(
                    rule_id="electrical.consumption_spike",
                    subsystem=Subsystem.ELECTRICAL,
                    severity=Severity.WARNING,
                    title=f"Node {label} consumption spike",
                    target=label,
                    summary=(
                        f"Load is {change:.0f}% above the trailing hour and "
                        f"{(reading.power_kw - baseline) / stddev:.1f} standard deviations "
                        "outside this panel's normal variability."
                    ),
                    metric="power_kw",
                    current_value=f"{reading.power_kw:.2f} kW (+{change:.0f}%)",
                    expected_value=f"~{baseline:.2f} kW (σ={stddev:.2f})",
                    # Sustained for half an hour, not a starting transient.
                    sustain_seconds=1800,
                    suggested_causes=["Equipment started", "HVAC load", "Schedule change"],
                    suggested_actions=[
                        "Check whether this pushes the site toward its contracted demand.",
                    ],
                    context={
                        "baseline_kw": baseline,
                        "change_pct": round(change, 1),
                        "stddev_kw": round(stddev, 3),
                    },
                    **location,
                )
            )
        elif change <= -limits.consumption_drop_pct:
            findings.append(
                Finding(
                    rule_id="electrical.consumption_drop",
                    subsystem=Subsystem.ELECTRICAL,
                    severity=Severity.INFO,
                    title=f"Node {label} consumption dropped sharply",
                    target=label,
                    metric="power_kw",
                    current_value=f"{reading.power_kw:.2f} kW ({change:.0f}%)",
                    expected_value=f"~{baseline:.2f} kW",
                    suggested_causes=[
                        "Equipment switched off",
                        "End of occupancy",
                        "A CT clamp that came loose",
                    ],
                    context={"baseline_kw": baseline, "change_pct": round(change, 1)},
                    **location,
                )
            )

    return findings


@rule(
    "electrical.no_consumption",
    Subsystem.ELECTRICAL,
    "Voltage present but no current on an active deployment",
)
def check_no_consumption(ctx: RuleContext) -> Iterable[Finding]:
    """A live panel drawing nothing, which usually means a detached CT.

    Voltage present with current at the noise floor is the classic signature of
    a CT clamp that has fallen off or was never closed around the conductor —
    the meter still sees the phase, but measures no load through it.

    Restricted to *active* deployments. A panel that is genuinely idle, or a
    node between campaigns, is not a fault, and alerting on it would train the
    reader to ignore this rule.
    """
    findings: list[Finding] = []
    limits = ctx.config.electrical
    suppressed: set[int] = ctx.scratch.get(_SUPPRESS_KEY, set())

    for node_id, reading in _electrical_nodes(ctx).items():

        if reading.voltage is None or reading.voltage < limits.missing_phase_voltage:
            continue  # no voltage either: that is a supply problem, not a CT problem

        currents = [
            value
            for value in (
                reading.phase_a_current,
                reading.phase_b_current,
                reading.phase_c_current,
                reading.current,
            )
            if value is not None
        ]
        if not currents or max(currents) >= limits.imbalance_min_current_a:
            continue

        node = ctx.session.get(Node, node_id)
        label = str(node.code if node else node_id)
        findings.append(
            Finding(
                rule_id="electrical.no_consumption",
                subsystem=Subsystem.ELECTRICAL,
                severity=Severity.WARNING,
                title=f"Node {label} sees voltage but no current",
                target=label,
                summary=(
                    "The panel is energised but measuring essentially zero current on "
                    "an active deployment. The most common cause is a CT clamp that is "
                    "open or has come off the conductor."
                ),
                metric="current",
                current_value=f"{max(currents):.4f} A at {reading.voltage:.0f} V",
                expected_value=f"≥ {limits.imbalance_min_current_a:.1f} A under load",
                suggested_causes=[
                    "CT clamp open, detached, or never closed around the conductor",
                    "CT lead unplugged from the ADC",
                    "The circuit really is de-energised downstream of the breaker",
                ],
                suggested_commands=[
                    "i2cdetect -y 1",
                    "journalctl -u energy-collector -n 50 --no-pager",
                ],
                suggested_actions=[
                    "Verify the clamp is closed around a single conductor, not around "
                    "the whole cable bundle.",
                ],
                **_location_from_reading(ctx.session, reading, node),
            )
        )

    return findings


@rule("electrical.reverse_energy", Subsystem.ELECTRICAL, "Reverse power flow")
def check_reverse_energy(ctx: RuleContext) -> Iterable[Finding]:
    """Negative active power on a consumption-only site.

    Without generation on site, sustained negative power means a CT is
    installed backwards, not that the building is exporting.
    """
    findings: list[Finding] = []

    limits = ctx.config.electrical

    for node_id, reading in _electrical_nodes(ctx).items():
        # A deadband, not a sign test. An idle meter reports values like
        # -1e-9 kW, which is measurement noise around zero, not export. Testing
        # `< 0` reported "reverse power flow: -0.00 kW" on a healthy idle panel.
        if reading.power_kw is None or reading.power_kw > -limits.reverse_power_deadband_kw:
            continue

        node = ctx.session.get(Node, node_id)
        label = str(node.code if node else node_id)
        findings.append(
            Finding(
                rule_id="electrical.reverse_energy",
                subsystem=Subsystem.ELECTRICAL,
                severity=Severity.WARNING,
                title=f"Node {label} is reporting reverse power flow",
                target=label,
                summary=(
                    "Active power is negative. With no generation on site the usual "
                    "explanation is a CT clamp mounted backwards."
                ),
                metric="power_kw",
                current_value=f"{reading.power_kw:.2f} kW",
                expected_value="≥ 0 kW",
                suggested_causes=[
                    "CT clamp arrow pointing the wrong way",
                    "CT on the wrong conductor",
                    "Voltage and current channels mismatched between phases",
                ],
                suggested_actions=[
                    "Reversing the clamp corrects the sign. Readings taken meanwhile "
                    "understate consumption.",
                ],
                **_location_from_reading(ctx.session, reading, node),
            )
        )

    return findings


@rule("smart_plug.availability", Subsystem.SMART_PLUG, "Smart plug reachability and health")
def check_smart_plugs(ctx: RuleContext) -> Iterable[Finding]:
    findings: list[Finding] = []
    now = ctx.now

    for plug in ctx.metrics.get("plugs") or []:
        name = plug.friendly_name or plug.mac

        if not plug.online:
            age = (now - plug.last_seen).total_seconds() if plug.last_seen else None
            findings.append(
                Finding(
                    rule_id="smart_plug.offline",
                    subsystem=Subsystem.SMART_PLUG,
                    severity=Severity.WARNING,
                    title=f"Smart plug {name} is offline",
                    target=plug.mac,
                    metric="online",
                    current_value=(f"offline for {int(age)}s" if age is not None else "offline"),
                    expected_value="online",
                    building=plug.building_label,
                    deployment=plug.deployment_label,
                    suggested_causes=[
                        "Plug unplugged or its outlet switched off",
                        "Moved to a different subnet after a DHCP lease change",
                        "WiFi out of range",
                    ],
                    suggested_actions=[
                        "The plug is retained, not deleted, and recovers automatically "
                        "when it responds again.",
                    ],
                    context={"ip": plug.ip_address, "mac": plug.mac},
                )
            )
            continue

        if plug.temperature_c is not None and plug.temperature_c >= 70:
            findings.append(
                Finding(
                    rule_id="smart_plug.overtemperature",
                    subsystem=Subsystem.SMART_PLUG,
                    severity=Severity.ERROR,
                    title=f"Smart plug {name} is overheating",
                    target=plug.mac,
                    metric="temperature_c",
                    current_value=f"{plug.temperature_c:.1f} °C",
                    expected_value="< 70 °C",
                    building=plug.building_label,
                    suggested_causes=["Sustained load near the plug's rating", "Poor ventilation"],
                    suggested_actions=["Reduce the load on this outlet."],
                )
            )

    return findings


@rule("electrical.ups", Subsystem.ELECTRICAL, "UPS battery, bypass, load and runtime")
def check_ups(ctx: RuleContext) -> Iterable[Finding]:
    """UPS telemetry.

    No UPS integration exists anywhere in this platform: there is no NUT
    client, no UPS model, and no node reports UPS fields. Registered as
    unavailable so the gap is visible in the status report rather than looking
    like a passing check. It becomes live as soon as a source reports UPS data.
    """
    return [
        unavailable(
            "electrical.ups",
            Subsystem.ELECTRICAL,
            "UPS telemetry",
            "no UPS integration on this platform (no NUT client, no UPS fields reported)",
        )
    ]


__all__ = ["collect_metrics"]
