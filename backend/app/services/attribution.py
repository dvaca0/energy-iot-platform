"""The attribution resolver.

Answers one question: given a node and the instant a measurement was captured,
where does that measurement count?

The whole module is a pure function of stored state. `resolve()` takes an
immutable snapshot and a reading, and returns a decision. It reads no globals,
consults no clock, caches nothing, and touches no connection. The same snapshot
and the same reading always produce exactly the same decision, on any machine,
in any order, any number of times.

That matters for three reasons:

  It is testable without a database.
  It can run in shadow mode against historical data and mean something.
  When it becomes authoritative, replaying a buffer cannot produce a different
  answer than the shadow run predicted.

Two properties are deliberate and worth stating plainly.

**Attribution follows `captured_at`, never upload time.** The resolver is never
given the ingestion instant, so it cannot depend on it even by accident. A
measurement buffered on a Raspberry Pi for a week resolves exactly as it would
have at the moment it was taken. This is the defect (B1) that motivated the
redesign: the current pipeline stamps a whole batch with the node's newest
deployment regardless of when each measurement was actually taken.

**Ambiguity is a result, not a tiebreak.** When two deployments overlap a
timestamp there is no correct answer, so the resolver returns
`MULTIPLE_MATCHES` with the candidates listed and attributes nothing. It never
silently picks one. Every outcome, including every refusal, carries a reason
code emitted here — never inferred later during rendering.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType


# --------------------------------------------------------------- reason codes
class Reason:
    """Deterministic outcome codes. Emitted by the resolver, never by a renderer."""

    # Attributed
    ATTRIBUTED_IN_WINDOW = "ATTRIBUTED_IN_WINDOW"

    # Not attributed — deployment geometry
    NO_MATCHING_DEPLOYMENT = "NO_MATCHING_DEPLOYMENT"
    OUTSIDE_DEPLOYMENT_WINDOW = "OUTSIDE_DEPLOYMENT_WINDOW"
    DEPLOYMENT_NOT_ATTRIBUTING = "DEPLOYMENT_NOT_ATTRIBUTING"
    MULTIPLE_MATCHES = "MULTIPLE_MATCHES"

    # Not attributed — declared node context
    BENCH_NODE = "BENCH_NODE"
    LABORATORY_NODE = "LABORATORY_NODE"
    CALIBRATION_NODE = "CALIBRATION_NODE"
    SIMULATION_NODE = "SIMULATION_NODE"
    COMMISSIONING_NODE = "COMMISSIONING_NODE"
    # Node powered for platform validation with no campaign running. Distinct
    # from BENCH_NODE (hardware on a desk) and from UNKNOWN_CONTEXT, which must
    # keep meaning "this context is not in the lookup table".
    INFRASTRUCTURE_VALIDATION_NODE = "INFRASTRUCTURE_VALIDATION_NODE"
    UNKNOWN_CONTEXT = "UNKNOWN_CONTEXT"

    # Not resolvable — identity
    UNKNOWN_NODE = "UNKNOWN_NODE"
    MISSING_CAPTURED_AT = "MISSING_CAPTURED_AT"


class Flag:
    """Secondary observations. Additive, and never change the attribution."""

    PLACEHOLDER_BUILDING = "PLACEHOLDER_BUILDING"
    MISSING_BUILDING = "MISSING_BUILDING"
    MISSING_PANEL = "MISSING_PANEL"
    OPEN_ENDED_DEPLOYMENT = "OPEN_ENDED_DEPLOYMENT"

    # Observed, never decisive. "May this node upload?" is the ingest gate's
    # question (ADR-0002 step 2), asked before the resolver is ever called and
    # answered about the node *now*. "Where does this reading belong?" is this
    # module's question, answered about the instant it was captured. Letting
    # authorization short-circuit attribution conflated the two: it replaced the
    # informative BENCH_NODE with an authorization status for 123,728 historical
    # rows, and made a stored reading's attribution change whenever an unrelated
    # operational fact about its node changed.
    NODE_MAY_NOT_UPLOAD = "NODE_MAY_NOT_UPLOAD"


# Node context -> the reason emitted when that context forbids attribution.
# A mapping rather than a chain of ifs, so adding a context is data.
_CONTEXT_REASON = MappingProxyType(
    {
        "bench": Reason.BENCH_NODE,
        "laboratory": Reason.LABORATORY_NODE,
        "calibration": Reason.CALIBRATION_NODE,
        "simulation": Reason.SIMULATION_NODE,
        "commissioning": Reason.COMMISSIONING_NODE,
        "infrastructure_validation": Reason.INFRASTRUCTURE_VALIDATION_NODE,
    }
)


# ------------------------------------------------------------------ structures
@dataclass(frozen=True)
class DeploymentWindow:
    """One deployment's attribution geometry. Immutable.

    The window is `[activated_at, closed_at]` — *operational* truth, written by
    the lifecycle transitions. It is deliberately **not** `start_date` /
    `end_date`, which are the campaign's planned schedule and are never
    authoritative for attribution.

    The distinction is not academic. Planning dates are day-granular, and a node
    handover happens at a specific moment: deployment 4 handed over to
    deployment 6 at 21:09 on 2026-07-30, one 15-second sample apart. No
    day-granular window can express that, and pretending otherwise is what made
    two deployments claim the same instant.
    """

    deployment_id: int
    node_id: int
    building_id: int | None
    electrical_panel_id: int | None
    activated_at: datetime | None  # None means never activated
    closed_at: datetime | None  # None means still open
    status: str
    allows_attribution: bool

    # Retained for display and diagnostics only. Never consulted by covers().
    planned_start: str | None = None
    planned_end: str | None = None

    def covers(self, captured_at: datetime) -> bool:
        """Whether this deployment was operationally responsible at an instant.

        Both bounds inclusive. A deployment that never activated covers nothing,
        whatever its schedule said — a campaign that was planned but never ran
        cannot own a measurement.
        """
        if self.activated_at is None:
            return False
        if captured_at < self.activated_at:
            return False
        if self.closed_at is not None and captured_at > self.closed_at:
            return False
        return True


@dataclass(frozen=True)
class ResolverState:
    """An immutable snapshot of everything the resolver may consult.

    Built once by `load_state()`, then read-only. Because it is passed in rather
    than fetched, `resolve()` has no I/O and no hidden dependency on when it
    runs — the same state produces the same decisions forever.
    """

    windows_by_node: Mapping[int, tuple[DeploymentWindow, ...]]
    node_context: Mapping[int, str]
    node_code: Mapping[int, str]
    node_may_upload: Mapping[int, bool]
    placeholder_buildings: frozenset[int]
    attributable_contexts: frozenset[str]
    known_contexts: frozenset[str]


@dataclass(frozen=True)
class Decision:
    """What the resolver would do. Carries its own justification."""

    deployment_id: int | None
    building_id: int | None
    electrical_panel_id: int | None
    context: str
    reason: str
    flags: tuple[str, ...] = field(default_factory=tuple)
    candidates: tuple[int, ...] = field(default_factory=tuple)

    @property
    def attributed(self) -> bool:
        return self.deployment_id is not None


# --------------------------------------------------------------------- loading
def _parse_ts(value) -> datetime | None:
    """Parse a stored timestamp. Pure: no clock, no locale, no fallback to now."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def load_state(conn) -> ResolverState:
    """Read the snapshot. The only function here that touches a connection.

    Uses SELECT exclusively. Callers are expected to pass a read-only
    connection so that "no side effects" is enforced by SQLite rather than by
    convention.
    """
    windows: dict[int, list[DeploymentWindow]] = {}
    rows = conn.execute("""
        SELECT d.id, d.node_id, d.building_id, d.electrical_panel_id,
               d.activated_at, d.closed_at, d.status,
               COALESCE(s.allows_attribution, 0),
               d.start_date, d.end_date
          FROM deployments d
          LEFT JOIN deployment_statuses s ON s.code = d.status
         ORDER BY d.node_id, d.activated_at, d.id
        """).fetchall()
    for row in rows:
        windows.setdefault(row[1], []).append(
            DeploymentWindow(
                deployment_id=row[0],
                node_id=row[1],
                building_id=row[2],
                electrical_panel_id=row[3],
                activated_at=_parse_ts(row[4]),
                closed_at=_parse_ts(row[5]),
                status=row[6],
                allows_attribution=bool(row[7]),
                planned_start=row[8],
                planned_end=row[9],
            )
        )

    node_context: dict[int, str] = {}
    node_code: dict[int, str] = {}
    node_may_upload: dict[int, bool] = {}
    for node_id, code, context, may_upload in conn.execute("""
        SELECT n.id, n.code, n.measurement_context,
               COALESCE(s.may_upload, 0)
          FROM nodes n
          LEFT JOIN node_commission_states s ON s.code = n.commission_state
         ORDER BY n.id
        """):
        node_context[node_id] = context
        node_code[node_id] = code
        node_may_upload[node_id] = bool(may_upload)

    placeholders = frozenset(
        row[0] for row in conn.execute("SELECT id FROM buildings WHERE is_placeholder = 1")
    )
    attributable = frozenset(
        row[0]
        for row in conn.execute("SELECT code FROM measurement_contexts WHERE may_attribute = 1")
    )
    known = frozenset(row[0] for row in conn.execute("SELECT code FROM measurement_contexts"))

    return ResolverState(
        windows_by_node=MappingProxyType({k: tuple(v) for k, v in windows.items()}),
        node_context=MappingProxyType(node_context),
        node_code=MappingProxyType(node_code),
        node_may_upload=MappingProxyType(node_may_upload),
        placeholder_buildings=placeholders,
        attributable_contexts=attributable,
        known_contexts=known,
    )


