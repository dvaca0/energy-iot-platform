"""The networking supervisor -- the subsystem's single decision-making daemon.

Responsibilities:

* evaluate connectivity on a fixed cadence
* feed the result to the state machine and execute the one action it asks for
* publish the collector-facing availability contract
* serve the control socket used by the portal and the TUI

It is the only component that mutates network state.  Everything else asks.

Failure containment matters more than elegance here: an exception inside the
loop must never stop the loop, because the daemon that gives up is the daemon
that leaves a node unreachable.  Every iteration is wrapped, and systemd
restarts the unit if the process dies outright.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .ap_manager import AccessPointManager
from .config import Config, load_config
from .diagnostics import Diagnostics
from .evaluator import ConnectivityEvaluator
from .factory_reset import FactoryNetworkReset
from .ipc import ControlServer
from .models import Action, ConnectivityVerdict, LinkKind, NetState
from .nm import NetworkManager
from .statefile import StatePublisher
from .statemachine import ConnectivityStateMachine, MachineInput
from .wifi_manager import WifiManager

log = logging.getLogger("netd.supervisor")

CONTROL_GROUP = "energy-net"


def _sd_notify(message: str) -> None:
    """Send a notification to systemd, if we were started by it."""
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return
    if address.startswith("@"):
        address = "\0" + address[1:]
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
            sock.connect(address)
            sock.sendall(message.encode("utf-8"))
    except OSError:
        pass


class Supervisor:
    """Owns the connectivity lifecycle of the node."""

    def __init__(self, config: Optional[Config] = None) -> None:
        self._config = config or load_config()
        self._nm = NetworkManager()
        self._wifi = WifiManager(self._config, self._nm)
        self._ap = AccessPointManager(self._config, self._nm)
        self._evaluator = ConnectivityEvaluator(self._config, self._nm)
        self._diagnostics = Diagnostics(self._config, self._nm)
        self._reset = FactoryNetworkReset(self._config, self._nm, self._ap)
        self._machine = ConnectivityStateMachine(self._config.timing)
        self._publisher = StatePublisher(
            self._config.paths.state_file,
            ttl_seconds=self._config.timing.monitor_interval * 3,
        )

        # A single lock serialises every network mutation, whether it comes
        # from the monitor loop or from an operator action on the portal.
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._server: Optional[ControlServer] = None

        self._verdict: Optional[ConnectivityVerdict] = None
        self._last_transition_reason: str = "starting"
        self._force_ap: bool = False
        self._suppress_ap: bool = False
        self._deep_counter: int = 0
        self._started_at: float = time.time()
        self._last_error: Optional[str] = None

        self._commands: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
            "ping": lambda _a: self._ok({"pong": True}),
            "status": lambda _a: self._ok(self.status()),
            "config": lambda _a: self._ok(self._config.redacted()),
            "wifi.scan": self._cmd_wifi_scan,
            "wifi.saved": self._cmd_wifi_saved,
            "wifi.connect": self._cmd_wifi_connect,
            "wifi.disconnect": self._cmd_wifi_disconnect,
            "wifi.forget": self._cmd_wifi_forget,
            "wifi.priority": self._cmd_wifi_priority,
            "wifi.networks": self._cmd_wifi_networks,
            "wifi.reconcile": self._cmd_wifi_reconcile,
            "wifi.reset_operator": self._cmd_wifi_reset_operator,
            "ap.start": self._cmd_ap_start,
            "ap.stop": self._cmd_ap_stop,
            "ap.auto": self._cmd_ap_auto,
            "net.restart": self._cmd_net_restart,
            "service.restart": self._cmd_service_restart,
            "diagnostics.full": lambda _a: self._ok(self._diagnostics.full_report()),
            "diagnostics.tests": lambda _a: self._ok(
                {"tests": self._diagnostics.connectivity_tests()}
            ),
            "diagnostics.collector": lambda _a: self._ok(self._diagnostics.collector_stats()),
            "diagnostics.services": lambda _a: self._ok({"services": self._diagnostics.services()}),
            "logs.network": self._cmd_logs_network,
            "logs.collector": self._cmd_logs_collector,
            "factory.network_reset": self._cmd_factory_reset,
            "system.reboot": self._cmd_reboot,
            "system.shutdown": self._cmd_shutdown,
        }

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _ok(data: Optional[Dict[str, Any]] = None, message: str = "") -> Dict[str, Any]:
        payload: Dict[str, Any] = {"ok": True}
        if message:
            payload["message"] = message
        if data is not None:
            payload["data"] = data
        return payload

    @staticmethod
    def _fail(error: str) -> Dict[str, Any]:
        return {"ok": False, "error": error}

    @property
    def config(self) -> Config:
        return self._config

    # ------------------------------------------------------------------
    # persisted operator overrides
    # ------------------------------------------------------------------
    @property
    def _runtime_path(self) -> Path:
        return self._config.paths.var_dir / "runtime.json"

    def _load_runtime(self) -> None:
        """Restore operator overrides so a netd restart preserves intent."""
        try:
            data = json.loads(self._runtime_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(data, dict):
            self._force_ap = bool(data.get("force_ap", False))
            self._suppress_ap = bool(data.get("suppress_ap", False))
            log.info(
                "restored operator overrides: force_ap=%s suppress_ap=%s",
                self._force_ap,
                self._suppress_ap,
            )

    def _save_runtime(self) -> None:
        try:
            self._runtime_path.parent.mkdir(parents=True, exist_ok=True)
            self._runtime_path.write_text(
                json.dumps({"force_ap": self._force_ap, "suppress_ap": self._suppress_ap}),
                encoding="utf-8",
            )
        except OSError as exc:
            log.warning("could not persist runtime overrides: %s", exc)

    # ------------------------------------------------------------------
    # status
    # ------------------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        """Complete status snapshot for the UIs."""
        verdict = self._verdict
        now = time.monotonic()
        cfg = self._config
        return {
            "node": {
                "id": cfg.node.id,
                "hostname": socket.gethostname(),
                "model": cfg.node.model,
                "site": cfg.node.site,
            },
            "state": self._machine.state.value,
            "state_reason": self._last_transition_reason,
            "time_in_state": round(self._machine.time_in_state(now), 1),
            "offline_seconds": round(self._machine.offline_duration(now), 1),
            "stable_seconds": round(self._machine.stable_duration(now), 1),
            "retry_delay": self._machine.retry_delay,
            "connectivity": verdict.to_dict() if verdict else None,
            "network_available": bool(verdict and verdict.usable),
            "ssid": self._wifi.current_ssid(),
            "access_point": self._ap.status(),
            "overrides": {"force_ap": self._force_ap, "suppress_ap": self._suppress_ap},
            "thresholds": {
                "offline_before_ap": cfg.timing.offline_before_ap,
                "stable_before_ap_down": cfg.timing.stable_before_ap_down,
                "monitor_interval": cfg.timing.monitor_interval,
            },
            "daemon": {
                "version": "1.0.0",
                "uptime_seconds": round(time.time() - self._started_at, 1),
                "last_error": self._last_error,
                "config_path": str(cfg.source_path) if cfg.source_path else None,
            },
        }

    # ------------------------------------------------------------------
    # command handlers
    # ------------------------------------------------------------------
    #: Commands that only read state. The console polls these every few
    #: seconds; logging them at INFO would bury the transitions an operator
    #: actually needs to see when reading back the networking history.
    _READ_ONLY_COMMANDS = frozenset(
        {
            "ping", "status", "config", "wifi.saved", "wifi.networks",
            "diagnostics.full", "diagnostics.tests", "diagnostics.collector",
            "diagnostics.services", "logs.network", "logs.collector",
        }
    )

    def dispatch(self, command: str, args: Dict[str, Any]) -> Dict[str, Any]:
        handler = self._commands.get(command)
        if handler is None:
            return self._fail(f"unknown command '{command}'")
        if command in self._READ_ONLY_COMMANDS:
            log.debug("control query: %s", command)
        else:
            log.info("control command: %s %s", command, self._redact(args))
        return handler(args)

    @staticmethod
    def _redact(args: Dict[str, Any]) -> Dict[str, Any]:
        return {k: ("********" if "pass" in k.lower() else v) for k, v in args.items()}

    def _cmd_wifi_scan(self, args: Dict[str, Any]) -> Dict[str, Any]:
        force = bool(args.get("force", True))
        with self._lock:
            results = self._wifi.scan(force=force)
        return self._ok({"networks": [r.to_dict() for r in results]})

    def _cmd_wifi_saved(self, _args: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            saved = self._wifi.saved_networks()
        return self._ok({"saved": [n.to_dict() for n in saved]})

    def _cmd_wifi_networks(self, _args: Dict[str, Any]) -> Dict[str, Any]:
        """The effective whitelist, its provenance, its health and its rank.

        Credentials are never included - only whether one is held.
        """
        with self._lock:
            described = self._wifi.store.describe()
            health = {k: v.as_dict() for k, v in self._wifi.store.health().items()}
            ranked = [
                {"ssid": c.network.ssid, "source": c.network.source,
                 "priority": c.network.priority, "eligible": c.eligible,
                 "reason": c.reason, "signal": c.signal,
                 "retry_after": c.retry_after}
                for c in self._wifi.ranked()
            ]
        described["health"] = health
        described["ranked"] = ranked
        described["secrets"] = self._wifi.store.secrets_audit()
        return self._ok(described)

    def _cmd_wifi_reconcile(self, _args: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            actions = self._wifi.reconcile()
        return self._ok({"actions": actions})

    def _cmd_wifi_reset_operator(self, _args: Dict[str, Any]) -> Dict[str, Any]:
        """Explicit return to the git baseline. Never automatic."""
        with self._lock:
            ok, message = self._wifi.store.reset_operator_networks()
            if ok:
                self._wifi.reconcile()
        return self._ok({"reset": ok, "message": message})

    def _cmd_wifi_connect(self, args: Dict[str, Any]) -> Dict[str, Any]:
        ssid = str(args.get("ssid", "")).strip()
        password = args.get("password")
        password = str(password) if password not in (None, "") else None
        hidden = bool(args.get("hidden", False))
        priority = args.get("priority")

        if not ssid:
            return self._fail("SSID is required")
        try:
            priority_value = int(priority) if priority not in (None, "") else None
        except (TypeError, ValueError):
            return self._fail("priority must be a whole number")

        with self._lock:
            # Connecting implies the operator wants off the AP.
            was_ap = self._ap.is_active()
            if was_ap:
                log.info("lowering maintenance AP to attempt connection to %s", ssid)
                self._ap.stop(reconnect=False)

            ok, message = self._wifi.connect(ssid, password, priority_value, hidden)

            if ok:
                self._force_ap = False
                self._suppress_ap = False
                self._save_runtime()
                self._machine.note_ap_lowered()
            elif was_ap:
                # Restore the operator's lifeline; without this a wrong
                # password would strand the node with no AP and no Wi-Fi.
                log.warning("connection to %s failed; restoring maintenance AP", ssid)
                self._ap.start()
                self._machine.note_ap_raised(time.monotonic())
        return self._ok({"connected": ok}, message) if ok else self._fail(message)

    def _cmd_wifi_disconnect(self, _args: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            ok, message = self._wifi.disconnect()
        return self._ok(None, message) if ok else self._fail(message)

    def _cmd_wifi_forget(self, args: Dict[str, Any]) -> Dict[str, Any]:
        identifier = str(args.get("id") or args.get("ssid") or "").strip()
        if not identifier:
            return self._fail("network identifier is required")
        with self._lock:
            ok, message = self._wifi.forget(identifier)
        return self._ok(None, message) if ok else self._fail(message)

    def _cmd_wifi_priority(self, args: Dict[str, Any]) -> Dict[str, Any]:
        identifier = str(args.get("id") or args.get("ssid") or "").strip()
        if not identifier:
            return self._fail("network identifier is required")
        try:
            priority = int(args.get("priority", 0))
        except (TypeError, ValueError):
            return self._fail("priority must be a whole number")
        with self._lock:
            ok, message = self._wifi.set_priority(identifier, priority)
        return self._ok(None, message) if ok else self._fail(message)

    def _cmd_ap_start(self, _args: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            ok, message = self._ap.start()
            if ok:
                self._force_ap = True
                self._suppress_ap = False
                self._machine.note_ap_raised(time.monotonic())
                self._save_runtime()
        return self._ok(None, message) if ok else self._fail(message)

    def _cmd_ap_stop(self, _args: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            ok, message = self._ap.stop(reconnect=True)
            self._force_ap = False
            # Defer automatic re-raise so the operator gets a clear window.
            self._suppress_ap = True
            self._machine.note_ap_lowered()
            self._save_runtime()
        return self._ok(None, message) if ok else self._fail(message)

    def _cmd_ap_auto(self, _args: Dict[str, Any]) -> Dict[str, Any]:
        """Return the access point to automatic control.

        Clears BOTH operator overrides, so the state machine decides again by
        its own rules. This is what SAFE MODE needs: it must guarantee the AP
        is not suppressed, without pinning it open.

        Pinning matters more than it looks. These nodes have one radio, so an
        AP that is held open is an AP the node cannot leave to rejoin Wi-Fi -
        which would make SAFE MODE permanent and require the very physical
        visit the whole design exists to avoid.
        """
        with self._lock:
            self._force_ap = False
            self._suppress_ap = False
            self._save_runtime()
        return self._ok({"force_ap": False, "suppress_ap": False},
                        "access point returned to automatic control")

    def _cmd_net_restart(self, _args: Dict[str, Any]) -> Dict[str, Any]:
        """Restart NetworkManager.

        Scheduled as a detached job so the reply reaches the caller before its
        own connection is torn down.
        """
        return self._detached(
            ["systemctl", "restart", "NetworkManager.service"],
            delay=2,
            message="Restarting NetworkManager; connectivity will drop briefly.",
        )

    def _cmd_service_restart(self, args: Dict[str, Any]) -> Dict[str, Any]:
        unit = str(args.get("unit", "")).strip()
        if not unit:
            return self._fail("unit is required")
        allowed = set(self._config.services.manageable)
        if unit not in allowed:
            return self._fail(f"unit '{unit}' is not in the manageable list")
        if unit in ("energy-node-netd.service", "NetworkManager.service"):
            return self._detached(
                ["systemctl", "restart", unit], delay=2, message=f"Restarting {unit}."
            )
        try:
            proc = subprocess.run(
                ["systemctl", "restart", unit],
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            return self._fail(str(exc))
        if proc.returncode != 0:
            return self._fail(proc.stderr.strip() or f"exit {proc.returncode}")
        log.info("restarted %s on operator request", unit)
        return self._ok(None, f"Restarted {unit}")

    def _cmd_logs_network(self, args: Dict[str, Any]) -> Dict[str, Any]:
        lines = int(args.get("lines", self._config.portal.log_tail_lines))
        return self._ok({"entries": self._diagnostics.network_events(lines)})

    def _cmd_logs_collector(self, args: Dict[str, Any]) -> Dict[str, Any]:
        lines = int(args.get("lines", self._config.portal.log_tail_lines))
        return self._ok({"entries": self._diagnostics.collector_events(lines)})

    def _cmd_factory_reset(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Network-only factory reset; requires an explicit confirmation token."""
        if str(args.get("confirm", "")) != "RESET-NETWORK":
            return self._fail("confirmation token required")
        with self._lock:
            report = self._reset.run(start_ap=True)
            self._force_ap = True
            self._suppress_ap = False
            self._machine.note_ap_raised(time.monotonic())
            self._save_runtime()
        return self._ok(report.to_dict(), "Network configuration reset")

    def _cmd_reboot(self, _args: Dict[str, Any]) -> Dict[str, Any]:
        if not self._config.portal.allow_power_actions:
            return self._fail("power actions are disabled in configuration")
        log.warning("reboot requested by operator")
        return self._detached(["systemctl", "reboot"], delay=3, message="Rebooting node.")

    def _cmd_shutdown(self, _args: Dict[str, Any]) -> Dict[str, Any]:
        if not self._config.portal.allow_power_actions:
            return self._fail("power actions are disabled in configuration")
        log.warning("shutdown requested by operator")
        return self._detached(["systemctl", "poweroff"], delay=3, message="Shutting node down.")

    @staticmethod
    def _detached(argv: List[str], delay: int, message: str) -> Dict[str, Any]:
        """Run a disruptive command shortly after replying to the caller."""
        def runner() -> None:
            time.sleep(delay)
            try:
                subprocess.run(argv, capture_output=True, text=True, timeout=120, check=False)
            except (subprocess.TimeoutExpired, OSError) as exc:  # pragma: no cover
                log.error("detached command %s failed: %s", argv, exc)

        threading.Thread(target=runner, name="netd-detached", daemon=True).start()
        return {"ok": True, "message": message}

    # ------------------------------------------------------------------
    # the monitor loop
    # ------------------------------------------------------------------
    def _execute(self, action: Action) -> None:
        """Perform the single side effect requested by the state machine."""
        if action is Action.NONE:
            return
        if action is Action.START_AP:
            ok, message = self._ap.start()
            if ok:
                self._machine.note_ap_raised(time.monotonic())
            else:
                log.error("automatic AP activation failed: %s", message)
        elif action is Action.STOP_AP:
            ok, message = self._ap.stop(reconnect=True)
            if ok:
                self._machine.note_ap_lowered()
            else:
                log.error("automatic AP deactivation failed: %s", message)
        elif action is Action.RETRY_WIFI:
            if self._ap.is_active():
                # Recovery probe: give the radio back to the client for one
                # cycle, then let the next iteration decide what to do.
                log.info("recovery probe: lowering AP to look for known networks")
                self._ap.stop(reconnect=True)
                self._machine.note_ap_lowered()
            else:
                ok, message = self._wifi.reconnect()
                if not ok:
                    log.debug("reconnect nudge: %s", message)
        elif action is Action.RESCAN:
            self._wifi.scan(force=True)

    def _iterate(self) -> None:
        """One full evaluate-decide-act-publish cycle."""
        with self._lock:
            ap_active = self._ap.is_active()

            # A full probe sweep every third cycle keeps the backend from
            # being polled every ten seconds while staying responsive to a
            # local link going down.
            self._deep_counter += 1
            deep = (self._deep_counter % 3 == 1) or self._machine.state in (
                NetState.OFFLINE_BUFFERING,
                NetState.RECOVERING,
                NetState.CONNECTING,
            )

            verdict = self._evaluator.evaluate(ap_active=ap_active, deep=deep)
            self._verdict = verdict

            # Health-aware: a network that is merely visible is not a network
            # worth trying. One that is backing off after repeated failures
            # does not count as available, so the AP goes up when there is
            # genuinely nothing left to attempt rather than when nothing is in
            # range. should_raise_ap() is the inverse of this flag.
            known = (not self._wifi.should_raise_ap()) if not ap_active else False

            # Record what the world just told us, and keep NetworkManager's
            # roaming order in step with it. Reconciling every cycle would
            # spawn nmcli constantly, so do it on the deep cycle only.
            if deep:
                # The verdict already carries the associated SSID, and
                # `usable` is netd's own bar for "a network worth staying on".
                if verdict.ssid and verdict.usable:
                    self._wifi.note_result(verdict.ssid, True)
                try:
                    self._wifi.reconcile()
                except Exception as exc:  # noqa: BLE001 - never break the loop
                    log.warning("network reconciliation failed: %s", exc)
            data = MachineInput(
                verdict=verdict,
                now=time.monotonic(),
                ap_active=ap_active,
                ap_clients=self._ap.client_count() if ap_active else 0,
                known_networks_in_range=known,
                force_ap=self._force_ap,
                suppress_ap=self._suppress_ap,
            )
            transition = self._machine.step(data)
            self._last_transition_reason = transition.reason

            if transition.changed:
                log.info(
                    "TRANSITION %s -> %s | %s | link=%s ssid=%s",
                    transition.previous.value,
                    transition.state.value,
                    transition.reason,
                    verdict.link.value,
                    verdict.ssid or "-",
                )
                # Once the node is back online, clear the operator's AP
                # suppression so automatic protection resumes.
                if transition.state is NetState.ONLINE:
                    self._suppress_ap = False
                    self._save_runtime()

            self._execute(transition.action)

            self._publisher.publish(
                available=verdict.usable,
                detail={
                    "state": self._machine.state.value,
                    "reason": transition.reason,
                    "link": verdict.link.value,
                    "ssid": verdict.ssid,
                    "ipv4": verdict.ipv4,
                    "gateway_ok": verdict.gateway_ok,
                    "dns_ok": verdict.dns_ok,
                    "internet_ok": verdict.internet_ok,
                    "backend_ok": verdict.backend_ok,
                    "ap_active": self._ap.is_active(),
                    "node_id": self._config.node.id,
                },
            )

    def run(self) -> int:
        """Start the daemon and block until stopped."""
        cfg = self._config
        log.info(
            "netd starting: node=%s wifi=%s ethernet=%s ap_ssid=%s portal=http://%s",
            cfg.node.id,
            cfg.interfaces.wifi,
            cfg.interfaces.ethernet,
            cfg.ap_ssid,
            cfg.access_point.address,
        )

        if not NetworkManager.available():
            log.error("nmcli not found; the networking subsystem cannot operate")
            return 1
        if not self._nm.running():
            log.warning("NetworkManager is not responding yet; continuing and retrying")

        try:
            cfg.paths.var_dir.mkdir(parents=True, exist_ok=True)
            cfg.paths.state_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.error("could not create working directories: %s", exc)

        self._load_runtime()

        # Prepare the AP profile up front so it is ready before it is needed.
        ok, message = self._ap.ensure_profile(force=True)
        if not ok:
            log.error("maintenance AP will not be available: %s", message)

        self._install_signal_handlers()

        try:
            self._server = ControlServer(
                cfg.paths.control_socket, self.dispatch, group=CONTROL_GROUP
            )
            self._server.serve_in_thread()
            log.info("control socket listening at %s", cfg.paths.control_socket)
        except OSError as exc:
            log.error("could not open control socket: %s", exc)

        _sd_notify("READY=1")
        _sd_notify(f"STATUS=monitoring ({cfg.node.id})")

        interval = cfg.timing.monitor_interval
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self._iterate()
                self._last_error = None
            except Exception as exc:  # noqa: BLE001 - the loop must never die
                self._last_error = f"{type(exc).__name__}: {exc}"
                log.exception("monitor iteration failed; continuing")
            _sd_notify("WATCHDOG=1")
            _sd_notify(f"STATUS={self._machine.state.value}: {self._last_transition_reason}")

            elapsed = time.monotonic() - started
            self._stop.wait(max(1.0, interval - elapsed))

        log.info("netd stopping")
        _sd_notify("STOPPING=1")
        if self._server is not None:
            self._server.shutdown_and_close()
        return 0

    # ------------------------------------------------------------------
    def stop(self) -> None:
        self._stop.set()

    def _install_signal_handlers(self) -> None:
        def handler(signum: int, _frame: Any) -> None:
            log.info("received signal %d", signum)
            self.stop()

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):  # pragma: no cover
                pass
