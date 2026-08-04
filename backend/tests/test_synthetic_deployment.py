"""End-to-end proof that a genuine failure still pages during a live campaign.

The alerting review of 2026-07-29 made monitoring much quieter. The risk of any
such change is that it goes quiet because it stopped looking. This drives the
**whole pipeline** — collect, classify, evaluate, alert, route, render, deliver —
against a node with an operational deployment and a real overload, and asserts a
message reaches a channel.

Runs entirely against a throwaway SQLite database. It never touches production
data and never creates a deployment in the real platform.

    cd <repo>/backend
    venv/bin/python3 tests/test_synthetic_deployment.py
"""

import os
import sys
from datetime import datetime, timedelta

# Paths are derived from this file's location so the suites run from any
# checkout — CI, a contributor's machine, the server — not only from the
# directory they were written in.
_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_REPO = os.path.dirname(_BACKEND)

sys.path.insert(0, _BACKEND)
os.chdir(_BACKEND)

os.environ["MONITORING_TELEGRAM_BOT_TOKEN"] = ""
os.environ["MONITORING_TELEGRAM_CHAT_ID"] = ""
os.environ["MONITORING_TELEGRAM_ENABLED"] = "false"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import models
from app.db.database import Base

TMP_DB = "/tmp/energy-platform-tests/test_synthetic.db"
os.makedirs("/tmp/energy-platform-tests", exist_ok=True)
for suffix in ("", "-wal", "-shm"):
    if os.path.exists(TMP_DB + suffix):
        os.remove(TMP_DB + suffix)

engine = create_engine(f"sqlite:///{TMP_DB}", connect_args={"check_same_thread": False})
TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)

import app.monitoring.storage as storage_module

storage_module.MonitoringSession = TestSession

from app.monitoring import lifecycle
from app.monitoring.alerts import process_findings
from app.monitoring.channels.base import (
    DeliveryResult,
    NotificationChannel,
)
from app.monitoring.config import get_config
from app.monitoring.heartbeat import collect_node_state
from app.monitoring.metrics import collect_metrics
from app.monitoring.models import MONITORING_TABLES
from app.monitoring.notifications import dispatch_pending, notify_alerts
from app.monitoring.rules import RuleContext, evaluate_all
from app.monitoring.severity import Severity

Base.metadata.create_all(bind=engine)
for table in MONITORING_TABLES:
    table.create(bind=engine, checkfirst=True)

from tests.lifecycle_fixtures import seed_lifecycle_tables

seed_lifecycle_tables(engine)

PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    print(
        f"  {'ok  ' if condition else 'FAIL'} {name}"
        + (f" :: {detail}" if not condition and detail else "")
    )


class CapturingChannel(NotificationChannel):
    """Records what would have been sent."""

    name = "telegram"

    def __init__(self):
        self.sent = []

    def is_configured(self):
        return True

    @property
    def recipient(self):
        return "capture"

    def send(self, message):
        self.sent.append(message)
        return DeliveryResult.success()


NOW = datetime.utcnow()

#: A healthy server snapshot. Without it the server rules fire on absent probe
#: data ("API not responding") and drown the electrical path this test is about.
HEALTHY_SERVER = {
    "hostname": "test",
    "cpu": {"percent": 5.0, "iowait": 1.0, "cores": 4},
    "memory": {"percent": 20.0, "swap_present": False, "swap_percent": None},
    "disks": {"/": {"percent": 40.0, "free_gb": 100.0, "total_gb": 200.0}},
    "readonly": {"/": False},
    "load": {"load_1": 0.1, "load_5": 0.1, "load_15": 0.1, "per_core_5": 0.02, "cores": 4},
    "temperature": {"celsius": None, "available": False},
    "uptime": {"uptime_seconds": 100000.0},
    "services": {},
    "failed_units": {"available": True, "failed": [], "count": 0},
    "api": {"ok": True, "status_code": 200, "latency_seconds": 0.05},
    "internet": {"ok": True, "host": "1.1.1.1"},
    "dns": {"ok": True, "name": "example.org"},
    "time_sync": {"available": True, "synchronized": True},
    "reboot": {"required": False},
    "kernel": {"available": True, "oom_events": 0, "panic_events": 0},
    "tailscale": {"available": False, "reason": "not installed"},
    "firewall": {"available": False, "reason": "requires root"},
    "certificates": {"available": False, "reason": "no TLS"},
    "database": {
        "ok": True,
        "db_mb": 1.0,
        "wal_mb": 0.1,
        "query_seconds": 0.001,
        "integrity_ok": True,
    },
}