# ------------------------------------------------------------------- resolving
def resolve(state: ResolverState, node_id: int, captured_at: datetime | None) -> Decision:
    """Decide where a measurement counts.

    Pure: no I/O, no clock, no globals, no mutation. `captured_at` is the only
    temporal input, so upload time cannot influence the outcome.
    """
    if captured_at is None:
        return Decision(None, None, None, "unknown", Reason.MISSING_CAPTURED_AT)

    if node_id not in state.node_context:
        return Decision(None, None, None, "unknown", Reason.UNKNOWN_NODE)

    context = state.node_context[node_id]

    # An unrecognised context is surfaced, never coerced to a default.
    if context not in state.known_contexts:
        return Decision(None, None, None, context, Reason.UNKNOWN_CONTEXT)

    # Authorization is *observed* here, never decisive. It belongs to the ingest
    # gate, which runs before this function and rejects with 403; a reading that
    # reaches the resolver has already been authorized. Carried as a flag so the
    # information survives without displacing the attribution answer.
    base: tuple[str, ...] = ()
    if not state.node_may_upload.get(node_id, False):
        base = (Flag.NODE_MAY_NOT_UPLOAD,)

    # Declared context decides attributability before any deployment is
    # considered — classification and attribution are independent (ADR-0003).
    if context not in state.attributable_contexts:
        return Decision(
            None,
            None,
            None,
            context,
            _CONTEXT_REASON.get(context, Reason.UNKNOWN_CONTEXT),
            flags=base,
        )

    windows = state.windows_by_node.get(node_id, ())
    if not windows:
        return Decision(None, None, None, context, Reason.NO_MATCHING_DEPLOYMENT, flags=base)

    covering = tuple(w for w in windows if w.covers(captured_at))

    if not covering:
        return Decision(None, None, None, context, Reason.OUTSIDE_DEPLOYMENT_WINDOW, flags=base)

    attributing = tuple(w for w in covering if w.allows_attribution)

    if not attributing:
        return Decision(
            None,
            None,
            None,
            context,
            Reason.DEPLOYMENT_NOT_ATTRIBUTING,
            flags=base,
            candidates=tuple(sorted(w.deployment_id for w in covering)),
        )

    if len(attributing) > 1:
        # Genuinely ambiguous. Never tie-break — report and attribute nothing.
        return Decision(
            None,
            None,
            None,
            context,
            Reason.MULTIPLE_MATCHES,
            flags=base,
            candidates=tuple(sorted(w.deployment_id for w in attributing)),
        )

    window = attributing[0]

    flags: list[str] = list(base)
    if window.building_id is None:
        flags.append(Flag.MISSING_BUILDING)
    elif window.building_id in state.placeholder_buildings:
        flags.append(Flag.PLACEHOLDER_BUILDING)
    if window.electrical_panel_id is None:
        flags.append(Flag.MISSING_PANEL)
    if window.closed_at is None:
        flags.append(Flag.OPEN_ENDED_DEPLOYMENT)

    return Decision(
        deployment_id=window.deployment_id,
        building_id=window.building_id,
        electrical_panel_id=window.electrical_panel_id,
        context=context,
        reason=Reason.ATTRIBUTED_IN_WINDOW,
        flags=tuple(flags),
    )
