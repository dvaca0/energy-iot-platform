#!/usr/bin/env python3
"""Curate OpenStreetMap building footprints into the Campus Map's GeoJSON.

The Campus Map renders real building outlines. Those outlines come from
OpenStreetMap, but the *page* must never depend on Overpass being reachable:
Overpass is a build-time source, not a runtime one. This script is that build
step. It runs by hand, when someone wants to add a campus or refresh geometry,
and writes a file the backend then serves from disk forever.

    python3 scripts/build_campus_geojson.py --campus 7
    python3 scripts/build_campus_geojson.py --all --offline raw/

What it does, per campus declared in ``backend/app/data/campus_map/campuses.json``:

1. asks Overpass for every ``building`` way and relation in the campus bounding
   box, and for the ``amenity=university`` areas that define the campus grounds;
2. keeps only the buildings whose centroid falls inside one of those areas
   (grown by ``clip_buffer_m``), which is what discards the hotel, the church
   and the municipal offices that share the bounding box;
3. writes a GeoJSON FeatureCollection carrying, per feature, the identifiers
   that let a human re-find it in OSM later: ``osm_type``, ``osm_id``,
   ``osm_name``, ``osm_building``, ``osm_operator``.

**No Energy IQ identity is written here.** The mapping from a polygon to a
``buildings.id`` lives in ``associations.json`` and is joined at request time.
Keeping them apart is the point: geometry can be re-fetched from OSM — this
script overwrites it wholesale — without disturbing a single curated
association, and an association survives an OSM re-import as long as the way
still exists.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "backend" / "app" / "data" / "campus_map"
GEOMETRY = DATA / "geometry"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

#: Metres per degree of latitude. Longitude is scaled by cos(lat) at use.
M_PER_DEG_LAT = 111_320.0


# --------------------------------------------------------------------- overpass
def _post(query: str, timeout: int = 180, attempts: int = 4) -> dict[str, Any]:
    """POST a query to Overpass, backing off on the public instance's 429/504.

    Overpass rate-limits by IP and returns 429 the moment two queries arrive
    back to back, which is exactly what curating several campuses does. Retrying
    is not optional politeness here; without it a multi-campus run fails halfway
    and leaves some files refreshed and others not.
    """
    request = urllib.request.Request(
        OVERPASS_URL,
        data=query.encode("utf-8"),
        headers={"User-Agent": "energy-iq-campus-map/1.0 (thesis platform, Universidad de Colima)"},
    )
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            if error.code not in (429, 504) or attempt == attempts:
                raise
            pause = 20 * attempt
            print(f"  Overpass returned {error.code}; retrying in {pause}s", flush=True)
            time.sleep(pause)
    raise RuntimeError("unreachable")


def buildings_query(bbox: list[float]) -> str:
    south, west, north, east = bbox
    return f"""[out:json][timeout:120];
