"""Non-destructive regression suite for the hardening package.

Runs unattended. NOTHING here restarts a service, writes to hardware, kills a
process or touches measurement data. The destructive recovery tests live in
bin/energy-node-recovery-test and are run deliberately, in a window.

    energy-node selftest [--json]
"""
from __future__ import annotations

__version__ = "1.0.0"

import json, os, sqlite3, subprocess, sys, time

_LIB = os.path.dirname(os.path.abspath(__file__))
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

RESULTS = []


def check(group, name):
    def deco(fn):
        RESULTS.append((group, name, fn))
        return fn
    return deco


# ------------------------------------------------------------- tri-state
@check("tristate", "unknown never coerces")
def _t1():
    from tristate import Tri, tri
    for v in (None, "", "maybe", [], {}):
        assert tri(v) is Tri.UNKNOWN, f"{v!r}"
    assert tri(True) is Tri.TRUE and tri(False) is Tri.FALSE
    assert tri("rw") is Tri.FALSE and tri("ro") is Tri.TRUE


@check("tristate", "bool coercion is refused")
def _t2():
    from tristate import Tri
    for m in (Tri.TRUE, Tri.FALSE, Tri.UNKNOWN):
        try:
            bool(m)
        except TypeError:
            continue
        raise AssertionError(f"{m} allowed bool()")


@check("tristate", "UNKNOWN never produces FAIL")
def _t3():
    from tristate import Outcome, evaluate_boolean, evaluate_threshold
    for age in (0, 10, 10 ** 9):
        assert evaluate_boolean("x", None, unknown_age_seconds=age).outcome is not Outcome.FAIL
    assert evaluate_threshold("x", None, fail_above=1).outcome is Outcome.UNKNOWN


@check("tristate", "filesystem regression: false != null != true")
def _t4():
    from tristate import Outcome, Tri, evaluate_boolean
    assert evaluate_boolean("fs", False, fail_on=Tri.TRUE).outcome is Outcome.PASS
    assert evaluate_boolean("fs", True, fail_on=Tri.TRUE).outcome is Outcome.FAIL
    assert evaluate_boolean("fs", None, fail_on=Tri.TRUE).outcome is Outcome.UNKNOWN


@check("tristate", "liveness distinguishes never-seen from lost")
def _t5():
    from tristate import Outcome, evaluate_liveness
    assert evaluate_liveness("hb", None, ever_seen=False,
                             registered_age_seconds=86400).outcome is Outcome.FAIL
    assert evaluate_liveness("hb", 10, ever_seen=True).outcome is Outcome.PASS
    assert evaluate_liveness("hb", 10**6, ever_seen=True).outcome is Outcome.FAIL
    assert evaluate_liveness("hb", -3, ever_seen=True).outcome is Outcome.PASS


# --------------------------------------------------------- configuration
@check("config", "required keys resolve")
def _c1():
    import enconfig
    for k in ("NODE_ID", "CENTRAL_API_URL", "DB_PATH", "EN_STATE_DIR"):
        assert enconfig.get(k), f"{k} unset"


@check("config", "typed getters coerce safely")
def _c2():
    import enconfig
    assert isinstance(enconfig.get_int("HEARTBEAT_INTERVAL", 60), int)
    assert isinstance(enconfig.get_float("HEARTBEAT_TIMEOUT", 10.0), float)
    assert enconfig.get_int("NOPE_MISSING", 7) == 7
    assert enconfig.get_bool("NOPE_MISSING", True) is True


@check("config", "no experimental recovery enabled")
def _c3():
    import enconfig
    for f in ("RECOVERY_UPS_ARM_ON_SHUTDOWN", "RECOVERY_RTC_WAKE",
              "RECOVERY_GPIO_WAKE", "RECOVERY_RELAY",
              "RECOVERY_EXTERNAL_WATCHDOG"):
        assert not enconfig.get_bool(f, False), f"{f} is ENABLED"


# ------------------------------------------------------------------- UPS
@check("ups", "discovery never guesses")
def _u1():
    import ups
    saved = dict(ups.REGISTRY)
    try:
        ups.REGISTRY.clear()
        s = ups.discover()
        assert s.battery_voltage_v is None, "invented a battery value"
        assert not s.identified
    finally:
        ups.REGISTRY.clear(); ups.REGISTRY.update(saved)


