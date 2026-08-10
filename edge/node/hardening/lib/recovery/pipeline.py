"""The recovery decision core — PURE. No I/O, no clock, no hardware.

Everything here is a function of its arguments. Time arrives as a parameter,
stage results arrive as values, and the persistent ledger arrives as a plain
dataclass. That is what makes every escalation path unit-testable without a
Raspberry Pi, a radio, a meter or a reboot.

    probes.py    gathers StageResults          (I/O)
    ledger.py    persists RebootLedger         (I/O)
    pipeline.py  decides what to do about it   (PURE)  <- this file
    daemon.py    carries the decision out      (I/O)

THE POLICY THIS IMPLEMENTS (agreed 2026-08-10)

    Try service-level recovery first.
    If that fails, reboot.
    At most 3 reboots within 30 minutes.
    If those fail, enter SAFE MODE: maintenance AP up, SSH up, portal up.
    SAFE MODE is NOT permanent - keep attempting full recovery every 10-15
    minutes, forever. A node must never need a human merely because it gave up.

WHY SOME FAILURES MUST NEVER REBOOT
    Rebooting cannot fix a backend that is down, an internet link that is out,
    or a Shelly meter that someone unplugged. A node that reboots itself over
    an external dependency turns somebody else's outage into its own, and does
    it in a loop. Stages are therefore classified LOCAL (a reboot is a
    plausible remedy) or EXTERNAL (it never is). Only LOCAL stages escalate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# --------------------------------------------------------------------- stages

#: Boot/health stages in dependency order. Each stage is only meaningful once
#: every stage before it holds, which is what lets the node say exactly where
#: boot failed rather than "something is wrong".
FILESYSTEM = "filesystem"
CLOCK = "clock"
NETWORK = "network"
TAILSCALE = "tailscale"
SENSOR = "sensor"
COLLECTOR = "collector"
HEARTBEAT = "heartbeat"
MEASUREMENTS = "measurements"
BACKEND = "backend"

#: Dependency order, and therefore the order in which a fault is attributed.
#: MEASUREMENTS precedes BACKEND because measuring does not need the backend,
#: and BACKEND precedes HEARTBEAT because heartbeat delivery does. Ordering
#: heartbeat earlier would make every backend outage look like a local
#: heartbeat fault - and heartbeat is LOCAL, so the node would reboot itself
#: over an outage it cannot fix.
STAGE_ORDER: Tuple[str, ...] = (
    FILESYSTEM,
    CLOCK,
    NETWORK,
    TAILSCALE,
    SENSOR,
    COLLECTOR,
    MEASUREMENTS,
    BACKEND,
    HEARTBEAT,
)

#: LOCAL   - the fault is on this node; a service restart, then a reboot, are
#:           plausible remedies.
#: EXTERNAL- the fault is somewhere else. Report it, alert on it, never reboot
#:           for it.
LOCAL = "local"
EXTERNAL = "external"

DEFAULT_STAGE_CLASS: Dict[str, str] = {
    FILESYSTEM: LOCAL,
    CLOCK: LOCAL,
    NETWORK: LOCAL,
    # Tailscale is an overlay on top of an uplink we already judge separately;
    # if it alone is down the node is reachable by other means and a reboot is
    # disproportionate.
    TAILSCALE: EXTERNAL,
    # A Shelly meter is a separate device on the sensor segment. Rebooting the
    # Pi cannot power it back on. Nodes whose sensor is ON the board (ADS1256
    # over SPI) should override this to LOCAL in hardening.conf.
    SENSOR: EXTERNAL,
    COLLECTOR: LOCAL,
    HEARTBEAT: LOCAL,
    MEASUREMENTS: LOCAL,
    BACKEND: EXTERNAL,
}

# -------------------------------------------------------------------- results

#: Tri-state, matching the convention the rest of the hardening package already
#: uses: a check with no data source reports UNKNOWN rather than passing.
OK = "ok"
FAILED = "failed"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class StageResult:
    """The outcome of probing one stage."""

    stage: str
    status: str  # OK | FAILED | UNKNOWN
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status == OK


# --------------------------------------------------------------------- policy


@dataclass(frozen=True)
class Policy:
    """Every tunable. No module below may hardcode any of these."""

    #: Service-level remedy attempts for one stage before a reboot is
    #: considered. "Try service-level recovery first" is this number.
    remedy_attempts: int = 3
    #: Seconds between remedy attempts for the same stage (exponential, capped).
    remedy_backoff_initial: int = 30
    remedy_backoff_max: int = 300
    #: Reboot budget: at most this many reboots inside this rolling window.
    reboot_max: int = 3
    reboot_window_s: int = 1800
    #: How often SAFE MODE re-attempts full recovery. Forever.
    safe_mode_retry_s: int = 900
    #: A node parked in SAFE MODE may try ONE more reboot after this long, in
    #: case the underlying fault was fixed externally (power restored, AP put
    #: back). Without it a node that entered SAFE MODE during a site outage
    #: would never reboot again even once the site came back. With it, the
    #: worst case is a handful of reboots per day, which is not a loop.
    safe_mode_reboot_after_s: int = 21600
    #: Stage classification overrides (stage -> LOCAL/EXTERNAL).
    stage_class: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_STAGE_CLASS))

    def classify(self, stage: str) -> str:
        return self.stage_class.get(stage, LOCAL)


# --------------------------------------------------------------------- ledger


@dataclass
class Ledger:
    """Recovery state that MUST survive a reboot.

    Kept as a plain dataclass so the decision core never touches a file. The
    escalation memory living across reboots is the whole boot-loop guard: the
    old selfheal reset its counter immediately before rebooting, so every boot
    started from zero and the node could reboot forever.
    """

    #: Monotonically appended UNIX timestamps of reboots WE performed.
    reboots: List[float] = field(default_factory=list)
    #: stage -> consecutive failed remedy attempts.
    attempts: Dict[str, int] = field(default_factory=dict)
    #: stage -> UNIX timestamp of the last remedy attempt.
    last_attempt: Dict[str, float] = field(default_factory=dict)
    #: When SAFE MODE was entered, or None.
    safe_mode_since: Optional[float] = None
    #: Last time SAFE MODE ran a full recovery sweep.
    safe_mode_last_retry: Optional[float] = None
    #: Last reboot performed FROM SAFE MODE. The cooldown is measured from
    #: this, not from safe_mode_since - otherwise the cooldown elapses once and
    #: stays elapsed, and SAFE MODE degenerates into a slow reboot loop.
    safe_mode_last_reboot: Optional[float] = None

    def reboots_in_window(self, now: float, window_s: int) -> int:
        return sum(1 for t in self.reboots if now - t <= window_s)


# --------------------------------------------------------------------- states

BOOTING = "BOOTING"
HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
RECOVERING = "RECOVERING"
SAFE_MODE = "SAFE_MODE"

# -------------------------------------------------------------------- actions

NONE = "none"
REMEDY = "remedy"
REBOOT = "reboot"
ENTER_SAFE_MODE = "enter_safe_mode"
LEAVE_SAFE_MODE = "leave_safe_mode"
WAIT = "wait"


@dataclass(frozen=True)
class Decision:
    state: str
    action: str
    stage: Optional[str] = None
    reason: str = ""


def first_failure(results: List[StageResult]) -> Optional[StageResult]:
    """The earliest FAILED stage in dependency order.

    UNKNOWN is deliberately not a failure. A stage with no data source (no UPS,
    no PMIC ADC, no Tailscale) must report unavailable, and a node must never
    reboot itself over a measurement it cannot take.
    """
    by_stage = {r.stage: r for r in results}
    for stage in STAGE_ORDER:
        r = by_stage.get(stage)
        if r is not None and r.status == FAILED:
            return r
    return None


def backoff_for(attempt: int, policy: Policy) -> int:
    """Exponential backoff, capped. attempt is 0-based."""
    delay = policy.remedy_backoff_initial * (2 ** max(0, attempt))
    return int(min(delay, policy.remedy_backoff_max))


def decide(
    results: List[StageResult],
    ledger: Ledger,
    now: float,
    policy: Policy,
) -> Decision:
    """Pure: what should the node do right now?

    Called on every tick. Returns exactly one action; the daemon performs it
    and records the outcome back into the ledger.
    """
    failure = first_failure(results)

    # ---------------------------------------------------------------- healthy
    if failure is None:
        if ledger.safe_mode_since is not None:
            return Decision(
                SAFE_MODE,
                LEAVE_SAFE_MODE,
                None,
                "all stages healthy - leaving SAFE MODE",
            )
        return Decision(HEALTHY, NONE, None, "all stages healthy")

    stage = failure.stage
    kind = policy.classify(stage)

    # -------------------------------------------------------------- safe mode
    if ledger.safe_mode_since is not None:
        last = ledger.safe_mode_last_retry or ledger.safe_mode_since
        # A reboot is permitted again only after a long cooldown measured from
        # the PREVIOUS safe-mode reboot, so SAFE MODE keeps trying forever
        # without becoming a slow reboot loop.
        since_reboot = now - (ledger.safe_mode_last_reboot or ledger.safe_mode_since)
        if (
            kind == LOCAL
            and since_reboot >= policy.safe_mode_reboot_after_s
            and ledger.reboots_in_window(now, policy.reboot_window_s) < policy.reboot_max
        ):
            return Decision(
                SAFE_MODE,
                REBOOT,
                stage,
                f"SAFE MODE cooldown elapsed - one more reboot attempt for {stage}",
            )
        if now - last >= policy.safe_mode_retry_s:
            return Decision(
                SAFE_MODE,
                REMEDY,
                stage,
                f"SAFE MODE periodic recovery attempt for {stage}",
            )
        return Decision(
            SAFE_MODE,
            WAIT,
            stage,
            f"SAFE MODE - next attempt in {int(policy.safe_mode_retry_s - (now - last))}s",
        )

    # ------------------------------------------------- external: never reboot
    attempts = ledger.attempts.get(stage, 0)
    last_attempt = ledger.last_attempt.get(stage)

    if last_attempt is not None:
        wait = backoff_for(attempts - 1 if attempts else 0, policy)
        if now - last_attempt < wait:
            return Decision(
                DEGRADED if kind == EXTERNAL else RECOVERING,
                WAIT,
                stage,
                f"{stage} failed; backing off {int(wait - (now - last_attempt))}s",
            )

    if kind == EXTERNAL:
        # Keep retrying the service-level remedy forever, never escalate.
        return Decision(
            DEGRADED,
            REMEDY,
            stage,
            f"{stage} failed (external dependency) - service-level remedy only",
        )

    # ------------------------------------------------ local: remedy then boot
    if attempts < policy.remedy_attempts:
        return Decision(
            RECOVERING,
            REMEDY,
            stage,
            f"{stage} failed - service-level remedy {attempts + 1}/{policy.remedy_attempts}",
        )

    if ledger.reboots_in_window(now, policy.reboot_window_s) < policy.reboot_max:
        return Decision(
            RECOVERING,
            REBOOT,
            stage,
            f"{stage} still failing after {attempts} remedies - rebooting",
        )

    return Decision(
        RECOVERING,
        ENTER_SAFE_MODE,
        stage,
        f"reboot budget exhausted ({policy.reboot_max} in "
        f"{policy.reboot_window_s}s) - entering SAFE MODE",
    )