(
  way["building"]({south},{west},{north},{east});
  relation["building"]({south},{west},{north},{east});
);
out geom;
"""


def grounds_query(bbox: list[float], selectors: list[str]) -> str:
    south, west, north, east = bbox
    clauses = "\n".join(
        f"  way{selector}({south},{west},{north},{east});\n"
        f"  relation{selector}({south},{west},{north},{east});"
        for selector in selectors
    )
    return f"[out:json][timeout:120];\n(\n{clauses}\n);\nout geom;\n"


# -------------------------------------------------------------------- geometry
def _rings(element: dict[str, Any]) -> list[list[list[float]]]:
    """Every closed ring of an element, as GeoJSON ``[lon, lat]`` positions.

    A way carries one ring. A multipolygon relation carries its outer members'
    rings; inner members (courtyards) are dropped, because a courtyard changes
    nothing about which building a click lands on and keeping them would mean
    stitching relation members into valid holes.
    """
    if element["type"] == "way":
        geometry = element.get("geometry") or []
        if len(geometry) < 4:
            return []
        return [[[point["lon"], point["lat"]] for point in geometry]]

    rings: list[list[list[float]]] = []
    for member in element.get("members", []):
        if member.get("role") != "outer" or member.get("type") != "way":
            continue
        geometry = member.get("geometry") or []
        if len(geometry) < 4:
            continue
        ring = [[point["lon"], point["lat"]] for point in geometry]
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        rings.append(ring)
    return rings


def _centroid(ring: list[list[float]]) -> tuple[float, float]:
    """Area centroid of a ring, falling back to the vertex mean when degenerate.

    **The ring is translated to its own first vertex before the shoelace sum.**
    Without that the arithmetic is worthless at these coordinates: a term of
    the untranslated sum is ``x0*y1 - x1*y0`` where both products are about
    -1969, while their difference for a 20 m building is about 1e-8. That is
    eleven digits of catastrophic cancellation out of the sixteen a double
    carries, and what survives is noise — the same footprint on Campus Tecomán
    produced centroids 270 m apart depending only on how many decimals the
    input happened to be rounded to. Buildings were then clipped against the
    campus boundary using a point that was not inside them.

    Translating first makes the operands about 1e-4, so the cancellation
    disappears and the result is exact to well under a millimetre.
    """
    origin_x, origin_y = ring[0]
    area = cx = cy = 0.0
    for (x0, y0), (x1, y1) in pairwise(ring):
        ax, ay = x0 - origin_x, y0 - origin_y
        bx, by = x1 - origin_x, y1 - origin_y
        cross = ax * by - bx * ay
        area += cross
        cx += (ax + bx) * cross
        cy += (ay + by) * cross

    # Degeneracy is relative to the ring's own extent, not an absolute epsilon:
    # a 5 m building spans about 5e-5 degrees, so its shoelace sum is around
    # 1e-9 and any fixed threshold big enough to catch a genuinely collapsed
    # ring would also catch a real small building.
    span_x = max(p[0] for p in ring) - min(p[0] for p in ring)
    span_y = max(p[1] for p in ring) - min(p[1] for p in ring)
    if abs(area) < 1e-6 * max(span_x * span_y, 1e-18):
        return (
            sum(p[0] for p in ring) / len(ring),
            sum(p[1] for p in ring) / len(ring),
        )
    area *= 0.5
    return origin_x + cx / (6 * area), origin_y + cy / (6 * area)


def _in_ring(point: tuple[float, float], ring: list[list[float]]) -> bool:
    """Ray casting. ``point`` and ring positions are ``(lon, lat)``."""
    x, y = point
    inside = False
    for (x0, y0), (x1, y1) in pairwise(ring):
        if (y0 > y) != (y1 > y):
            crossing = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if crossing > x:
                inside = not inside
    return inside


def _near_ring(point: tuple[float, float], ring: list[list[float]], metres: float) -> bool:
    """Within ``metres`` of the ring itself — the nearest edge, not the nearest vertex.

    This is the tolerance for a building that straddles the campus boundary,
    and it has to be small: a 40 m grab reaches across a street and drags in
    the church, the clinic and the kindergarten next door, which is exactly
    what it did to Campus San Pedrito. Measuring to the vertices instead of to
    the edges made a small tolerance unusable, because a long straight
    boundary run has vertices only at its ends — a building 5 m from the fence
    could be 80 m from the nearest corner and get dropped.
    """
    if metres <= 0:
        return False

    # Local equirectangular projection: metres per degree, at this latitude.
    scale_x = M_PER_DEG_LAT * math.cos(math.radians(point[1]))
    px, py = point[0] * scale_x, point[1] * M_PER_DEG_LAT

    for (x0, y0), (x1, y1) in pairwise(ring):
        ax, ay = x0 * scale_x, y0 * M_PER_DEG_LAT
        bx, by = x1 * scale_x, y1 * M_PER_DEG_LAT
        dx, dy = bx - ax, by - ay
        length_sq = dx * dx + dy * dy
        if length_sq == 0:
            closest = 0.0
        else:
            closest = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
        if math.hypot(px - (ax + closest * dx), py - (ay + closest * dy)) <= metres:
            return True
    return False


def _round(value: float) -> float:
    """Six decimals — about 11 cm, well past what a traced footprint knows."""
    return round(value, 6)


# --------------------------------------------------------------------- curation
def curate(campus: dict[str, Any], raw_buildings: dict, raw_grounds: dict) -> dict[str, Any]:
    grounds: list[list[list[float]]] = []
    for element in raw_grounds.get("elements", []):
        grounds.extend(_rings(element))
    if not grounds:
        sys.exit(
            f"campus {campus['campus_id']}: Overpass returned no grounds polygon for "
            f"{campus['grounds_selectors']} — refusing to write a file clipped to nothing"
        )

    buffer_m = float(campus.get("clip_buffer_m", 0))
    features = []
    for element in raw_buildings.get("elements", []):
        rings = _rings(element)
        if not rings:
            continue
        centroid = _centroid(rings[0])
        if not any(
            _in_ring(centroid, ring) or _near_ring(centroid, ring, buffer_m) for ring in grounds
        ):
            continue

        tags = element.get("tags", {})
        coordinates = [[[_round(x), _round(y)] for x, y in ring] for ring in rings]
        features.append(
            {
                "type": "Feature",
                # A stable, human-readable feature id. The frontend keys React
                # elements and the selection on this, so it must not be a list
                # index — re-running this script reorders features freely.
                "id": f"{element['type']}/{element['id']}",
                "properties": {
                    "osm_type": element["type"],
                    "osm_id": element["id"],
                    "osm_name": tags.get("name"),
                    "osm_building": tags.get("building"),
                    "osm_operator": tags.get("operator"),
                },
                "geometry": (
                    {"type": "Polygon", "coordinates": coordinates}
                    if len(coordinates) == 1
                    else {"type": "MultiPolygon", "coordinates": [[ring] for ring in coordinates]}
                ),
            }
        )

    features.sort(key=lambda f: (f["properties"]["osm_type"], f["properties"]["osm_id"]))
    return {
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "campus_id": campus["campus_id"],
            "campus_name": campus["name"],
            "source": "OpenStreetMap contributors, via the Overpass API (ODbL)",
            "generator": "scripts/build_campus_geojson.py",
            "bbox": campus["bbox"],
            "curated_at": datetime.now(UTC).strftime("%Y-%m-%d"),
            "grounds_selectors": campus["grounds_selectors"],
            # The campus outline itself, kept alongside the footprints it was
            # used to clip. Two reasons it earns its place in the file rather
            # than being discarded after clipping: the map can draw a subtle
            # property boundary, and a small site — a bachillerato with three
            # buildings — fits to something sensible instead of to three
            # rooftops. It is not a Feature: it is not clickable, carries no
            # Energy IQ state, and must never be mistaken for a building.
            "grounds": [[[_round(x), _round(y)] for x, y in ring] for ring in grounds],
        },
    }


def load_campuses() -> list[dict[str, Any]]:
    return json.loads((DATA / "campuses.json").read_text(encoding="utf-8"))["campuses"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campus", type=int, action="append", help="campus id (repeatable)")
    parser.add_argument("--all", action="store_true", help="every campus with a bbox declared")
    parser.add_argument(
        "--offline",
        type=Path,
        help="directory of previously saved Overpass responses "
        "(<id>-buildings.json, <id>-grounds.json) — avoids hitting the API",
    )
    parser.add_argument(
        "--grounds-only",
        action="store_true",
        help="refresh only the campus outline, leaving every curated building "
        "footprint in the existing file exactly as it is",
    )
    args = parser.parse_args()

    wanted = set(args.campus or [])
    campuses = [
        c for c in load_campuses() if c.get("bbox") and (args.all or c["campus_id"] in wanted)
    ]
    if not campuses:
        parser.error("nothing to do — pass --all or --campus <id> for a campus that has a bbox")

    GEOMETRY.mkdir(parents=True, exist_ok=True)
    for campus in campuses:
        campus_id = campus["campus_id"]
        if args.offline:
            raw_buildings = json.loads(
                (args.offline / f"{campus_id}-buildings.json").read_text(encoding="utf-8")
            )
            raw_grounds = json.loads(
                (args.offline / f"{campus_id}-grounds.json").read_text(encoding="utf-8")
            )
        else:
            print(f"campus {campus_id} ({campus['name']}): querying Overpass…", flush=True)
            raw_buildings = (
                {"elements": []} if args.grounds_only else _post(buildings_query(campus["bbox"]))
            )
            raw_grounds = _post(grounds_query(campus["bbox"], campus["grounds_selectors"]))

        collection = curate(campus, raw_buildings, raw_grounds)
        target = GEOMETRY / campus["geometry_file"]

        if args.grounds_only:
            # Splice the new outline into the file on disk. Rewriting the whole
            # collection would silently re-import buildings from whatever OSM
            # looks like today, which is exactly what this flag exists to avoid.
            existing = json.loads(target.read_text(encoding="utf-8"))
            existing.setdefault("properties", {})["grounds"] = collection["properties"]["grounds"]
            existing["properties"]["grounds_selectors"] = campus["grounds_selectors"]
            target.write_text(
                json.dumps(existing, ensure_ascii=False, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            print(
                f"campus {campus_id} ({campus['name']}): outline refreshed, "
                f"{len(existing['features'])} footprints untouched → {target.relative_to(ROOT)}"
            )
            continue
        target.write_text(
            json.dumps(collection, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        named = sum(1 for f in collection["features"] if f["properties"]["osm_name"])
        acquired = sum(1 for e in raw_buildings.get("elements", []) if _rings(e))
        print(
            f"campus {campus_id} ({campus['name']}): "
            f"{len(collection['features'])} footprints ({named} named) kept of "
            f"{acquired} in the bbox, {acquired - len(collection['features'])} discarded as "
            f"outside the grounds → {target.relative_to(ROOT)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
