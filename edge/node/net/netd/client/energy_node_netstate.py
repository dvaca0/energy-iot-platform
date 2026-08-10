"""Network availability client -- the collector's entire view of networking.

This single file is installed alongside the collector.  It is deliberately
standalone: no imports from ``netd``, no third-party packages, nothing that
ties the collector's lifecycle to the networking subsystem's.  Copy it, import
it, done.

The collector may ask exactly one question::

    from energy_node_netstate import network_available

    if network_available():
        upload_pending_measurements()
    else:
        keep_buffering()

It must never learn *how* connectivity is achieved.  Ethernet, Wi-Fi client
and maintenance access point are all invisible behind this boundary, so the
networking subsystem can be redesigned without touching collector code.

Fail-open behaviour: if the state file is missing or stale -- meaning the
networking supervisor is not running -- this returns True.  A collector that
stopped trying because the *monitor* died would turn a networking fault into a
data-loss fault.  Let it attempt and fail normally instead; it already handles
an unreachable backend.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional

__all__ = ["network_available", "network_state", "STATE_PATH"]

STATE_PATH = os.environ.get("ENERGY_NODE_NETWORK_STATE", "/run/energy-node/network-state.json")

#: A document older than this many multiples of its own TTL is stale.
_STALE_TTL_MULTIPLE = 3


def network_state(path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Return the raw state document, or None if unavailable.

    Diagnostic use only.  Production code should call
    :func:`network_available`.
    """
    try:
        with open(path or STATE_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def network_available(path: Optional[str] = None, fail_open: bool = True) -> bool:
    """Whether the node currently has a usable network.

    :param path: override the state file location (testing only)
    :param fail_open: value returned when the networking subsystem is not
        reporting; defaults to True for the reason described above
    """
    data = network_state(path)
    if not data:
        return fail_open

    try:
        updated = float(data.get("updated_at", 0))
        ttl = float(data.get("ttl_seconds", 60))
    except (TypeError, ValueError):
        return fail_open

    if (time.time() - updated) > (ttl * _STALE_TTL_MULTIPLE):
        return fail_open

    return data.get("network") == "available"
