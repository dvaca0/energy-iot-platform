"""The Shelly Pro 3EM field expansion (M15), against the real device capture.

Every number in ``EM_CAPTURE`` and ``EMDATA_CAPTURE`` is a verbatim read-only
capture from N001's production meter on 2026-08-18 — SPEM-003CEBEU, app Pro3EM,
generation 2, firmware 1.4.2, profile triphase, 120 A CT. They are not a
plausible-looking fixture and must not be "tidied": the point of pinning the
real response is that a firmware whose contract differs shows up as a failure
here rather than as a silently missing column in production.

Four properties are worth stating, because each one has a way of going wrong
that produces plausible numbers rather than an error:

**Units convert exactly once.** The meter speaks W, VA and Wh. A value divided
by a thousand twice is still a number, still positive, still plots — and is
wrong by three orders of magnitude. §2 pins every converted field against the
capture.

**Null is not zero.** ``n_current`` is genuinely null on this installation.
Storing 0.0 would assert that zero amperes flow in the neutral, which is a
measurement claim nobody made. §3.

**Old rows stay untouched.** Readings written before M15 have NULL in every new
column, and that is the truthful value — those instants were measured but not
kept. §4 verifies a pre-M15 row survives the expansion unchanged.

**Both ingest paths agree.** ``/api/readings`` and
``/api/v1/measurements/batch`` have diverged before, which is why N003 data is
not comparable to N001's. §5 sends the same physical measurement through both
and compares the stored rows against each other rather than against a constant.

Plain python, no pytest — it is not installed in this venv.
"""

import os
import sys
from datetime import datetime, timedelta

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO = os.path.dirname(_BACKEND)
sys.path.insert(0, _BACKEND)
os.chdir(_BACKEND)

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db import models, node_auth
from app.db.database import Base, get_db
from app.main import app
from app.services.units import va_to_kva, w_to_kw, wh_to_kwh
from tests.lifecycle_fixtures import seed_lifecycle_tables

SCRATCH = "/tmp/energy-platform-tests"
os.makedirs(SCRATCH, exist_ok=True)
TMP_DB = f"{SCRATCH}/test_shelly_phase_detail.db"
for suffix in ("", "-wal", "-shm"):
    if os.path.exists(TMP_DB + suffix):
        os.remove(TMP_DB + suffix)

engine = create_engine(f"sqlite:///{TMP_DB}", connect_args={"check_same_thread": False})
Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base.metadata.create_all(bind=engine)
seed_lifecycle_tables(engine)

# The energy-era tables come from migration 012, not from ORM metadata, and
# energy_aggregate joins them on every query. Without them the history endpoint
# fails before it can be tested. Seeded with the same two rows N001 really has,
# so the interval energy this suite sees is resolved by the same rule production
# uses (ADR-0007) rather than by a convenient stand-in.
with engine.begin() as connection:
    connection.execute(text("""
        CREATE TABLE IF NOT EXISTS energy_semantics (
            code TEXT PRIMARY KEY, label TEXT NOT NULL,
            reads_legacy BOOLEAN NOT NULL, requires_delta BOOLEAN NOT NULL,
            description TEXT)"""))
    connection.execute(text("""
        CREATE TABLE IF NOT EXISTS measurement_eras (
            id INTEGER PRIMARY KEY, node_id INTEGER NOT NULL,
            starts_at DATETIME, ends_at DATETIME,
            energy_semantics TEXT NOT NULL,
            nominal_interval_seconds REAL, discovered_by TEXT, notes TEXT)"""))
    for code, delta in (
        ("cumulative_counter", 1),
        ("interval_energy", 0),
        ("canonical", 0),
        ("absent", 0),
    ):
        connection.execute(
            text(
                "INSERT OR IGNORE INTO energy_semantics "
                "(code, label, reads_legacy, requires_delta) VALUES (:c, :c, 1, :d)"
            ),
            {"c": code, "d": delta},
        )


def override_get_db():
    db = Session()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

passed = failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ok   {name}")
    else:
        failed += 1
        print(f"  FAIL {name}" + (f" — {detail}" if detail else ""))


def close(a, b, tol=1e-9):
    return a is not None and b is not None and abs(a - b) <= tol


# --------------------------------------------------------------------------
# The capture. Verbatim.
# --------------------------------------------------------------------------

