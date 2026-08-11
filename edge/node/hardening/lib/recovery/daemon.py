"""The Recovery Manager supervisor loop — the I/O half.

Probes the node, asks the pure decision core what to do, does exactly that
one thing, records the outcome, and publishes health state for anything else
that wants it.

    while True:
        results  = probes.probe_all()
        decision = pipeline.decide(results, ledger, now, policy)
        act(decision)
        ledger.save()
        publish(health-state.json)

DESIGN RULES
    * One action per tick. Never restart three services and a reboot in the
      same breath: the ledger would not know which one was being tested.
    * Every transition is logged with its reason, so the journal answers
      "where did boot fail" without anyone having to reproduce it.
    * OBSERVE-ONLY is the default. A recovery mechanism that has never been
      watched is not trustworthy, so the first deployment computes decisions
      and actuates nothing until an operator has read them.
    * The daemon must never be the reason a node is unrecoverable. Every
      failure path is caught; a crash in a probe is UNKNOWN, not a fault.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from typing import List, Optional

_LIB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

import enconfig  # noqa: E402

from recovery import bootstate  # noqa: E402
from recovery import ledger as ledger_mod  # noqa: E402
from recovery import pipeline as P  # noqa: E402
from recovery import probes  # noqa: E402

__version__ = "1.0.0"

STATE_FILE = "health-state.json"


# ------------------------------------------------------------------ remedies

#: Service-level remedies, tried in order as attempts accumulate. The last
#: entry is reused once the list is exhausted.
#:
#: NETWORK follows the agreed ladder explicitly: reconnect (netd's own job),
#: then restart NetworkManager, then both - and only then does the decision
#: core allow a reboot.
REMEDIES = {
    P.FILESYSTEM: [["mount", "-o", "remount,rw", "/"]],
    P.CLOCK: [
        ["systemctl", "restart", "systemd-timesyncd.service"],
        ["systemctl", "restart", "systemd-timesyncd.service"],
    ],
    P.NETWORK: [
        ["systemctl", "restart", "energy-node-netd.service"],
        ["systemctl", "restart", "NetworkManager.service"],
        ["systemctl", "restart", "NetworkManager.service", "energy-node-netd.service"],
    ],
    P.TAILSCALE: [["systemctl", "restart", "tailscaled.service"]],
    P.SENSOR: [["systemctl", "restart", "energy-node-collector.service"]],
    P.COLLECTOR: [["systemctl", "restart", "energy-node-collector.service"]],
    P.MEASUREMENTS: [["systemctl", "restart", "energy-node-collector.service"]],
    P.HEARTBEAT: [["systemctl", "restart", "energy-node-collector.service"]],
    # Nothing on this node can fix a backend that is down. The remedy is to
    # keep looking, which the loop does anyway.
    P.BACKEND: [],
}


def log(msg: str) -> None:
    print(f"[recovery] {msg}", flush=True)


# --------------------------------------------------------------- boot record

#: The boot record is valuable but it is NOT load-bearing for recovery. If the
#: database is missing, locked or corrupt the node must still recover itself,
#: so every call goes through here: it complains loudly, once per failure, and
#: never propagates.
_bs_conn = None
_bs_broken = False


def bs(fn, *args, **kwargs):
    """Run a bootstate operation, tolerating a broken database."""
    global _bs_conn, _bs_broken
    try:
        if _bs_conn is None:
            _bs_conn = bootstate.connect()
            _bs_broken = False
        return fn(_bs_conn, *args, **kwargs)
    except Exception as exc:
        if not _bs_broken:
            log(f"BOOT RECORD UNAVAILABLE ({type(exc).__name__}: {exc}). "
                f"Recovery continues; boot progression is not being persisted.")
            _bs_broken = True
        try:
            if _bs_conn is not None:
                _bs_conn.close()
        except Exception:
            pass
        _bs_conn = None
        return None


def run(cmd: List[str], timeout: int = 90) -> bool:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            log(f"  command failed rc={r.returncode}: {' '.join(cmd)} :: "
                f"{(r.stderr or '').strip()[:200]}")
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"  command error: {' '.join(cmd)} :: {exc}")
        return False


# -------------------------------------------------------------------- policy


def load_policy() -> P.Policy:
    stage_class = dict(P.DEFAULT_STAGE_CLASS)
    for stage in P.STAGE_ORDER:
        key = f"RECOVERY_STAGE_{stage.upper()}_CLASS"
        val = (enconfig.get(key, "") or "").strip().lower()
        if val in (P.LOCAL, P.EXTERNAL):
            stage_class[stage] = val
    return P.Policy(
        remedy_attempts=enconfig.get_int("RECOVERY_REMEDY_ATTEMPTS", 3),
        remedy_backoff_initial=enconfig.get_int("RECOVERY_REMEDY_BACKOFF_INITIAL", 30),
        remedy_backoff_max=enconfig.get_int("RECOVERY_REMEDY_BACKOFF_MAX", 300),
        reboot_max=enconfig.get_int("RECOVERY_REBOOT_MAX", 3),
        reboot_window_s=enconfig.get_int("RECOVERY_REBOOT_WINDOW_S", 1800),
        safe_mode_retry_s=enconfig.get_int("RECOVERY_SAFE_MODE_RETRY_S", 900),
        safe_mode_reboot_after_s=enconfig.get_int(
            "RECOVERY_SAFE_MODE_REBOOT_AFTER_S", 21600),
        stage_class=stage_class,
    )


def observe_only() -> bool:
    return enconfig.get_bool("RECOVERY_OBSERVE_ONLY", True)


def forced_safe_mode() -> bool:
    """Deliberate, reversible test trigger for SAFE MODE.

    SAFE MODE is the hardest state to reach honestly - it needs a fault the
    ladder cannot fix - and validating it by breaking a node for real is a poor
    trade. This flag enters and HOLDS SAFE MODE without any fault, so the AP,
    the portal, the retry cadence and the exit path can all be watched on a
    live node and then undone by clearing one config value.

    It lives here in the I/O layer on purpose: the pure decision core must not
    grow a test-only branch, or the thing under test stops being the thing
    that runs in production.
    """
    return enconfig.get_bool("RECOVERY_FORCE_SAFE_MODE", False)


# ----------------------------------------------------------------- safe mode


def netdctl(*args: str, timeout: int = 60) -> bool:
    binary = ("/usr/local/bin/netdctl" if os.path.exists("/usr/local/bin/netdctl")
              else "netdctl")
    return run([binary, *args], timeout=timeout)


def safe_mode_actions(dry: bool = False) -> List[str]:
    """What SAFE MODE does, as a list of steps. Shared by the doer and the
    planner, so `plan` can never drift from what actually happens."""
    return [
        "systemctl start ssh.service            (keep the operator's way in)",
        "systemctl start energy-node-portal.service  (recovery portal)",
        "netdctl ap auto                        (permit the AP; never pin it)",
    ]


def enter_safe_mode(dry: bool = False) -> None:
    """SSH up, portal up, access point PERMITTED - never pinned.

    SAFE MODE is what a technician arrives to, so it is deliberately the most
    reachable the node ever gets. But reachable to a visitor is not the point:
    the node must still be able to rescue itself.

    WHY THIS DOES NOT RAISE THE AP
        `netdctl ap start` sets force_ap, and the state machine then answers
        "AP held open by operator" and skips its own self-healing probe. These
        nodes have ONE radio, so an access point that is held open is an access
        point the node can never leave to rejoin Wi-Fi. SAFE MODE would become
        permanent and would require exactly the physical visit this whole
        design exists to avoid.

        So SAFE MODE only guarantees the AP is not SUPPRESSED. netd raises it
        by its own rules when the node is genuinely offline, drops it
        periodically to look for known networks, and takes it down for good
        once an uplink is stable. The radio stays netd's to own.
    """
    prefix = "WOULD " if dry else ""
    log(f"{prefix}SAFE MODE: ensuring SSH and portal, returning AP to "
        f"automatic control (NOT pinning it)")
    if dry:
        for step in safe_mode_actions():
            log(f"    WOULD {step}")
        return
    run(["systemctl", "start", "ssh.service"])
    run(["systemctl", "start", "energy-node-portal.service"])
    netdctl("ap", "auto")


def leave_safe_mode(dry: bool = False) -> None:
    """Nothing to undo on the radio.

    netd lowers the access point itself once an uplink has been stable, so
    tearing it down from here would race the supervisor for control of the
    one thing it owns.
    """
    prefix = "WOULD " if dry else ""
    log(f"{prefix}leaving SAFE MODE - netd lowers the AP on its own once the "
        f"uplink is stable")


# ------------------------------------------------------------------ publish


def publish(state: str, results: List[P.StageResult], decision: P.Decision,
            led: P.Ledger, now: float, boot: Optional[dict] = None) -> None:
    """One fact, on the netd pattern, so Health has a machine-readable contract
    instead of something a human reads in a terminal."""
    d = enconfig.get("NETD_STATE_DIR", "/run/energy-node")
    path = os.path.join(d, STATE_FILE)
    payload = {
        "schema": 1,
        "state": state,
        "updated_at": now,
        "ttl_seconds": enconfig.get_int("RECOVERY_INTERVAL_S", 60) * 3,
        "node_id": enconfig.node_id(),
        "observe_only": observe_only(),
        "decision": {
            "action": decision.action,
            "stage": decision.stage,
            "reason": decision.reason,
        },
        "stages": [
            {"stage": r.stage, "status": r.status, "detail": r.detail} for r in results
        ],
        "first_failure": (P.first_failure(results).stage
                          if P.first_failure(results) else None),
        "ledger": {
            "reboots_last_window": led.reboots_in_window(
                now, load_policy().reboot_window_s),
            "attempts": led.attempts,
            "safe_mode_since": led.safe_mode_since,
        },
        # The durable boot record, surfaced through the SAME local contract
        # rather than a second daemon or a second endpoint.
        "boot": {
            "boot_id": (boot or {}).get("boot_id"),
            "started_at": (boot or {}).get("boot_started_iso"),
            "prev_boot_reason": (boot or {}).get("prev_boot_reason"),
            "last_successful_stage": (boot or {}).get("last_successful_stage"),
            "first_failed_stage": (boot or {}).get("first_failed_stage"),
            "failure_owner": (boot or {}).get("failure_owner"),
            "boot_complete": bool((boot or {}).get("boot_complete")),
            "time_to_healthy_s": (boot or {}).get("time_to_healthy_s"),
            "service_restarts": (boot or {}).get("service_restarts"),
            "reboot_attempts": (boot or {}).get("reboot_attempts"),
            "safe_mode_entered": bool((boot or {}).get("safe_mode_entered")),
        } if boot else None,
    }
    try:
        os.makedirs(d, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except OSError as exc:
        log(f"could not publish health state: {exc}")


# ------------------------------------------------------------------- sd_notify


def sd_notify(msg: str) -> None:
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        s.connect(addr)
        s.sendall(msg.encode())
        s.close()
    except OSError:
        pass


# ---------------------------------------------------------------------- tick


def act(decision: P.Decision, led: P.Ledger, now: float, dry: bool) -> None:
    stage = decision.stage
    prefix = "WOULD " if dry else ""

    if decision.action == P.REMEDY:
        attempt = led.attempts.get(stage, 0)
        ladder = REMEDIES.get(stage, [])
        if not ladder:
            log(f"{stage}: no local remedy exists (external) - continuing to watch")
            led.attempts[stage] = attempt + 1
            led.last_attempt[stage] = now
            return
        cmd = ladder[min(attempt, len(ladder) - 1)]
        log(f"{prefix}REMEDY {stage} attempt {attempt + 1}: {' '.join(cmd)}")
        if not dry:
            run(cmd)
            bs(bootstate.event, bootstate.E_REMEDY, stage,
               f"attempt {attempt + 1}: {' '.join(cmd)}", now)
        led.attempts[stage] = attempt + 1
        led.last_attempt[stage] = now
        if led.safe_mode_since is not None:
            led.safe_mode_last_retry = now

    elif decision.action == P.REBOOT:
        log(f"{prefix}REBOOT: {decision.reason}")
        led.reboots.append(now)
        led.attempts[stage] = 0
        if led.safe_mode_since is not None:
            led.safe_mode_last_reboot = now
            led.safe_mode_last_retry = now
        if not dry:
            # Persist BEFORE rebooting: a ledger written after the reboot
            # command is a ledger that never gets written, and that is exactly
            # how the old code lost its escalation memory every boot.
            bs(bootstate.event, bootstate.E_REBOOT, stage, decision.reason, now)
            ledger_mod.save(led, observe_only=False)
            run(["systemctl", "reboot"], timeout=30)

    elif decision.action == P.ENTER_SAFE_MODE:
        log(f"{prefix}ENTER SAFE MODE: {decision.reason}")
        led.safe_mode_since = now
        led.safe_mode_last_retry = now
        bs(bootstate.event, bootstate.E_SAFE_MODE, stage, decision.reason, now)
        enter_safe_mode(dry=dry)

    elif decision.action == P.LEAVE_SAFE_MODE:
        log("LEAVING SAFE MODE - node healthy")
        bs(bootstate.event, bootstate.E_SAFE_MODE_EXIT, None,
           "all stages healthy", now)
        leave_safe_mode(dry=dry)
        led.safe_mode_since = None
        led.safe_mode_last_retry = None
        led.safe_mode_last_reboot = None
        led.attempts.clear()
        led.last_attempt.clear()


def tick(led: P.Ledger, policy: P.Policy, last_state: Optional[str]) -> str:
    now = time.time()
    results = probes.probe_all()
    decision = P.decide(results, led, now, policy)

    # The forced-SAFE-MODE test hook. Applied AFTER the real decision, so the
    # production path is exactly what it would be without it.
    if forced_safe_mode():
        if led.safe_mode_since is None:
            log("FORCED SAFE MODE (RECOVERY_FORCE_SAFE_MODE=1) - entering "
                "deliberately; no fault is present")
            led.safe_mode_since = now
            led.safe_mode_last_retry = now
            bs(bootstate.event, bootstate.E_SAFE_MODE, None,
               "forced by RECOVERY_FORCE_SAFE_MODE (test)", now)
            enter_safe_mode(dry=observe_only())
        elif now - (led.safe_mode_last_retry or 0) >= policy.safe_mode_retry_s:
            log("FORCED SAFE MODE: periodic recovery attempt (no fault to fix)")
            led.safe_mode_last_retry = now
            bs(bootstate.event, bootstate.E_SAFE_MODE_RETRY, None,
               "forced safe-mode periodic retry (no service was restarted)",
               now)
        decision = P.Decision(P.SAFE_MODE, P.WAIT, decision.stage,
                              "held by RECOVERY_FORCE_SAFE_MODE (test hook)")

    if decision.state != last_state:
        log(f"STATE {last_state or 'START'} -> {decision.state} | {decision.reason}")
        for r in results:
            if r.status != P.OK:
                log(f"    {r.stage:14} {r.status:8} {r.detail}")

    if (not forced_safe_mode() and led.safe_mode_since is not None
            and P.first_failure(results) is None):
        # The flag was cleared (or the fault cleared) while parked in SAFE
        # MODE: leave on the very next tick rather than waiting for a retry.
        decision = P.Decision(P.SAFE_MODE, P.LEAVE_SAFE_MODE, None,
                              "no failing stage and SAFE MODE not forced")

    if decision.action not in (P.NONE, P.WAIT):
        act(decision, led, now, dry=observe_only())

    # A healthy stage clears its own attempt counter, so a transient fault
    # does not accumulate toward a reboot across unrelated incidents.
    for r in results:
        if r.status == P.OK and r.stage in led.attempts:
            led.attempts.pop(r.stage, None)
            led.last_attempt.pop(r.stage, None)

    # Durable boot progression, so "how far did this boot get" survives the
    # next reboot, watchdog reset or power cut.
    bs(bootstate.update, results, decision, policy, now)

    ledger_mod.prune(led, now)
    try:
        ledger_mod.save(led, observe_only=observe_only())
    except OSError as exc:
        log(f"could not persist ledger: {exc}")
    publish(decision.state, results, decision, led, now,
            boot=bs(bootstate.status))
    return decision.state


def main() -> int:
    interval = enconfig.get_int("RECOVERY_INTERVAL_S", 60)
    policy = load_policy()
    log(f"Recovery Manager {__version__} starting | node={enconfig.node_id()} "
        f"interval={interval}s observe_only={observe_only()}")
    if forced_safe_mode():
        log("  RECOVERY_FORCE_SAFE_MODE=1 - SAFE MODE will be entered and held "
            "deliberately. Clear the flag to leave.")
    log(f"  policy: remedy x{policy.remedy_attempts}, reboot max "
        f"{policy.reboot_max}/{policy.reboot_window_s}s, safe-mode retry "
        f"{policy.safe_mode_retry_s}s, safe-mode reboot after "
        f"{policy.safe_mode_reboot_after_s}s")
    if observe_only():
        log("  OBSERVE-ONLY: decisions are computed and logged, nothing is actuated")

    led = ledger_mod.load(observe_only=observe_only())
    sd_notify("READY=1")
    state: Optional[str] = None
    while True:
        try:
            state = tick(led, policy, state)
        except Exception as exc:  # pragma: no cover - the daemon must not die
            log(f"tick failed: {exc}")
        sd_notify("WATCHDOG=1")
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
