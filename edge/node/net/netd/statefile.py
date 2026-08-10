"""The published network state -- the subsystem's contract with the appliance.

This file is the *entire* interface between networking and everything else on
the node.  The collector reads one key::

    {"network": "available"}   or   {"network": "unavailable"}

Everything else in the document is diagnostic detail for the portal and the
TUI.  The collector must never read it, and must never learn *how* the node
is connected -- Ethernet, Wi-Fi client and maintenance AP are all invisible
behind this boundary by design.

Writes are atomic (temp file + ``os.replace``) so a reader never observes a
half-written document, and the file is world-readable so an unprivileged
collector can consume it without talking to a socket.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger("netd.statefile")

AVAILABLE = "available"
UNAVAILABLE = "unavailable"

SCHEMA_VERSION = 1


class StatePublisher:
    """Writes the network state document atomically."""

    def __init__(self, path: Path, ttl_seconds: int = 60) -> None:
        self._path = path
        self._ttl = ttl_seconds

    @property
    def path(self) -> Path:
        return self._path

    def publish(self, *, available: bool, detail: Optional[Dict[str, Any]] = None) -> None:
        """Publish the current network availability.

        ``detail`` is advisory diagnostic content for the UIs only.
        """
        document: Dict[str, Any] = {
            "schema": SCHEMA_VERSION,
            "network": AVAILABLE if available else UNAVAILABLE,
            "updated_at": time.time(),
            "ttl_seconds": self._ttl,
            "detail": detail or {},
        }
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                dir=str(self._path.parent), prefix=".network-state-", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(document, handle, separators=(",", ":"))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(tmp_name, 0o644)
                os.replace(tmp_name, self._path)
            except BaseException:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
        except OSError as exc:
            log.error("could not publish network state to %s: %s", self._path, exc)


def read_state(path: Path) -> Optional[Dict[str, Any]]:
    """Read the raw state document, or None if absent or unparsable."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def network_available(path: Path, fail_open: bool = True) -> bool:
    """The collector-facing question: is the network available?

    If the document is missing or stale -- meaning the networking subsystem
    itself is not running -- this returns ``fail_open``.  Defaulting to True is
    deliberate: a collector that stops trying because the *monitor* died would
    turn a networking fault into a data-loss fault.  Let it attempt and fail
    normally instead.
    """
    data = read_state(path)
    if not data:
        return fail_open
    updated = data.get("updated_at", 0)
    ttl = data.get("ttl_seconds", 60)
    try:
        if (time.time() - float(updated)) > (float(ttl) * 3):
            return fail_open
    except (TypeError, ValueError):
        return fail_open
    return data.get("network") == AVAILABLE