EM_CAPTURE = {
    "id": 0,
    "a_current": 37.470,
    "a_voltage": 124.7,
    "a_act_power": 4632.3,
    "a_aprt_power": 4679.9,
    "a_pf": 0.99,
    "a_freq": 60.0,
    "b_current": 35.133,
    "b_voltage": 126.1,
    "b_act_power": 4392.3,
    "b_aprt_power": 4437.9,
    "b_pf": 0.99,
    "b_freq": 60.0,
    "c_current": 33.257,
    "c_voltage": 126.0,
    "c_act_power": 3628.2,
    "c_aprt_power": 4194.1,
    "c_pf": 0.87,
    "c_freq": 60.0,
    "n_current": None,
    "total_current": 105.860,
    "total_act_power": 12652.766,
    "total_aprt_power": 13311.875,
    "user_calibrated_phase": [],
}

EMDATA_CAPTURE = {
    "id": 0,
    "a_total_act_energy": 2050299.69,
    "a_total_act_ret_energy": 73315.64,
    "b_total_act_energy": 1768543.71,
    "b_total_act_ret_energy": 47786.37,
    "c_total_act_energy": 1492076.51,
    "c_total_act_ret_energy": 63485.57,
    "total_act": 5310919.91,
    "total_act_ret": 184587.57,
}

METER_TEMPERATURE_C = 43.6


def batch_measurement(captured_at):
    """The batch payload a collector builds from the capture, in DEVICE units."""
    em, ed = EM_CAPTURE, EMDATA_CAPTURE
    return {
        "captured_at": captured_at,
        "voltage_a": em["a_voltage"],
        "current_a": em["a_current"],
        "active_power_a": em["a_act_power"],
        "apparent_power_a": em["a_aprt_power"],
        "power_factor_a": em["a_pf"],
        "frequency_a": em["a_freq"],
        "voltage_b": em["b_voltage"],
        "current_b": em["b_current"],
        "active_power_b": em["b_act_power"],
        "apparent_power_b": em["b_aprt_power"],
        "power_factor_b": em["b_pf"],
        "frequency_b": em["b_freq"],
        "voltage_c": em["c_voltage"],
        "current_c": em["c_current"],
        "active_power_c": em["c_act_power"],
        "apparent_power_c": em["c_aprt_power"],
        "power_factor_c": em["c_pf"],
        "frequency_c": em["c_freq"],
        "total_active_power": em["total_act_power"],
        "total_apparent_power": em["total_aprt_power"],
        "total_current": em["total_current"],
        "neutral_current": em["n_current"],
        "a_total_act_energy": ed["a_total_act_energy"],
        "b_total_act_energy": ed["b_total_act_energy"],
        "c_total_act_energy": ed["c_total_act_energy"],
        "a_total_act_ret_energy": ed["a_total_act_ret_energy"],
        "b_total_act_ret_energy": ed["b_total_act_ret_energy"],
        "c_total_act_ret_energy": ed["c_total_act_ret_energy"],
        "total_act": ed["total_act"],
        "total_act_ret": ed["total_act_ret"],
        "temperature_c": METER_TEMPERATURE_C,
    }


def readings_payload(node_code, captured_at):
    """The /api/readings payload, in PLATFORM units — already converted."""
    em, ed = EM_CAPTURE, EMDATA_CAPTURE
    return {
        "node_id": node_code,
        "timestamp": captured_at,
        "voltage": (em["a_voltage"] + em["b_voltage"] + em["c_voltage"]) / 3,
        "current": em["total_current"],
        "power_kw": w_to_kw(em["total_act_power"]),
        "power_factor": em["total_act_power"] / em["total_aprt_power"],
        "frequency_hz": em["a_freq"],
        "phase_a_voltage": em["a_voltage"],
        "phase_b_voltage": em["b_voltage"],
        "phase_c_voltage": em["c_voltage"],
        "phase_a_current": em["a_current"],
        "phase_b_current": em["b_current"],
        "phase_c_current": em["c_current"],
        "phase_a_power_kw": w_to_kw(em["a_act_power"]),
        "phase_b_power_kw": w_to_kw(em["b_act_power"]),
        "phase_c_power_kw": w_to_kw(em["c_act_power"]),
        "phase_a_apparent_kva": va_to_kva(em["a_aprt_power"]),
        "phase_b_apparent_kva": va_to_kva(em["b_aprt_power"]),
        "phase_c_apparent_kva": va_to_kva(em["c_aprt_power"]),
        "phase_a_power_factor": em["a_pf"],
        "phase_b_power_factor": em["b_pf"],
        "phase_c_power_factor": em["c_pf"],
        "phase_a_frequency_hz": em["a_freq"],
        "phase_b_frequency_hz": em["b_freq"],
        "phase_c_frequency_hz": em["c_freq"],
        "apparent_kva": va_to_kva(em["total_aprt_power"]),
        "neutral_current": em["n_current"],
        "phase_a_energy_imported_kwh": wh_to_kwh(ed["a_total_act_energy"]),
        "phase_b_energy_imported_kwh": wh_to_kwh(ed["b_total_act_energy"]),
        "phase_c_energy_imported_kwh": wh_to_kwh(ed["c_total_act_energy"]),
        "phase_a_energy_returned_kwh": wh_to_kwh(ed["a_total_act_ret_energy"]),
        "phase_b_energy_returned_kwh": wh_to_kwh(ed["b_total_act_ret_energy"]),
        "phase_c_energy_returned_kwh": wh_to_kwh(ed["c_total_act_ret_energy"]),
        "meter_energy_kwh": wh_to_kwh(ed["total_act"]),
        "meter_energy_returned_kwh": wh_to_kwh(ed["total_act_ret"]),
    }


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

