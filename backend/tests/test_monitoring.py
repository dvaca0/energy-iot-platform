"""Monitoring system test suite.

Runs against a throwaway SQLite database with the ``get_db`` dependency
overridden, so production history is never touched. Follows the convention of
the existing suites in this directory: plain Python, no pytest (which is not
installed in this venv), a ``check()`` helper, and a non-zero exit on failure.

Run with::

    cd <repo>/backend
    venv/bin/python3 tests/test_monitoring.py

Coverage is organised around the behaviours that would be expensive to get
wrong in production: deduplication (an alert storm), escalation (a missed
outage), the outbox (a silently discarded alert), and the false-positive guards
(a system nobody trusts because it cries wolf).
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

# Neutralise any ambient credentials so the suite can never send a real
# Telegram message, regardless of what is in .env.
os.environ["MONITORING_TELEGRAM_BOT_TOKEN"] = ""
os.environ["MONITORING_TELEGRAM_CHAT_ID"] = ""
os.environ["MONITORING_TELEGRAM_ENABLED"] = "false"

from app.db import models
from app.db.database import Base, get_db
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.makedirs("/tmp/energy-platform-tests", exist_ok=True)
TMP_DB = "/tmp/energy-platform-tests/test_monitoring.db"
for suffix in ("", "-wal", "-shm"):
    if os.path.exists(TMP_DB + suffix):
        os.remove(TMP_DB + suffix)

test_engine = create_engine(f"sqlite:///{TMP_DB}", connect_args={"check_same_thread": False})
TestSession = sessionmaker(bind=test_engine, autocommit=False, autoflush=False)

# Point the monitoring package's own session factory at the test database
# before anything imports it, so storage writes land here too.
import app.monitoring.storage as storage_module

storage_module.MonitoringSession = TestSession

from app.monitoring import metrics as metrics_module
from app.monitoring.alerts import process_findings
from app.monitoring.channels.base import (
    DeliveryResult,
    NotificationChannel,
    OutboundMessage,
)
from app.monitoring.config import MonitoringConfig, get_config
from app.monitoring.heartbeat import (
    HeartbeatPayload,
    collect_node_state,
    record_heartbeat,
)
from app.monitoring.history import list_alerts, recurrence, statistics
from app.monitoring.lifecycle import (
    MonitoringPolicy,
    classify,
    commission_states,
)
from app.monitoring.models import (
    MONITORING_TABLES,
    AlertEvent,
    MonitorAlert,
    NodeHeartbeat,
    NodeHeartbeatLatest,
    NotificationOutbox,
)
from app.monitoring.notifications import (
    dispatch_pending,
    enqueue,
    humanize_duration,
    in_quiet_hours,
    notify_alerts,
    render_alert,
)
from app.monitoring.rules import (
    Finding,
    RuleContext,
    Subsystem,
    evaluate_all,
    registered_rules,
)

# Policy fixtures matching the platform's reference tables.
FULL = MonitoringPolicy(True, True, True, True, True, "test: full monitoring", heartbeat_pages=True)
HARDWARE_ONLY = MonitoringPolicy(
    False, False, False, True, True, "test: no operational deployment", heartbeat_pages=False
)
MUTED = MonitoringPolicy(False, False, False, False, False, "test: not monitored")
from app.monitoring.severity import Severity
from app.monitoring.status import build_status, render_report

Base.metadata.create_all(bind=test_engine)
for table in MONITORING_TABLES:
    table.create(bind=test_engine, checkfirst=True)

# The platform's lifecycle reference tables are created by SQL migrations,
# not by the ORM metadata, so the throwaway database needs them seeded.
# Monitoring policy is derived entirely from these flags, so testing against
# a database without them would test nothing real.
from tests.lifecycle_fixtures import seed_lifecycle_tables

seed_lifecycle_tables(test_engine)


from app.main import app


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
    if condition:
        PASS.append(name)
        print(f"  ok   {name}")
    else:
        FAIL.append(f"{name} :: {detail}")
        print(f"  FAIL {name} :: {detail}")


def iso(dt):
    return dt.isoformat() + "Z"


CONFIG = get_config()


# ==========================================================================
print("\n=== 1. Seed operational data ===")
# ==========================================================================
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

# Commissioned: in service, monitored, silence is an alarm. Without this the
# ORM default of 'registered' applies, which is an unmonitored state — every
# alert would then be closed by the lifecycle rather than by its own condition.
node_a = models.Node(code="N001", name="Energy Node 001", commission_state="commissioned")
node_b = models.Node(code="N002", name="Energy Node 002", commission_state="commissioned")
db.add_all([node_a, node_b])
db.flush()

deployment = models.Deployment(
    node_id=node_a.id,
    building_id=building.id,
    electrical_panel_id=panel.id,
    start_date="2026-07-01",
    end_date="2026-08-01",
    status="active",
)
db.add(deployment)
db.commit()
node_a_id, node_b_id, deployment_id, building_id = (
    node_a.id,
    node_b.id,
    deployment.id,
    building.id,
)
db.close()
check("operational fixtures created", node_a_id and node_b_id and deployment_id)


# ==========================================================================
print("\n=== 2. Monitoring tables are additive ===")
# ==========================================================================
from sqlalchemy import inspect as sa_inspect

tables = set(sa_inspect(test_engine).get_table_names())
for name in (
    "monitor_node_heartbeats",
    "monitor_node_heartbeat_latest",
    "monitor_server_heartbeats",
    "monitor_alerts",
    "monitor_alert_events",
    "monitor_notification_outbox",
):
    check(f"table {name} exists", name in tables)
for name in ("energy_readings", "nodes", "smart_plugs", "deployments"):
    check(f"operational table {name} untouched", name in tables)


# ==========================================================================
print("\n=== 3. Heartbeat ingestion ===")
# ==========================================================================
now = datetime.utcnow()
db = TestSession()
beat = record_heartbeat(
    db,
    HeartbeatPayload(
        node_id="N001",
        timestamp=iso(now),
        hostname="pi-eng-01",
        software_version="1.2.0",
        cpu_percent=17.5,
        cpu_temperature_c=52.3,
        memory_percent=41.0,
        disk_percent=63.0,
        uptime_seconds=86400,
        buffered_readings=12,
        collector_status="active",
        collector_pid=1234,
        undervoltage=False,
        ads_ok=True,
        shelly_reachable=3,
        shelly_total=4,
        latency_ms=45.0,
    ),
    source_ip="148.213.2.245",
    now=now,
)
db.commit()
check("heartbeat stored", beat.id is not None)
check("node resolved to id", beat.node_id == node_a_id)
check("telemetry persisted", beat.cpu_temperature_c == 52.3)
check("raw payload retained", "collector_pid" in (beat.raw_payload or ""))
check("source ip recorded", beat.source_ip == "148.213.2.245")

latest = db.query(NodeHeartbeatLatest).filter_by(node_code="N001").first()
check("latest row created", latest is not None)
check("marked online", latest.online is True)
check("ever_seen set", latest.ever_seen is True)
check("missed reset to zero", latest.missed_beats == 0)
db.close()


print("\n--- 3b. Unknown node codes are recorded, not dropped ---")
db = TestSession()
record_heartbeat(db, HeartbeatPayload(node_id="GHOST-9"), now=now)
db.commit()
ghost = db.query(NodeHeartbeat).filter_by(node_code="GHOST-9").first()
check("unknown node heartbeat stored", ghost is not None)
check("unknown node has no node_id", ghost.node_id is None)
db.close()


print("\n--- 3c. Partial payloads are accepted (rollout safety) ---")
db = TestSession()
minimal = record_heartbeat(db, HeartbeatPayload(node_id="N002"), now=now)
db.commit()
check("minimal payload accepted", minimal.id is not None)
check("absent telemetry stays null", minimal.cpu_percent is None)
db.close()


print("\n--- 3d. Clock drift is computed against the server clock ---")
db = TestSession()
skewed = record_heartbeat(
    db,
    HeartbeatPayload(node_id="N001", timestamp=iso(now + timedelta(seconds=600))),
    now=now,
)
db.commit()
check(
    "drift detected",
    skewed.clock_drift_seconds is not None and abs(skewed.clock_drift_seconds - 600) < 2,
    str(skewed.clock_drift_seconds),
)
db.close()


print("\n--- 3e. HTTP heartbeat endpoint ---")
r = client.post(
    "/api/monitoring/heartbeat",
    json={"node_id": "N001", "cpu_percent": 22.0, "collector_status": "active"},
)
check("endpoint accepts heartbeat", r.status_code == 200, r.text)
check("endpoint reports registration", r.json().get("registered") is True, r.text)
check(
    "endpoint returns cadence",
    r.json().get("next_interval_seconds") == CONFIG.heartbeat.interval_seconds,
    r.text,
)
r = client.post("/api/monitoring/heartbeat", json={"node_id": "NOT-A-NODE"})
check("unregistered node still accepted", r.status_code == 200, r.text)
check("but flagged unregistered", r.json().get("registered") is False, r.text)


# ==========================================================================
print("\n=== 4. Missed-beat accounting and escalation ladder ===")
# ==========================================================================
from app.monitoring.heartbeat import _missed_beats, _severity_for_misses

check("on time -> 0 missed", _missed_beats(30, CONFIG) == 0)
check("within grace -> 0 missed", _missed_beats(85, CONFIG) == 0)
check("90s -> 1 missed", _missed_beats(95, CONFIG) == 1)
check("2 missed at ~120s", _missed_beats(125, CONFIG) == 2)
check("5 missed at ~300s", _missed_beats(305, CONFIG) == 5)
check("10 missed at ~600s", _missed_beats(605, CONFIG) == 10)

check("2 missed -> WARNING", _severity_for_misses(2, CONFIG) is Severity.WARNING)
check("5 missed -> ERROR", _severity_for_misses(5, CONFIG) is Severity.ERROR)
check("10 missed -> CRITICAL", _severity_for_misses(10, CONFIG) is Severity.CRITICAL)
check("1 missed -> OK", _severity_for_misses(1, CONFIG) is Severity.OK)
check("30 missed -> EMERGENCY", _severity_for_misses(30, CONFIG) is Severity.EMERGENCY)


print("\n--- 4b. Miss state survives a restart (derived, not counted) ---")
db = TestSession()
row = db.query(NodeHeartbeatLatest).filter_by(node_code="N001").first()
row.received_at = now - timedelta(seconds=400)
db.commit()
state = collect_node_state(db, CONFIG, now)
db.commit()
check(
    "missed derived from elapsed time",
    state["N001"]["missed_beats"] == 6,
    str(state["N001"]["missed_beats"]),
)
check("offline_since recorded", state["N001"]["offline_since"] is not None)
# Recomputing from scratch must give the same answer.
state2 = collect_node_state(db, CONFIG, now)
db.commit()
check("recomputation is stable", state2["N001"]["missed_beats"] == 6)
db.close()


# ==========================================================================
print("\n=== 5. Severity ordering and presentation ===")
# ==========================================================================
check(
    "ordering",
    Severity.INFO < Severity.WARNING < Severity.ERROR < Severity.CRITICAL < Severity.EMERGENCY,
)
check("parse from string", Severity.parse("critical") is Severity.CRITICAL)
check("parse garbage falls back", Severity.parse("nonsense") is Severity.INFO)
check("parse None falls back", Severity.parse(None) is Severity.INFO)
check("emoji distinct", len({s.emoji for s in Severity}) == len(list(Severity)))
check("CRITICAL breaks quiet hours", Severity.CRITICAL.breaks_quiet_hours)
check("WARNING does not break quiet hours", not Severity.WARNING.breaks_quiet_hours)
check("INFO is not actionable", not Severity.INFO.is_actionable)


# ==========================================================================
print("\n=== 6. Alert lifecycle: create, dedupe, escalate, resolve ===")


# ==========================================================================
def make_finding(severity=Severity.WARNING, target="N001", value="1"):
    return Finding(
        rule_id="test.rule",
        subsystem=Subsystem.NODE,
        severity=severity,
        title="Test problem",
        target=target,
        summary="A synthetic problem",
        metric="test_metric",
        current_value=value,
        expected_value="0",
        node_code="N001",
        building="Engineering",
        suggested_causes=["cause one"],
        suggested_commands=["systemctl status test"],
        suggested_actions=["do the thing"],
        # 0 = notify immediately. These tests cover dedupe, escalation and
        # resolution; the sustain window has its own section (7c).
        sustain_seconds=0,
    )


t0 = datetime.utcnow()
db = TestSession()
transitions = process_findings(db, [make_finding()], now=t0, config=CONFIG)
db.commit()
check("new problem creates one transition", len(transitions) == 1)
check("transition is NEW", transitions[0].status == "NEW")
alert_id = transitions[0].alert.alert_id
check("alert id generated", alert_id.startswith("ALT-"))
check("one alert row", db.query(MonitorAlert).filter_by(rule_id="test.rule").count() == 1)

print("\n--- 6b. Repeat occurrence must NOT notify (anti-flood) ---")
transitions = process_findings(
    db, [make_finding(value="2")], now=t0 + timedelta(seconds=30), config=CONFIG
)
db.commit()
check("ongoing produces no transition", len(transitions) == 0)
alert = db.query(MonitorAlert).filter_by(alert_id=alert_id).first()
check("occurrence counter advanced", alert.occurrence_count == 2)
check("current value refreshed", alert.current_value == "2")
check(
    "still exactly one alert row",
    db.query(MonitorAlert).filter_by(rule_id="test.rule").count() == 1,
)

print("\n--- 6c. Many repeats still produce no notifications ---")
for i in range(20):
    extra = process_findings(
        db, [make_finding()], now=t0 + timedelta(seconds=31 + i), config=CONFIG
    )
    db.commit()
    if extra:
        break
check("20 further evaluations produced no notifications", not extra, str(len(extra)))

print("\n--- 6d. Duration escalation ---")
transitions = process_findings(db, [make_finding()], now=t0 + timedelta(minutes=6), config=CONFIG)
db.commit()
check("escalated after 6 minutes", len(transitions) == 1 and transitions[0].status == "ESCALATED")
check("severity now ERROR", transitions[0].severity is Severity.ERROR, str(transitions[0].severity))

transitions = process_findings(db, [make_finding()], now=t0 + timedelta(minutes=16), config=CONFIG)
db.commit()
check("escalated again after 16 minutes", len(transitions) == 1)
check("severity now CRITICAL", transitions[0].severity is Severity.CRITICAL)

transitions = process_findings(db, [make_finding()], now=t0 + timedelta(minutes=61), config=CONFIG)
db.commit()
check("escalated to EMERGENCY after 61 minutes", transitions[0].severity is Severity.EMERGENCY)

alert = db.query(MonitorAlert).filter_by(alert_id=alert_id).first()
check("peak severity retained", alert.peak_severity == "EMERGENCY")
check("initial severity retained", alert.initial_severity == "WARNING")

print("\n--- 6e. Resolution ---")
transitions = process_findings(db, [], now=t0 + timedelta(minutes=90), config=CONFIG)
db.commit()
check("absent finding resolves the alert", len(transitions) == 1)
check("transition is RESOLVED", transitions[0].status == "RESOLVED")
alert = db.query(MonitorAlert).filter_by(alert_id=alert_id).first()
check("resolved_at set", alert.resolved_at is not None)
check("duration computed", alert.duration_seconds and alert.duration_seconds > 5000)
check("status resolved", alert.status == "resolved")

print("\n--- 6f. A new occurrence opens a fresh alert ---")
transitions = process_findings(db, [make_finding()], now=t0 + timedelta(minutes=100), config=CONFIG)
db.commit()
check("recurrence opens a new alert", len(transitions) == 1 and transitions[0].status == "NEW")
check("new alert id differs", transitions[0].alert.alert_id != alert_id)
check("history retains both", db.query(MonitorAlert).filter_by(rule_id="test.rule").count() == 2)

print("\n--- 6g. Distinct targets do not collide ---")
transitions = process_findings(
    db,
    [make_finding(target="N001"), make_finding(target="N002")],
    now=t0 + timedelta(minutes=101),
    config=CONFIG,
)
db.commit()
check("second target opens its own alert", len(transitions) == 1, str(len(transitions)))
check("three alert rows total", db.query(MonitorAlert).filter_by(rule_id="test.rule").count() == 3)

print("\n--- 6h. Audit trail ---")
events = db.query(AlertEvent).all()
kinds = {event.event_type for event in events}
check("created events recorded", "created" in kinds)
check("escalated events recorded", "escalated" in kinds)
check("resolved events recorded", "resolved" in kinds)
db.close()


# ==========================================================================
print("\n=== 7. De-escalation is recorded but not announced ===")
# ==========================================================================
db = TestSession()
db.query(AlertEvent).delete()
db.query(MonitorAlert).delete()
db.commit()

t1 = datetime.utcnow()
process_findings(
    db, [make_finding(severity=Severity.CRITICAL, target="DEESC")], now=t1, config=CONFIG
)
db.commit()
# WARNING, not INFO: an INFO finding is not actionable, so it is not a problem
# at all and correctly *resolves* the alert rather than de-escalating it.
transitions = process_findings(
    db,
    [make_finding(severity=Severity.WARNING, target="DEESC")],
    now=t1 + timedelta(seconds=20),
    config=CONFIG,
)
db.commit()
check("improvement produces no notification", len(transitions) == 0, str(len(transitions)))
row = db.query(MonitorAlert).filter_by(fingerprint=make_finding(target="DEESC").fingerprint).first()
check(
    "de-escalation event recorded",
    db.query(AlertEvent).filter_by(alert_id=row.id, event_type="de-escalated").count() == 1,
)
check("peak severity preserved", row.peak_severity == "CRITICAL")
db.close()


# ==========================================================================
print("\n=== 7b. max_severity caps escalation for persistent states ===")
# ==========================================================================
db = TestSession()
db.query(AlertEvent).delete()
db.query(MonitorAlert).delete()
db.commit()

capped = make_finding(target="CAPPED")
capped.max_severity = Severity.WARNING
t2 = datetime.utcnow()
process_findings(db, [capped], now=t2, config=CONFIG)
db.commit()
# Two hours open: the normal ladder would have reached EMERGENCY by now, and
# the reminder timer would have fired twice.
transitions = process_findings(db, [capped], now=t2 + timedelta(minutes=120), config=CONFIG)
db.commit()
check(
    "capped alert does not escalate",
    len(transitions) == 0,
    str([(t.status, t.severity) for t in transitions]),
)
row = db.query(MonitorAlert).filter_by(fingerprint=capped.fingerprint).first()
check("capped alert stays at WARNING", row.severity == "WARNING", row.severity)
check(
    "capped alert does not spam reminders", row.notification_count <= 1, str(row.notification_count)
)

# An uncapped finding with the same age must still escalate, proving the cap is
# what suppressed it rather than something else.
uncapped = make_finding(target="UNCAPPED")
process_findings(db, [uncapped, capped], now=t2, config=CONFIG)
db.commit()
transitions = process_findings(
    db, [uncapped, capped], now=t2 + timedelta(minutes=120), config=CONFIG
)
db.commit()
escalations = [t for t in transitions if t.status == "ESCALATED"]
check(
    "uncapped finding still escalates to EMERGENCY",
    len(escalations) == 1 and escalations[0].severity is Severity.EMERGENCY,
    str([(t.status, t.severity) for t in transitions]),
)
db.close()


# ==========================================================================
print("\n=== 8. Notification outbox durability and retry ===")


# ==========================================================================
class FlakyChannel(NotificationChannel):
    """Fails a set number of times, then succeeds."""

    name = "telegram"  # reuse the registered name so outbox rows match

    def __init__(self, failures, permanent=False):
        self.remaining = failures
        self.permanent = permanent
        self.sent = []

    def is_configured(self):
        return True

    @property
    def recipient(self):
        return "test-chat"

    def send(self, message):
        if self.remaining > 0:
            self.remaining -= 1
            return (
                DeliveryResult.permanent("bad credentials")
                if self.permanent
                else DeliveryResult.retry("network glitch")
            )
        self.sent.append(message)
        return DeliveryResult.success()


class ExplodingChannel(NotificationChannel):
    name = "telegram"

    def is_configured(self):
        return True

    def send(self, message):
        raise RuntimeError("channel exploded")


db = TestSession()
db.query(NotificationOutbox).delete()
db.commit()

msg = OutboundMessage(body="hello", severity=Severity.WARNING, subject="s", kind="alert")
flaky = FlakyChannel(failures=2)
rows = enqueue(db, msg, channels=[flaky], now=datetime.utcnow(), config=CONFIG)
db.commit()
check("message queued before any send", len(rows) == 1)
check("queued as pending", rows[0].status == "pending")

t = datetime.utcnow()
result = dispatch_pending(db, channels=[flaky], now=t, config=CONFIG)
db.commit()
check("first attempt retried, not lost", result["retried"] == 1, str(result))
row = db.query(NotificationOutbox).first()
check("still pending after failure", row.status == "pending")
check("attempt counted", row.attempts == 1)
check("backoff scheduled", row.next_attempt_at is not None and row.next_attempt_at > t)
check("error recorded", "network glitch" in (row.last_error or ""))

result = dispatch_pending(db, channels=[flaky], now=t + timedelta(seconds=60), config=CONFIG)
db.commit()
check("second attempt also retried", result["retried"] == 1, str(result))

result = dispatch_pending(db, channels=[flaky], now=t + timedelta(seconds=200), config=CONFIG)
db.commit()
check("third attempt delivered", result["delivered"] == 1, str(result))
row = db.query(NotificationOutbox).first()
check("marked delivered", row.status == "delivered")
check("delivery timestamp set", row.delivered_at is not None)
check("error cleared on success", row.last_error is None)
check("channel actually received it", len(flaky.sent) == 1)

print("\n--- 8b. Not-yet-due rows are left alone ---")
db.query(NotificationOutbox).delete()
db.commit()
enqueue(db, msg, channels=[FlakyChannel(0)], now=t, config=CONFIG)
db.commit()
row = db.query(NotificationOutbox).first()
row.next_attempt_at = t + timedelta(hours=1)
db.commit()
result = dispatch_pending(db, channels=[FlakyChannel(0)], now=t, config=CONFIG)
db.commit()
check("future retry not attempted early", result["delivered"] == 0, str(result))

print("\n--- 8c. Permanent failure is not retried forever ---")
db.query(NotificationOutbox).delete()
db.commit()
dead = FlakyChannel(failures=99, permanent=True)
enqueue(db, msg, channels=[dead], now=t, config=CONFIG)
db.commit()
result = dispatch_pending(db, channels=[dead], now=t, config=CONFIG)
db.commit()
row = db.query(NotificationOutbox).first()
check("permanent failure marked failed", row.status == "failed", row.status)
check("failure reason retained", "bad credentials" in (row.last_error or ""))
check("row retained, not deleted", db.query(NotificationOutbox).count() == 1)

print("\n--- 8d. A channel that raises is contained ---")
db.query(NotificationOutbox).delete()
db.commit()
enqueue(db, msg, channels=[ExplodingChannel()], now=t, config=CONFIG)
db.commit()
result = dispatch_pending(db, channels=[ExplodingChannel()], now=t, config=CONFIG)
db.commit()
row = db.query(NotificationOutbox).first()
check("exception treated as retryable", row.status == "pending", row.status)
check("exception detail captured", "exploded" in (row.last_error or ""))

print("\n--- 8e. Unconfigured channel does not burn attempts ---")


class Unconfigured(NotificationChannel):
    name = "telegram"

    def is_configured(self):
        return False

    def send(self, message):
        raise AssertionError("must not be called")


db.query(NotificationOutbox).delete()
db.commit()
enqueue(db, msg, channels=[FlakyChannel(0)], now=t, config=CONFIG)
db.commit()
dispatch_pending(db, channels=[Unconfigured()], now=t, config=CONFIG)
db.commit()
row = db.query(NotificationOutbox).first()
check("stays pending when channel unconfigured", row.status == "pending")
check("no attempt consumed", row.attempts == 0, str(row.attempts))

print("\n--- 8f. Unconfigured channels are skipped at enqueue ---")
db.query(NotificationOutbox).delete()
db.commit()
rows = enqueue(db, msg, channels=[Unconfigured()], now=t, config=CONFIG)
db.commit()
check("nothing queued for unconfigured channel", len(rows) == 0)
db.close()


# ==========================================================================
print("\n=== 9. Rate limiting and quiet hours ===")
# ==========================================================================
db = TestSession()
db.query(NotificationOutbox).delete()
db.commit()

limited = MonitoringConfig()
limited.notifications.max_messages_per_hour = 2
ok_channel = FlakyChannel(0)

for i in range(4):
    enqueue(db, msg, channels=[ok_channel], now=t, config=limited)
db.commit()
queued = db.query(NotificationOutbox).filter_by(status="pending").count()
suppressed = db.query(NotificationOutbox).filter_by(status="failed").count()
check("rate limit caps queued messages", queued == 2, str(queued))
check("suppressed messages are recorded, not dropped", suppressed == 2, str(suppressed))
row = db.query(NotificationOutbox).filter_by(status="failed").first()
check("suppression reason recorded", "rate limit" in (row.last_error or ""))

print("\n--- 9b. EMERGENCY bypasses the rate limit ---")
emergency = OutboundMessage(body="!", severity=Severity.EMERGENCY, kind="alert")
rows = enqueue(db, emergency, channels=[ok_channel], now=t, config=limited)
db.commit()
check("emergency queued despite the cap", rows and rows[0].status == "pending")

print("\n--- 9c. Quiet hours ---")
quiet = MonitoringConfig()
quiet.timezone = "UTC"
quiet.quiet_hours.enabled = True
quiet.quiet_hours.start_hour = 22
quiet.quiet_hours.end_hour = 7
check("inside wrapped window (23:00)", in_quiet_hours(datetime(2026, 7, 26, 23, 0), quiet))
check("inside wrapped window (03:00)", in_quiet_hours(datetime(2026, 7, 26, 3, 0), quiet))
check("outside window (12:00)", not in_quiet_hours(datetime(2026, 7, 26, 12, 0), quiet))
check("boundary open (22:00)", in_quiet_hours(datetime(2026, 7, 26, 22, 0), quiet))
check("boundary closed (07:00)", not in_quiet_hours(datetime(2026, 7, 26, 7, 0), quiet))
quiet.quiet_hours.enabled = False
check("disabled means never quiet", not in_quiet_hours(datetime(2026, 7, 26, 23, 0), quiet))

print("\n--- 9d. Critical alerts survive quiet hours ---")
quiet.quiet_hours.enabled = True
db.query(NotificationOutbox).delete()
db.commit()
night = datetime(2026, 7, 26, 23, 30)
enqueue(
    db,
    OutboundMessage(body="w", severity=Severity.WARNING),
    channels=[ok_channel],
    now=night,
    config=quiet,
)
enqueue(
    db,
    OutboundMessage(body="c", severity=Severity.CRITICAL),
    channels=[ok_channel],
    now=night,
    config=quiet,
)
db.commit()
check(
    "warning suppressed at night",
    db.query(NotificationOutbox).filter_by(status="failed").count() == 1,
)
check(
    "critical delivered at night",
    db.query(NotificationOutbox).filter_by(status="pending").count() == 1,
)
db.close()


# ==========================================================================
print("\n=== 10. Rendering ===")
# ==========================================================================
db = TestSession()
db.query(MonitorAlert).delete()
db.commit()
transitions = process_findings(
    db,
    [make_finding(severity=Severity.CRITICAL, target="RENDER")],
    now=datetime.utcnow(),
    config=CONFIG,
)
db.commit()
message = render_alert(transitions[0], CONFIG)
body = message.body
check("severity headline present", "CRITICAL" in body)
check("emoji present", "🚨" in body)
check("title present", "Test problem" in body)
check("location present", "Engineering" in body)
check("current value present", "test_metric" in body)
check("causes present", "cause one" in body)
check("commands present", "systemctl status test" in body)
check("actions present", "do the thing" in body)
check("alert id in footer", transitions[0].alert.alert_id in body)
check("html rendering provided", message.html_body is not None)

print("\n--- 10b. HTML escaping ---")
from app.monitoring.channels.telegram import escape

check("ampersand escaped", escape("a & b") == "a &amp; b")
check("angle brackets escaped", escape("<script>") == "&lt;script&gt;")
check("underscores untouched", escape("energy_platform_backend") == "energy_platform_backend")
check("asterisks untouched", escape("a*b") == "a*b")

print("\n--- 10c. Long messages split rather than truncate ---")
channel = FlakyChannel(0)
long_body = "\n".join(f"line {i} with some text" for i in range(500))
parts = channel.split_body(long_body, 1000)
check("split into multiple parts", len(parts) > 1)
check("no part exceeds the limit", all(len(p) <= 1000 for p in parts))
check("nothing lost in the split", "".join(parts) == long_body)
single_long_line = "x" * 3000
parts = channel.split_body(single_long_line, 1000)
check("over-long single line hard-cut", all(len(p) <= 1000 for p in parts))
check("hard-cut loses nothing", "".join(parts) == single_long_line)

print("\n--- 10d. Duration humanisation ---")
check("seconds", humanize_duration(45) == "45s")
check("minutes", humanize_duration(120) == "2m")
check("hours", humanize_duration(7200) == "2h")
check("days", humanize_duration(90000) == "1d 1h")
check("none", humanize_duration(None) == "unknown")
db.close()


# ==========================================================================
print("\n=== 11. Rule engine ===")
# ==========================================================================
check("rules registered", len(registered_rules()) >= 35, str(len(registered_rules())))

print("\n--- 11b. A failing rule is isolated and reported ---")
from app.monitoring.rules import rule as rule_decorator


@rule_decorator("test.explodes", Subsystem.MONITORING, "Deliberately broken rule")
def _broken(ctx):
    raise ValueError("boom")


db = TestSession()
ctx = RuleContext(session=db, config=CONFIG, now=datetime.utcnow(), server={}, nodes={}, metrics={})
findings = evaluate_all(ctx)
db.close()
failure = [f for f in findings if f.rule_id == "monitoring.rule_failed"]
check("broken rule produced a finding", len(failure) == 1, str(len(failure)))
check("failure is actionable", failure[0].severity is Severity.ERROR)
check("failure names the rule", "test.explodes" in failure[0].title)
check("traceback captured", "boom" in str(failure[0].context.get("traceback", "")))
check("other rules still ran", len(findings) > 1)

# Remove the deliberately broken rule so it cannot leak into other assertions.
registered_rules().pop("test.explodes", None)
from app.monitoring import rules as rules_module

rules_module._REGISTRY.pop("test.explodes", None)

print("\n--- 11c. Fingerprints ---")
f1, f2 = make_finding(target="A"), make_finding(target="B")
check("different targets differ", f1.fingerprint != f2.fingerprint)
check("same target is stable", make_finding(target="A").fingerprint == f1.fingerprint)
check("fingerprint carries the rule id", f1.fingerprint.startswith("test.rule:"))

print("\n--- 11d. Unavailable findings are not alerts ---")
from app.monitoring.rules import unavailable

gap = unavailable("x.y", Subsystem.SERVER, "Thing", "no source")
check("unavailable is not a problem", not gap.is_problem)
check("unavailable carries its reason", gap.unavailable_reason == "no source")

print("\n--- 11e. Threshold helper ---")
ctx = RuleContext(session=None, config=CONFIG, now=datetime.utcnow())
check("below thresholds -> OK", ctx.threshold_severity(10, 80, 90) is Severity.OK)
check("above warning -> WARNING", ctx.threshold_severity(85, 80, 90) is Severity.WARNING)
check("above critical -> CRITICAL", ctx.threshold_severity(95, 80, 90) is Severity.CRITICAL)
check("None -> OK", ctx.threshold_severity(None, 80, 90) is Severity.OK)
check(
    "inverted below critical -> CRITICAL",
    ctx.threshold_severity(0.5, 0.9, 0.7, inverted=True) is Severity.CRITICAL,
)
check(
    "inverted below warning -> WARNING",
    ctx.threshold_severity(0.85, 0.9, 0.7, inverted=True) is Severity.WARNING,
)
check(
    "inverted healthy -> OK", ctx.threshold_severity(0.98, 0.9, 0.7, inverted=True) is Severity.OK
)


# ==========================================================================
print("\n=== 12. Electrical rules and their false-positive guards ===")


# ==========================================================================
def electrical_ctx(db, reading, policy=None, baseline=None, stddev=None):
    """Context for an electrical rule, with the node lifecycle annotated.

    Electrical rules are gated on lifecycle, so a context without it is
    correctly ignored — the tests must state which state they are exercising.
    """
    state = {
        "code": "N001",
        "node_id": node_a_id,
        "policy": policy or FULL,
        "deployment": None,
    }
    return RuleContext(
        session=db,
        config=CONFIG,
        now=datetime.utcnow(),
        server={},
        nodes={"N001": state},
        metrics={
            "latest_readings": {node_a_id: reading},
            "power_baseline": {node_a_id: baseline} if baseline else {},
            "power_stddev": {node_a_id: stddev} if stddev else {},
            "current_baseline": {node_a_id: {"threshold": 296.0, "source": "test"}},
        },
    )


db = TestSession()
db.query(models.EnergyReading).delete()
db.commit()


def add_reading(**kwargs):
    fields = dict(
        node_id=node_a_id,
        building_id=building_id,
        deployment_id=deployment_id,
        timestamp=datetime.utcnow(),
    )
    fields.update(kwargs)
    reading = models.EnergyReading(**fields)
    db.add(reading)
    db.commit()
    db.refresh(reading)
    return reading


print("\n--- 12a. Noise-floor currents must NOT report imbalance ---")
noise = add_reading(
    voltage=127.7,
    current=0.00006,
    phase_a_voltage=127.7,
    phase_b_voltage=129.8,
    phase_c_voltage=128.8,
    phase_a_current=1.94e-05,
    phase_b_current=2.38e-05,
    phase_c_current=1.09e-05,
)
findings = metrics_module.check_phases(electrical_ctx(db, noise))
imbalance = [f for f in findings if "imbalance" in f.rule_id]
check(
    "no imbalance alert at the noise floor",
    len(imbalance) == 0,
    str([f.rule_id for f in imbalance]),
)

print("\n--- 12b. Genuine imbalance under load IS reported ---")
loaded = add_reading(
    voltage=128.3,
    current=93.1,
    phase_a_voltage=127.4,
    phase_b_voltage=128.8,
    phase_c_voltage=128.7,
    phase_a_current=36.59,
    phase_b_current=28.82,
    phase_c_current=27.70,
)
findings = metrics_module.check_phases(electrical_ctx(db, loaded))
imbalance = [f for f in findings if f.rule_id == "electrical.current_imbalance"]
check("real imbalance detected", len(imbalance) == 1, str([f.rule_id for f in findings]))
check("imbalance severity is WARNING", imbalance[0].severity is Severity.WARNING)

print("\n--- 12c. Missing phase ---")
missing = add_reading(
    voltage=85.0,
    phase_a_voltage=127.4,
    phase_b_voltage=128.8,
    phase_c_voltage=2.0,
    phase_a_current=10.0,
    phase_b_current=10.0,
    phase_c_current=0.0,
)
findings = metrics_module.check_phases(electrical_ctx(db, missing))
phase_loss = [f for f in findings if f.rule_id == "electrical.missing_phase"]
check("missing phase detected", len(phase_loss) == 1)
check("missing phase is CRITICAL", phase_loss[0].severity is Severity.CRITICAL)

print("\n--- 12d. Impossible values are sensor faults, not electrical events ---")
absurd = add_reading(voltage=9999.0, current=5000.0, power_factor=4.2)
ctx = electrical_ctx(db, absurd)
implausible = list(metrics_module.check_implausible(ctx))
check("impossible reading flagged", len(implausible) == 1)
check("reported as a measurement fault", "impossible" in implausible[0].title.lower())
voltage_findings = list(metrics_module.check_voltage(ctx))
current_findings = list(metrics_module.check_current(ctx))
check("voltage rule suppressed for that node", len(voltage_findings) == 0)
check("current rule suppressed for that node", len(current_findings) == 0)

print("\n--- 12e. Negative current is impossible, not 'low' ---")
negative = add_reading(voltage=127.0, current=-5.0)
ctx = electrical_ctx(db, negative)
check("negative current flagged", len(list(metrics_module.check_implausible(ctx))) == 1)

print("\n--- 12f. Reverse power flow ---")
reverse = add_reading(voltage=127.0, current=10.0, power_kw=-2.5)
findings = list(metrics_module.check_reverse_energy(electrical_ctx(db, reverse)))
check("reverse flow detected", len(findings) == 1)
check(
    "CT reversal suggested",
    any("backwards" in c or "arrow" in c for c in findings[0].suggested_causes),
)

# Regression: an idle meter reports values like -1e-9 kW. A bare sign test
# reported that as "reverse power flow: -0.00 kW" on a healthy idle panel.
noise_negative = add_reading(voltage=127.0, current=0.0, power_kw=-1e-9)
findings = list(metrics_module.check_reverse_energy(electrical_ctx(db, noise_negative)))
check(
    "negative noise is not reverse flow",
    len(findings) == 0,
    str([f.current_value for f in findings]),
)
just_under = add_reading(voltage=127.0, current=0.0, power_kw=-0.01)
check(
    "small negative within deadband ignored",
    len(list(metrics_module.check_reverse_energy(electrical_ctx(db, just_under)))) == 0,
)

print("\n--- 12g. Power factor ignored at negligible load ---")
idle_pf = add_reading(voltage=127.0, current=0.01, power_kw=0.001, power_factor=0.10)
findings = list(metrics_module.check_power_factor(electrical_ctx(db, idle_pf)))
check("no PF alert at negligible load", len(findings) == 0, str([f.rule_id for f in findings]))

loaded_pf = add_reading(voltage=127.0, current=50.0, power_kw=15.0, power_factor=0.55)
findings = list(metrics_module.check_power_factor(electrical_ctx(db, loaded_pf)))
check("PF alert under real load", len(findings) == 1)
check("severity CRITICAL below 0.70", findings[0].severity is Severity.CRITICAL)

print("\n--- 12h. Frequency of exactly zero is not a grid excursion ---")
dead_freq = add_reading(voltage=127.0, frequency_hz=0.0)
findings = list(metrics_module.check_frequency(electrical_ctx(db, dead_freq)))
check("zero frequency ignored", len(findings) == 0)

bad_freq = add_reading(voltage=127.0, frequency_hz=57.5)
findings = list(metrics_module.check_frequency(electrical_ctx(db, bad_freq)))
check("real frequency excursion detected", len(findings) == 1)

print("\n--- 12h2. Current uses a learned envelope, not a flat constant ---")
normal_high = add_reading(voltage=127.0, current=224.0)
check(
    "224 A is normal for this panel and stays silent",
    len(list(metrics_module.check_current(electrical_ctx(db, normal_high)))) == 0,
)
real_overload = add_reading(voltage=127.0, current=320.0)
check(
    "320 A exceeds the learned envelope and fires",
    len(list(metrics_module.check_current(electrical_ctx(db, real_overload)))) == 1,
)

print("\n--- 12i. Voltage band ---")
low = add_reading(voltage=100.0, current=10.0)
findings = list(metrics_module.check_voltage(electrical_ctx(db, low)))
check(
    "low voltage detected", len(findings) == 1 and findings[0].rule_id == "electrical.voltage_low"
)
high = add_reading(voltage=155.0, current=10.0)
findings = list(metrics_module.check_voltage(electrical_ctx(db, high)))
check(
    "high voltage detected", len(findings) == 1 and findings[0].rule_id == "electrical.voltage_high"
)
nominal = add_reading(voltage=127.0, current=10.0)
check(
    "nominal voltage is quiet",
    len(list(metrics_module.check_voltage(electrical_ctx(db, nominal)))) == 0,
)

print("\n--- 12j. No consumption while deployed ---")
detached = add_reading(
    voltage=127.5,
    current=0.00004,
    phase_a_current=0.00002,
    phase_b_current=0.00001,
    phase_c_current=0.00001,
)
findings = list(metrics_module.check_no_consumption(electrical_ctx(db, detached)))
check(
    "detached CT detected on an active deployment",
    len(findings) == 1,
    str([f.rule_id for f in findings]),
)
check(
    "CT clamp suggested as the cause",
    any("clamp" in cause.lower() for cause in findings[0].suggested_causes),
)
db.close()


# ==========================================================================
print("\n=== 13. Node rules ===")
# ==========================================================================
db = TestSession()
now = datetime.utcnow()


def node_ctx(policy=None, **beat_kwargs):
    beat = NodeHeartbeat(node_code="N001", received_at=now, **beat_kwargs)
    state = {
        "N001": {
            "code": "N001",
            "node_id": node_a_id,
            "heartbeat": beat,
            "missed_beats": 0,
            "ever_seen": True,
            "latest": None,
            "campus": "Campus Coquimatlan",
            "building": "Engineering",
            "deployment_label": "active",
            "deployment": True,
            "reading_age_seconds": 10,
            "policy": policy or FULL,
        }
    }
    return RuleContext(session=db, config=CONFIG, now=now, server={}, nodes=state, metrics={})


from app.monitoring import heartbeat as hb_module

check(
    "undervoltage detected",
    len(
        [
            f
            for f in hb_module.check_node_power(node_ctx(undervoltage=True))
            if f.rule_id == "node.undervoltage"
        ]
    )
    == 1,
)
check(
    "healthy power is quiet",
    len(list(hb_module.check_node_power(node_ctx(undervoltage=False, throttled=False)))) == 0,
)
check(
    "read-only filesystem is CRITICAL",
    [
        f.severity
        for f in hb_module.check_node_power(node_ctx(filesystem_readonly=True))
        if f.rule_id == "node.filesystem_readonly"
    ]
    == [Severity.CRITICAL],
)
check(
    "hot node detected",
    len(
        [
            f
            for f in hb_module.check_node_resources(node_ctx(cpu_temperature_c=84.0))
            if f.rule_id == "node.cpu_temperature_c"
        ]
    )
    == 1,
)
check(
    "cool node is quiet",
    len(list(hb_module.check_node_resources(node_ctx(cpu_temperature_c=45.0)))) == 0,
)
check(
    "large buffer detected",
    len(
        [
            f
            for f in hb_module.check_node_storage(node_ctx(buffered_readings=9000))
            if f.rule_id == "node.buffer"
        ]
    )
    == 1,
)
check(
    "dead collector is CRITICAL",
    [
        f.severity
        for f in hb_module.check_node_collector(node_ctx(collector_status="inactive"))
        if f.rule_id == "node.collector_down"
    ]
    == [Severity.CRITICAL],
)
check(
    "active collector is quiet",
    len(list(hb_module.check_node_collector(node_ctx(collector_status="active")))) == 0,
)
check(
    "ADS failure detected",
    len(
        [
            f
            for f in hb_module.check_node_collector(
                node_ctx(collector_status="active", ads_ok=False)
            )
            if f.rule_id == "node.ads"
        ]
    )
    == 1,
)
check(
    "unreachable plugs detected",
    len(
        [
            f
            for f in hb_module.check_node_collector(
                node_ctx(collector_status="active", shelly_reachable=1, shelly_total=4)
            )
            if f.rule_id == "node.shelly_unreachable"
        ]
    )
    == 1,
)
check(
    "access point fallback detected",
    len(
        [
            f
            for f in hb_module.check_node_connectivity(node_ctx(access_point_active=True))
            if f.rule_id == "node.access_point"
        ]
    )
    == 1,
)
check(
    "clock drift detected",
    len(
        [
            f
            for f in hb_module.check_node_connectivity(node_ctx(clock_drift_seconds=-400.0))
            if f.rule_id == "node.clock_drift"
        ]
    )
    == 1,
)

print("\n--- 13b. Stale telemetry is not evaluated ---")
stale = node_ctx(cpu_temperature_c=95.0)
stale.nodes["N001"]["missed_beats"] = 5
check(
    "no resource alerts from a node that is not reporting",
    len(list(hb_module.check_node_resources(stale))) == 0,
)
db.close()


# ==========================================================================
print("\n=== 14. Alive-but-not-measuring detection ===")
# ==========================================================================
db = TestSession()
state = {
    "N001": {
        "code": "N001",
        "node_id": node_a_id,
        "heartbeat": None,
        "missed_beats": 0,
        "ever_seen": True,
        "latest": None,
        "reading_age_seconds": 1200,
        "deployment": True,
        "deployment_status": "active",
        "building": "Engineering",
        "campus": "Campus",
        "deployment_label": "active",
        "policy": FULL,
    }
}
ctx = RuleContext(session=db, config=CONFIG, now=now, server={}, nodes=state, metrics={})
findings = list(hb_module.check_measurement_freshness(ctx))
check("stale measurements detected while node is alive", len(findings) == 1)
check("severity is CRITICAL past 900s", findings[0].severity is Severity.CRITICAL)
check(
    "summary distinguishes it from a connectivity fault",
    "network" in (findings[0].summary or "").lower(),
)

print("\n--- 14b. Deployed node that has never recorded anything ---")
state = {
    "N002": {
        "code": "N002",
        "node_id": node_b_id,
        "heartbeat": None,
        "missed_beats": 0,
        "ever_seen": True,
        "latest": None,
        "reading_age_seconds": None,
        "deployment": None,
        "deployment_status": None,
        "building": None,
        "campus": None,
        "deployment_label": None,
        # Full policy: a deployment is running, so "never recorded anything"
        # is a real fault rather than an expected silence.
        "policy": FULL,
    }
}
ctx = RuleContext(session=db, config=CONFIG, now=now, server={}, nodes=state, metrics={})
findings = list(hb_module.check_measurement_freshness(ctx))
check("commissioning node with no data detected", len(findings) == 1)
check(
    "reported as WARNING, with a grace period",
    findings[0].rule_id == "node.no_measurements"
    and findings[0].severity is Severity.WARNING
    and findings[0].sustain_seconds == 1800,
)
check(
    "suggests creating a deployment",
    any("deployment" in a.lower() for a in findings[0].suggested_actions),
)
db.close()


# ==========================================================================
print("\n=== 15. Status report ===")
# ==========================================================================
db = TestSession()
status = build_status(
    db,
    server={"hostname": "test", "disks": {}, "database": {}, "api": {}},
    nodes={},
    metrics={},
    findings=[],
    config=CONFIG,
    now=now,
)
check("status has an overall verdict", "overall" in status)
check("status has a server block", "server" in status)
check("status has an alerts block", "alerts" in status)
check("status has a database block", "database" in status)
report = render_report(status, CONFIG)
check("report renders", len(report.body) > 100)
check("report names the sections", "SERVER" in report.body and "NODES" in report.body)
check("report kind is report", report.kind == "report")

print("\n--- 15b. Missing values render as dashes, not zeros ---")
check("missing value is a dash", "—" in report.body)
db.close()


# ==========================================================================
print("\n=== 16. History queries ===")
# ==========================================================================
db = TestSession()
listing = list_alerts(db, limit=10)
check("listing returns a total", "total" in listing)
check("listing returns alerts", isinstance(listing["alerts"], list))
stats = statistics(db, days=7)
check("statistics by severity", "by_severity" in stats)
check("statistics counts open", "currently_open" in stats)
row = db.query(MonitorAlert).first()
if row is not None:
    rec = recurrence(db, row.fingerprint)
    check("recurrence counts occurrences", rec["occurrences"] >= 1)
db.close()


# ==========================================================================
print("\n=== 17. API surface ===")
# ==========================================================================
r = client.get("/api/monitoring/health")
check("health endpoint responds", r.status_code == 200, r.text)
check("health reports the scheduler", "scheduler" in r.json())
check("health reports channels", "channels" in r.json())

r = client.get("/api/monitoring/rules")
check("rules endpoint responds", r.status_code == 200)
check("rules are listed", r.json()["count"] >= 35)

r = client.get("/api/monitoring/alerts")
check("alerts endpoint responds", r.status_code == 200)

r = client.get("/api/monitoring/alerts/statistics")
check("statistics endpoint responds", r.status_code == 200)

r = client.get("/api/monitoring/alerts/ALT-NOPE-0000")
check("unknown alert -> 404", r.status_code == 404)

r = client.get("/api/monitoring/config")
check("config endpoint responds", r.status_code == 200)
check(
    "bot token never exposed",
    "8978688082" not in r.text
    and r.json()["telegram"].get("bot_token") in (None, "", "***redacted***"),
    r.json().get("telegram"),
)

r = client.get("/api/monitoring/channels")
check("channels endpoint responds", r.status_code == 200)

r = client.get("/api/monitoring/nodes/N001/heartbeats")
check("node heartbeat history responds", r.status_code == 200)
check("history returns rows", isinstance(r.json()["heartbeats"], list))

r = client.get("/api/monitoring/status")
check("status endpoint responds", r.status_code == 200, r.text[:300])


# ==========================================================================
print("\n=== 18. Existing platform endpoints still work ===")
# ==========================================================================
r = client.post("/api/edge/heartbeat", json={"node_id": "N001"})
check("legacy heartbeat endpoint unchanged", r.status_code == 200, r.text)

r = client.post(
    "/api/v1/measurements/batch",
    json={
        "device_id": "N001",
        "measurements": [
            {
                "captured_at": iso(datetime.utcnow()),
                "voltage_a": 127.0,
                "current_a": 5.0,
                "total_active_power": 1800.0,
                "total_current": 15.0,
            }
        ],
    },
)
check(
    "energy node batch ingest unchanged",
    r.status_code == 200 and r.json().get("inserted") == 1,
    r.text,
)

r = client.get("/health")
check("backend health endpoint unchanged", r.status_code == 200)

r = client.get("/api/alerts/status")
check("pre-existing alerts router still mounted", r.status_code == 200, r.text[:200])

db = TestSession()
check(
    "monitoring wrote nothing to energy_readings beyond the test ingests",
    db.query(models.EnergyReading).count() > 0,
)
check("nodes table row count unchanged", db.query(models.Node).count() == 2)
db.close()


# ==========================================================================
print("\n=== 19. Lifecycle policy is derived from the platform's own tables ===")
# ==========================================================================
db = TestSession()
states = commission_states(db)
check("commission states loaded from the platform table", len(states) == 4, str(list(states)))
check(
    "commissioned is monitored and may upload",
    states["commissioned"].is_monitored and states["commissioned"].may_upload,
)
check("registered is not monitored (silence is expected)", not states["registered"].is_monitored)
check("decommissioned is not monitored", not states["decommissioned"].is_monitored)
check(
    "suspended is monitored but may not upload",
    states["suspended"].is_monitored and not states["suspended"].may_upload,
)


def policy_for_node(commission, dep_status, start="2026-01-01", end=None):
    node = models.Node(code="NX", name="NX", status="online", buffer_pending=0, samples=0)
    node.commission_state = commission
    dep = None
    if dep_status:
        dep = models.Deployment(
            node_id=1,
            building_id=building_id,
            electrical_panel_id=1,
            start_date=start,
            end_date=end,
            status=dep_status,
        )
    return classify(
        db, {"code": "NX", "node": node, "deployment": dep}, CONFIG, datetime(2026, 7, 29)
    )


pol = policy_for_node("commissioned", "active")
check(
    "commissioned + active -> full monitoring",
    pol.electrical and pol.heartbeat and pol.measurement_freshness and pol.node_hardware,
)

pol = policy_for_node("commissioned", "active")
check("operational deployment -> heartbeat loss pages", pol.heartbeat_pages)

pol = policy_for_node("commissioned", "completed")
check("commissioned + completed -> NO electrical alerts", not pol.electrical)
check("commissioned + completed -> still watches liveness", pol.heartbeat)
check("commissioned + completed -> but liveness does NOT page", not pol.heartbeat_pages)
check("commissioned + completed -> no 'not measuring' alerts", not pol.measurement_freshness)

pol = policy_for_node("commissioned", None)
check("commissioned + no deployment -> no electrical", not pol.electrical)

pol = policy_for_node("commissioned", "planned")
check("planned deployment is not operational -> no electrical", not pol.electrical)

pol = policy_for_node("commissioned", "installing")
check("installing IS operational -> electrical enabled", pol.electrical)

pol = policy_for_node("registered", "active")
check(
    "registered node alerts on nothing",
    not any(
        [pol.electrical, pol.heartbeat, pol.sensors, pol.measurement_freshness, pol.node_hardware]
    ),
)

pol = policy_for_node("decommissioned", "active")
check(
    "decommissioned node alerts on nothing",
    not any([pol.electrical, pol.heartbeat, pol.node_hardware]),
)

pol = policy_for_node("suspended", "active")
check(
    "suspended: hardware watched, silence not alarmed",
    pol.node_hardware and not pol.heartbeat and not pol.electrical,
)

pol = policy_for_node("commissioned", "active", start="2026-01-01", end="2026-02-01")
check("expired date window -> not operational", not pol.electrical)

pol = policy_for_node("commissioned", "active", start="2027-01-01")
check("future start date -> not operational", not pol.electrical)

cfg = MonitoringConfig()
cfg.node_lifecycle = {"NX": "maintenance"}
node = models.Node(code="NX", name="NX", status="online", buffer_pending=0, samples=0)
node.commission_state = "commissioned"
dep = models.Deployment(
    node_id=1,
    building_id=building_id,
    electrical_panel_id=1,
    start_date="2026-01-01",
    end_date=None,
    status="active",
)
pol = classify(db, {"code": "NX", "node": node, "deployment": dep}, cfg, datetime(2026, 7, 29))
check(
    "maintenance override silences everything",
    not any([pol.electrical, pol.heartbeat, pol.node_hardware]),
)
db.close()


# ==========================================================================
print("\n=== 20. Sustain window suppresses transients ===")
# ==========================================================================
db = TestSession()
db.query(AlertEvent).delete()
db.query(MonitorAlert).delete()
db.commit()


def sustained_finding(target="SUS", sustain=1800):
    f = make_finding(target=target)
    f.sustain_seconds = sustain
    return f


t3 = datetime.utcnow()
tr = process_findings(db, [sustained_finding()], now=t3, config=CONFIG)
db.commit()
check("condition inside its sustain window does not notify", len(tr) == 0)
row = db.query(MonitorAlert).filter_by(fingerprint=sustained_finding().fingerprint).first()
check("but the alert IS recorded for the report and the API", row is not None)
check("and it is marked unannounced", row.notification_count == 0)

tr = process_findings(db, [sustained_finding()], now=t3 + timedelta(minutes=10), config=CONFIG)
db.commit()
check("still silent at 10 minutes", len(tr) == 0)

tr = process_findings(db, [sustained_finding()], now=t3 + timedelta(minutes=31), config=CONFIG)
db.commit()
check("notifies once the condition has held for 30 minutes", len(tr) == 1)
check("delivered as NEW, not as an escalation", tr[0].status == "NEW")

# A transient that clears before the window never reaches anyone.
db.query(AlertEvent).delete()
db.query(MonitorAlert).delete()
db.commit()
t4 = datetime.utcnow()
process_findings(db, [sustained_finding(target="FLAP")], now=t4, config=CONFIG)
db.commit()
tr = process_findings(db, [], now=t4 + timedelta(minutes=20), config=CONFIG)
db.commit()
check("transient resolves without ever notifying", len(tr) == 0)
db.close()


# ==========================================================================
print("\n=== 21. Hysteresis prevents the open/resolve flap ===")
# ==========================================================================
db = TestSession()
db.query(AlertEvent).delete()
db.query(MonitorAlert).delete()
db.commit()

t5 = datetime.utcnow()
process_findings(db, [make_finding(target="HYST")], now=t5, config=CONFIG)
db.commit()

tr = process_findings(db, [], now=t5 + timedelta(minutes=2), config=CONFIG)
db.commit()
check("does not resolve the moment the value dips", len(tr) == 0)
row = db.query(MonitorAlert).filter_by(fingerprint=make_finding(target="HYST").fingerprint).first()
check("alert stays open during the hysteresis window", row.resolved_at is None)

# Re-crossing inside the window must NOT produce a second alert.
tr = process_findings(
    db, [make_finding(target="HYST")], now=t5 + timedelta(minutes=4), config=CONFIG
)
db.commit()
check("re-crossing inside the window sends nothing", len(tr) == 0)
check(
    "and does not open a second alert",
    db.query(MonitorAlert).filter_by(rule_id="test.rule").count() == 1,
)

tr = process_findings(db, [], now=t5 + timedelta(minutes=30), config=CONFIG)
db.commit()
check("resolves once genuinely absent", len(tr) == 1 and tr[0].status == "RESOLVED")

# Simulate the real N001 flap: 20 crossings over 40 minutes.
db.query(AlertEvent).delete()
db.query(MonitorAlert).delete()
db.commit()
t6 = datetime.utcnow()
statuses = []
for i in range(40):
    findings = [make_finding(target="N001FLAP")] if i % 2 == 0 else []
    for tr in process_findings(db, findings, now=t6 + timedelta(minutes=i), config=CONFIG):
        statuses.append(tr.status)
    db.commit()

# Old behaviour: 20 crossings x (1 alert + 1 resolve) = 40 messages.
# New behaviour: one NEW, plus duration escalations because the condition
# genuinely persists for 40 minutes. Escalations are intentional and few; the
# flap itself is gone entirely.
check(
    "20 threshold crossings no longer produce 40 messages",
    len(statuses) <= 4,
    f"{len(statuses)}: {statuses}",
)
check("exactly one NEW alert, not twenty", statuses.count("NEW") == 1, str(statuses))
check("zero flap-resolve messages", statuses.count("RESOLVED") == 0, str(statuses))
check(
    "the rest are genuine duration escalations",
    all(st in ("NEW", "ESCALATED") for st in statuses),
    str(statuses),
)
db.close()


# ==========================================================================
print("\n=== 22. Report-only routing, with a severity breakout ===")
# ==========================================================================
from app.monitoring.rules import apply_routing

quiet = Finding(
    rule_id="electrical.power_factor",
    subsystem=Subsystem.ELECTRICAL,
    severity=Severity.WARNING,
    title="PF low",
    target="N001",
)
loud = Finding(
    rule_id="electrical.power_factor",
    subsystem=Subsystem.ELECTRICAL,
    severity=Severity.CRITICAL,
    title="PF collapsed",
    target="N001",
)
paging = Finding(
    rule_id="database.corruption",
    subsystem=Subsystem.DATABASE,
    severity=Severity.WARNING,
    title="DB",
    target="",
)
apply_routing([quiet, loud, paging], CONFIG)
check("report-only rule is muted at WARNING", not quiet.notify)
check("same rule breaks out at CRITICAL", loud.notify)
check("non-report-only rule always notifies", paging.notify)

muted = {
    "electrical.consumption_spike",
    "electrical.current_imbalance",
    "smart_plug.offline",
    "server.cpu",
    "node.heartbeat_never",
}
check(
    "the known-noisy rules are all report-only",
    muted.issubset(set(CONFIG.report_only_rules)),
    str(muted - set(CONFIG.report_only_rules)),
)
for critical_rule in (
    "database.corruption",
    "server.filesystem_readonly",
    "backend.api",
    "electrical.missing_phase",
    "node.collector_down",
    "node.heartbeat_lost",
):
    check(f"{critical_rule} still pages", critical_rule not in CONFIG.report_only_rules)


# ==========================================================================
print("\n=== 23. Regression: the exact values from the Telegram history ===")
# ==========================================================================
db = TestSession()
db.query(models.EnergyReading).delete()
db.commit()

noisy = add_reading(voltage=127.0, current=236.7)
check(
    "236.7 A (471 alerts / 962 messages) is now silent",
    len(list(metrics_module.check_current(electrical_ctx(db, noisy)))) == 0,
)

pf089 = add_reading(voltage=127.0, current=50.0, power_kw=15.0, power_factor=0.89)
check(
    "PF 0.89 (66 alerts) is now silent",
    len(list(metrics_module.check_power_factor(electrical_ctx(db, pf089)))) == 0,
)

spike = add_reading(voltage=127.0, current=50.0, power_kw=27.8)
check(
    "+31%% consumption spike is now silent",
    len(
        list(metrics_module.check_consumption(electrical_ctx(db, spike, baseline=21.3, stddev=3.0)))
    )
    == 0,
)

# ...and the genuine faults still fire.
overload = add_reading(voltage=127.0, current=320.0)
check(
    "320 A genuine overload still fires",
    len(list(metrics_module.check_current(electrical_ctx(db, overload)))) == 1,
)

pf055 = add_reading(voltage=127.0, current=50.0, power_kw=15.0, power_factor=0.55)
found = list(metrics_module.check_power_factor(electrical_ctx(db, pf055)))
apply_routing(found, CONFIG)
check(
    "PF 0.55 collapse still pages (severity breakout)",
    len(found) == 1 and found[0].notify and found[0].severity is Severity.CRITICAL,
)

phase = add_reading(
    voltage=85.0,
    phase_a_voltage=127.0,
    phase_b_voltage=128.0,
    phase_c_voltage=2.0,
    phase_a_current=40.0,
    phase_b_current=40.0,
    phase_c_current=0.0,
)
check(
    "missing phase still CRITICAL",
    [
        f.severity
        for f in metrics_module.check_phases(electrical_ctx(db, phase))
        if f.rule_id == "electrical.missing_phase"
    ]
    == [Severity.CRITICAL],
)

# Deployment gate beats severity: the same fault on an undeployed node is silent.
check(
    "severe overload on a non-operational deployment is silent",
    len(
        list(
            metrics_module.check_current(
                electrical_ctx(db, add_reading(voltage=127.0, current=480.0), policy=HARDWARE_ONLY)
            )
        )
    )
    == 0,
)
db.close()


# ==========================================================================
print("\n=== 24. Threshold resolution from physical ratings ===")
# ==========================================================================
from app.monitoring.thresholds import (
    physical_ceiling,
    resolve_current_thresholds,
)

db = TestSession()


def rated_node(**kw):
    n = models.Node(
        code="NR",
        name="NR",
        status="online",
        buffer_pending=0,
        samples=0,
        commission_state="commissioned",
    )
    for k, v in kw.items():
        setattr(n, k, v)
    return n


def rated_deployment(**kw):
    d = models.Deployment(
        node_id=1,
        building_id=building_id,
        electrical_panel_id=1,
        start_date="2026-01-01",
        end_date=None,
        status="active",
    )
    for k, v in kw.items():
        setattr(d, k, v)
    return d


LEARNED = {"threshold": 296.0, "source": "learned p99.5"}

# --- order 1: deployment explicit limits win over everything -------------
r = resolve_current_thresholds(
    rated_node(ct_max_current_a=100.0, warning_current_a=90.0),
    rated_deployment(warning_current_a=180.0, critical_current_a=200.0, emergency_current_a=240.0),
    CONFIG,
    baseline=LEARNED,
)
check("deployment explicit limits win", r.warning == 180.0 and r.critical == 200.0, r.source)
check("emergency limit carried", r.emergency == 240.0)
check("provenance names the deployment", "deployment" in r.source, r.source)

# --- order 2: deployment panel rating -------------------------------------
r = resolve_current_thresholds(
    rated_node(), rated_deployment(panel_main_breaker_a=400.0), CONFIG, baseline=LEARNED
)
check("panel breaker derives the threshold", r.warning == 360.0, str(r.warning))
check("critical is the rating itself", r.critical == 400.0)
check("provenance names the breaker", "breaker" in r.source, r.source)

# --- order 3: node explicit limits ----------------------------------------
r = resolve_current_thresholds(
    rated_node(warning_current_a=150.0, critical_current_a=170.0), None, CONFIG, baseline=LEARNED
)
check(
    "node explicit limits used when no deployment values",
    r.warning == 150.0 and "node" in r.source,
    r.source,
)

# --- order 4: node CT rating ----------------------------------------------
r = resolve_current_thresholds(rated_node(ct_max_current_a=120.0), None, CONFIG, baseline=LEARNED)
check("node CT rating derives the threshold", r.warning == 108.0, str(r.warning))
check("provenance names the CT", "CT" in r.source, r.source)

# --- order 5: learned baseline, only with no rating -----------------------
r = resolve_current_thresholds(rated_node(), None, CONFIG, baseline=LEARNED)
check(
    "learned baseline used as a last resort before the fallback",
    r.warning == 296.0 and "learned" in r.source,
    r.source,
)

# --- order 6: conservative fallback ---------------------------------------
r = resolve_current_thresholds(rated_node(), None, CONFIG, baseline=None)
check(
    "conservative fallback when nothing is known",
    r.warning == CONFIG.electrical.current_warning,
    str(r.warning),
)
check("fallback says so", "conservative" in r.source, r.source)

# --- THE CAP: a learned baseline may never exceed physical reality --------
r = resolve_current_thresholds(
    rated_node(ct_max_current_a=150.0),
    None,
    CONFIG,
    baseline={"threshold": 900.0, "source": "learned p99.5"},
)
check(
    "learned baseline cannot exceed the CT rating",
    r.warning <= 150.0,
    f"warning={r.warning} ceiling=150",
)

ceiling, label = physical_ceiling(
    rated_node(ct_max_current_a=150.0), rated_deployment(panel_main_breaker_a=400.0)
)
check("physical ceiling takes the LOWEST limit", ceiling == 150.0, str(ceiling))
check("and names which one binds", "CT" in (label or ""), str(label))

ceiling, _ = physical_ceiling(
    rated_node(ct_max_current_a=600.0), rated_deployment(panel_main_breaker_a=200.0)
)
check("breaker binds when it is the lower limit", ceiling == 200.0, str(ceiling))
check("no ratings -> no ceiling", physical_ceiling(rated_node(), None)[0] is None)

# --- sustained duration is configurable per node/deployment ---------------
r = resolve_current_thresholds(
    rated_node(sustained_seconds=60),
    rated_deployment(sustained_seconds=120),
    CONFIG,
    baseline=LEARNED,
)
check("deployment sustained duration wins", r.sustained_seconds == 120, str(r.sustained_seconds))
r = resolve_current_thresholds(rated_node(sustained_seconds=60), None, CONFIG, baseline=LEARNED)
check("node sustained duration used otherwise", r.sustained_seconds == 60)

# --- all ratings nullable by default --------------------------------------
plain = rated_node()
check(
    "every rating is NULL until entered",
    all(
        getattr(plain, f) is None
        for f in (
            "ct_max_current_a",
            "nominal_voltage_v",
            "phase_count",
            "warning_current_a",
            "critical_current_a",
            "emergency_current_a",
            "sustained_seconds",
        )
    ),
)
db.close()


# ==========================================================================
print("\n=== 25. Node commission transitions go through the lifecycle ===")
# ==========================================================================
from app.db import commissioning as commissioning_svc

db = TestSession()
node = db.query(models.Node).filter_by(code="N002").first()

check(
    "legal moves from commissioned",
    set(commissioning_svc.legal_transitions_from(db, "commissioned"))
    == {"registered", "suspended", "decommissioned"},
    str(commissioning_svc.legal_transitions_from(db, "commissioned")),
)
check(
    "decommissioned is terminal — no way out",
    commissioning_svc.legal_transitions_from(db, "decommissioned") == (),
    str(commissioning_svc.legal_transitions_from(db, "decommissioned")),
)
check(
    "registered is NOT terminal (reversible storage state)",
    "commissioned" in commissioning_svc.legal_transitions_from(db, "registered"),
)

result = commissioning_svc.transition(
    db, node, "registered", reason="stored pending future campaign", actor="test"
)
db.commit()
check("transition applied", node.commission_state == "registered")
check(
    "transition reports both states",
    result["from_state"] == "commissioned" and result["to_state"] == "registered",
)

hist = commissioning_svc.history(db, node.id)
check("audit row written", len(hist) == 1, str(hist))
check("audit records the reason", hist[0]["reason"] == "stored pending future campaign")
check("audit records the actor", hist[0]["actor"] == "test")

# Illegal move is rejected and changes nothing.
before = node.commission_state
try:
    commissioning_svc.transition(db, node, "suspended")
    illegal_rejected = False
except commissioning_svc.IllegalTransition:
    illegal_rejected = True
check("illegal transition rejected", illegal_rejected)
check("illegal transition changed nothing", node.commission_state == before)

try:
    commissioning_svc.transition(db, node, "not-a-state")
    unknown_rejected = False
except commissioning_svc.IllegalTransition:
    unknown_rejected = True
check("unknown state rejected", unknown_rejected)

check(
    "no-op transition is legal and records nothing",
    commissioning_svc.transition(db, node, "registered") is None,
)
check("history unchanged by the no-op", len(commissioning_svc.history(db, node.id)) == 1)

# An unmonitored node alerts on nothing.
pol = classify(
    db, {"code": "N002", "node": node, "deployment": None}, CONFIG, datetime(2026, 7, 29)
)
check(
    "registered node alerts on nothing",
    not any(
        [pol.electrical, pol.heartbeat, pol.sensors, pol.measurement_freshness, pol.node_hardware]
    ),
    pol.rationale,
)

# Put it back so later sections see a commissioned node.
commissioning_svc.transition(db, node, "commissioned", reason="test teardown")
db.commit()
db.close()


# ==========================================================================
print("\n" + "=" * 60)
print(f"PASSED: {len(PASS)}   FAILED: {len(FAIL)}")
if FAIL:
    print("FAILURES:")
    for f in FAIL:
        print("  -", f)
print("=" * 60)
sys.exit(1 if FAIL else 0)
