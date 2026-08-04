"""Dashboard anomaly detection, with recovery tracking.

This is the *display* engine behind the Insight Center. It is deliberately not
the alerting engine in ``app/monitoring`` — that one decides whether to wake
somebody up and is tuned far more conservatively. Colouring a card and paging a
human are different decisions, so this module keeps reading the UI display
thresholds from ``platform_settings`` and does not import monitoring policy.

Two defects it exists to correct:

**A condition that had recovered was still shown as current.** The engine only
ever looked at the newest reading and reported a violation with no notion of
time. For a node that stopped reporting, that newest reading is however old it
happens to be — so N003's last bench sample raised a permanent "low power
factor" card long after the fact. Every finding now carries a ``status``:

    ACTIVE      the newest reading in scope still violates the threshold
    RESOLVED    it violated earlier in the window and no longer does

A resolved finding reports the value that breached, the value now, and when the
first clean reading arrived, so the card can say what happened instead of
implying it is still happening.

**A power factor of 0.00 on an idle meter was read as a fault.** Power factor is
undefined without load; an unloaded panel reports 0.00 legitimately. The rule
now requires real current before it will fire, on the same reasoning — and with
the same 1 A floor — as ``imbalance_min_current_a`` in the monitoring config,
where an unguarded comparison against ADC noise produced a permanent false
CRITICAL.

Evaluation covers the whole scope window (a deployment's measuring period) in
one conditional aggregate per node, rather than loading readings into Python.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import scope
from app.db.models import Deployment, EnergyReading, Node
from app.services import deployment_scope
from app.services.platform_settings import get_thresholds

ACTIVE = "active"
RESOLVED = "resolved"

#: Power factor is meaningless below real load. An idle panel reads ~1e-5 A and
#: a power factor of 0.00, which is not a fault. Same floor and same reasoning
#: as `imbalance_min_current_a` in app/monitoring/config.py.
MIN_LOAD_CURRENT_A = 1.0

#: Night-consumption threshold, unchanged from the rule this replaced.
NIGHT_POWER_KW = 5.0


def _rule_definitions() -> list[dict]:
    """The rules, as SQL predicates plus presentation metadata.

    A predicate is written once and used three ways — to test the newest
    reading, to find the last breach in the window, and to describe the finding
    — so the "is it still happening" answer cannot drift from the rule that
    raised it in the first place.
    """
    thresholds = get_thresholds()
    min_pf = float(thresholds.get("minPowerFactor", 0.90))
    max_current = float(thresholds.get("maxCurrent", 200))

    return [
        {
            "key": "power_factor",
            "category": "Power Factor",
            "severity": "medium",
            "title": "Low power factor detected",
            "threshold": min_pf,
            "unit": "",
            # The load guard lives in the predicate, so an idle reading is not a
            # breach for either the current test or the historical one.
            "sql": "power_factor IS NOT NULL AND power_factor < :min_pf "
                   "AND current IS NOT NULL AND current >= :min_load",
            "test": lambda r: (
                r.power_factor is not None
                and r.current is not None
                and r.current >= MIN_LOAD_CURRENT_A
                and r.power_factor < min_pf
            ),
            "value": lambda r: r.power_factor,
            "describe": lambda b, v: (
                f"{b}: power factor {v:.2f} is below the configured threshold of {min_pf:.2f}."
            ),
        },
        {
            "key": "current_load",
            "category": "Current Load",
            "severity": "high",
            "title": "High current detected",
            "threshold": max_current,
            "unit": " A",
            "sql": "current IS NOT NULL AND current > :max_current",
            "test": lambda r: r.current is not None and r.current > max_current,
            "value": lambda r: r.current,
            "describe": lambda b, v: (
                f"{b}: current load is {v:.2f} A. Review panel load and phase balance."
            ),
        },
        {
            "key": "night_consumption",
            "category": "Night Consumption",
            "severity": "medium",
            "title": "Unexpected night consumption",
            "threshold": NIGHT_POWER_KW,
            "unit": " kW",
            # NOTE: the hour is UTC, matching the behaviour this replaced. The
            # platform is UTC-6, so "night" is currently offset by six hours.
            # Correcting it changes which readings qualify, so it is left as-is
            # and reported separately rather than folded into this change.
            "sql": "power_kw IS NOT NULL AND power_kw > :night_kw "
                   "AND CAST(strftime('%H', timestamp) AS INTEGER) < 6",
            "test": lambda r: (
                r.power_kw is not None
                and r.timestamp.hour < 6
                and r.power_kw > NIGHT_POWER_KW
            ),
            "value": lambda r: r.power_kw,
            "describe": lambda b, v: (
                f"{b}: power is {v:.2f} kW outside normal operating hours."
            ),
        },
    ]


def _last_breach_sql(db: Session, rules: list[dict], node_id: int,
                     deployment_id: int | None) -> tuple[str, dict]:
    """One conditional aggregate: the last breach timestamp for every rule."""
    contexts = scope.analytic_contexts(db)
    thresholds = get_thresholds()

    binds: dict[str, object] = {
        "node_id": node_id,
        "min_pf": float(thresholds.get("minPowerFactor", 0.90)),
        "max_current": float(thresholds.get("maxCurrent", 200)),
        "night_kw": NIGHT_POWER_KW,
        "min_load": MIN_LOAD_CURRENT_A,
    }
    context_binds = []
    for i, code in enumerate(contexts):
        key = f"ctx{i}"
        binds[key] = code
        context_binds.append(f":{key}")

    scope_filter = ""
    if deployment_id is not None:
        scope_filter = "AND deployment_id = :deployment_id"
        binds["deployment_id"] = int(deployment_id)

    selects = ",\n               ".join(
        f"MAX(CASE WHEN {rule['sql']} THEN timestamp END) AS {rule['key']}_last"
        for rule in rules
    )
    sql = f"""
        SELECT {selects}
          FROM energy_readings
         WHERE node_id = :node_id
           AND context IN ({", ".join(context_binds)})
           {scope_filter}
    """
    return sql, binds


def _reading_at(db: Session, node_id: int, stamp, deployment_id: int | None):
    query = scope.production_readings(db).filter(
        EnergyReading.node_id == node_id, EnergyReading.timestamp == stamp
    )
    return deployment_scope.scope_readings(query, deployment_id).first()


def _first_reading_after(db: Session, node_id: int, stamp, deployment_id: int | None):
    """The first reading after the last breach — i.e. when it recovered.

    Everything after the *most recent* breach is by definition clean, so the
    earliest of them is the recovery instant; no second predicate is needed.
    """
    query = (
        scope.production_readings(db)
        .filter(EnergyReading.node_id == node_id, EnergyReading.timestamp > stamp)
        .order_by(EnergyReading.timestamp.asc())
    )
    return deployment_scope.scope_readings(query, deployment_id).first()


def detect_node_anomalies(db: Session, node: Node, deployment_id: int | None = None):
    anomalies = []

    latest = deployment_scope.scope_readings(
        scope.production_readings(db).filter(EnergyReading.node_id == node.id),
        deployment_id,
    ).order_by(EnergyReading.timestamp.desc()).first()

    if not latest:
        return anomalies

    building_name = latest.building.name if latest.building else "Sin edificio"
    rules = _rule_definitions()

    sql, binds = _last_breach_sql(db, rules, node.id, deployment_id)
    row = db.execute(text(sql), binds).fetchone()
    last_breach = dict(zip([r["key"] for r in rules], row)) if row else {}

    for rule in rules:
        currently = rule["test"](latest)
        current_value = rule["value"](latest)
        breach_stamp = last_breach.get(rule["key"])

        if currently:
            status, previous_value, previous_at, recovered_at = ACTIVE, None, None, None
        elif breach_stamp:
            breach = _reading_at(db, node.id, breach_stamp, deployment_id)
            if breach is None:
                continue
            recovery = _first_reading_after(db, node.id, breach.timestamp, deployment_id)
            status = RESOLVED
            previous_value = rule["value"](breach)
            previous_at = breach.timestamp
            recovered_at = recovery.timestamp if recovery else None
        else:
            # Never breached anywhere in this window. Not a finding at all.
            continue

        reference_value = current_value if currently else previous_value
        anomalies.append({
            # --- fields the previous response already carried -------------
            "severity": rule["severity"],
            "category": rule["category"],
            "node_id": node.code,
            "building": building_name,
            "title": rule["title"],
            "description": (rule["describe"](building_name, reference_value)
                            if reference_value is not None else rule["title"]),
            "value": reference_value,
            "threshold": rule["threshold"],
            "timestamp": (latest.timestamp if currently else previous_at).isoformat(),

            # --- recovery tracking, added --------------------------------
            "status": status,
            "current_value": current_value,
            "current_at": latest.timestamp.isoformat(),
            "previous_value": previous_value,
            "previous_at": previous_at.isoformat() if previous_at else None,
            "recovered_at": recovered_at.isoformat() if recovered_at else None,
            "unit": rule["unit"],
        })

    # Demand spike is a transient by construction — it compares the newest
    # reading against its own trailing average. There is no meaningful
    # "resolved" form of it, so it is reported only while it is happening.
    spike = _demand_spike(db, node, latest, building_name, deployment_id)
    if spike:
        anomalies.append(spike)

    return anomalies


def _demand_spike(db, node, latest, building_name, deployment_id):
    start = datetime.utcnow() - timedelta(hours=2)
    readings = deployment_scope.scope_readings(
        scope.production_readings(db).filter(
            EnergyReading.node_id == node.id,
            EnergyReading.timestamp >= start,
            EnergyReading.power_kw.isnot(None),
        ),
        deployment_id,
    ).order_by(EnergyReading.timestamp.asc()).all()

    if len(readings) < 10:
        return None

    powers = [r.power_kw for r in readings if r.power_kw is not None]
    if not powers:
        return None
    avg_power = sum(powers) / len(powers)

    if not (avg_power > 0 and latest.power_kw and latest.power_kw > avg_power * 1.35):
        return None

    return {
        "severity": "high",
        "category": "Demand Spike",
        "node_id": node.code,
        "building": building_name,
        "title": "Demand spike detected",
        "description": f"{building_name}: latest power {latest.power_kw:.2f} kW is above "
                       f"the recent average of {avg_power:.2f} kW.",
        "value": latest.power_kw,
        "threshold": round(avg_power * 1.35, 3),
        "timestamp": latest.timestamp.isoformat(),
        "status": ACTIVE,
        "current_value": latest.power_kw,
        "current_at": latest.timestamp.isoformat(),
        "previous_value": None,
        "previous_at": None,
        "recovered_at": None,
        "unit": " kW",
    }


def detect_all_anomalies(db: Session, deployment_id: int | None = None):
    """Findings across every node in scope.

    ``deployment_id`` restricts both the node set and the readings evaluated to
    one deployment. ``None`` keeps the fleet-wide behaviour.
    """
    if deployment_id is None:
        nodes = db.query(Node).all()
    else:
        deployment = db.query(Deployment).filter(Deployment.id == deployment_id).first()
        if deployment is None:
            return []
        nodes = db.query(Node).filter(Node.id == deployment.node_id).all()

    anomalies = []
    for node in nodes:
        anomalies.extend(detect_node_anomalies(db, node, deployment_id))

    return anomalies