db = Session()
node = models.Node(
    code="NCAP",
    name="Capture node",
    status="online",
    hardware_kind="shelly",
    commission_state="commissioned",
    measurement_context="production",
    samples=0,
    buffer_pending=0,
)
db.add(node)
db.commit()
db.refresh(node)
NODE_ID = node.id

# Identity is a credential the node presents, never an attribute of the request
# (ADR-0002). The test issues one and sends it, rather than disabling the gate:
# a suite that ingests through an unauthenticated side door would not be
# exercising the path production uses.
TOKEN = node_auth.issue_token(db, node)
db.commit()
AUTH = {"Authorization": f"Bearer {TOKEN}"}

with engine.begin() as connection:
    connection.execute(
        text(
            "INSERT INTO measurement_eras (node_id, starts_at, ends_at, "
            "energy_semantics, nominal_interval_seconds, discovered_by, notes) "
            "VALUES (:n, NULL, NULL, 'interval_energy', 15.0, 'test', "
            "'mirrors N001 era 2: the collector derives energy from power')"
        ),
        {"n": NODE_ID},
    )

# A reading written BEFORE the expansion: only the columns that existed then.
PRE_M15_TS = datetime(2026, 8, 1, 12, 0, 0)
legacy = models.EnergyReading(
    node_id=node.id,
    context="production",
    timestamp=PRE_M15_TS,
    voltage=125.6,
    current=105.86,
    power_kw=12.652766,
    power_factor=0.95048714,
    frequency_hz=60.0,
    energy_kwh=0.0527198583,
    phase_a_voltage=124.7,
    phase_b_voltage=126.1,
    phase_c_voltage=126.0,
    phase_a_current=37.470,
    phase_b_current=35.133,
    phase_c_current=33.257,
)
db.add(legacy)
db.commit()
db.refresh(legacy)
LEGACY_ID = legacy.id
db.close()


print("\n§1  units — one conversion, at one boundary")
check("4632.3 W -> 4.6323 kW", close(w_to_kw(4632.3), 4.6323))
check("13311.875 VA -> 13.311875 kVA", close(va_to_kva(13311.875), 13.311875))
check("5310919.91 Wh -> 5310.91991 kWh", close(wh_to_kwh(5310919.91), 5310.91991, 1e-6))
check(
    "None survives every converter",
    w_to_kw(None) is None and va_to_kva(None) is None and wh_to_kwh(None) is None,
)
# The specific failure this guards: applying the converter twice.
check(
    "double conversion is detectably wrong, not merely small",
    not close(w_to_kw(w_to_kw(4632.3)), 4.6323),
    "w_to_kw applied twice must not equal the correct answer",
)


print("\n§2  batch ingest — device units in, platform units stored")
stamp = (datetime.utcnow() - timedelta(seconds=30)).isoformat()
response = client.post(
    "/api/v1/measurements/batch",
    json={"device_id": "NCAP", "measurements": [batch_measurement(stamp)]},
    headers=AUTH,
)
check(
    "batch accepted",
    response.status_code == 200,
    f"HTTP {response.status_code} {response.text[:200]}",
)

db = Session()
row = (
    db.query(models.EnergyReading)
    .filter(models.EnergyReading.node_id == NODE_ID, models.EnergyReading.id != LEGACY_ID)
    .order_by(models.EnergyReading.id.desc())
    .first()
)
check("batch stored a reading", row is not None)

