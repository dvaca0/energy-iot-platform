"""Plain-language answer to "why is this node not healthy?"

PURE. Takes the published health state, the boot record and the recent events
as plain dicts, and returns lines of text. No I/O, so it is testable without a
node and can be reused by the CLI, the portal and anything else.

The audience is a person at 2am who did not write this system. Four questions,
in this order:

    what is wrong
    whose fault is it
    what has already been tried
    what happens next

"Nothing is wrong" is a first-class answer and must be said plainly.
"""

from __future__ import annotations

from typing import List, Optional

from recovery import pipeline as P

#: What each stage means to someone who does not know the codebase.
HUMAN = {
    P.FILESYSTEM: "the root filesystem is not writable",
    P.CLOCK: "the clock has not been set by NTP yet",
    P.NETWORK: "there is no usable network uplink",
    P.TAILSCALE: "the Tailscale overlay is down",
    P.SENSOR: "the measurement hardware is not reachable",
    P.COLLECTOR: "the collector service is not running",
    P.MEASUREMENTS: "the collector is running but not producing readings",
    P.BACKEND: "the backend server cannot be reached",
    P.HEARTBEAT: "the node's heartbeat is not arriving at the backend",
}

OWNER_TEXT = {
    "LOCAL": ("This is a fault on this node, so recovery may escalate as far "
              "as a reboot."),
    "EXTERNAL": ("This is NOT a fault on this node - rebooting cannot fix it, "
                 "so the node will keep retrying but will never reboot for it."),
    "UNKNOWN": ("The node cannot tell whose fault this is, so it will not "
                "escalate."),
    "NONE": "",
}


def _fmt_secs(s: Optional[float]) -> str:
    if s is None:
        return "unknown"
    s = int(s)
    if s < 90:
        return f"{s}s"
    if s < 5400:
        return f"{s // 60}m"
    return f"{s // 3600}h{(s % 3600) // 60:02d}m"


def explain(health: Optional[dict], boot: Optional[dict] = None,
            events: Optional[list] = None, policy: Optional[P.Policy] = None,
            now: Optional[float] = None) -> List[str]:
    """Return the answer as lines of plain text."""
    out: List[str] = []
    policy = policy or P.Policy()
    events = events or []

    if not health:
        return ["The Recovery Manager has not published any state yet.",
                "Check that energy-node-recovery.service is running:",
                "    systemctl status energy-node-recovery"]

    state = health.get("state", "UNKNOWN")
    failure = health.get("first_failure")
    decision = health.get("decision") or {}
    stages = {s["stage"]: s for s in health.get("stages", [])}

    # ------------------------------------------------------------ what is wrong
    if state == P.HEALTHY and not failure:
        out.append("The node is HEALTHY. Every boot stage passed.")
        if boot and boot.get("boot_complete"):
            tth = boot.get("time_to_healthy_s")
            if tth is not None:
                out.append(f"This boot reached HEALTHY in {_fmt_secs(tth)}.")
            else:
                # Honest: the record began mid-boot, so it never saw the start.
                out.append("This boot is complete. Time-to-healthy was not "
                           "measured (the record started mid-boot).")
        if health.get("observe_only"):
            out.append("")
            out.append("NOTE: recovery is in OBSERVE-ONLY mode. It is deciding "
                       "but not acting.")
        return out

    st = stages.get(failure, {})
    what = HUMAN.get(failure, f"stage '{failure}' failed")
    out.append(f"The node is {state}: {what}.")
    if st.get("detail"):
        out.append(f"    {st['detail']}")

    # -------------------------------------------------------------- whose fault
    owner = (boot or {}).get("failure_owner") or (
        policy.classify(failure).upper() if failure else "NONE")
    if OWNER_TEXT.get(owner):
        out.append("")
        out.append(f"Owner: {owner}. {OWNER_TEXT[owner]}")

    # ------------------------------------------------------- what has been tried
    tried = [e for e in events
             if e.get("kind") in ("remedy", "reboot", "safe_mode_entered")]
    out.append("")
    if tried:
        out.append("Already attempted this boot:")
        for e in tried[:6]:
            out.append(f"    {e.get('at', '')}  {e.get('kind')}"
                       f"{' ' + e['stage'] if e.get('stage') else ''}"
                       f"  {(e.get('detail') or '')[:70]}")
    else:
        out.append("Nothing has been attempted yet for this fault.")

    if boot:
        out.append(f"    service restarts this boot: "
                   f"{boot.get('service_restarts', 0)}   "
                   f"reboots: {boot.get('reboot_attempts', 0)}   "
                   f"safe mode: {'yes' if boot.get('safe_mode_entered') else 'no'}")

    # ------------------------------------------------------------- what is next
    out.append("")
    action = decision.get("action")
    reason = decision.get("reason", "")
    used = (health.get("ledger") or {}).get("reboots_last_window", 0)

    if state == P.SAFE_MODE:
        out.append("The node is in SAFE MODE: the maintenance access point is "
                   "up, SSH is up and the recovery portal is up.")
        out.append(f"It will keep retrying recovery every "
                   f"{_fmt_secs(policy.safe_mode_retry_s)}, forever. It may try "
                   f"one more reboot after "
                   f"{_fmt_secs(policy.safe_mode_reboot_after_s)}.")
        out.append("SAFE MODE is not permanent and does not need a human.")
    elif action == P.REMEDY:
        out.append(f"Next: a service-level remedy. {reason}")
        if owner == "LOCAL":
            out.append(f"If that keeps failing it will reboot, at most "
                       f"{policy.reboot_max} times in "
                       f"{_fmt_secs(policy.reboot_window_s)} "
                       f"({used} used so far), then enter SAFE MODE.")
    elif action == P.REBOOT:
        out.append(f"Next: REBOOT. {reason}")
        out.append(f"Reboots used in the current window: {used}/"
                   f"{policy.reboot_max}.")
    elif action == P.ENTER_SAFE_MODE:
        out.append(f"Next: SAFE MODE. {reason}")
    elif action == P.WAIT:
        out.append(f"Next: waiting. {reason}")
    else:
        out.append(f"Next: {action}. {reason}")

    if health.get("observe_only"):
        out.append("")
        out.append("NOTE: OBSERVE-ONLY is on, so none of the above will "
                   "actually be carried out.")
    return out
