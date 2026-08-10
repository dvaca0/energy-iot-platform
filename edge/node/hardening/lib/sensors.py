"""Measurement-hardware discovery.

The fleet is not homogeneous:

    N001  hardware_kind=shelly    production   Pi 5
    N002  hardware_kind=shelly    production   board unverified
    N003  hardware_kind=ads1256   bench        board unverified

Nothing here may assume Shelly. N003 measures through an ADS1256 over SPI and
would otherwise go completely unverified. Nothing may assume a Pi 5 either.

DESIGN RULE — same as the UPS registry: probe, never guess. Unknown hardware
is reported as unidentified WITH diagnostics, not forced into a known shape.

STDLIB ONLY (urllib for the Shelly HTTP probe).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Optional

_LIB = os.path.dirname(os.path.abspath(__file__))
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

import enconfig  # noqa: E402

__version__ = "1.0.0"


class SensorInfo:
    __slots__ = ("kind", "identified", "reachable", "detail", "diagnostics")

    def __init__(self, kind: str = "unknown", identified: bool = False,
                 reachable: Optional[bool] = None, detail: str = "",
                 diagnostics: Optional[dict] = None):
        self.kind = kind
        self.identified = identified
        self.reachable = reachable
        self.detail = detail
        self.diagnostics = diagnostics or {}

    def as_dict(self) -> dict:
        return {"kind": self.kind, "identified": self.identified,
                "reachable": self.reachable, "detail": self.detail,
                "diagnostics": self.diagnostics}

    def __repr__(self):
        return f"SensorInfo({self.kind}, reachable={self.reachable})"


# ------------------------------------------------------------------ shelly
def probe_shelly(ip: Optional[str] = None,
                 timeout: float = 4.0) -> Optional[SensorInfo]:
    """Probe a Shelly energy meter over HTTP. None if not configured."""
    ip = ip or enconfig.get("SHELLY_IP")
    if not ip:
        return None
    url = f"http://{ip}/rpc/Shelly.GetDeviceInfo"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            info = json.loads(r.read().decode("utf-8", "replace"))
        return SensorInfo(
            kind="shelly", identified=True, reachable=True,
            detail=f"{info.get('model') or info.get('app') or 'Shelly'} "
                   f"id={info.get('id')} fw={info.get('ver')} at {ip}",
            diagnostics={"ip": ip, "id": info.get("id"),
                         "model": info.get("model"), "gen": info.get("gen"),
                         "fw": info.get("ver")})
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
        return SensorInfo(kind="shelly", identified=True, reachable=False,
                          detail=f"configured at {ip} but unreachable: {exc}",
                          diagnostics={"ip": ip, "error": str(exc)})


# ----------------------------------------------------------------- ads1256
def probe_ads1256() -> Optional[SensorInfo]:
    """Probe for an ADS1256 ADC on SPI.

    We deliberately do NOT drive the chip. Reading an ADC mid-conversion can
    disturb an active measurement, and this package must never perturb the
    measurement path. We verify the SPI transport exists and is usable, which
    is what actually breaks in the field.
    """
    spidevs = sorted(p for p in os.listdir("/dev") if p.startswith("spidev"))
    if not spidevs:
        return None
    overlay_spi = False
    for cfg in ("/boot/firmware/config.txt", "/boot/config.txt"):
        try:
            with open(cfg) as fh:
                overlay_spi = any(l.strip().startswith("dtparam=spi=on")
                                  for l in fh)
            break
        except OSError:
            continue
    readable = os.access(f"/dev/{spidevs[0]}", os.R_OK | os.W_OK)
    return SensorInfo(
        kind="ads1256", identified=True, reachable=readable,
        detail=f"SPI present ({', '.join(spidevs)}); "
               f"{'accessible' if readable else 'NOT accessible to this user'}",
        diagnostics={"spidevs": spidevs, "dtparam_spi_on": overlay_spi,
                     "note": "transport verified; the ADC itself is not "
                             "driven, to avoid disturbing measurements"})


# ------------------------------------------------------------------ smart plugs
def probe_smart_plugs() -> Optional[SensorInfo]:
    state_db = os.path.join(enconfig.get("EN_STATE_DIR",
                                         "/opt/energy-node/state"),
                            "smart_plugs.db")
    if not os.path.exists(state_db):
        return None
    try:
        import sqlite3
        conn = sqlite3.connect(f"file:{state_db}?mode=ro", uri=True, timeout=5)
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        n = 0
        if "plugs" in tables:
            n = conn.execute("SELECT COUNT(*) FROM plugs").fetchone()[0]
        conn.close()
        return SensorInfo(kind="smart_plugs", identified=True,
                          reachable=True, detail=f"{n} plug(s) known",
                          diagnostics={"db": state_db, "tables": tables})
    except Exception as exc:
        return SensorInfo(kind="smart_plugs", identified=True, reachable=None,
                          detail=f"state db unreadable: {exc}",
                          diagnostics={"db": state_db})


# ---------------------------------------------------------------- discovery
PROBES = (("shelly", probe_shelly),
          ("ads1256", probe_ads1256),
          ("smart_plugs", probe_smart_plugs))


def discover() -> dict:
    """Discover every measurement source. Never raises, never guesses.

    Returns {"primary": SensorInfo, "all": [SensorInfo], "expected": str|None}
    `expected` comes from config when the operator has declared the node's
    hardware kind, so a mismatch between declared and discovered is visible.
    """
    found = []
    for _, fn in PROBES:
        try:
            info = fn()
        except Exception as exc:                      # never break the caller
            info = SensorInfo(kind="probe-error", detail=str(exc))
        if info is not None:
            found.append(info)

    expected = enconfig.get("SENSOR_KIND") or None
    primary = None
    if expected:
        primary = next((f for f in found if f.kind == expected), None)
    if primary is None:
        # prefer a reachable source, else the first identified one
        primary = next((f for f in found if f.reachable), None) \
            or (found[0] if found else None)
    if primary is None:
        primary = SensorInfo(
            kind="unknown", identified=False, reachable=None,
            detail="no measurement hardware discovered — neither a configured "
                   "Shelly, an SPI ADC, nor a smart-plug store",
            diagnostics={"probed": [n for n, _ in PROBES],
                         "shelly_ip_configured": bool(enconfig.get("SHELLY_IP")),
                         "spidevs": sorted(p for p in os.listdir("/dev")
                                           if p.startswith("spidev"))})
    return {"primary": primary, "all": found, "expected": expected}


if __name__ == "__main__":
    d = discover()
    print(json.dumps({"expected": d["expected"],
                      "primary": d["primary"].as_dict(),
                      "all": [f.as_dict() for f in d["all"]]}, indent=2))