if row is not None:
    check("phase A active power 4632.3 W -> 4.6323 kW", close(row.phase_a_power_kw, 4.6323))
    check("phase B active power 4392.3 W -> 4.3923 kW", close(row.phase_b_power_kw, 4.3923))
    check("phase C active power 3628.2 W -> 3.6282 kW", close(row.phase_c_power_kw, 3.6282))
    check("phase A apparent 4679.9 VA -> 4.6799 kVA", close(row.phase_a_apparent_kva, 4.6799))
    check("phase C apparent 4194.1 VA -> 4.1941 kVA", close(row.phase_c_apparent_kva, 4.1941))
    check("total apparent 13311.875 VA -> 13.311875 kVA", close(row.apparent_kva, 13.311875))
    # The per-phase PF is the whole reason this migration matters: the aggregate
    # 0.95 hides that phase C is running at 0.87.
    check("phase A power factor stored verbatim 0.99", close(row.phase_a_power_factor, 0.99))
    check("phase C power factor stored verbatim 0.87", close(row.phase_c_power_factor, 0.87))
    check(
        "per-phase PF preserves the spread the aggregate hides",
        row.phase_a_power_factor - row.phase_c_power_factor > 0.1,
    )
    check(
        "phase frequencies stored",
        all(close(getattr(row, f"phase_{p}_frequency_hz"), 60.0) for p in "abc"),
    )
    check(
        "meter import register 5310919.91 Wh -> 5310.91991 kWh",
        close(row.meter_energy_kwh, 5310.91991, 1e-6),
    )
    check(
        "meter return register 184587.57 Wh -> 184.58757 kWh",
        close(row.meter_energy_returned_kwh, 184.58757, 1e-6),
    )
    check("phase A import register", close(row.phase_a_energy_imported_kwh, 2050.29969, 1e-6))
    check("phase B return register", close(row.phase_b_energy_returned_kwh, 47.78637, 1e-6))
    # A register in the millions of Wh must not lose its watt-hour digit.
    check(
        "register keeps full magnitude, not a truncated one",
        row.meter_energy_kwh > 5310 and row.meter_energy_kwh < 5311,
        f"got {row.meter_energy_kwh}",
    )


print("\n§3  null semantics — n_current is null on this installation")
if row is not None:
    check(
        "neutral current stored as NULL, not 0.0",
        row.neutral_current is None,
        f"got {row.neutral_current!r}",
    )
    check(
        "NULL is not falsy-coerced anywhere on the path",
        row.neutral_current != 0.0 or row.neutral_current is None,
    )

# The meter's temperature is health telemetry: accepted by the batch model,
# deliberately NOT a column on the reading.
check(
    "meter temperature is not stored on energy_readings",
    not hasattr(models.EnergyReading, "meter_temperature_c"),
)
check(
    "meter temperature IS a column on the heartbeat model",
    hasattr(models.Node, "code")
    and "meter_temperature_c"
    in __import__("app.monitoring.models", fromlist=["x"]).NodeHeartbeat.__table__.columns,
)


print("\n§4  backward compatibility — the pre-expansion row is untouched")
old = db.query(models.EnergyReading).filter(models.EnergyReading.id == LEGACY_ID).first()
check("the old row still exists", old is not None)
if old is not None:
    check(
        "its measured values are unchanged",
        close(old.power_kw, 12.652766) and close(old.phase_a_current, 37.470),
    )
    check("its timestamp is unchanged", old.timestamp == PRE_M15_TS)
    NEW_COLUMNS = [
        "phase_a_power_kw",
        "phase_b_power_kw",
        "phase_c_power_kw",
        "phase_a_apparent_kva",
        "phase_b_apparent_kva",
        "phase_c_apparent_kva",
        "phase_a_power_factor",
        "phase_b_power_factor",
        "phase_c_power_factor",
        "phase_a_frequency_hz",
        "phase_b_frequency_hz",
        "phase_c_frequency_hz",
        "apparent_kva",
        "neutral_current",
        "phase_a_energy_imported_kwh",
        "phase_b_energy_imported_kwh",
        "phase_c_energy_imported_kwh",
        "phase_a_energy_returned_kwh",
        "phase_b_energy_returned_kwh",
        "phase_c_energy_returned_kwh",
        "meter_energy_returned_kwh",
    ]
    check(
        "every new column is NULL on it — never backfilled, never zero",
        all(getattr(old, column) is None for column in NEW_COLUMNS),
        str({c: getattr(old, c) for c in NEW_COLUMNS if getattr(old, c) is not None}),
    )