@check("ups", "missing bus fails safe")
def _u2():
    import ups
    s = ups.discover(bus_num=99)
    assert not s.present and s.battery_voltage_v is None


@check("ups", "drivers do not both claim the same hardware")
def _u3():
    import ups
    from i2cbus import I2CBus
    if not I2CBus.available(1):
        return "skip: no i2c bus"
    with I2CBus(1) as bus:
        claims = [d.name for d in ups._ordered_drivers() if d.probe(bus)]
    assert len(claims) <= 1, f"ambiguous: {claims}"
    return f"claimed by: {claims or ['none']}"


@check("ups", "identified UPS reports sane battery")
def _u4():
    import ups
    s = ups.read()
    if not s.identified:
        return f"skip: {s.confidence}"
    assert 2.0 < s.battery_voltage_v < 30.0, s.battery_voltage_v
    assert 0 <= s.battery_percent <= 100
    return s.summary()


# --------------------------------------------------------------- sensors
@check("sensors", "discovery returns a primary or an honest unknown")
def _s1():
    import sensors
    p = sensors.discover()["primary"]
    assert p is not None
    if not p.identified:
        assert p.diagnostics, "unknown hardware must expose diagnostics"
    return f"{p.kind} reachable={p.reachable}"


# ------------------------------------------------------------- telemetry
@check("telemetry", "payload has the canonical contract")
def _p1():
    import telemetry
    p = telemetry.build()
    for k in ("node_id", "timestamp", "hostname", "undervoltage",
              "filesystem_readonly", "buffered_readings", "pending_sync",
              "collector_status", "local_alerts"):
        assert k in p, f"missing {k}"
    assert p["node_id"], "node_id empty"


@check("telemetry", "timestamp is UTC, not local")
def _p2():
    import telemetry
    p = telemetry.build()
    sent = time.mktime(time.strptime(p["timestamp"], "%Y-%m-%dT%H:%M:%S"))
    drift = abs(sent - time.mktime(time.gmtime()))
    assert drift < 120, f"timestamp drifts {drift:.0f}s from UTC"


@check("telemetry", "buffered_readings is unsent, not total")
def _p3():
    import enconfig, telemetry
    p = telemetry.build()
    conn = sqlite3.connect(f"file:{enconfig.get('DB_PATH')}?mode=ro", uri=True, timeout=10)
    total = conn.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]
    conn.close()
    assert p["buffered_readings"] <= total
    if total > 1000:
        assert p["buffered_readings"] < total, "reporting total, not backlog"
    return f"unsent={p['buffered_readings']} of {total}"


@check("telemetry", "undervoltage is edge-triggered, not sticky")
def _p4():
    import sysinfo, telemetry
    mask = sysinfo.throttled_mask()
    if mask is None or not (mask & 0x10000):
        return "skip: no sticky bit set to test against"
    p = telemetry.build()
    if not (mask & 0x1) and not telemetry.recent_undervoltage():
        assert p["undervoltage"] is not True, "sticky bit leaked -> permanent ERROR"
    return "sticky bit correctly not reported as live"


# ------------------------------------------------------------- heartbeat
@check("heartbeat", "negotiation flips when backend becomes canonical")
def _h1():
    import enconfig, heartbeat
    os.environ["HEARTBEAT_LEGACY_EDGE_PUBLISH"] = "auto"
    os.environ["EN_STATE_DIR"] = "/tmp/en-selftest"
    os.makedirs("/tmp/en-selftest", exist_ok=True)
    enconfig.load(reload=True)

    class R:
        def __init__(s, b): s._b, s.status_code, s.text = b, 200, ""
        def json(s): return s._b

    class S:
        def __init__(s, canon): s.canon, s.calls = canon, []
        def post(s, url, json=None, timeout=None):
            s.calls.append(url)
            if "monitoring" in url:
                return R({"status": "ok", "last_sync": "x"} if s.canon
                         else {"status": "ok", "node_code": "N001"})
            return R({"status": "ok", "last_sync": "x"})

    try:
        s = S(False)
        r = heartbeat.publish(payload={"node_id": "N001", "pending_sync": 0}, session=s)
        assert r.legacy_required is True and len(s.calls) == 2
        s = S(True)
        r = heartbeat.publish(payload={"node_id": "N001", "pending_sync": 0}, session=s)
        assert r.legacy_required is False and len(s.calls) == 1, "did not stop dual-publishing"
    finally:
        os.environ.pop("HEARTBEAT_LEGACY_EDGE_PUBLISH", None)
        os.environ.pop("EN_STATE_DIR", None)
        enconfig.load(reload=True)
    return "unpatched->dual, patched->single"


