"""The rule engine.

A *rule* is a named, self-describing health check. Adding monitoring coverage
means writing one function and decorating it — no other file changes, no
registration list to maintain, no dispatch table to extend. That is the whole
extensibility contract of this package.

A rule receives a :class:`RuleContext` and yields :class:`Finding` objects. It
does not know what happens next: whether a finding becomes an alert, whether it
escalates, whether it reaches Telegram or email is decided by
``alerts.py`` and ``notifications.py``. A rule's only job is to look at the
world and describe what it sees.

Three properties matter for a production system and are enforced here:

**Isolation.** A rule that raises does not stop the others. Its failure is
converted into a finding about itself, so a broken check is visible rather than
silently absent.

**Shared probing.** Expensive facts (CPU sample, disk usage, node heartbeats,
latest readings) are gathered once per tick into the context and reused by
every rule, instead of each rule independently shelling out.

**Honest unavailability.** A check whose data source does not exist on this
deployment reports ``unavailable`` rather than inventing a value or silently
passing. UPS telemetry, TLS certificates and Tailscale have no source on this
server today; they are registered, they report why they cannot run, and they
begin working the moment the source appears.
"""

from __future__ import annotations

import hashlib
import logging
import traceback
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.monitoring.config import MonitoringConfig, get_config
from app.monitoring.severity import Severity

log = logging.getLogger("monitoring.rules")


# --------------------------------------------------------------------------
# Subsystems
# --------------------------------------------------------------------------

class Subsystem:
    """Subsystem names, used for grouping in reports and filtering in the API.

    Plain string constants rather than an enum: they are stored in the database
    and appear in the API, and a new subsystem should not require a migration.
    """

    SERVER = "server"
    DATABASE = "database"
    BACKEND = "backend"
    FRONTEND = "frontend"
    NETWORK = "network"
    NODE = "node"
    ELECTRICAL = "electrical"
    SMART_PLUG = "smart_plug"
    SECURITY = "security"
    MONITORING = "monitoring"


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------

@dataclass
class Finding:
    """A single observation produced by a rule.

    A finding is not yet an alert. It becomes one when the alert engine decides
    it is new, and it closes an existing alert when a rule stops emitting it.

    ``target`` is what distinguishes two findings from the same rule: the node
    code for a per-node check, the mount point for a disk check, the empty
    string for a singleton check. Together with the rule id it forms the
    deduplication fingerprint, so the same problem on the same target updates
    one alert instead of creating a stream of them.
    """

    rule_id: str
    subsystem: str
    severity: Severity
    title: str

    #: Distinguishes instances of the same rule. Empty for singleton checks.
    target: str = ""

    summary: str | None = None

    # --- The numbers behind the verdict ------------------------------------
    metric: str | None = None
    current_value: str | None = None
    expected_value: str | None = None

    # --- Location, for the alert header ------------------------------------
    node_code: str | None = None
    node_id: int | None = None
    campus: str | None = None
    building: str | None = None
    deployment: str | None = None
    hostname: str | None = None

    # --- Diagnosis, so the alert can be acted on without an SSH session -----
    suggested_causes: list[str] = field(default_factory=list)
    suggested_commands: list[str] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)
    related_services: list[str] = field(default_factory=list)

    #: Anything else worth preserving on the alert record.
    context: dict[str, Any] = field(default_factory=dict)

    #: When set, the check could not run. It is reported as a capability gap,
    #: never as a passing check and never as an alert.
    unavailable: bool = False
    unavailable_reason: str | None = None

    #: When False the finding is recorded and appears in the status report and
    #: the alerts API, but is never pushed to a channel. The "interesting, not
    #: urgent" tier. Set from ``config.report_only_rules`` unless a rule opts
    #: out explicitly.
    notify: bool = True

    #: Seconds the condition must hold before anyone is notified. A breach
    #: lasting a single poll interval is a transient, not an incident; the
    #: first production run showed 404 of 472 current alerts lasting under two
    #: minutes. The alert is still *created* immediately, so the history and
    #: the report show it — only the notification waits.
    sustain_seconds: int | None = None

    #: Ceiling for duration-based escalation. Some conditions are persistent
    #: states rather than incidents — a node awaiting commissioning, a node in
    #: standby — and they are open for days by their nature. Escalating those
    #: to EMERGENCY on a timer would teach the reader that EMERGENCY is
    #: meaningless. ``None`` means the normal ladder applies.
    max_severity: Severity | None = None

    @property
    def fingerprint(self) -> str:
        """Stable deduplication key for this problem on this target.

        Hashed so it stays a bounded length regardless of how long a target
        string is, and prefixed with the readable rule id so a human scanning
        the database can still tell what a row is about.
        """
        digest = hashlib.sha1(
            f"{self.rule_id}|{self.target}".encode("utf-8")
        ).hexdigest()[:12]
        return f"{self.rule_id}:{digest}"

    @property
    def is_problem(self) -> bool:
        """True when this finding should drive an alert."""
        return (
            not self.unavailable
            and self.severity is not Severity.OK
            and self.severity.is_actionable
        )


