"""Resolution of electrical alert thresholds from physical reality.

A threshold that is not derived from the equipment it watches is a guess. The
first production run proved the cost: a flat 200 A default sat at roughly the
94th percentile of one panel's normal operation and produced 962 Telegram
messages in three days.

Resolution order, most authoritative first
------------------------------------------

1. **Deployment-specific limits.** Explicit warning/critical/emergency currents
   entered for this campaign, or derived from the panel's main-breaker rating.
   The panel is what the conductor and breaker actually protect, and the same
   node measures a different panel next month — so this wins.
2. **Node hardware limits.** Explicit currents on the node, or derived from the
   CT/clamp rating. This is the measurement equipment's own ceiling.
3. **Learned baseline.** A high percentile of the node's own history, used only
   when there is enough data *from operational deployments* to be meaningful.
4. **Conservative fallback.** A fixed safety ceiling, so an unconfigured node
   with no history still reports a genuinely dangerous value.

The physical ceiling is a hard cap
----------------------------------
A learned baseline may never exceed the physical rating of the CT, panel,
breaker or conductor. Two reasons, both real:

*A baseline learns overload.* If a panel runs at 110 % of its breaker rating for
a week, the trailing percentile learns that as normal and stops reporting it —
the alert quietly disappears exactly when it matters most.

*A CT cannot report beyond its range.* Readings above the clamp's rating are
measurement artefacts, not currents, so a baseline computed from them describes
the sensor's saturation behaviour rather than the installation.

Nothing here invents a rating. Every field is nullable and unset by default;
resolution falls through to the next source, and the source actually used is
reported in the alert so a reader can see whether it came from a nameplate or
from statistics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Deployment, EnergyReading, Node
from app.monitoring.config import MonitoringConfig

log = logging.getLogger("monitoring.thresholds")


@dataclass(frozen=True)
class CurrentThresholds:
    """Resolved current limits and the provenance of each."""

    warning: float | None
    critical: float | None
    emergency: float | None
    #: Where the numbers came from, shown verbatim in the alert.
    source: str
    #: The hard physical limit, when one is known.
    physical_ceiling: float | None = None
    #: Seconds the condition must hold. Falls back to the policy default.
    sustained_seconds: int | None = None

    @property
    def known(self) -> bool:
        return self.warning is not None


def _first(*values: Any) -> Any:
    """First non-None value, or None."""
    for value in values:
        if value is not None:
            return value
    return None


def physical_ceiling(
    node: Node | None, deployment: Deployment | None
) -> tuple[float | None, str | None]:
    """The lowest physical limit that applies, and what it is.

    The binding constraint is whichever piece of equipment gives out first: the
    clamp's measurement range, or the breaker protecting the conductor. Taking
    the minimum is the only safe reading of "the physical rating".
    """
    candidates: list[tuple[float, str]] = []

    if deployment is not None:
        if deployment.panel_main_breaker_a:
            candidates.append((deployment.panel_main_breaker_a, "panel main breaker"))
        if deployment.ct_max_current_a:
            candidates.append((deployment.ct_max_current_a, "deployment CT rating"))
    if node is not None and node.ct_max_current_a:
        candidates.append((node.ct_max_current_a, "node CT rating"))

    if not candidates:
        return None, None

    value, label = min(candidates, key=lambda pair: pair[0])
    return value, label


def learned_baseline(
    session: Session,
    node_id: int,
    config: MonitoringConfig,
    now: datetime,
) -> dict[str, Any]:
    """Learn a current envelope from **operational-deployment data only**.

    Readings taken while no campaign was running describe a node on a bench or
    a CT clamped to nothing. Including them makes the baseline describe the
    storeroom rather than the installation, so they are excluded here rather
    than filtered by the caller.
    """
    limits = config.electrical
    window_start = now - timedelta(days=7)

    try:
        from app.db import lifecycle as db_lifecycle

        operational = tuple(db_lifecycle.operational_statuses(session))
    except Exception:
        operational = ()

    if not operational:
        return {
            "threshold": None,
            "samples": 0,
            "source": "no operational deployment statuses defined",
        }

    values = [
        row[0]
        for row in (
            session.query(EnergyReading.current)
            .join(Deployment, Deployment.id == EnergyReading.deployment_id)
            .filter(
                EnergyReading.timestamp >= window_start,
                EnergyReading.current.isnot(None),
                EnergyReading.current > 0,
                Deployment.status.in_(operational),
            )
            .all()
        )
    ]

    if len(values) < limits.baseline_min_samples:
        return {
            "threshold": None,
            "samples": len(values),
            "source": (
                f"insufficient operational data "
                f"({len(values)}/{limits.baseline_min_samples} samples)"
            ),
        }

    values.sort()
    index = min(len(values) - 1, int(len(values) * limits.baseline_percentile / 100.0))
    percentile = values[index]
    return {
        "threshold": round(percentile * limits.baseline_margin, 1),
        "percentile": round(percentile, 1),
        "samples": len(values),
        "source": (
            f"learned p{limits.baseline_percentile} of {len(values)} "
            f"operational samples x {limits.baseline_margin}"
        ),
    }


def resolve_current_thresholds(
    node: Node | None,
    deployment: Deployment | None,
    config: MonitoringConfig,
    *,
    baseline: dict[str, Any] | None = None,
) -> CurrentThresholds:
    """Resolve warning/critical/emergency currents for one node.

    See the module docstring for the ordering. The returned ``source`` string
    is written into the alert so the reader always knows whether the number
    came from a nameplate or from statistics.
    """
    limits = config.electrical
    ceiling, ceiling_label = physical_ceiling(node, deployment)

    sustained = _first(
        getattr(deployment, "sustained_seconds", None),
        getattr(node, "sustained_seconds", None),
    )

    # --- 1 & 3. Explicit limits, deployment first ------------------------
    for owner, label in ((deployment, "deployment"), (node, "node")):
        if owner is None:
            continue
        warning = getattr(owner, "warning_current_a", None)
        critical = getattr(owner, "critical_current_a", None)
        emergency = getattr(owner, "emergency_current_a", None)
        if warning or critical or emergency:
            # A partially specified set is still usable: order what was given
            # and let the missing levels stay absent rather than inventing them.
            return CurrentThresholds(
                warning=_first(warning, critical, emergency),
                critical=_first(critical, emergency),
                emergency=emergency,
                source=f"{label} configured limits",
                physical_ceiling=ceiling,
                sustained_seconds=sustained,
            )

    # --- 2 & 4. Derived from a physical rating ---------------------------
    if ceiling is not None:
        return CurrentThresholds(
            warning=round(ceiling * limits.current_limit_warning_ratio, 1),
            critical=round(ceiling, 1),
            # Beyond the rating by a clear margin: the protective device should
            # already have operated, so this is an emergency by definition.
            emergency=round(ceiling * 1.15, 1),
            source=f"{ceiling_label} {ceiling:.0f} A",
            physical_ceiling=ceiling,
            sustained_seconds=sustained,
        )

    # --- 5. Learned baseline, hard-capped by any physical limit ----------
    if baseline and baseline.get("threshold"):
        learned = baseline["threshold"]
        source = baseline.get("source", "learned baseline")

        # Belt and braces: `ceiling` is None on this path by construction, but
        # if a rating is added later this cap is what stops a baseline that
        # learned an overload from silently exceeding it.
        if ceiling is not None and learned > ceiling:
            learned = ceiling
            source += f" (capped at {ceiling_label} {ceiling:.0f} A)"

        return CurrentThresholds(
            warning=min(learned, limits.current_warning),
            critical=limits.current_critical,
            emergency=None,
            source=source,
            physical_ceiling=ceiling,
            sustained_seconds=sustained,
        )

    # --- 6. Conservative fallback ----------------------------------------
    return CurrentThresholds(
        warning=limits.current_warning,
        critical=limits.current_critical,
        emergency=None,
        source=(
            "conservative safety ceiling — no panel rating, no node rating, "
            "and not enough operational history to learn one"
        ),
        physical_ceiling=ceiling,
        sustained_seconds=sustained,
    )


def describe(node: Node | None, deployment: Deployment | None) -> dict[str, Any]:
    """Every rating that applies, for the API and the status report.

    Shows which values are set and which are still NULL, so an operator can see
    at a glance what remains to be entered.
    """
    fields = (
        "ct_max_current_a",
        "nominal_voltage_v",
        "phase_count",
        "warning_current_a",
        "critical_current_a",
        "emergency_current_a",
        "sustained_seconds",
    )
    out: dict[str, Any] = {
        "node": {f: getattr(node, f, None) for f in fields} if node else None,
        "deployment": None,
    }
    if deployment is not None:
        out["deployment"] = {f: getattr(deployment, f, None) for f in fields}
        out["deployment"]["panel_main_breaker_a"] = deployment.panel_main_breaker_a

    ceiling, label = physical_ceiling(node, deployment)
    out["physical_ceiling_a"] = ceiling
    out["physical_ceiling_source"] = label
    return out


__all__ = [
    "CurrentThresholds",
    "describe",
    "learned_baseline",
    "physical_ceiling",
    "resolve_current_thresholds",
]
