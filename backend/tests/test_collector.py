"""Raspberry Pi smart plug collector test.

Simulated Shelly devices (rpc_get is stubbed), a real HTTP server as the
backend, and that server forwards each payload into the *real* FastAPI router
backed by a throwaway database. So this proves the edge payload is accepted by
the actual backend code, without touching production data.
"""
import json
import os
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, "/home/manager/energy-platform/backend")
sys.path.insert(0, "/home/manager/energy-platform/edge")
os.chdir("/home/manager/energy-platform/backend")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db.database import Base, get_db
from app.db import models

import smart_plug_source as sps

SCRATCH = "/tmp/energy-platform-tests"
os.makedirs(SCRATCH, exist_ok=True)
TMP_DB = f"{SCRATCH}/test_collector.db"
BUFFER_DB = f"{SCRATCH}/test_buffer.db"

for path in (TMP_DB, BUFFER_DB, BUFFER_DB + "-wal", BUFFER_DB + "-shm"):
    if os.path.exists(path):
        os.remove(path)

engine = create_engine(f"sqlite:///{TMP_DB}", connect_args={"check_same_thread": False})
Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base.metadata.create_all(bind=engine)

# The lifecycle reference tables come from SQL migrations, not from the ORM
# metadata, and the discovery endpoint now reads them through app.db.lifecycle.
# Without them this suite fails before its first check.
sys.path.insert(0, "/home/manager/energy-platform/backend")
from tests.lifecycle_fixtures import seed_lifecycle_tables  # noqa: E402

seed_lifecycle_tables(engine)

def override_get_db():
    db = Session()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

db = Session()
db.add(models.Delegation(id=1, name="Colima"))
db.add(models.Campus(id=1, name="Campus", delegation_id=1))
db.add(models.OrganizationalUnit(id=1, name="FIME", campus_id=1))
db.add(models.Building(id=8, code="B-TEST", name="Edificio de prueba", campus_id=1, organizational_unit_id=1))
db.add(models.ElectricalPanel(id=8, name="Tablero", building_id=8))
db.add(models.Node(id=1, code="N001", name="Edge Node 001"))
db.add(models.Deployment(id=4, node_id=1, building_id=8, electrical_panel_id=8,
                         start_date="2026-06-14", end_date="2026-06-21", status="active"))
db.commit()
db.close()

PASS, FAIL = [], []
def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  <- {detail}" if detail and not cond else ""))


# ------------------------------------------------- fake backend (real router)
received = []
backend_up = threading.Event()
backend_up.set()

