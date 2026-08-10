"""Canonical heartbeat publisher — ONE producer, ONE payload.

The collector owns heartbeat production; it imports this module and calls
publish() from its existing sync loop. No other process on the node produces
heartbeats.

SELF-NEGOTIATING TRANSITIONAL TRANSPORT
    The backend still has two ingest URLs. Verified against the live service:

        POST /api/monitoring/heartbeat -> {"status","received_at","node_code",
                                           "registered","next_interval_seconds",
                                           "clock_drift_seconds"}
                                          ...no last_sync. Dashboards go stale.
        POST /api/edge/heartbeat       -> {"status","last_sync"}

    So until backend/canonical_heartbeat.py is deployed, the single producer
    must also publish sync state to the legacy path.

    Rather than leave that as a permanent flag someone must remember to flip,
    the node NEGOTIATES it. The patched backend returns `last_sync` from the
    canonical endpoint (see backend/canonical_heartbeat.ingest_heartbeat).
    When this module sees that key it stops publishing to the legacy path by
    itself — no config change, no redeploy, no downtime.

    HEARTBEAT_LEGACY_EDGE_PUBLISH:
        auto  (default) negotiate from the canonical response  <-- correct
        1               force legacy publishing on
        0               force it off

    The transitional code therefore has a defined, automatic end-of-life. Once
    every node reports legacy_required=false, delete the branch and the config
    key; docs/node-rollout.md documents that cleanup step.

STDLIB + requests only (requests IS present in the collector venv).
"""

from __future__ import annotations

__version__ = "2.0.0"

import json
import os
import sys
import time
from typing import Optional

_LIB = os.path.dirname(os.path.abspath(__file__))
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

import enconfig  # noqa: E402
import telemetry  # noqa: E402

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

#: Marker proving the backend collapsed the two ingest paths.
CANONICAL_MARKER = "last_sync"

_negotiated: Optional[bool] = None      # True = legacy still required
_negotiated_at: float = 0.0


def _state_file() -> str:
    return os.path.join(enconfig.get("EN_STATE_DIR", "/opt/energy-node/state"),
                        "heartbeat_negotiation.json")


def _load_cached() -> None:
    global _negotiated, _negotiated_at
    try:
        with open(_state_file()) as fh:
            d = json.load(fh)
        _negotiated = d.get("legacy_required")
        _negotiated_at = float(d.get("at", 0))
    except (OSError, ValueError, TypeError):
        pass