def unavailable(
    rule_id: str,
    subsystem: str,
    title: str,
    reason: str,
    *,
    target: str = "",
) -> Finding:
    """Build a finding for a check that has no data source on this deployment.

    Used instead of returning nothing, so the status report can show the
    difference between "checked and healthy" and "never checked".
    """
    return Finding(
        rule_id=rule_id,
        subsystem=subsystem,
        severity=Severity.OK,
        title=title,
        target=target,
        unavailable=True,
        unavailable_reason=reason,
    )


# --------------------------------------------------------------------------
# Rule context
# --------------------------------------------------------------------------

@dataclass
class RuleContext:
    """Everything a rule may need, gathered once per evaluation tick.

    Rules must not open their own database sessions or run their own system
    probes: doing so would multiply cost by the rule count and produce
    inconsistent snapshots within a single tick.
    """

    session: Session
    config: MonitoringConfig
    now: datetime

    #: Populated by ``health.collect_server_snapshot`` before rules run.
    server: dict[str, Any] = field(default_factory=dict)
    #: Node code -> latest heartbeat state, from ``heartbeat.collect_node_state``.
    nodes: dict[str, Any] = field(default_factory=dict)
    #: Assorted derived metrics, from ``metrics.collect_metrics``.
    metrics: dict[str, Any] = field(default_factory=dict)

    #: Scratch space for rules that want to pass data to later rules within the
    #: same tick. Cleared between ticks.
    scratch: dict[str, Any] = field(default_factory=dict)

    def threshold_severity(
        self,
        value: float | None,
        warning: float | None,
        critical: float | None,
        *,
        inverted: bool = False,
    ) -> Severity:
        """Classify a numeric value against warning and critical thresholds.

        ``inverted`` flips the comparison for metrics where *lower is worse*
        (power factor, free disk), so a single helper covers both directions
        instead of every rule reimplementing the comparison.
        """
        if value is None:
            return Severity.OK

        if inverted:
            if critical is not None and value <= critical:
                return Severity.CRITICAL
            if warning is not None and value <= warning:
                return Severity.WARNING
            return Severity.OK

        if critical is not None and value >= critical:
            return Severity.CRITICAL
        if warning is not None and value >= warning:
            return Severity.WARNING
        return Severity.OK


#: A rule evaluator: takes the tick context, yields zero or more findings.
Evaluator = Callable[[RuleContext], Iterable[Finding]]


@dataclass
class Rule:
    """A registered health check and its metadata."""

    rule_id: str
    subsystem: str
    description: str
    evaluator: Evaluator
    #: Rules can be turned off by id through configuration.
    enabled_by_default: bool = True
    #: Documentation-only: what this rule needs in order to run at all.
    requires: tuple[str, ...] = ()


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

_REGISTRY: dict[str, Rule] = {}


def rule(
    rule_id: str,
    subsystem: str,
    description: str,
    *,
    enabled_by_default: bool = True,
    requires: tuple[str, ...] = (),
) -> Callable[[Evaluator], Evaluator]:
    """Register a rule evaluator.

    ::

        @rule("server.disk_full", Subsystem.SERVER, "Root filesystem capacity")
        def check_disk(ctx: RuleContext) -> Iterable[Finding]:
            ...

    Re-registering an id replaces the previous rule rather than raising, so a
    module reimported during development does not blow up on a duplicate.
    """

    def decorator(func: Evaluator) -> Evaluator:
        if rule_id in _REGISTRY:
            log.debug("Rule %s re-registered", rule_id)
        _REGISTRY[rule_id] = Rule(
            rule_id=rule_id,
            subsystem=subsystem,
            description=description,
            evaluator=func,
            enabled_by_default=enabled_by_default,
            requires=requires,
        )
        return func

    return decorator


