"""The connectivity state machine.

Pure decision logic: it consumes an immutable :class:`MachineInput` and
produces a :class:`~netd.models.Transition` naming the next state and the one
side effect the supervisor should perform.  It touches no files, no sockets
and no clock of its own -- time arrives as a parameter -- which makes every
transition in this module directly unit-testable.

Designed flow::

    BOOT -> CONNECTING -> ONLINE
                 |           |
                 v           v
          OFFLINE_BUFFERING <-
                 |
                 v
          MAINTENANCE_AP -> RECOVERING -> ONLINE

No path in this machine requires a reboot, and every state has an edge back to
ONLINE.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from .config import TimingConfig
from .models import Action, ConnectivityVerdict, LinkKind, NetState, Transition

log = logging.getLogger("netd.statemachine")


@dataclass(frozen=True)
class MachineInput:
    """Everything the machine needs to decide, at one instant."""

    verdict: ConnectivityVerdict
    now: float
    """Monotonic seconds."""

    ap_active: bool = False
    ap_clients: int = 0
    """Stations associated with the maintenance AP.  A non-zero value means an
    operator is mid-session, and the machine will not pull the AP out from
    under them to run a recovery probe."""

    known_networks_in_range: bool = False
    """True when a saved Wi-Fi profile matches a network seen in the last scan."""

    force_ap: bool = False
    """Operator asked for the AP explicitly."""

    suppress_ap: bool = False
    """Operator dismissed the AP; auto-raise is deferred."""


class ConnectivityStateMachine:
    """Tracks connectivity state and decides transitions."""

    def __init__(self, timing: TimingConfig, initial: NetState = NetState.BOOT) -> None:
        self._timing = timing
        self._state: NetState = initial
        self._entered_at: Optional[float] = None
        self._usable_since: Optional[float] = None
        self._unusable_since: Optional[float] = None
        self._ap_raised_at: Optional[float] = None
        self._last_retry: Optional[float] = None
        self._retry_delay: int = timing.retry_backoff_initial
        self._last_reason: str = "initialised"

    # ------------------------------------------------------------------
    # introspection
    # ------------------------------------------------------------------
    @property
    def state(self) -> NetState:
        return self._state

    @property
    def reason(self) -> str:
        return self._last_reason

    @property
    def retry_delay(self) -> int:
        return self._retry_delay

    def time_in_state(self, now: float) -> float:
        if self._entered_at is None:
            return 0.0
        return max(0.0, now - self._entered_at)

    def offline_duration(self, now: float) -> float:
        if self._unusable_since is None:
            return 0.0
        return max(0.0, now - self._unusable_since)

    def stable_duration(self, now: float) -> float:
        if self._usable_since is None:
            return 0.0
        return max(0.0, now - self._usable_since)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    def _enter(self, state: NetState, now: float, reason: str) -> None:
        if state is not self._state:
            log.info("state %s -> %s (%s)", self._state.value, state.value, reason)
        self._state = state
        self._entered_at = now
        self._last_reason = reason

    def _track_usability(self, usable: bool, now: float) -> None:
        """Maintain the continuous usable / unusable timers."""
        if usable:
            if self._usable_since is None:
                self._usable_since = now
            self._unusable_since = None
        else:
            if self._unusable_since is None:
                self._unusable_since = now
            self._usable_since = None

    def _should_retry(self, now: float) -> bool:
        """Whether a reconnect attempt is due, honouring exponential backoff."""
        if self._last_retry is None:
            return True
        return (now - self._last_retry) >= self._retry_delay

    def _note_retry(self, now: float) -> None:
        self._last_retry = now
        self._retry_delay = min(self._retry_delay * 2, self._timing.retry_backoff_max)

    def _reset_backoff(self) -> None:
        self._last_retry = None
        self._retry_delay = self._timing.retry_backoff_initial

    def note_ap_raised(self, now: float) -> None:
        self._ap_raised_at = now

    def note_ap_lowered(self) -> None:
        self._ap_raised_at = None

    # ------------------------------------------------------------------
    # the machine
    # ------------------------------------------------------------------
    def step(self, data: MachineInput) -> Transition:
        """Advance the machine by one observation."""
        previous = self._state
        now = data.now
        if self._entered_at is None:
            self._entered_at = now

        usable = data.verdict.usable
        self._track_usability(usable, now)

        # --- operator overrides win over everything -------------------
        if data.force_ap and self._state is not NetState.MAINTENANCE_AP:
            self._enter(NetState.MAINTENANCE_AP, now, "operator forced maintenance AP")
            return Transition(self._state, previous, Action.START_AP, self._last_reason)

        timing = self._timing

        # --- BOOT -----------------------------------------------------
        if self._state is NetState.BOOT:
            if usable:
                self._reset_backoff()
                self._enter(NetState.ONLINE, now, f"uplink up at boot ({data.verdict.summary})")
                return Transition(self._state, previous, Action.NONE, self._last_reason)
            if self.time_in_state(now) >= timing.boot_grace:
                self._enter(
                    NetState.CONNECTING,
                    now,
                    f"boot grace of {timing.boot_grace}s elapsed without an uplink",
                )
                return Transition(self._state, previous, Action.RESCAN, self._last_reason)
            return Transition(self._state, previous, Action.NONE, "waiting for NetworkManager")

        # --- CONNECTING -----------------------------------------------
        if self._state is NetState.CONNECTING:
            if usable:
                self._reset_backoff()
                self._enter(NetState.ONLINE, now, f"connected ({data.verdict.summary})")
                return Transition(self._state, previous, Action.NONE, self._last_reason)
            if self.time_in_state(now) >= timing.connect_grace:
                self._enter(
                    NetState.OFFLINE_BUFFERING,
                    now,
                    f"no uplink after {timing.connect_grace}s of connecting",
                )
                return Transition(self._state, previous, Action.NONE, self._last_reason)
            if self._should_retry(now):
                self._note_retry(now)
                return Transition(
                    self._state, previous, Action.RETRY_WIFI, "retrying saved networks"
                )
            return Transition(self._state, previous, Action.NONE, "connection attempt in flight")

        # --- ONLINE ---------------------------------------------------
        if self._state is NetState.ONLINE:
            if usable:
                self._reset_backoff()
                return Transition(self._state, previous, Action.NONE, data.verdict.summary)
            self._enter(NetState.OFFLINE_BUFFERING, now, "uplink lost")
            return Transition(self._state, previous, Action.RETRY_WIFI, self._last_reason)

        # --- OFFLINE_BUFFERING ----------------------------------------
        if self._state is NetState.OFFLINE_BUFFERING:
            if usable:
                self._reset_backoff()
                self._enter(NetState.ONLINE, now, f"uplink restored ({data.verdict.summary})")
                return Transition(self._state, previous, Action.NONE, self._last_reason)

            offline_for = self.offline_duration(now)
            if (
                offline_for >= timing.offline_before_ap
                and not data.suppress_ap
                and not data.ap_active
            ):
                self._enter(
                    NetState.MAINTENANCE_AP,
                    now,
                    f"offline for {int(offline_for)}s (threshold {timing.offline_before_ap}s)",
                )
                return Transition(self._state, previous, Action.START_AP, self._last_reason)

            if self._should_retry(now):
                self._note_retry(now)
                return Transition(
                    self._state,
                    previous,
                    Action.RETRY_WIFI,
                    f"reconnect attempt (next backoff {self._retry_delay}s)",
                )
            return Transition(
                self._state, previous, Action.NONE, f"offline {int(offline_for)}s, buffering"
            )

        # --- MAINTENANCE_AP -------------------------------------------
        if self._state is NetState.MAINTENANCE_AP:
            # Ethernet can recover the node without disturbing the AP at all.
            if usable and data.verdict.link is not LinkKind.AP:
                self._enter(
                    NetState.RECOVERING, now, f"uplink available ({data.verdict.summary})"
                )
                return Transition(self._state, previous, Action.NONE, self._last_reason)

            if data.force_ap:
                return Transition(self._state, previous, Action.NONE, "AP held open by operator")

            # Periodic self-healing: drop the AP briefly to look for a known
            # network again, so a node recovers on its own when the Wi-Fi
            # comes back. Never while an operator is associated.
            ap_uptime = (
                now - self._ap_raised_at if self._ap_raised_at is not None else self.time_in_state(now)
            )
            if (
                ap_uptime >= timing.ap_min_uptime
                and data.ap_clients == 0
                and self._should_retry(now)
            ):
                self._note_retry(now)
                return Transition(
                    self._state,
                    previous,
                    Action.RETRY_WIFI,
                    "recovery probe: looking for known networks",
                )
            return Transition(
                self._state,
                previous,
                Action.NONE,
                f"maintenance AP active ({data.ap_clients} client(s))",
            )

        # --- RECOVERING -----------------------------------------------
        if self._state is NetState.RECOVERING:
            if not usable:
                self._enter(NetState.OFFLINE_BUFFERING, now, "uplink lost again during recovery")
                return Transition(self._state, previous, Action.NONE, self._last_reason)
            stable_for = self.stable_duration(now)
            if stable_for >= timing.stable_before_ap_down:
                self._reset_backoff()
                self._enter(
                    NetState.ONLINE,
                    now,
                    f"uplink stable for {int(stable_for)}s; maintenance AP no longer needed",
                )
                return Transition(
                    self._state,
                    previous,
                    Action.STOP_AP if data.ap_active else Action.NONE,
                    self._last_reason,
                )
            return Transition(
                self._state,
                previous,
                Action.NONE,
                f"confirming stability ({int(stable_for)}/{timing.stable_before_ap_down}s)",
            )

        # Unreachable in practice; fail safe towards reconnecting.
        self._enter(NetState.CONNECTING, now, "unknown state, resetting")
        return Transition(self._state, previous, Action.RESCAN, self._last_reason)
