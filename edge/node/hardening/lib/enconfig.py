"""Configuration loader for the energy-node hardening package.

Single source of truth. Every tunable comes from hardening.conf; node identity
comes from node.env. No module may hardcode a threshold, path or address.

STDLIB ONLY. This module is imported by the collector, which runs in a venv
containing only `requests` — no psutil, no smbus2. Anything added here must
work with the standard library alone.
"""

from __future__ import annotations

import os
from typing import Optional

DEFAULT_CONF = "/opt/energy-node/hardening/config/hardening.conf"
CONF_ENV = "EN_HARDENING_CONF"

_cache: Optional[dict] = None


def _parse(path: str) -> dict:
    out = {}
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def load(reload: bool = False) -> dict:
    """hardening.conf overlaid with node.env (node.env wins on identity keys)."""
    global _cache
    if _cache is not None and not reload:
        return _cache
    conf = _parse(os.environ.get(CONF_ENV, DEFAULT_CONF))
    node_env = conf.get("EN_NODE_ENV", "/opt/energy-node/config/node.env")
    conf.update(_parse(node_env))
    # Real environment variables win over everything, for testing.
    for k in list(conf):
        if k in os.environ:
            conf[k] = os.environ[k]
    _cache = conf
    return conf


def get(key: str, default=None):
    return load().get(key, default)


def get_int(key: str, default: int) -> int:
    try:
        return int(str(load().get(key, default)).strip())
    except (TypeError, ValueError):
        return default


def get_float(key: str, default: float) -> float:
    try:
        return float(str(load().get(key, default)).strip())
    except (TypeError, ValueError):
        return default


def get_bool(key: str, default: bool = False) -> bool:
    v = load().get(key)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def get_list(key: str, default=None) -> list:
    v = load().get(key)
    if not v:
        return list(default or [])
    return [x.strip() for x in v.split(",") if x.strip()]


def node_id() -> str:
    return get("NODE_ID", "UNKNOWN")


def api_base() -> str:
    return str(get("CENTRAL_API_URL", "")).rstrip("/")
