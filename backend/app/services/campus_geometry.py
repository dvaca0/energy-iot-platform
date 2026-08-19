"""Curated campus geometry, and the bridge from a footprint to a building.

The Campus Map draws real OpenStreetMap building outlines. This module is the
only thing that reads them, and it reads them **from disk** — never from
Overpass. Overpass is a curation-time source (``scripts/build_campus_geojson.py``
runs by hand and writes the files); making the page depend on it at request time
would mean the map goes blank whenever a public API two thousand kilometres away
is rate-limiting.

Three files, deliberately separate:

``campuses.json``   which campuses have a traced map, and where to point the
                    viewport when one has no geometry at all.

``geometry/*.geojson``
                    the footprints, plus the campus outline they were clipped
                    to under ``properties.grounds``. Overwritten wholesale by a
                    re-import. Carries OSM identity only — ``osm_type``/
                    ``osm_id``/``osm_name`` — and no Energy IQ identity
                    whatsoever.

``associations.json``
                    the curated mapping ``(osm_type, osm_id) → buildings.id``.
                    Never touched by a re-import.

That split is the point of the module. **The OSM name is not a key.** Most
footprints have none; the ones that do carry a local nickname that drifts from
the institutional name in ``buildings`` (the DIGESET building is tagged
"Servicios Telemáticos" in OSM). Matching on it would silently re-point a
building's energy data at a different polygon the day a mapper fixes a typo.
The identity is the numeric OSM id, and the join is a file a human maintains.

Everything is cached after first read and invalidated by file mtime, so editing
``associations.json`` on a running server takes effect on the next request
without a reload.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "campus_map"
GEOMETRY_DIR = DATA_DIR / "geometry"

#: Shown on the map and required by the ODbL. Never remove it from a response.
ATTRIBUTION = "© OpenStreetMap contributors"

_lock = Lock()
_cache: dict[str, tuple[float, Any]] = {}


def _load_json(path: Path) -> Any | None:
    """Parse ``path``, memoised on its modification time. ``None`` if absent."""
    try:
        stamp = path.stat().st_mtime
    except FileNotFoundError:
        with _lock:
            _cache.pop(str(path), None)
        return None

    key = str(path)
    cached = _cache.get(key)
    if cached and cached[0] == stamp:
        return cached[1]

    with _lock:
        value = json.loads(path.read_text(encoding="utf-8"))
        _cache[key] = (stamp, value)
        return value


def refresh() -> None:
    """Drop every cached file. For tests, and for a deliberate hot reload."""
    with _lock:
        _cache.clear()


# ------------------------------------------------------------------- campuses
@dataclass(frozen=True)
class CampusView:
    """How the map should open on a campus, geometry or not."""

    campus_id: int
    name: str
    geometry_file: str | None
    fallback_center: list[float] | None
    fallback_zoom: int | None

    @property
    def has_geometry(self) -> bool:
        return bool(self.geometry_file) and (GEOMETRY_DIR / self.geometry_file).exists()


def campus_views() -> dict[int, CampusView]:
    """``{campus id: CampusView}`` for every campus declared in campuses.json.

    A campus missing from that file is not an error — it is simply one nobody
    has configured, and the API reports ``has_geometry: false`` for it.
    """
    raw = _load_json(DATA_DIR / "campuses.json") or {"campuses": []}
    views: dict[int, CampusView] = {}
    for entry in raw.get("campuses", []):
        views[entry["campus_id"]] = CampusView(
            campus_id=entry["campus_id"],
            name=entry.get("name", ""),
            geometry_file=entry.get("geometry_file"),
            fallback_center=entry.get("fallback_center"),
            fallback_zoom=entry.get("fallback_zoom"),
        )
    return views


def geometry(campus_id: int) -> dict[str, Any] | None:
    """The curated FeatureCollection for a campus, or ``None`` if untraced.

    Returning ``None`` rather than raising is deliberate: a campus without a
    traced map is an ordinary state of the system — nine of the ten campuses
    are in it — and the page renders its summary without a map. Only a file
    that exists and is malformed is worth an exception.
    """
    view = campus_views().get(campus_id)
    if not view or not view.geometry_file:
        return None
    return _load_json(GEOMETRY_DIR / view.geometry_file)


def grounds(campus_id: int) -> list[list[list[float]]] | None:
    """The campus property outline: the rings the footprints were clipped to.

    Kept because it answers a question the footprints cannot. A site with no
    traced buildings — the Santiago bachillerato is one — would otherwise have
    nothing to draw and nothing to fit the viewport to, and a campus with three
    buildings would fit to three rooftops instead of to the campus.

    Returned as bare rings, not as Features: nothing about them is clickable,
    they carry no Energy IQ state, and they must never be counted as buildings.
    """
    collection = geometry(campus_id)
    if collection is None:
        return None
    return collection.get("properties", {}).get("grounds") or None


# --------------------------------------------------------------- associations
def _feature_key(osm_type: str, osm_id: int) -> str:
    return f"{osm_type}/{osm_id}"


def associations() -> list[dict[str, Any]]:
    raw = _load_json(DATA_DIR / "associations.json") or {"associations": []}
    return list(raw.get("associations", []))


def buildings_by_feature(campus_id: int | None = None) -> dict[str, list[dict[str, Any]]]:
    """``{"way/625447870": [association, ...]}``.

    A list, not a single entry, because one footprint legitimately holds more
    than one Energy IQ building: a physical building has several panels, and a
    re-instrumentation creates a second ``buildings`` row for the same walls.
    Collapsing them to one would hide whichever campaign happened to be
    curated second.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in associations():
        if campus_id is not None and entry.get("campus_id") != campus_id:
            continue
        key = _feature_key(entry["osm_type"], entry["osm_id"])
        grouped.setdefault(key, []).append(entry)
    return grouped


def features_by_building(campus_id: int | None = None) -> dict[int, str]:
    """``{buildings.id: "way/625447870"}`` — the reverse lookup.

    If a building were curated onto two footprints the last one wins; that is a
    curation mistake rather than a modelled case, and :func:`orphans` is where
    it becomes visible.
    """
    mapping: dict[int, str] = {}
    for entry in associations():
        if campus_id is not None and entry.get("campus_id") != campus_id:
            continue
        mapping[entry["energy_iq_building_id"]] = _feature_key(entry["osm_type"], entry["osm_id"])
    return mapping


def orphans(campus_id: int, known_building_ids: set[int]) -> list[dict[str, Any]]:
    """Associations that no longer resolve on one side or the other.

    Curation drifts: a way gets redrawn under a new id in OSM, or a building is
    deleted from Energy IQ. Reporting the broken pair is far more useful than
    dropping it silently, because a footprint that quietly stops being monitored
    looks exactly like a footprint that was never monitored.
    """
    collection = geometry(campus_id)
    present = {feature.get("id") for feature in (collection or {}).get("features", [])}
    broken = []
    for entry in associations():
        if entry.get("campus_id") != campus_id:
            continue
        key = _feature_key(entry["osm_type"], entry["osm_id"])
        reasons = []
        if collection is not None and key not in present:
            reasons.append("osm_feature_missing")
        if entry["energy_iq_building_id"] not in known_building_ids:
            reasons.append("building_missing")
        if reasons:
            broken.append({**entry, "reasons": reasons})
    return broken