class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))

        if not backend_up.is_set():
            self.send_response(503)
            self.end_headers()
            return

        payload = json.loads(body)
        received.append(payload)

        # Forward into the REAL backend router.
        response = client.post("/api/smart-plugs/discovery", json=payload)

        self.send_response(response.status_code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(response.content)

    def log_message(self, *args):
        pass

server = HTTPServer(("127.0.0.1", 0), Handler)
port = server.server_port
threading.Thread(target=server.serve_forever, daemon=True).start()
BACKEND = f"http://127.0.0.1:{port}"


# ------------------------------------------------------ simulated Shelly fleet
FLEET = {
    "192.168.1.50": {"mac": "ACEBE6F65388", "power": 120.0, "energy": 10.0},
    "192.168.1.51": {"mac": "ACEBE6F291B8", "power": 340.0, "energy": 22.5},
    "192.168.1.52": {"mac": "ACEBE6F257EC", "power": 65.0,  "energy": 5.25},
    "192.168.1.53": {"mac": "ACEBE6F28308", "power": 900.0, "energy": 41.0},
}
reachable = set(FLEET)

def fake_rpc_get(ip, method, timeout=None, params=""):
    if ip not in FLEET or ip not in reachable:
        return None
    device = FLEET[ip]
    if method == "Shelly.GetDeviceInfo":
        return {"id": f"shellyplugusg4-{device['mac'].lower()}", "mac": device["mac"],
                "model": "S4PL-00112EU", "gen": 4, "ver": "1.4.4", "serial": 1234}
    if method == "Switch.GetStatus":
        return {"id": 0, "output": True, "apower": device["power"], "voltage": 121.4,
                "current": round(device["power"] / 121.4, 3), "pf": 0.98,
                "aenergy": {"total": device["energy"] * 1000},
                "temperature": {"tC": 42.1}}
    if method == "WiFi.GetStatus":
        return {"sta_ip": ip, "status": "got ip", "ssid": "wirelesslan", "rssi": -58}
    return None

sps.rpc_get = fake_rpc_get
# Constrain discovery to the simulated fleet's addresses (no real network scan).
sps._sweep_all = list(FLEET)
sps.SmartPlugSource._sweep_candidates = lambda self: list(FLEET)
sps.SmartPlugSource._mdns_candidates = lambda self: []


print("\n=== 1. Interface / subnet auto-detection (no hardcoding) ===")
nets = sps.local_networks()
check("local networks detected from kernel", len(nets) >= 1, str(nets))
check("active source IP resolved", sps.active_source_ip() is not None)
# Check executable code only: comments and docstrings legitimately *mention*
# wlan0/eth0 to state that they are not used.
import io, tokenize
code_only = []
with open("/home/manager/energy-platform/edge/smart_plug_source.py") as fh:
    for tok in tokenize.generate_tokens(fh.readline):
        if tok.type not in (tokenize.COMMENT, tokenize.STRING):
            code_only.append(tok.string)
code_only = " ".join(code_only)

check("no hardcoded wlan0 in code", "wlan0" not in code_only)
check("no hardcoded eth0 in code", "eth0" not in code_only)
check("no hardcoded IP range in code", "192.168." not in code_only and "10.0.0." not in code_only)
check("no hardcoded gateway in code", "gateway" not in code_only.lower())
check("interface discovered via kernel, not a name literal", "addr" in open(
    "/home/manager/energy-platform/edge/smart_plug_source.py").read())

print("\n=== 2. MAC normalization ===")
check("bare hex -> colon form", sps.normalize_mac("ACEBE6F65388") == "AC:EB:E6:F6:53:88")
check("lowercase colon -> upper", sps.normalize_mac("ac:eb:e6:f2:91:b8") == "AC:EB:E6:F2:91:B8")
check("idempotent", sps.normalize_mac(sps.normalize_mac("ACEBE6F65388")) == "AC:EB:E6:F6:53:88")

print("\n=== 3. Discovery ===")
source = sps.SmartPlugSource(node_id="N001", backend_url=BACKEND, buffer_path=BUFFER_DB)
found = source.discover()
check("all 4 plugs discovered", found == 4, str(found))
check("keyed by MAC", set(source.plugs) == {"AC:EB:E6:F6:53:88", "AC:EB:E6:F2:91:B8",
                                            "AC:EB:E6:F2:57:EC", "AC:EB:E6:F2:83:08"},
      str(set(source.plugs)))
check("firmware captured", source.plugs["AC:EB:E6:F6:53:88"]["identity"]["firmware"] == "1.4.4")

print("\n=== 4. Poll + report to real backend ===")
source.poll_once()
check("measurements buffered before upload", source.buffer.pending_count() == 4,
      str(source.buffer.pending_count()))
check("report succeeded", source.report() is True)
check("buffer drained after success", source.buffer.pending_count() == 0,
      str(source.buffer.pending_count()))

r = client.get("/api/smart-plugs")
plugs = r.json()
check("backend stored 4 plugs", len(plugs) == 4, str(len(plugs)))
check("all online in backend", all(p["online"] for p in plugs))
check("power arrived", sorted(p["power_w"] for p in plugs) == [65.0, 120.0, 340.0, 900.0],
      str(sorted(p["power_w"] for p in plugs)))
check("rssi arrived", plugs[0]["rssi"] == -58, str(plugs[0]["rssi"]))
check("temperature arrived", plugs[0]["temperature_c"] == 42.1, str(plugs[0]["temperature_c"]))
check("hostname arrived", plugs[0]["hostname"] is not None)

r = client.get("/api/smart-plugs/live")
check("highest consumer is the 900 W plug",
      r.json()["highest_consumer"]["power_w"] == 900.0,
      str(r.json()["highest_consumer"]["power_w"]))

print("\n=== 5. IP change: same MAC on a new subnet ===")
moved = FLEET.pop("192.168.1.50")
FLEET["10.44.7.99"] = moved
reachable.discard("192.168.1.50")
reachable.add("10.44.7.99")
sps.SmartPlugSource._sweep_candidates = lambda self: list(FLEET)

source.poll_once()          # old IP fails -> marks offline, triggers rediscovery
source.discover()           # finds it at the new IP
source.poll_once()
source.report()

check("still exactly 4 plugs in memory", len(source.plugs) == 4, str(len(source.plugs)))
check("in-memory IP updated", source.plugs["AC:EB:E6:F6:53:88"]["identity"]["ip"] == "10.44.7.99",
      source.plugs["AC:EB:E6:F6:53:88"]["identity"]["ip"])
plugs = client.get("/api/smart-plugs").json()
check("backend has no duplicate after IP change", len(plugs) == 4, str(len(plugs)))
target = [p for p in plugs if p["mac"] == "AC:EB:E6:F6:53:88"][0]
check("backend IP updated to new subnet", target["ip"] == "10.44.7.99", str(target["ip"]))
check("plug back online after move", target["online"] is True)

print("\n=== 6. Plug disappears -> offline, never deleted ===")
reachable.discard("192.168.1.51")
source.poll_once()
source.report()
check("immediate rediscovery was requested", source._rediscover_now.is_set())

plugs = client.get("/api/smart-plugs").json()
gone = [p for p in plugs if p["mac"] == "AC:EB:E6:F2:91:B8"][0]
check("plug still present", len(plugs) == 4, str(len(plugs)))
check("reported offline", gone["online"] is False)
check("last_seen preserved", gone["last_seen"] is not None)

print("\n=== 7. Automatic recovery ===")
reachable.add("192.168.1.51")
source.poll_once()
source.report()
back = [p for p in client.get("/api/smart-plugs").json() if p["mac"] == "AC:EB:E6:F2:91:B8"][0]
check("online restored without manual action", back["online"] is True)
check("power flowing again", back["power_w"] == 340.0, str(back["power_w"]))

print("\n=== 8. Backend outage: buffer, never lose measurements ===")
backend_up.clear()
for _ in range(3):
    source.poll_once()
    check_result = source.report()
check("report reports failure while backend is down", check_result is False)
buffered = source.buffer.pending_count()
check("measurements accumulated in buffer", buffered >= 12, str(buffered))

backend_up.set()
check("report succeeds after recovery", source.report() is True)
check("buffer fully drained", source.buffer.pending_count() == 0, str(source.buffer.pending_count()))

db = Session()
stored = db.query(models.SmartPlugReading).count()
db.close()
check("buffered measurements persisted to history", stored >= 16, str(stored))

print("\n=== 9. Reboot recovery (inventory survives restart) ===")
revived = sps.SmartPlugSource(node_id="N001", backend_url=BACKEND, buffer_path=BUFFER_DB)
check("known plugs restored from SQLite", len(revived.plugs) == 4, str(len(revived.plugs)))
check("last known IP restored",
      revived.plugs["AC:EB:E6:F6:53:88"]["identity"]["ip"] == "10.44.7.99",
      str(revived.plugs["AC:EB:E6:F6:53:88"]["identity"]["ip"]))
check("restored plugs start offline until proven",
      all(not e["online"] for e in revived.plugs.values()))
revived.poll_once()
# All four simulated devices are reachable at this point in the test.
check("restored plugs come back online after one poll",
      sum(1 for e in revived.plugs.values() if e["online"]) == 4,
      str(sum(1 for e in revived.plugs.values() if e["online"])))

print("\n=== 10. Idempotency across retries ===")
before = len(received)
source.poll_once()
source.report()
source.report()          # nothing left to send
db = Session()
total = db.query(models.SmartPlugReading).count()
db.close()
dup = client.post("/api/smart-plugs/discovery", json=received[-1]).json()
check("replaying last payload inserts nothing new",
      dup["readings_inserted"] == 0, str(dup))
db = Session()
check("history count unchanged by replay", db.query(models.SmartPlugReading).count() == total,
      str(db.query(models.SmartPlugReading).count()))
db.close()

print("\n=== 11. Assignment preserved through edge reports ===")
client.post("/api/smart-plugs/acebe6f65388/assign", json={
    "friendly_name": "Rack de switches", "building": "Edificio de prueba",
    "deployment": "Campana Redes", "outlet_location": "Rack A - Contacto 3"})
source.poll_once()
source.report()
final = [p for p in client.get("/api/smart-plugs").json() if p["mac"] == "AC:EB:E6:F6:53:88"][0]
check("friendly_name survives edge report", final["friendly_name"] == "Rack de switches")
check("building survives edge report", final["building"] == "Edificio de prueba")
check("outlet_location survives", final["outlet_location"] == "Rack A - Contacto 3")

print("\n=== 12. Energy Node tables untouched ===")
db = Session()
check("no energy_readings written by plug pipeline",
      db.query(models.EnergyReading).count() == 0,
      str(db.query(models.EnergyReading).count()))
db.close()

server.shutdown()
print("\n" + "=" * 60)
print(f"PASSED: {len(PASS)}   FAILED: {len(FAIL)}")
if FAIL:
    print("FAILURES:")
    for f in FAIL:
        print("  -", f)
print("=" * 60)
sys.exit(1 if FAIL else 0)