@check("heartbeat", "exactly one producer on this node")
def _h2():
    out = subprocess.run(["grep", "-rl", "-e", "monitoring/heartbeat",
                          "-e", "edge/heartbeat", "/opt/energy-node/app"],
                         capture_output=True, text=True).stdout
    producers = [l for l in out.splitlines() if l.endswith(".py")
                 and "pycache" not in l and "pre-netstate" not in l]
    assert len(producers) <= 1, f"multiple producers: {producers}"
    return f"producers: {[os.path.basename(p) for p in producers]}"


@check("heartbeat", "failure never raises into the collector")
def _h3():
    import heartbeat

    class Boom:
        def post(self, *a, **k): raise RuntimeError("network on fire")

    r = heartbeat.publish(payload={"node_id": "N001"}, session=Boom())
    assert r.canonical_ok is False and r.error


# ------------------------------------------------------------- collector
@check("collector", "unit is active")
def _k1():
    import sysinfo
    st = sysinfo.systemd_is_active("energy-node-collector.service")
    assert st == "active", st


@check("collector", "measurements are fresh")
def _k2():
    import datetime, enconfig
    conn = sqlite3.connect(f"file:{enconfig.get('DB_PATH')}?mode=ro", uri=True, timeout=10)
    newest = conn.execute("SELECT MAX(captured_at) FROM measurements").fetchone()[0]
    conn.close()
    t = datetime.datetime.fromisoformat(newest.replace("Z", "+00:00"))
    age = (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds()
    limit = enconfig.get_int("VERIFY_MEASUREMENT_MAX_AGE", 300)
    assert age < limit, f"{age:.0f}s old"
    return f"{age:.0f}s old"


# ---------------------------------------------------------------- sqlite
@check("sqlite", "measurement db integrity")
def _q1():
    import enconfig
    conn = sqlite3.connect(f"file:{enconfig.get('DB_PATH')}?mode=ro", uri=True, timeout=20)
    res = conn.execute("PRAGMA quick_check").fetchone()[0]
    conn.close()
    assert res == "ok", res


@check("sqlite", "measurement schema untouched by hardening")
def _q2():
    import enconfig
    conn = sqlite3.connect(f"file:{enconfig.get('DB_PATH')}?mode=ro", uri=True, timeout=10)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(measurements)")}
    conn.close()
    for c in ("captured_at", "sync_status", "total_active_power", "voltage_a"):
        assert c in cols, f"missing {c}"
    return f"{len(cols)} columns intact"


@check("buffer", "backlog within threshold")
def _b1():
    import enconfig
    conn = sqlite3.connect(f"file:{enconfig.get('DB_PATH')}?mode=ro", uri=True, timeout=10)
    pending = conn.execute("SELECT COUNT(*) FROM measurements WHERE sync_status=0").fetchone()[0]
    conn.close()
    limit = enconfig.get_int("VERIFY_BUFFER_MAX_PENDING", 500)
    assert pending <= limit * 10, f"{pending} unsent"
    return f"{pending} unsent"


# ----------------------------------------------------------- power logger
@check("powerlog", "recorder is running and sampling")
def _w1():
    import enconfig, sysinfo
    if not enconfig.get_bool("POWERLOG_ENABLED", True):
        return "skip: disabled"
    st = sysinfo.systemd_is_active("energy-node-powerlog.service")
    assert st == "active", st
    conn = sqlite3.connect(f"file:{enconfig.get('EN_POWER_DB')}?mode=ro", uri=True, timeout=10)
    n, newest = conn.execute("SELECT COUNT(*), MAX(ts) FROM samples").fetchone()
    conn.close()
    assert n > 0, "no samples"
    age = time.time() - (newest or 0)
    assert age < 300, f"newest sample {age:.0f}s old"
    return f"{n} samples, newest {age:.0f}s old"


@check("powerlog", "event schema present for edge-triggered undervoltage")
def _w2():
    import enconfig
    conn = sqlite3.connect(f"file:{enconfig.get('EN_POWER_DB')}?mode=ro", uri=True, timeout=10)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(events)")}
    n = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    conn.close()
    for c in ("kind", "ext5v_min_60s", "batt_ma", "on_battery"):
        assert c in cols, f"missing {c}"
    return f"{n} events recorded"


# ---------------------------------------------------------------- doctor
@check("doctor", "all checks execute without crashing")
def _d1():
    import doctor
    rs = doctor.run_all()
    crashed = [r for r in rs if "check crashed" in r.detail]
    assert not crashed, f"crashed: {[r.subsystem for r in crashed]}"
    assert len(rs) >= 25, f"only {len(rs)} checks"
    return f"{len(rs)} checks, overall={doctor.worst(rs).value}"


@check("doctor", "json output is well-formed and complete")
def _d2():
    import doctor
    p = doctor.to_json(doctor.run_all())
    json.dumps(p)
    for k in ("schema", "node_id", "overall", "ok", "counts", "checks"):
        assert k in p, f"missing {k}"
    assert p["schema"] == "energy-node.doctor/1"
    return f"{len(p['checks'])} checks serialised"


@check("doctor", "no FAIL on a healthy node")
def _d3():
    import doctor
    from tristate import Outcome
    fails = [f"{r.subsystem}: {r.detail}" for r in doctor.run_all()
             if r.outcome is Outcome.FAIL]
    assert not fails, "; ".join(fails)


# --------------------------------------------------------------- version
@check("version", "checksum is deterministic")
def _v1():
    import version
    assert version.package_checksum() == version.package_checksum()


@check("version", "upgrade compatibility gate works")
def _v2():
    import version
    ok, _ = version.check_upgrade()
    assert isinstance(ok, bool)
    saved = version.PACKAGE_VERSION
    try:
        version.PACKAGE_VERSION = "0.0.1"
        if version.read_state().get("package_version"):
            ok, _ = version.check_upgrade()
            assert ok is False, "downgrade was not refused"
            ok, _ = version.check_upgrade(force=True)
            assert ok is True, "force did not override"
            return "downgrade refused, --force honoured"
        return "skip: not installed via install.sh yet"
    finally:
        version.PACKAGE_VERSION = saved


# -------------------------------------------------------------- recovery
@check("recovery", "every experimental module is inert")
def _r1():
    import recovery
    st = recovery.status()
    on = [n for n, s in st.items() if s.get("experimental") and s["enabled"]]
    assert not on, f"ENABLED: {on}"
    exp = len([1 for s in st.values() if s.get("experimental")])
    return f"{len(st)} modules, {exp} experimental all off"


@check("recovery", "disabled actions are true no-ops")
def _r2():
    import ups
    from recovery import external_watchdog, relay, rtc_wake, selfheal, ups_wake
    before = ups.read().arm_register
    for fn in (ups_wake.arm, rtc_wake.set_alarm, selfheal.run, relay.cycle,
               external_watchdog.pet):
        rc = fn()
        assert rc == 0, f"{fn.__module__} returned {rc} while disabled"
    after = ups.read().arm_register
    assert before == after, f"arm register changed {before}->{after}"
    return f"arm register untouched (0x{after:02x})" if after is not None else "ok"


@check("recovery", "watchdog is armed by the OS")
def _r3():
    import sysinfo
    wd = sysinfo.watchdog_state()
    assert wd.get("present"), "no watchdog device"
    assert wd.get("state") == "active", wd.get("state")
    return f"{wd.get('identity')} timeout={wd.get('timeout')}s"


# -------------------------------------------------------------- blackbox
@check("blackbox", "classifier reproduces both real incidents")
def _bb1():
    import blackbox as bb
    assert bb.classify(True, False, 0, 5347.9)[0] == "latch_or_hang"
    assert bb.classify(True, False, 0, 157037.0)[0] == "latch_or_hang"
    assert bb.classify(False, False, 0, 3.0)[0] == "power_loss"
    assert bb.classify(True, True, 0, 40.0)[0] == "clean_shutdown"
    assert bb.classify(True, False, 1, 65.0)[0] == "watchdog_reset"
    assert bb.classify(None, None, 0, None)[0] == "unknown"
    return "Aug1 + Aug3 -> latch, Jul27 -> power_loss"


@check("blackbox", "boot record is durable and idempotent")
def _bb2():
    import blackbox as bb
    r1 = bb.record_boot()
    r2 = bb.record_boot()
    assert r2.get("already_recorded") or r1.get("boot_id") == r2.get("boot_id")
    conn = bb.connect()
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    sync = conn.execute("PRAGMA synchronous").fetchone()[0]
    conn.close()
    assert mode.lower() == "wal", mode
    assert int(sync) == 2, f"synchronous={sync} (want FULL=2)"
    return f"WAL + synchronous=FULL, boot {r1.get('boot_id','')[:8]}"


# ------------------------------------------------------------------- CLI
@check("cli", "energy-node subcommands respond")
def _x1():
    exe = "/opt/energy-node/hardening/bin/energy-node"
    if not os.path.exists(exe):
        return "skip: not installed yet"
    for args in (["version"], ["hardening", "status", "--json"],
                 ["ups", "--json"], ["sensors", "--json"]):
        r = subprocess.run([exe] + args, capture_output=True, text=True, timeout=60)
        assert r.returncode in (0, 1), f"{args} rc={r.returncode}: {r.stderr[:200]}"
    return "version, hardening, ups, sensors"


@check("cli", "doctor --json emits valid JSON")
def _x2():
    exe = "/opt/energy-node/hardening/bin/energy-node"
    if not os.path.exists(exe):
        return "skip: not installed yet"
    r = subprocess.run([exe, "doctor", "--json"], capture_output=True, text=True, timeout=120)
    d = json.loads(r.stdout)
    assert d["schema"] == "energy-node.doctor/1"
    return f"overall={d['overall']}"


# ------------------------------------------------------------------ main
def main(json_out: bool = False) -> int:
    started = time.time()
    rows = []
    for group, name, fn in RESULTS:
        t0 = time.time()
        try:
            detail = fn()
            state = "PASS"
            if isinstance(detail, str) and detail.startswith("skip"):
                state, detail = "SKIP", detail[5:].strip(": ")
        except AssertionError as exc:
            state, detail = "FAIL", str(exc)
        except Exception as exc:
            state, detail = "ERROR", f"{type(exc).__name__}: {exc}"
        rows.append({"group": group, "name": name, "state": state,
                     "detail": detail if isinstance(detail, str) else "",
                     "seconds": round(time.time() - t0, 3)})

    bad = [r for r in rows if r["state"] in ("FAIL", "ERROR")]
    summary = {"schema": "energy-node.selftest/1",
               "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "total": len(rows),
               "passed": sum(1 for r in rows if r["state"] == "PASS"),
               "skipped": sum(1 for r in rows if r["state"] == "SKIP"),
               "failed": len(bad), "ok": not bad,
               "duration_seconds": round(time.time() - started, 2),
               "tests": rows}

    if json_out:
        print(json.dumps(summary, indent=2))
        return 0 if not bad else 1

    last = None
    for r in rows:
        if r["group"] != last:
            print(f"\n  {r['group']}")
            last = r["group"]
        mark = {"PASS": "PASS", "SKIP": "SKIP", "FAIL": "FAIL", "ERROR": "ERR "}[r["state"]]
        line = f"    [{mark}] {r['name']}"
        if r["detail"]:
            line += f"  -- {r['detail'][:88]}"
        print(line)
    print(f"\n  {summary['total']} tests: {summary['passed']} passed, "
          f"{summary['skipped']} skipped, {summary['failed']} failed "
          f"({summary['duration_seconds']}s)")
    print(f"  RESULT: {'PASS' if summary['ok'] else 'FAIL'}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main("--json" in sys.argv))
