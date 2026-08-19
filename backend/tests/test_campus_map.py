"""Checks for the Campus Map's geometry loading, association and status rules.

Runs against a throwaway SQLite database and throwaway data files. It never
reads the production database and never writes to the curated GeoJSON.

Three things are worth proving here, because each is a way the map could
mislead an operator rather than merely look wrong:

* **an association is a curated file, never a name match** — the fixture gives
  the OSM feature a different name from the Energy IQ building on purpose, and
  a second building shares one footprint;
* **an active deployment is not a claim of liveness** — the same deployment is
  driven through fresh, stale and closed and must produce three different
  states;
* **a missing or broken curation degrades** — a campus with no geometry, an
  association pointing at a deleted building, and one pointing at a way that is
  no longer in OSM all have defined, non-fatal outcomes.

    cd <repo>/backend
    venv/bin/python3 -m tests.test_campus_map
"""

import importlib.util
import json
import math
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)
os.chdir(_BACKEND)

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db import models
from app.db.database import Base
from app.monitoring.severity import Severity
from app.services import campus_geometry as geo
from app.services import campus_map_state as state

_CURATION = importlib.util.spec_from_file_location(
    "build_campus_geojson", Path(_BACKEND).parent / "scripts" / "build_campus_geojson.py"
)
curation = importlib.util.module_from_spec(_CURATION)
_CURATION.loader.exec_module(curation)

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        PASS.append(name)
        print(f"  ok    {name}")
    else:
        FAIL.append(f"{name}{f' — {detail}' if detail else ''}")
        print(f"  FAIL  {name}{f' — {detail}' if detail else ''}")


# --------------------------------------------------------- curation arithmetic
def _square(lon: float, lat: float, metres: float) -> list[list[float]]:
    """A closed square of side ``metres`` with its lower-left corner at lon/lat."""
    dy = metres / 111_320.0
    dx = dy / math.cos(math.radians(lat))
    return [
        [lon, lat],
        [lon + dx, lat],
        [lon + dx, lat + dy],
        [lon, lat + dy],
        [lon, lat],
    ]


def curation_checks() -> None:
    """The shoelace arithmetic, at the coordinates it actually runs at.

    A centroid test written around the origin proves nothing here. The whole
    dataset lives near 19.2 N, 103.7 W, where the untranslated shoelace sum
    cancels eleven of a double's sixteen digits and returns noise — which is
    how footprints on Campus Tecomán came to be clipped against a point that
    was not inside them. Every check below is therefore anchored at Colima.
    """
    print("\nCuration arithmetic at Colima's coordinates")

    for size in (5.0, 20.0, 100.0):
        ring = _square(-103.6993, 19.2478, size)
        cx, cy = curation._centroid(ring)
        expect_x = (ring[0][0] + ring[1][0]) / 2
        expect_y = (ring[0][1] + ring[2][1]) / 2
        off_m = math.hypot(
            (cx - expect_x) * 111_320 * math.cos(math.radians(19.2478)),
            (cy - expect_y) * 111_320,
        )
        check(
            f"a {size:.0f} m square's centroid is its centre, to the millimetre",
            off_m < 0.001,
            f"{off_m:.3f} m off",
        )
        check(
            f"a {size:.0f} m square's centroid is inside it",
            curation._in_ring((cx, cy), ring),
        )

    # Rounding the input must not move the answer. This is the exact symptom
    # the cancellation produced: the same footprint, read from the raw
    # Overpass response and from the six-decimal file, disagreed by 270 m.
    raw = _square(-103.898143, 18.947939, 18.0)
    rounded = [[round(x, 6), round(y, 6)] for x, y in raw]
    a = curation._centroid(raw)
    b = curation._centroid(rounded)
    drift = math.hypot(
        (a[0] - b[0]) * 111_320 * math.cos(math.radians(18.95)), (a[1] - b[1]) * 111_320
    )
    check(
        "rounding the ring to six decimals does not move its centroid",
        drift < 0.2,
        f"{drift:.1f} m drift",
    )

    collapsed = [[-103.6993, 19.2478]] * 4
    cx, cy = curation._centroid(collapsed)
    check(
        "a collapsed ring falls back to the vertex mean rather than dividing by zero",
        abs(cx + 103.6993) < 1e-9 and abs(cy - 19.2478) < 1e-9,
    )

    # The clip tolerance is a distance to the boundary, not to its corners.
    # A long straight campus edge has vertices only at its ends; measuring to
    # those made a small tolerance behave like no tolerance at all.
    edge = [
        [-103.70, 19.24],
        [-103.69, 19.24],
        [-103.69, 19.25],
        [-103.70, 19.25],
        [-103.70, 19.24],
    ]
    midpoint_outside = (-103.695, 19.2399)  # ~11 m below the middle of a 1 km edge
    check(
        "a point 11 m from the middle of a long edge is within a 15 m tolerance",
        curation._near_ring(midpoint_outside, edge, 15),
    )
    check(
        "and outside a 5 m one",
        not curation._near_ring(midpoint_outside, edge, 5),
    )
    check(
        "a zero tolerance admits nothing",
        not curation._near_ring(midpoint_outside, edge, 0),
    )
    far = (-103.695, 19.235)  # ~550 m below the same edge
    check(
        "a building across the street is not within tolerance",
        not curation._near_ring(far, edge, 40),
    )