db.close()


print("\n§5  the two ingest paths agree")
stamp2 = (datetime.utcnow() - timedelta(seconds=15)).isoformat()
response = client.post("/api/readings", json=readings_payload("NCAP", stamp2), headers=AUTH)
check(
    "readings route accepted",
    response.status_code == 200,
    f"HTTP {response.status_code} {response.text[:200]}",
)

db = Session()
rows = (
    db.query(models.EnergyReading)
    .filter(models.EnergyReading.node_id == NODE_ID, models.EnergyReading.id != LEGACY_ID)
    .order_by(models.EnergyReading.id.asc())
    .all()
)
check("both routes stored a row", len(rows) == 2, f"got {len(rows)}")
if len(rows) == 2:
    from_batch, from_readings = rows
    COMPARED = [
        "phase_a_power_kw",
        "phase_b_power_kw",
        "phase_c_power_kw",
        "phase_a_apparent_kva",
        "phase_b_apparent_kva",
        "phase_c_apparent_kva",
        "phase_a_power_factor",
        "phase_b_power_factor",
        "phase_c_power_factor",
        "phase_a_frequency_hz",
        "phase_b_frequency_hz",
        "phase_c_frequency_hz",
        "apparent_kva",
        "neutral_current",
        "meter_energy_kwh",
        "meter_energy_returned_kwh",
        "phase_a_energy_imported_kwh",
        "phase_c_energy_returned_kwh",
    ]
    disagreements = {}
    for column in COMPARED:
        a, b = getattr(from_batch, column), getattr(from_readings, column)
        if a is None and b is None:
            continue
        if a is None or b is None or abs(a - b) > 1e-9:
            disagreements[column] = (a, b)
    check(
        "the same physical measurement stores identically on both routes",
        not disagreements,
        str(disagreements),
    )
db.close()


print("\n§6  the API exposes what was stored")
history = client.get("/api/metrics/live/history?node_ids=NCAP&range=1h").json()
points = history["series"][0]["points"] if history["series"] else []
check("history returns the ingested points", len(points) >= 2, f"got {len(points)}")
check("history is raw at 1 h", history["resolution_seconds"] == 0)
newest = points[-1] if points else {}
check(
    "per-phase power reaches the API", close(newest.get("pa"), 4.6323, 1e-5), str(newest.get("pa"))
)
check("per-phase apparent reaches the API", close(newest.get("sa"), 4.6799, 1e-5))
check("per-phase power factor reaches the API", close(newest.get("pfc"), 0.87, 1e-4))
check("total apparent reaches the API", close(newest.get("kva"), 13.311875, 1e-5))
check("import register reaches the API", close(newest.get("imp_t"), 5310.91991, 1e-3))
# The omission rule: a null series is absent from the payload, not serialised.
check("null neutral current is omitted, not sent as 0", "nc" not in newest, str(newest.get("nc")))

snapshot = client.get("/api/metrics/live/snapshot?node_ids=NCAP").json()
snap = snapshot["nodes"][0]
check(
    "snapshot reports the new metric groups as available",
    {
        "phase_power",
        "phase_apparent",
        "phase_power_factor",
        "phase_frequency",
        "apparent_kva",
        "energy_imported",
        "energy_returned",
    }.issubset(set(snap["available_metrics"])),
    str(snap["available_metrics"]),
)
check(
    "snapshot does NOT advertise neutral current — the meter reported null",
    "neutral_current" not in snap["available_metrics"],
)
check(
    "snapshot carries the per-phase reading", close(snap["reading"]["phase_c_power_factor"], 0.87)
)


print("\n§7  ranges")
for key, expect_raw in [
    ("5m", True),
    ("15m", True),
    ("30m", True),
    ("1h", True),
    ("6h", False),
    ("24h", False),
    ("7d", False),
]:
    body = client.get(f"/api/metrics/live/history?node_ids=NCAP&range={key}").json()
    raw = body["resolution_seconds"] == 0
    check(
        f"{key} is {'RAW' if expect_raw else 'aggregated'}",
        raw == expect_raw,
        f"resolution_seconds={body['resolution_seconds']}",
    )
    check(f"{key} declares its aggregation", bool(body.get("aggregation")))

body = client.get("/api/metrics/live/history?node_ids=NCAP&range=deployment").json()
check("deployment range answers even with no activated deployment", body["resolution_seconds"] >= 0)
check("deployment range declares itself", body["range"] == "deployment")