# ---------------------------------------------------------------- fixtures
db = TestSession()
delegation = models.Delegation(name="Colima", municipality="Colima")
db.add(delegation)
db.flush()
campus = models.Campus(name="Campus Coquimatlan", delegation_id=delegation.id)
db.add(campus)
db.flush()
unit = models.OrganizationalUnit(name="Engineering", campus_id=campus.id)
db.add(unit)
db.flush()
building = models.Building(
    code="ENG", name="Engineering", campus_id=campus.id, organizational_unit_id=unit.id
)
db.add(building)
db.flush()
panel = models.ElectricalPanel(name="Panel A", building_id=building.id)
db.add(panel)
db.flush()

# A commissioned node on a live campaign, with a real panel rating.
node = models.Node(
    code="N900",
    name="Synthetic Node",
    status="online",
    buffer_pending=0,
    samples=0,
    commission_state="commissioned",
)
db.add(node)
db.flush()

deployment = models.Deployment(
    node_id=node.id,
    building_id=building.id,
    electrical_panel_id=panel.id,
    start_date=(NOW - timedelta(days=3)).strftime("%Y-%m-%d"),
    end_date=None,
    status="active",
    # `collect_node_state` resolves the CURRENT deployment by
    # `activated_at IS NOT NULL AND closed_at IS NULL` (migration 010), not by
    # status, so that an alert never names a building the node has already left.
    # Without these the node reads as having no operational deployment and every
    # electrical rule is correctly suppressed — which would make this suite pass
    # vacuously by never exercising the path it exists to guard.
    activated_at=NOW - timedelta(days=3),
    closed_at=None,
    panel_main_breaker_a=250.0,
    nominal_voltage_v=127.0,
    phase_count=3,
)
db.add(deployment)
db.commit()
node_id, deployment_id, building_id = node.id, deployment.id, building.id
db.close()

print("\n=== 1. The node is classified as operational ===")
db = TestSession()
nodes = collect_node_state(db, get_config(), NOW)
lifecycle.annotate(db, nodes, get_config(), NOW)
policy = nodes["N900"]["policy"]
check(
    "deployment is operational -> electrical alerting enabled", policy.electrical, policy.rationale
)
check("measurement freshness enabled", policy.measurement_freshness)
check("heartbeat loss pages during a campaign", policy.heartbeat_pages)
db.close()


def add_reading(db, current, when, **kw):
    fields = dict(
        node_id=node_id,
        building_id=building_id,
        deployment_id=deployment_id,
        timestamp=when,
        voltage=127.0,
        current=current,
    )
    fields.update(kw)
    db.add(models.EnergyReading(**fields))


def run_tick(now):
    """One full monitoring cycle. Returns messages that reached the channel.

    ``notify_alerts`` builds the real channel list internally, and Telegram is
    deliberately unconfigured here, so the capturing channel is substituted for
    the duration of the tick. Everything else — routing, sustain, rendering,
    the outbox — runs exactly as in production.
    """
    channel = CapturingChannel()
    import app.monitoring.notifications as notifications_module

    original_build = notifications_module.build_channels
    notifications_module.build_channels = lambda *a, **k: [channel]
    try:
        return _run_tick_inner(now, channel)
    finally:
        notifications_module.build_channels = original_build


def _run_tick_inner(now, channel):
    with storage_module.session_scope() as session:
        nodes = collect_node_state(session, get_config(), now)
        lifecycle.annotate(session, nodes, get_config(), now)
        metrics = collect_metrics(session, get_config(), now)
        ctx = RuleContext(
            session=session,
            config=get_config(),
            now=now,
            server=HEALTHY_SERVER,
            nodes=nodes,
            metrics=metrics,
        )
        findings = evaluate_all(ctx)
        transitions = process_findings(session, findings, now=now, config=get_config())
        notify_alerts(session, transitions, now=now, config=get_config())
    with storage_module.session_scope() as session:
        dispatch_pending(session, channels=[channel], now=now, config=get_config())
    return channel.sent, findings


