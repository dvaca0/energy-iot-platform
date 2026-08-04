import json
from copy import deepcopy
from pathlib import Path

SETTINGS_FILE = Path("runtime_platform_settings.json")

DEFAULT_SETTINGS = {
    "thresholds": {
        "minPowerFactor": 0.90,
        "maxCurrent": 200,
        "voltageDeviation": 10,
        "freqDeviation": 0.5,
        "costAnomaly": 30,
        "demandSpike": 25,
        "nodeOfflineTimeout": 300,
    },
    "retention": {
        "edgeDays": 7,
        "backendDays": "Ilimitado",
        "readingInterval": 15,
        "syncInterval": 60,
    },
    "tariff": {
        "active": "GDMTH",
        "source": "Manual fallback",
        "baseRate": 1.0375,
        "interRate": 1.8463,
        "peakRate": 2.0789,
        "lastUpdate": "Configuración persistente local",
        "apiStatus": "Pendiente",
        "apiNote": "Scraper/API CFE pendiente",
    },
    "ai": {
        "forecasting": {"enabled": True, "model": "Random Forest"},
        "anomaly": {"enabled": True, "model": "Isolation Forest"},
        "clustering": {"enabled": True, "model": "K-Means"},
        "confidence": "Backtesting cuando existe historial suficiente",
        "minHistoryDays": 7,
    },
    "system": {
        "frontendVersion": "React/Vite activo",
        "backendVersion": "FastAPI activo",
        "apiVersion": "v1",
    },
}


def deep_merge(base, incoming):
    result = deepcopy(base)
    for k, v in (incoming or {}).items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


#: Cached merged settings, keyed on the file's (mtime_ns, size).
#:
#: This function read the settings file from disk, parsed it, and deep-merged it
#: with the defaults on EVERY call. `get_thresholds()` is called inside
#: per-reading loops, so one /api/ai-center request called it 5,103 times —
#: 834,669 deepcopy() calls and the single largest cost on the platform.
#:
#: Invalidation is the file's own mtime and size: a stat() per call (about a
#: microsecond) instead of a read, parse and deep copy. Editing the file by any
#: means, including save_platform_settings below, is picked up on the next call.
#: There is no TTL and nothing to expire.
_CACHE = {"signature": None, "value": None}


def _signature():
    stat = SETTINGS_FILE.stat()
    return (stat.st_mtime_ns, stat.st_size)


def get_platform_settings():
    """Merged platform settings.

    The returned dict is shared and cached — treat it as read-only. Callers that
    need to modify settings must go through save_platform_settings(), which
    deep-copies before merging.
    """
    if not SETTINGS_FILE.exists():
        SETTINGS_FILE.write_text(json.dumps(DEFAULT_SETTINGS, indent=2, ensure_ascii=False))
        _CACHE["signature"] = None
        return deepcopy(DEFAULT_SETTINGS)

    try:
        signature = _signature()
    except OSError:
        signature = None

    if signature is not None and _CACHE["signature"] == signature and _CACHE["value"] is not None:
        return _CACHE["value"]

    try:
        data = json.loads(SETTINGS_FILE.read_text())
    except Exception:
        data = {}

    merged = deep_merge(DEFAULT_SETTINGS, data)
    _CACHE["signature"] = signature
    _CACHE["value"] = merged
    return merged


def save_platform_settings(payload):
    merged = deep_merge(get_platform_settings(), payload or {})
    SETTINGS_FILE.write_text(json.dumps(merged, indent=2, ensure_ascii=False))
    return merged


def get_thresholds():
    return get_platform_settings()["thresholds"]