# --------------------------------------------------------------- status rules
def status_checks() -> None:
    print("\nStatus derivation")

    check(
        "a building with no deployment and no readings is merely registered",
        state.derive_status(
            has_active_deployment=False,
            telemetry_live=False,
            max_open_severity=None,
            has_history=False,
        )
        == state.REGISTERED,
    )
    check(
        "one that has measured before is historical",
        state.derive_status(
            has_active_deployment=False,
            telemetry_live=False,
            max_open_severity=None,
            has_history=True,
        )
        == state.HISTORICAL,
    )
    check(
        "an active deployment with no fresh reading is stale, not healthy",
        state.derive_status(
            has_active_deployment=True,
            telemetry_live=False,
            max_open_severity=None,
            has_history=True,
        )
        == state.ACTIVE_STALE,
    )
    check(
        "an active deployment with no fresh reading is not historical either",
        state.derive_status(
            has_active_deployment=True,
            telemetry_live=False,
            max_open_severity=None,
            has_history=True,
        )
        != state.HISTORICAL,
    )
    check(
        "active and fresh with nothing open is healthy",
        state.derive_status(
            has_active_deployment=True,
            telemetry_live=True,
            max_open_severity=None,
            has_history=True,
        )
        == state.ACTIVE_HEALTHY,
    )
    check(
        "a WARNING escalates the colour to amber",
        state.derive_status(
            has_active_deployment=True,
            telemetry_live=True,
            max_open_severity=Severity.WARNING,
            has_history=True,
        )
        == state.ACTIVE_WARNING,
    )
    check(
        "an ERROR is amber too, not red",
        state.derive_status(
            has_active_deployment=True,
            telemetry_live=True,
            max_open_severity=Severity.ERROR,
            has_history=True,
        )
        == state.ACTIVE_WARNING,
    )
    check(
        "CRITICAL is red",
        state.derive_status(
            has_active_deployment=True,
            telemetry_live=True,
            max_open_severity=Severity.CRITICAL,
            has_history=True,
        )
        == state.ACTIVE_CRITICAL,
    )
    check(
        "EMERGENCY is red",
        state.derive_status(
            has_active_deployment=True,
            telemetry_live=True,
            max_open_severity=Severity.EMERGENCY,
            has_history=True,
        )
        == state.ACTIVE_CRITICAL,
    )
    check(
        "an INFO alert does not colour a healthy building",
        state.derive_status(
            has_active_deployment=True,
            telemetry_live=True,
            max_open_severity=Severity.INFO,
            has_history=True,
        )
        == state.ACTIVE_HEALTHY,
    )
    check(
        "an alert on a node whose campaign ended cannot make it stale-critical",
        state.derive_status(
            has_active_deployment=False,
            telemetry_live=False,
            max_open_severity=Severity.EMERGENCY,
            has_history=True,
        )
        == state.HISTORICAL,
    )

    print("\nShared footprints and freshness")
    check(
        "a shared footprint takes the most urgent of its buildings",
        state.worst([state.ACTIVE_HEALTHY, state.ACTIVE_CRITICAL, state.HISTORICAL])
        == state.ACTIVE_CRITICAL,
    )
    check(
        "a healthy neighbour cannot mask a stale one",
        state.worst([state.ACTIVE_HEALTHY, state.ACTIVE_STALE]) == state.ACTIVE_STALE,
    )
    check("no buildings means unregistered", state.worst([]) == state.UNREGISTERED)

    now = datetime(2026, 8, 18, 12, 0, 0)
    inside = state.freshness(now - timedelta(seconds=100), 300, now)
    check("a reading inside the window is live", inside["is_live"] and inside["age_seconds"] == 100)
    outside = state.freshness(now - timedelta(seconds=301), 300, now)
    check("one second past the window is not live", not outside["is_live"])
    edge = state.freshness(now - timedelta(seconds=300), 300, now)
    check("the window boundary itself counts as live", edge["is_live"])
    none = state.freshness(None, 300, now)
    check(
        "no reading is not live and reports no age, rather than age 0",
        not none["is_live"] and none["age_seconds"] is None,
    )
    future = state.freshness(now + timedelta(seconds=30), 300, now)
    check("a clock-skewed future reading clamps to zero, not negative", future["age_seconds"] == 0)