def _save_cached(legacy_required: bool, marker_seen: bool) -> None:
    try:
        path = _state_file()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump({"legacy_required": legacy_required,
                       "backend_canonical": marker_seen,
                       "at": time.time(),
                       "checked_at_iso": time.strftime(
                           "%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, fh, indent=2)
        os.replace(tmp, path)
    except OSError:
        pass


def negotiation_state() -> dict:
    """What the node currently believes about the backend. For doctor/CLI."""
    if _negotiated is None:
        _load_cached()
    mode = str(enconfig.get("HEARTBEAT_LEGACY_EDGE_PUBLISH", "auto")).lower()
    return {"mode": mode,
            "legacy_required": _negotiated,
            "backend_canonical": (None if _negotiated is None
                                  else not _negotiated),
            "last_checked": _negotiated_at,
            "state_file": _state_file()}


def _legacy_wanted(marker_seen: Optional[bool]) -> bool:
    """Decide whether to publish to the legacy path this cycle."""
    global _negotiated, _negotiated_at
    mode = str(enconfig.get("HEARTBEAT_LEGACY_EDGE_PUBLISH",
                            "auto")).strip().lower()

    if mode in ("0", "false", "no", "off"):
        return False
    if mode in ("1", "true", "yes", "on"):
        return True

    # auto
    if _negotiated is None and _negotiated_at == 0.0:
        _load_cached()
    if marker_seen is not None:
        legacy = not marker_seen
        if legacy != _negotiated:
            msg = ("backend is CANONICAL — legacy edge publishing DISABLED "
                   "automatically" if not legacy else
                   "backend still split — legacy edge publishing ENABLED")
            print(f"[heartbeat] negotiation: {msg}", flush=True)
        _negotiated = legacy
        _negotiated_at = time.time()
        _save_cached(legacy, marker_seen)
        return legacy
    if _negotiated is not None:
        return _negotiated
    # Never negotiated and no signal yet: assume legacy is needed. One extra
    # request is harmless; stale dashboards are not.
    return True


class HeartbeatResult:
    def __init__(self):
        self.canonical_ok = False
        self.legacy_ok = None          # None = not attempted
        self.legacy_required = None
        self.backend_canonical = None
        self.status = None
        self.error = None
        self.payload: Optional[dict] = None

    def __bool__(self) -> bool:
        return self.canonical_ok

    def __str__(self) -> str:
        bits = [f"canonical={'OK' if self.canonical_ok else 'FAIL'}"]
        if self.legacy_ok is not None:
            bits.append(f"legacy={'OK' if self.legacy_ok else 'FAIL'}")
        elif self.backend_canonical:
            bits.append("legacy=not-needed")
        if self.payload:
            bits.append(f"undervolt={self.payload.get('undervoltage')}")
            bits.append(f"pending={self.payload.get('pending_sync')}")
        if self.error:
            bits.append(f"err={self.error}")
        return " | ".join(bits)



def _auth_headers() -> dict:
    # Bearer credential for this node (ADR-0002). Read from the
    # environment on every call rather than cached at import, so a
    # rotated credential takes effect on the next beat without a
    # restart. No token -> no header; the server decides whether an
    # unauthenticated beat is acceptable under its enforcement mode.
    tok = os.environ.get('NODE_AUTH_TOKEN') or enconfig.get('NODE_AUTH_TOKEN', '')
    return {'Authorization': 'Bearer ' + tok} if tok else {}


def publish(payload: Optional[dict] = None, session=None) -> HeartbeatResult:
    """Publish one canonical heartbeat. Never raises."""
    res = HeartbeatResult()

    if not enconfig.get_bool("HEARTBEAT_ENABLED", True):
        res.error = "HEARTBEAT_ENABLED=0"
        return res
    if requests is None:
        res.error = "requests unavailable"
        return res

    try:
        res.payload = payload if payload is not None else telemetry.build()
    except Exception as exc:
        res.error = f"payload build failed: {exc}"
        return res

    base = enconfig.api_base()
    timeout = enconfig.get_float("HEARTBEAT_TIMEOUT", 10.0)
    post = (session or requests).post

    marker_seen = None
    url = base + enconfig.get("HEARTBEAT_PATH", "/api/monitoring/heartbeat")
    try:
        r = post(url, json=res.payload, timeout=timeout, headers=_auth_headers())
        res.status = r.status_code
        res.canonical_ok = r.status_code < 400
        if res.canonical_ok:
            try:
                marker_seen = CANONICAL_MARKER in (r.json() or {})
            except ValueError:
                marker_seen = False
        else:
            res.error = f"{r.status_code}: {r.text[:200]}"
    except Exception as exc:
        res.error = str(exc)

    res.backend_canonical = (None if marker_seen is None else marker_seen)
    legacy = _legacy_wanted(marker_seen)
    res.legacy_required = legacy

    if legacy:
        legacy_url = base + enconfig.get("HEARTBEAT_LEGACY_EDGE_PATH",
                                         "/api/edge/heartbeat")
        slim = {"node_id": res.payload.get("node_id"),
                "buffer_pending": res.payload.get("pending_sync") or 0,
                "status": "online"}
        try:
            r = post(legacy_url, json=slim, timeout=timeout, headers=_auth_headers())
            res.legacy_ok = r.status_code < 400
        except Exception:
            res.legacy_ok = False

    return res


if __name__ == "__main__":
    print(publish())
    print(json.dumps(negotiation_state(), indent=2, default=str))