def registered_rules() -> dict[str, Rule]:
    """Every registered rule, keyed by id."""
    return dict(_REGISTRY)


def active_rules(config: MonitoringConfig | None = None) -> list[Rule]:
    """Rules that are not administratively disabled."""
    config = config or get_config()
    disabled = set(config.disabled_rules)
    return [
        rule_obj
        for rule_id, rule_obj in sorted(_REGISTRY.items())
        if rule_id not in disabled and rule_obj.enabled_by_default
    ]


def apply_routing(findings: list[Finding], config: MonitoringConfig) -> list[Finding]:
    """Mark findings whose rule is configured as report-only.

    Applied centrally after evaluation so the routing decision is visible in
    one list (``config.report_only_rules``) instead of scattered across thirty
    rule bodies, and so it can be retuned without touching code.
    """
    report_only = set(config.report_only_rules)
    breakout = Severity.parse(config.report_only_escalates_at, Severity.CRITICAL)

    for finding in findings:
        if finding.rule_id not in report_only:
            continue
        # Report-only describes the routine case. A rule that is usually boring
        # can still produce a genuinely severe finding on the same metric —
        # power factor at 0.89 is noise, at 0.55 it is a real fault — and
        # silencing that would be a monitoring failure, not a tuning choice.
        if finding.severity >= breakout:
            continue
        finding.notify = False
    return findings


def evaluate_all(context: RuleContext) -> list[Finding]:
    """Run every active rule and collect the findings.

    Each rule is isolated: an exception is caught, logged with its traceback,
    and turned into a monitoring-subsystem finding. A check that crashes is a
    fault worth alerting on — the failure mode this avoids is a rule that
    silently stops working and leaves a blind spot nobody notices.
    """
    findings: list[Finding] = []

    for rule_obj in active_rules(context.config):
        try:
            produced = rule_obj.evaluator(context)
            if produced:
                findings.extend(produced)
        except Exception as exc:  # noqa: BLE001 - deliberate catch-all
            log.exception("Rule %s failed", rule_obj.rule_id)
            findings.append(
                Finding(
                    rule_id="monitoring.rule_failed",
                    subsystem=Subsystem.MONITORING,
                    severity=Severity.ERROR,
                    title=f"Monitoring check '{rule_obj.rule_id}' is failing",
                    target=rule_obj.rule_id,
                    summary=f"{type(exc).__name__}: {exc}",
                    metric="rule_status",
                    current_value="raising an exception",
                    expected_value="evaluating cleanly",
                    suggested_causes=[
                        "A schema or data shape the rule did not expect",
                        "A probe returning a different type than assumed",
                        "A recent change to the rule or to the data it reads",
                    ],
                    suggested_commands=[
                        "journalctl -u energy-platform-monitoring.service -n 100",
                    ],
                    suggested_actions=[
                        f"This check is blind until fixed. Inspect the traceback "
                        f"for {rule_obj.rule_id}.",
                    ],
                    context={
                        "rule": rule_obj.rule_id,
                        "subsystem": rule_obj.subsystem,
                        "traceback": traceback.format_exc(limit=6),
                    },
                )
            )

    return apply_routing(findings, context.config)


def iter_problems(findings: Iterable[Finding]) -> Iterator[Finding]:
    """Only the findings that represent an actual problem."""
    return (finding for finding in findings if finding.is_problem)


def iter_unavailable(findings: Iterable[Finding]) -> Iterator[Finding]:
    """Only the findings whose check could not run."""
    return (finding for finding in findings if finding.unavailable)


__all__ = [
    "Subsystem",
    "Finding",
    "Rule",
    "RuleContext",
    "rule",
    "unavailable",
    "registered_rules",
    "active_rules",
    "evaluate_all",
    "iter_problems",
    "iter_unavailable",
]