# ------------------------------------------------------------ geometry & join
def geometry_checks() -> None:
    print("\nCuration files: geometry, associations and orphans")

    workspace = tempfile.mkdtemp(prefix="campus-map-test-")
    original_data, original_geometry = geo.DATA_DIR, geo.GEOMETRY_DIR
    geo.DATA_DIR = __import__("pathlib").Path(workspace)
    geo.GEOMETRY_DIR = geo.DATA_DIR / "geometry"
    geo.GEOMETRY_DIR.mkdir()
    geo.refresh()

    try:
        (geo.DATA_DIR / "campuses.json").write_text(
            json.dumps(
                {
                    "campuses": [
                        {
                            "campus_id": 7,
                            "name": "Campus Traced",
                            "geometry_file": "campus-7.geojson",
                            "fallback_center": [19.24, -103.7],
                            "fallback_zoom": 16,
                        },
                        {
                            "campus_id": 9,
                            "name": "Campus Untraced",
                            "geometry_file": "campus-9.geojson",
                            "fallback_center": [19.21, -103.8],
                            "fallback_zoom": 16,
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

        ring = [
            [-103.7, 19.24],
            [-103.699, 19.24],
            [-103.699, 19.241],
            [-103.7, 19.241],
            [-103.7, 19.24],
        ]
        (geo.GEOMETRY_DIR / "campus-7.geojson").write_text(
            json.dumps(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "id": "way/111",
                            # Named nothing like the Energy IQ building it holds.
                            "properties": {
                                "osm_type": "way",
                                "osm_id": 111,
                                "osm_name": "Servicios Telemáticos",
                            },
                            "geometry": {"type": "Polygon", "coordinates": [ring]},
                        },
                        {
                            "type": "Feature",
                            "id": "way/222",
                            "properties": {"osm_type": "way", "osm_id": 222, "osm_name": None},
                            "geometry": {"type": "Polygon", "coordinates": [ring]},
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        (geo.DATA_DIR / "associations.json").write_text(
            json.dumps(
                {
                    "associations": [
                        {
                            "osm_type": "way",
                            "osm_id": 111,
                            "energy_iq_building_id": 10,
                            "campus_id": 7,
                            "confidence": "surveyed",
                        },
                        {
                            "osm_type": "way",
                            "osm_id": 111,
                            "energy_iq_building_id": 9,
                            "campus_id": 7,
                            "confidence": "inferred",
                        },
                        {
                            "osm_type": "way",
                            "osm_id": 999,
                            "energy_iq_building_id": 10,
                            "campus_id": 7,
                            "confidence": "inferred",
                        },
                        {
                            "osm_type": "way",
                            "osm_id": 222,
                            "energy_iq_building_id": 4242,
                            "campus_id": 7,
                            "confidence": "inferred",
                        },
                    ]
                }
            ),
            encoding="utf-8",
        )

        views = geo.campus_views()
        check("a traced campus reports geometry", views[7].has_geometry)
        check("a campus whose file is absent reports none", not views[9].has_geometry)
        check("an untraced campus returns None rather than raising", geo.geometry(9) is None)
        check("a campus not in campuses.json at all returns None", geo.geometry(1234) is None)

        collection = geo.geometry(7)
        check(
            "the traced campus loads its features",
            collection is not None and len(collection["features"]) == 2,
        )

        grouped = geo.buildings_by_feature(7)
        check(
            "one footprint can carry two Energy IQ buildings",
            [entry["energy_iq_building_id"] for entry in grouped["way/111"]] == [10, 9],
        )
        check(
            "the association is keyed on the OSM id, not on the name",
            all("osm_name" not in entry for entry in grouped["way/111"]),
        )

        reverse = geo.features_by_building(7)
        check("the reverse lookup finds a building's footprint", reverse[9] == "way/111")

        broken = geo.orphans(7, known_building_ids={9, 10})
        reasons = {(entry["osm_id"], tuple(entry["reasons"])) for entry in broken}
        check(
            "an association naming a way that is no longer in OSM is reported",
            (999, ("osm_feature_missing", "building_missing")) in reasons
            or any(
                entry["osm_id"] == 999 and "osm_feature_missing" in entry["reasons"]
                for entry in broken
            ),
        )
        check(
            "an association naming a deleted building is reported",
            any(
                entry["energy_iq_building_id"] == 4242 and "building_missing" in entry["reasons"]
                for entry in broken
            ),
        )
        check(
            "a sound association is not reported as an orphan",
            not any(entry["osm_id"] == 111 for entry in broken),
        )

        # Editing associations.json on a running server must take effect.
        (geo.DATA_DIR / "associations.json").write_text(
            json.dumps({"associations": []}), encoding="utf-8"
        )
        os.utime(geo.DATA_DIR / "associations.json", (0, 0))
        check(
            "the cache invalidates when a curation file changes", geo.buildings_by_feature(7) == {}
        )
    finally:
        geo.DATA_DIR, geo.GEOMETRY_DIR = original_data, original_geometry
        geo.refresh()
        shutil.rmtree(workspace, ignore_errors=True)


# ------------------------------------------------------- the shipped curation
def shipped_curation_checks() -> None:
    """The curated datasets that actually ship, against the invariants they claim.

    This runs on the real files rather than fixtures, because the failure mode
    that matters is not "the code is wrong" but "the data on disk drifted from
    what the code would produce now". Both have happened.
    """
    print("\nThe curation actually shipped")

    views = geo.campus_views()
    check("at least one campus has traced geometry", any(v.has_geometry for v in views.values()))

    configured = json.loads((geo.DATA_DIR / "campuses.json").read_text(encoding="utf-8"))[
        "campuses"
    ]
    for entry in configured:
        if entry.get("bbox"):
            check(
                f"campus {entry['campus_id']} declares a bbox and has the file to match",
                (geo.GEOMETRY_DIR / entry["geometry_file"]).exists(),
            )
        check(
            f"campus {entry['campus_id']} records how its site was identified",
            bool(entry.get("evidence")),
        )

    buffers = {e["campus_id"]: float(e.get("clip_buffer_m", 0)) for e in configured}

    for campus_id, view in views.items():
        if not view.has_geometry:
            continue
        collection = geo.geometry(campus_id)
        features = collection["features"]
        rings = geo.grounds(campus_id)

        check(
            f"campus {campus_id} is a FeatureCollection", collection["type"] == "FeatureCollection"
        )
        check(
            f"campus {campus_id} features carry OSM identity",
            all(
                f["properties"].get("osm_id") and f["properties"].get("osm_type") for f in features
            ),
        )
        check(
            f"campus {campus_id} geometry carries no Energy IQ identity",
            all("energy_iq_building_id" not in f["properties"] for f in features),
        )
        check(
            f"campus {campus_id} feature ids are unique",
            len({f["id"] for f in features}) == len(features),
        )
        check(
            f"campus {campus_id} geometries are polygons or multipolygons",
            all(f["geometry"]["type"] in ("Polygon", "MultiPolygon") for f in features),
        )
        check(
            f"campus {campus_id} rings are closed and have at least four points",
            all(len(ring) >= 4 and ring[0] == ring[-1] for f in features for ring in _all_rings(f)),
        )
        check(f"campus {campus_id} records its campus outline", bool(rings))
        check(
            f"campus {campus_id} outline rings are closed",
            all(len(r) >= 4 and r[0] == r[-1] for r in (rings or [])),
        )
        check(
            f"campus {campus_id} records when it was curated",
            bool(collection.get("properties", {}).get("curated_at")),
        )

        # The invariant the whole curation exists to enforce: nothing outside
        # the university grounds. A footprint that fails this is a hotel, a
        # church or a neighbour's house that slipped through.
        buffer_m = buffers.get(campus_id, 0.0)
        strays = [
            f["id"]
            for f in features
            if not _within_grounds(curation._centroid(_all_rings(f)[0]), rings or [], buffer_m)
        ]
        check(
            f"campus {campus_id} keeps only footprints on the university grounds",
            not strays,
            f"{len(strays)} stray: {strays[:4]}",
        )

        # A single distant polygon makes fitBounds zoom out to the whole state.
        outlier = _furthest_from(rings or [], features)
        check(
            f"campus {campus_id} has no distant outlier to wreck the map fit",
            outlier < 2.0,
            f"{outlier:.2f} km from the campus centre",
        )

    known = set()
    for campus_id in views:
        known |= {f["id"] for f in (geo.geometry(campus_id) or {"features": []})["features"]}

    for entry in geo.associations():
        key = f"{entry['osm_type']}/{entry['osm_id']}"
        check(f"association {key} resolves to a real footprint", key in known)
        check(
            f"association {key} names the campus its footprint is on",
            key
            in {
                f["id"] for f in (geo.geometry(entry["campus_id"]) or {"features": []})["features"]
            },
        )
        check(
            f"association {key} records how it was matched",
            entry.get("confidence") in ("surveyed", "inferred"),
        )


def _all_rings(feature: dict) -> list:
    geometry = feature["geometry"]
    if geometry["type"] == "Polygon":
        return geometry["coordinates"]
    return [ring for polygon in geometry["coordinates"] for ring in polygon]


def _within_grounds(point, rings: list, buffer_m: float) -> bool:
    return any(
        curation._in_ring(point, ring) or curation._near_ring(point, ring, buffer_m)
        for ring in rings
    )


def _furthest_from(rings: list, features: list) -> float:
    """Kilometres from the campus centre to the furthest footprint vertex."""
    points = [p for ring in rings for p in ring]
    if not points or not features:
        return 0.0
    centre_x = sum(p[0] for p in points) / len(points)
    centre_y = sum(p[1] for p in points) / len(points)
    scale_x = 111.32 * math.cos(math.radians(centre_y))
    return max(
        math.hypot((p[0] - centre_x) * scale_x, (p[1] - centre_y) * 111.32)
        for f in features
        for ring in _all_rings(f)
        for p in ring
    )


def _seed_measurement_eras(engine) -> None:
    """``energy_semantics`` and ``measurement_eras``, which migrations create.

    ``energy_aggregate`` resolves how to read ``energy_kwh`` from these, so a
    campus-map request touches them the moment it asks for today's energy. The
    ORM metadata does not know about them; seeding a canonical era for every
    node keeps the suite hermetic without pulling in the migration runner.
    """
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS energy_semantics ("
                " code TEXT PRIMARY KEY, label TEXT NOT NULL, reads_legacy BOOLEAN NOT NULL,"
                " requires_delta BOOLEAN NOT NULL, description TEXT)"
            )
        )
        connection.execute(
            text(
                "INSERT OR REPLACE INTO energy_semantics VALUES"
                " ('canonical','Canonical',0,0,'Collector populates interval_energy_kwh.'),"
                " ('absent','No energy',0,0,'The node reports no energy at all.')"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS measurement_eras ("
                " id INTEGER PRIMARY KEY, node_id INTEGER NOT NULL, starts_at DATETIME,"
                " ends_at DATETIME, energy_semantics TEXT NOT NULL,"
                " nominal_interval_seconds REAL, discovered_by TEXT, notes TEXT)"
            )
        )
        connection.execute(
            text(
                "INSERT OR REPLACE INTO measurement_eras"
                " (id, node_id, energy_semantics, discovered_by)"
                " VALUES (1, 1, 'canonical', 'tests/test_campus_map.py')"
            )
        )


# --------------------------------------------------------------- the endpoint
def endpoint_checks() -> None:
    print("\nThe endpoint, against a throwaway database")

    tmp_dir = "/tmp/energy-platform-tests"
    os.makedirs(tmp_dir, exist_ok=True)
    db_path = f"{tmp_dir}/test_campus_map.db"
    for suffix in ("", "-wal", "-shm"):
        if os.path.exists(db_path + suffix):
            os.remove(db_path + suffix)

    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=engine)

    from app.monitoring.models import MONITORING_TABLES

    for table in MONITORING_TABLES:
        table.create(bind=engine, checkfirst=True)

    from tests.lifecycle_fixtures import seed_lifecycle_tables

    seed_lifecycle_tables(engine)
    _seed_measurement_eras(engine)

    db = TestSession()
    delegation = models.Delegation(name="Colima", municipality="Colima")
    db.add(delegation)
    db.flush()
    traced = models.Campus(id=7, name="Campus Traced", delegation_id=delegation.id)
    # An id deliberately absent from campuses.json, so this stays the "nobody
    # has traced this one yet" case even as real campuses gain geometry — which
    # is exactly what happened to campus 6 when Tecomán was curated.
    untraced = models.Campus(id=77, name="Campus Untraced", delegation_id=delegation.id)
    db.add_all([traced, untraced])
    db.flush()
    unit = models.OrganizationalUnit(name="DIGESET", unit_type="technical", campus_id=traced.id)
    db.add(unit)
    db.flush()
    building = models.Building(
        id=10,
        code="B-TEST-10",
        name="Edificio Principal 2.0",
        campus_id=traced.id,
        organizational_unit_id=unit.id,
    )
    db.add(building)
    db.flush()
    panel = models.ElectricalPanel(name="SITE", building_id=building.id)
    db.add(panel)
    db.flush()
    node = models.Node(code="N001", name="Edge Node 001", commission_state="commissioned")
    db.add(node)
    db.flush()
    deployment = models.Deployment(
        node_id=node.id,
        building_id=building.id,
        electrical_panel_id=panel.id,
        start_date="2026-08-13",
        status="active",
        activated_at=datetime.utcnow(),
    )
    db.add(deployment)
    db.flush()
    db.add(
        models.EnergyReading(
            node_id=node.id,
            building_id=building.id,
            deployment_id=deployment.id,
            context="production",
            timestamp=datetime.utcnow() - timedelta(seconds=30),
            power_kw=12.7,
            voltage=124.3,
            current=107.8,
            power_factor=0.95,
            frequency_hz=60.0,
        )
    )
    db.commit()
    db.close()

    from fastapi.testclient import TestClient

    import app.db.database as database_module
    from app.main import app

    def override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[database_module.get_db] = override_get_db
    client = TestClient(app)

    try:
        listing = client.get("/api/campus-map/campuses")
        check("the campus list responds", listing.status_code == 200, str(listing.status_code))
        names = {row["name"] for row in listing.json()["campuses"]}
        check(
            "every campus in the database is listed, traced or not",
            names == {"Campus Traced", "Campus Untraced"},
        )
        check(
            "OSM attribution is in the response", "OpenStreetMap" in listing.json()["attribution"]
        )

        traced_payload = client.get("/api/campus-map/7")
        check(
            "a traced campus responds",
            traced_payload.status_code == 200,
            str(traced_payload.status_code),
        )
        data = traced_payload.json()
        target = next(b for b in data["buildings"] if b["id"] == 10)
        check(
            "a live deployment is healthy",
            target["map_status"] == state.ACTIVE_HEALTHY,
            target["map_status"],
        )
        check("the reading is reported live", target["telemetry"]["is_live"])
        check("the node is named", target["deployment"]["node"]["code"] == "N001")
        check(
            "a quantity the meter never reported comes back null, not zero",
            target["latest_reading"]["apparent_kva"] is None,
        )
        check("the telemetry window is published", data["telemetry_window_seconds"] > 0)
        check("a traced campus returns its property outline", bool(data["grounds"]))
        check("attribution is published with the map", "OpenStreetMap" in data["attribution"])

        untraced_payload = client.get("/api/campus-map/77")
        check("an untraced campus responds 200, not 404", untraced_payload.status_code == 200)
        check(
            "and returns no geometry rather than an empty collection",
            untraced_payload.json()["geometry"] is None,
        )
        check("and says so in the view", untraced_payload.json()["view"]["has_geometry"] is False)
        check(
            "and offers no campus outline either",
            untraced_payload.json()["grounds"] is None,
        )

        check(
            "a campus that does not exist is a 404",
            client.get("/api/campus-map/4242").status_code == 404,
        )

        # Push the reading out of the telemetry window: same deployment, same
        # status, and the map must stop calling it live.
        db = TestSession()
        reading = db.query(models.EnergyReading).first()
        reading.timestamp = datetime.utcnow() - timedelta(hours=6)
        db.commit()
        db.close()

        stale = client.get("/api/campus-map/7").json()
        stale_target = next(b for b in stale["buildings"] if b["id"] == 10)
        check(
            "an active deployment with an old reading is stale, not healthy",
            stale_target["map_status"] == state.ACTIVE_STALE,
            stale_target["map_status"],
        )
        check("and is not reported live", not stale_target["telemetry"]["is_live"])
        check(
            "the age is reported so the interface can say how old it is",
            stale_target["telemetry"]["age_seconds"] > 3600,
        )

        # Close the campaign: now it is history, not a silent active one.
        db = TestSession()
        db.query(models.Deployment).first().status = "completed"
        db.commit()
        db.close()

        closed = client.get("/api/campus-map/7").json()
        closed_target = next(b for b in closed["buildings"] if b["id"] == 10)
        check(
            "a completed deployment reads as historical",
            closed_target["map_status"] == state.HISTORICAL,
            closed_target["map_status"],
        )

        db = TestSession()
        surviving = db.query(models.EnergyReading).count()
        db.close()
        check("no reading was deleted by any of this", surviving == 1, str(surviving))
    finally:
        app.dependency_overrides.clear()


print("Campus map checks")
curation_checks()
status_checks()
geometry_checks()
shipped_curation_checks()
endpoint_checks()

print("\n" + "=" * 60)
print(f"PASSED: {len(PASS)}   FAILED: {len(FAIL)}")
if FAIL:
    for entry in FAIL:
        print("  -", entry)
print("=" * 60)
sys.exit(1 if FAIL else 0)
