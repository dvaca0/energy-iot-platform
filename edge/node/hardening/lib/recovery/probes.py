"""Stage probes — the I/O half of the Recovery Manager.

Every probe DELEGATES to the checks `energy-node doctor` already performs.
Recovery must never grow a second opinion about node health: two threshold
sets for the same condition drift apart, and then the operator tool and the
actuator disagree about whether the node is well.

    doctor.check_*()  ->  tristate.Result  ->  pipeline.StageResult

Two false positives are corrected here, both of which would otherwise reboot a
healthy node over somebody else's outage:

1. `doctor.check_heartbeat` asks the BACKEND whether it has seen us recently,
   so it reports FAIL when the backend is simply down. Heartbeat is only
   assertable when the backend is reachable; otherwise it is UNKNOWN.

2. `doctor.check_collector` folds "unit is not active" and "measurements are
   stale" into one result. Recovery needs them apart: a dead unit and a wedged
   unit have the same symptom but the second is the case systemd cannot see.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import List, Optional

_LIB = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

import doctor  # noqa: E402
import enconfig  # noqa: E402
import sysinfo  # noqa: E402
from tristate import Outcome  # noqa: E402

from recovery import pipeline as P  # noqa: E402

#: doctor's five-way outcome collapsed onto the three states recovery can act
#: on. WARN is deliberately NOT a failure: degraded is not broken, and a node
#: must not reboot over a warning.
_MAP = {
    Outcome.PASS: P.OK,
    Outcome.WARN: P.OK,
    Outcome.FAIL: P.FAILED,
    Outcome.UNKNOWN: P.UNKNOWN,
    Outcome.SKIP: P.UNKNOWN,
}


def _from_result(stage: str, r) -> P.StageResult:
    return P.StageResult(stage, _MAP.get(r.outcome, P.UNKNOWN), r.detail)


def _safe(stage: str, fn, *args) -> P.StageResult:
    """A probe that crashes must not be read as a fault worth rebooting for."""
    try:
        return _from_result(stage, fn(*args))
    except Exception as exc:  # pragma: no cover - defensive
        return P.StageResult(stage, P.UNKNOWN, f"probe crashed: {exc}")


# ------------------------------------------------------------------- network


def _netstate() -> Optional[dict]:
    """netd publishes one fact at /run/energy-node/network-state.json.

    Recovery consumes exactly that, the same way the collector does, so there
    is one answer to 'is the network usable' on the whole node.
    """
    p = os.path.join(
        enconfig.get("NETD_STATE_DIR", "/run/energy-node"), "network-state.json"
    )
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def probe_network() -> P.StageResult:
    st = _netstate()
    if st is None:
        # netd is the authority and it is not publishing. That is a real local
        # fault (the supervisor is down), and restarting it is the remedy.
        return P.StageResult(P.NETWORK, P.FAILED, "netd publishes no network state")
    ttl = float(st.get("ttl_seconds") or 30)
    updated = float(st.get("updated_at") or 0)
    if time.time() - updated > ttl * 3:
        return P.StageResult(
            P.NETWORK, P.FAILED,
            f"network state stale ({int(time.time() - updated)}s > {int(ttl * 3)}s)")
    detail = (st.get("detail") or {}).get("reason", "")
    if st.get("network") == "available":
        return P.StageResult(P.NETWORK, P.OK, detail)
    return P.StageResult(P.NETWORK, P.FAILED, detail or "network unavailable")


# --------------------------------------------------------------------- clock


def probe_clock() -> P.StageResult:
    return _safe(P.CLOCK, doctor.check_time_sync)


# ---------------------------------------------------------------- collector


def probe_collector() -> P.StageResult:
    """Is the unit running? Measurement freshness is a separate stage."""
    unit = enconfig.get("COLLECTOR_UNIT", "energy-node-collector.service")
    state = sysinfo.systemd_is_active(unit)
    if state is None:
        return P.StageResult(P.COLLECTOR, P.UNKNOWN, "systemctl unavailable")
    if state != "active":
        return P.StageResult(P.COLLECTOR, P.FAILED, f"{unit} is {state}")
    return P.StageResult(P.COLLECTOR, P.OK, f"{unit} active")


def probe_measurements() -> P.StageResult:
    """Fresh measurements. This is the 'alive but not measuring' case that
    systemd cannot see, because a wedged process is still 'active'."""
    return _safe(P.MEASUREMENTS, doctor.check_collector)


# ------------------------------------------------------------------ external


def probe_backend() -> P.StageResult:
    return _safe(P.BACKEND, doctor.check_backend)


def probe_heartbeat(backend: P.StageResult) -> P.StageResult:
    """Only assertable when the backend is reachable.

    Without this guard a backend outage looks like a local heartbeat fault,
    and HEARTBEAT is a LOCAL stage, so the node would restart its collector
    three times and then reboot itself over an outage it cannot fix.
    """
    if backend.status != P.OK:
        return P.StageResult(
            P.HEARTBEAT, P.UNKNOWN,
            "backend unreachable - heartbeat delivery not assertable")
    return _safe(P.HEARTBEAT, doctor.check_heartbeat)


def probe_sensor() -> P.StageResult:
    return _safe(P.SENSOR, doctor.check_sensor)


def probe_tailscale() -> P.StageResult:
    return _safe(P.TAILSCALE, doctor.check_tailscale)


def probe_filesystem() -> P.StageResult:
    return _safe(P.FILESYSTEM, doctor.check_filesystem)


# ----------------------------------------------------------------- the sweep


def probe_all() -> List[P.StageResult]:
    """One full sweep, in dependency order.

    BACKEND is probed before HEARTBEAT because heartbeat delivery depends on
    it; ordering them the other way makes a backend outage surface as a local
    heartbeat failure and escalate.
    """
    fs = probe_filesystem()
    clock = probe_clock()
    net = probe_network()
    tail = probe_tailscale()
    sensor = probe_sensor()
    collector = probe_collector()
    measurements = probe_measurements()
    backend = probe_backend()
    heartbeat = probe_heartbeat(backend)
    return [fs, clock, net, tail, sensor, collector, measurements, backend, heartbeat]