print("\n§8  the deployment range is scoped by deployment, not by node and dates")

# A campaign for this node, and a reading attributed to it.
# A building needs a campus, which needs its own row: the schema requires the
# organisational chain rather than allowing an orphan.
db = Session()
delegation = models.Delegation(name="Delegación de prueba M15")
db.add(delegation)
db.commit()
db.refresh(delegation)
campus = models.Campus(name="Campus de prueba M15", delegation_id=delegation.id)
db.add(campus)
db.commit()
db.refresh(campus)
unit = models.OrganizationalUnit(name="Unidad de prueba M15", campus_id=campus.id)
db.add(unit)
db.commit()
db.refresh(unit)
building = models.Building(
    code="M15-TEST",
    name="Edificio de prueba M15",
    campus_id=campus.id,
    organizational_unit_id=unit.id,
)
db.add(building)
db.commit()
db.refresh(building)
panel = models.ElectricalPanel(name="Tablero de prueba M15", building_id=building.id)
db.add(panel)
db.commit()
db.refresh(panel)
campaign = models.Deployment(
    node_id=NODE_ID,
    building_id=building.id,
    electrical_panel_id=panel.id,
    status="active",
    start_date=(datetime.utcnow() - timedelta(hours=3)).date(),
    end_date=(datetime.utcnow() + timedelta(days=1)).date(),
    activated_at=datetime.utcnow() - timedelta(hours=3),
    closed_at=None,
)
db.add(campaign)
db.commit()
db.refresh(campaign)
CAMPAIGN_ID = campaign.id
# Capture the value now: the session closes below and the instance detaches.
CAMPAIGN_ACTIVATED = campaign.activated_at

inside = models.EnergyReading(
    node_id=NODE_ID,
    deployment_id=CAMPAIGN_ID,
    building_id=building.id,
    context="production",
    timestamp=datetime.utcnow() - timedelta(hours=1),
    power_kw=9.0,
    phase_a_power_kw=3.0,
)
# The defect deployment 5 exhibits on the live platform: a reading carrying the
# campaign's id but stamped outside the campaign's own window. It must be
# counted and reported, never charted and never silently absorbed by widening
# the window — attribution is written once at ingest and not recomputed.
outside = models.EnergyReading(
    node_id=NODE_ID,
    deployment_id=CAMPAIGN_ID,
    building_id=building.id,
    context="production",
    timestamp=datetime.utcnow() - timedelta(days=30),
    power_kw=7.0,
    phase_a_power_kw=2.0,
)
db.add_all([inside, outside])
db.commit()
db.close()

listed = client.get("/api/metrics/live/deployments").json()
check(
    "the campaign appears in the selector", any(d["deployment_id"] == CAMPAIGN_ID for d in listed)
)

scoped = client.get(
    f"/api/metrics/live/history?range=deployment&deployment_id={CAMPAIGN_ID}"
).json()
span = scoped["deployments"][0] if scoped["deployments"] else {}
check("the window is the campaign's own", scoped["deployment_id"] == CAMPAIGN_ID)
check(
    "bounds come from activated_at",
    scoped["window_start"][:16] == CAMPAIGN_ACTIVATED.isoformat()[:16],
)
check("the census counts the in-window reading", span.get("readings_in_window") == 1, str(span))
check(
    "the census counts the out-of-window reading",
    span.get("readings_outside_window") == 1,
    str(span),
)
points = scoped["series"][0]["points"] if scoped["series"] else []
check("only the in-window reading is charted", len(points) == 1, f"{len(points)} points")

# Node selection must not change a deployment-scoped answer.
narrowed = client.get(
    f"/api/metrics/live/history?range=deployment&deployment_id={CAMPAIGN_ID}&node_ids=NOTANODE"
).json()
check(
    "node_ids is ignored in deployment mode",
    narrowed["point_count"] == scoped["point_count"],
    f"{narrowed['point_count']} vs {scoped['point_count']}",
)

# An unknown id must not fabricate a window.
unknown = client.get("/api/metrics/live/history?range=deployment&deployment_id=999999").json()
check(
    "an unknown deployment falls back to a real one and names it",
    unknown["deployment_id"] != 999999 and bool(unknown["deployments"]),
    str(unknown["deployment_id"]),
)

print("\n" + "=" * 60)
print(f"PASSED: {passed}   FAILED: {failed}")
print("=" * 60)
sys.exit(1 if failed else 0)
