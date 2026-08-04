"""Smart Plug API test suite.

Runs against a throwaway SQLite database (the get_db dependency is overridden),
so production history is never touched.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, "/home/manager/energy-platform/backend")
os.chdir("/home/manager/energy-platform/backend")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db.database import Base, get_db
from app.db import models

os.makedirs("/tmp/energy-platform-tests", exist_ok=True)
TMP_DB = "/tmp/energy-platform-tests/test_plugs.db"
if os.path.exists(TMP_DB):
    os.remove(TMP_DB)

test_engine = create_engine(f"sqlite:///{TMP_DB}", connect_args={"check_same_thread": False})
TestSession = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)
Base.metadata.create_all(bind=test_engine)

# The lifecycle reference tables come from SQL migrations, not from the
# ORM metadata, and ingest/discovery now read them through
# app.db.lifecycle. Without them this suite fails before its first check.
sys.path.insert(0, "/home/manager/energy-platform/backend")
from tests.lifecycle_fixtures import seed_lifecycle_tables  # noqa: E402

seed_lifecycle_tables(test_engine)


def override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    print(f"  {'PASS' if condition else 'FAIL'}  {name}" + (f"  <- {detail}" if detail and not condition else ""))


# ---------------------------------------------------------------- fixtures
db = TestSession()
db.add(models.Delegation(id=1, name="Colima"))
db.add(models.Campus(id=1, name="Campus Coquimatlan", delegation_id=1))
db.add(models.OrganizationalUnit(id=1, name="FIME", campus_id=1))
db.add(models.Building(id=8, code="B-TEST", name="Edificio de prueba", campus_id=1, organizational_unit_id=1))
db.add(models.ElectricalPanel(id=8, name="Tablero principal", building_id=8))
db.add(models.Node(id=1, code="N001", name="Edge Node 001"))
db.add(models.Node(id=3, code="N003", name="Energy Node 003"))
# `activated_at` / `closed_at` (migration 010) are what mark a campaign as the
# one CURRENTLY measuring a building — assignment resolves the deployment through
# them, deliberately, so a plug is never attached to a campaign that ended months
# ago. A fixture that sets only `status` leaves the plug with no deployment.
db.add(models.Deployment(id=4, node_id=1, building_id=8, electrical_panel_id=8,
                         start_date="2026-06-14", end_date="2026-06-21", status="active",
                         activated_at=datetime(2026, 6, 14), closed_at=None))
db.commit()
db.close()

MACS = ["ac:eb:e6:f6:53:88", "ac:eb:e6:f2:91:b8", "ac:eb:e6:f2:57:ec", "ac:eb:e6:f2:83:08"]
now = datetime.utcnow()


def iso(dt):
    return dt.isoformat() + "Z"


print("\n=== 1. Empty inventory ===")
r = client.get("/api/smart-plugs")
check("GET /api/smart-plugs returns 200 + empty list", r.status_code == 200 and r.json() == [], r.text)

print("\n=== 2. Discovery from Raspberry N001 (4 real MACs) ===")
payload = {
    "node_id": "N001",
    "plugs": [
        {
            "mac": m.upper().replace(":", ""),  # Shelly bare-hex notation
            "ip": f"192.168.1.{50 + i}",
            "hostname": f"shellyplugusg4-{m.replace(':','')}",
            "model": "Shelly Plug US Gen4",
            "firmware": "1.4.4",
            "rssi": -55 - i,
            "temperature_c": 40.5 + i,
            "online": True,
            "last_seen": iso(now),
            "measurements": [
                {"captured_at": iso(now - timedelta(seconds=30)), "power_w": 100.0 + i * 50,
                 "voltage_v": 121.3, "current_a": 0.9, "power_factor": 0.97,
                 "energy_total_kwh": 10.0 + i, "temperature_c": 40.5, "rssi": -55},
                {"captured_at": iso(now - timedelta(seconds=15)), "power_w": 110.0 + i * 50,
                 "voltage_v": 121.1, "current_a": 0.95, "power_factor": 0.98,
                 "energy_total_kwh": 10.01 + i, "temperature_c": 40.6, "rssi": -56},
            ],
        }
        for i, m in enumerate(MACS)
    ],
}
r = client.post("/api/smart-plugs/discovery", json=payload)
body = r.json()
check("POST discovery returns 200", r.status_code == 200, r.text)
check("4 plugs created", body.get("plugs_created") == 4, str(body))
check("8 readings inserted", body.get("readings_inserted") == 8, str(body))

print("\n=== 3. MAC normalization ===")
r = client.get("/api/smart-plugs")
plugs = r.json()
check("inventory has 4 plugs", len(plugs) == 4, str(len(plugs)))
check("bare hex normalized to colon MAC", plugs[0]["mac"] == "AC:EB:E6:F6:53:88", plugs[0]["mac"])
check("public id is slug", plugs[0]["id"] == "acebe6f65388", plugs[0]["id"])
check("all plugs online", all(p["online"] for p in plugs))
check("telemetry present", plugs[0]["power_w"] == 110.0, str(plugs[0]["power_w"]))
check("firmware stored", plugs[0]["firmware"] == "1.4.4")
check("node attributed", plugs[0]["node"] == "N001", str(plugs[0]["node"]))
check("energy_today computed from deltas", plugs[0]["energy_today_kwh"] is not None,
      str(plugs[0]["energy_today_kwh"]))

print("\n=== 4. Idempotent replay (buffer retry must not duplicate) ===")
r = client.post("/api/smart-plugs/discovery", json=payload)
body = r.json()
check("no new plugs on replay", body.get("plugs_created") == 0, str(body))
check("no new readings on replay", body.get("readings_inserted") == 0, str(body))
check("duplicates detected", body.get("readings_duplicated") == 8, str(body))

print("\n=== 5. IP change (same MAC, new subnet) — must NOT duplicate ===")
ip_change = {
    "node_id": "N001",
    "plugs": [{
        "mac": "AC:EB:E6:F6:53:88",
        "ip": "10.20.30.77",  # different subnet entirely
        "online": True,
        "last_seen": iso(now + timedelta(seconds=20)),
        "measurements": [],
    }],
}
r = client.post("/api/smart-plugs/discovery", json=ip_change)
check("IP change creates no duplicate", r.json().get("plugs_created") == 0, r.text)
r = client.get("/api/smart-plugs")
plugs = r.json()
target = [p for p in plugs if p["mac"] == "AC:EB:E6:F6:53:88"][0]
check("still exactly 4 plugs", len(plugs) == 4, str(len(plugs)))
check("stored IP updated to new subnet", target["ip"] == "10.20.30.77", str(target["ip"]))

print("\n=== 6. Assignment ===")
r = client.post("/api/smart-plugs/acebe6f65388/assign", json={
    "friendly_name": "Rack de switches",
    "building": "Edificio de prueba",
    "deployment": "Campana Laboratorio de Redes",
    "outlet_location": "Rack A - Contacto 3",
})
assigned = r.json()
check("assign returns 200", r.status_code == 200, r.text)
check("friendly_name persisted", assigned["friendly_name"] == "Rack de switches")
check("building label round-trips", assigned["building"] == "Edificio de prueba", str(assigned["building"]))
check("deployment label round-trips", assigned["deployment"] == "Campana Laboratorio de Redes")
check("outlet_location persisted", assigned["outlet_location"] == "Rack A - Contacto 3")

# building name matched an existing record -> FK must be resolved
db = TestSession()
row = db.query(models.SmartPlug).filter(models.SmartPlug.mac == "AC:EB:E6:F6:53:88").first()
check("building FK resolved from free text", row.building_id == 8, str(row.building_id))
check("deployment FK resolved", row.deployment_id == 4, str(row.deployment_id))
db.close()

print("\n=== 7. Assignment survives a later discovery report ===")
client.post("/api/smart-plugs/discovery", json=payload)
r = client.get("/api/smart-plugs/acebe6f65388")
still = r.json()
check("friendly_name not overwritten by edge", still["friendly_name"] == "Rack de switches")
check("building not overwritten by edge", still["building"] == "Edificio de prueba")

print("\n=== 8. Offline behaviour (plug disappears) ===")
gone = {
    "node_id": "N001",
    "plugs": [{"mac": "AC:EB:E6:F2:91:B8", "online": False, "measurements": []}],
}
r = client.post("/api/smart-plugs/discovery", json=gone)
check("offline report accepted", r.status_code == 200, r.text)
r = client.get("/api/smart-plugs")
plugs = r.json()
off = [p for p in plugs if p["mac"] == "AC:EB:E6:F2:91:B8"][0]
check("plug not deleted", len(plugs) == 4, str(len(plugs)))
check("marked offline", off["online"] is False)
check("last_seen preserved", off["last_seen"] is not None, str(off["last_seen"]))
check("stale telemetry hidden", off["power_w"] is None, str(off["power_w"]))

print("\n=== 9. Automatic recovery on rediscovery ===")
back = {
    "node_id": "N001",
    "plugs": [{
        "mac": "AC:EB:E6:F2:91:B8", "ip": "192.168.5.9", "online": True,
        "last_seen": iso(datetime.utcnow()),
        "measurements": [{"captured_at": iso(datetime.utcnow()), "power_w": 77.0,
                          "voltage_v": 120.9, "energy_total_kwh": 12.0}],
    }],
}
client.post("/api/smart-plugs/discovery", json=back)
r = client.get("/api/smart-plugs")
rec = [p for p in r.json() if p["mac"] == "AC:EB:E6:F2:91:B8"][0]
check("online restored automatically", rec["online"] is True)
check("telemetry restored", rec["power_w"] == 77.0, str(rec["power_w"]))
check("assignment/history intact after outage", rec["ip"] == "192.168.5.9")

print("\n=== 10. Staleness window (Raspberry itself dies) ===")
db = TestSession()
row = db.query(models.SmartPlug).filter(models.SmartPlug.mac == "AC:EB:E6:F2:57:EC").first()
row.online = True
row.last_seen = datetime.utcnow() - timedelta(minutes=10)  # stale
db.commit()
db.close()
r = client.get("/api/smart-plugs")
stale = [p for p in r.json() if p["mac"] == "AC:EB:E6:F2:57:EC"][0]
check("stale plug forced offline despite online flag", stale["online"] is False)

print("\n=== 11. /live endpoint ===")
r = client.get("/api/smart-plugs/live")
live = r.json()
check("live returns 200", r.status_code == 200, r.text)
check("only online plugs listed", all(p["online"] for p in live["smart_plugs"]))
check("highest_consumer identified", live["highest_consumer"] is not None)
check("sorted by power desc",
      [p["power_w"] for p in live["smart_plugs"]] == sorted([p["power_w"] for p in live["smart_plugs"]], reverse=True),
      str([p["power_w"] for p in live["smart_plugs"]]))
check("total_power_w computed", live["total_power_w"] > 0, str(live["total_power_w"]))

print("\n=== 12. History ===")
r = client.get("/api/smart-plugs/acebe6f65388/history?hours=24")
hist = r.json()
check("history returns 200", r.status_code == 200, r.text)
check("history has points", len(hist) >= 2, str(len(hist)))
check("history ascending by time", [h["timestamp"] for h in hist] == sorted(h["timestamp"] for h in hist))
check("history carries power", hist[0]["power_w"] is not None)

print("\n=== 13. Lookup by MAC and 404 ===")
check("lookup by colon MAC", client.get("/api/smart-plugs/AC:EB:E6:F6:53:88").status_code == 200)
check("lookup by bare hex", client.get("/api/smart-plugs/acebe6f65388").status_code == 200)
check("unknown plug -> 404", client.get("/api/smart-plugs/deadbeefdead").status_code == 404)
check("unknown node in discovery -> 404",
      client.post("/api/smart-plugs/discovery", json={"node_id": "NOPE", "plugs": []}).status_code == 404)

print("\n=== 14. Energy Node ingestion untouched ===")
r = client.post("/api/v1/measurements/batch", json={
    "device_id": "N001",
    "measurements": [{"captured_at": iso(datetime.utcnow()), "voltage_a": 121.0, "current_a": 5.0,
                      "total_active_power": 1800.0, "total_current": 15.0}],
})
check("energy node batch still ingests", r.status_code == 200 and r.json().get("inserted") == 1, r.text)
r = client.post("/api/edge/heartbeat", json={"node_id": "N001"})
check("heartbeat still works", r.status_code == 200, r.text)

db = TestSession()
check("plug readings did NOT go into energy_readings",
      db.query(models.EnergyReading).count() == 1,
      str(db.query(models.EnergyReading).count()))
check("plug history stored separately",
      db.query(models.SmartPlugReading).count() >= 9,
      str(db.query(models.SmartPlugReading).count()))
db.close()

print("\n" + "=" * 60)
print(f"PASSED: {len(PASS)}   FAILED: {len(FAIL)}")
if FAIL:
    print("FAILURES:")
    for f in FAIL:
        print("  -", f)
print("=" * 60)
sys.exit(1 if FAIL else 0)