print("\n=== 2. Normal load on the same panel is silent ===")
db = TestSession()
for i in range(40):
    add_reading(
        db,
        120.0,
        NOW - timedelta(minutes=60 - i),
        power_kw=40.0,
        power_factor=0.95,
        frequency_hz=60.0,
    )
db.commit()
db.close()

sent, findings = run_tick(NOW)
check("120 A on a 250 A panel sends nothing", len(sent) == 0, str([m.subject for m in sent]))


print("\n=== 3. A genuine sustained overload PAGES ===")
# 300 A against a 250 A main breaker: past the rating, sustained well beyond the
# window. This is the case the whole system exists for.
db = TestSession()
start = NOW
for i in range(70):
    add_reading(
        db,
        300.0,
        start + timedelta(minutes=i),
        power_kw=110.0,
        power_factor=0.95,
        frequency_hz=60.0,
    )
db.commit()
db.close()

sent_first, findings = run_tick(start + timedelta(minutes=1))
overload = [f for f in findings if f.rule_id == "electrical.current"]
check(
    "overload detected as a finding",
    len(overload) == 1,
    str([f.rule_id for f in findings if f.is_problem]),
)
if overload:
    check(
        "threshold came from the panel rating, not statistics",
        "breaker" in (overload[0].expected_value or ""),
        overload[0].expected_value,
    )
    check(
        "300 A past a 250 A breaker is EMERGENCY",
        overload[0].severity is Severity.EMERGENCY,
        overload[0].severity.name,
    )
check(
    "but it does NOT page within the sustain window",
    len(sent_first) == 0,
    str([m.subject for m in sent_first]),
)

# Now let it persist past the sustain requirement.
sent_later, _ = run_tick(start + timedelta(minutes=45))
check("it DOES page once sustained", len(sent_later) >= 1, str([m.subject for m in sent_later]))
overload_msgs = [m for m in sent_later if "current is high" in m.body]
check(
    "the overload itself was delivered",
    len(overload_msgs) == 1,
    str([m.subject for m in sent_later]),
)
if overload_msgs:
    body = overload_msgs[0].body
    check("message names the node", "N900" in body)
    check("message names the building", "Engineering" in body)
    check("message carries the measured value", "300" in body)
    check("message states the threshold basis", "breaker" in body, body[:200])
    check(
        "message is EMERGENCY",
        overload_msgs[0].severity is Severity.EMERGENCY,
        overload_msgs[0].severity.name,
    )


print("\n=== 4. The same panel, campaign completed -> silent ===")
db = TestSession()
dep = db.query(models.Deployment).filter_by(id=deployment_id).first()
dep.status = "completed"
dep.end_date = (NOW - timedelta(days=1)).strftime("%Y-%m-%d")
db.commit()
db.close()
lifecycle.refresh()

db = TestSession()
for i in range(20):
    add_reading(db, 300.0, start + timedelta(minutes=80 + i), power_kw=110.0)
db.commit()
db.close()

sent_after, findings_after = run_tick(start + timedelta(minutes=100))
overload_after = [f for f in findings_after if f.rule_id == "electrical.current" and f.is_problem]
check(
    "no electrical finding once the campaign is completed",
    len(overload_after) == 0,
    str([f.rule_id for f in overload_after]),
)
check(
    "the open overload alert is closed, not left hanging",
    any("RESOLVED" in (m.subject or "") or "RESOLVED" in m.body for m in sent_after)
    or len(sent_after) == 0,
    str([m.subject for m in sent_after]),
)

db = TestSession()
from app.monitoring.models import MonitorAlert

total = db.query(MonitorAlert).count()
check("alert history retained, nothing deleted", total >= 1, str(total))
db.close()


print("\n" + "=" * 60)
print(f"PASSED: {len(PASS)}   FAILED: {len(FAIL)}")
if FAIL:
    for f in FAIL:
        print("  -", f)
print("=" * 60)
sys.exit(1 if FAIL else 0)
