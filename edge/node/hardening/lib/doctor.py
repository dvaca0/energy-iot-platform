"""energy-node doctor — the permanent operator health tool.

Every check resolves through the tri-state framework, so a value that is not
reported comes back UNKNOWN rather than being silently coerced into PASS or
FAIL. Checks that do not apply to this hardware come back SKIP, never a silent
pass — a Pi 4 has no PMIC ADC, and N003 has no Shelly.

Exit codes:  0 = no FAIL   1 = at least one FAIL
JSON output is the contract the backend will later consume.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from typing import Optional

_LIB = os.path.dirname(os.path.abspath(__file__))
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

import enconfig  # noqa: E402
import sensors  # noqa: E402
import sysinfo  # noqa: E402
import ups as ups_pkg  # noqa: E402
import version as version_mod  # noqa: E402
import blackbox as blackbox_mod  # noqa: E402
from tristate import (Outcome, Result, Tri, evaluate_boolean,  # noqa: E402
                      evaluate_liveness, evaluate_threshold, tri, worst)

try:
    import recovery as recovery_pkg
except Exception:  # pragma: no cover
    recovery_pkg = None

try:
    import requests
except ImportError:
    requests = None

__version__ = "1.0.0"


def _ro(path: str):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)


def _age_of(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    import datetime
    try:
        t = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=datetime.timezone.utc)
    return (datetime.datetime.now(datetime.timezone.utc) - t).total_seconds()


# ============================================================ hardware
def check_board() -> Result:
    c = sysinfo.capabilities()
    return Result("board", Outcome.PASS,
                  f"{c['model']} | vcgencmd={c['vcgencmd']} "
                  f"pmic_adc={c['pmic_adc']} watchdog={c['watchdog']} "
                  f"rtc_wakealarm={c['rtc_wakealarm']}",
                  Tri.FALSE, c["model"])


def check_i2c() -> Result:
    bus = enconfig.get_int("UPS_I2C_BUS", 1)
    dev = f"/dev/i2c-{bus}"
    if os.path.exists(dev):
        return Result("i2c", Outcome.PASS, f"{dev} present", Tri.FALSE, dev)
    persisted = False
    for cfg in ("/boot/firmware/config.txt", "/boot/config.txt"):
        try:
            with open(cfg) as fh:
                persisted = any(l.strip() == "dtparam=i2c_arm=on" for l in fh)
            break
        except OSError:
            continue
    return Result("i2c", Outcome.FAIL,
                  f"{dev} missing; dtparam=i2c_arm=on persisted={persisted}"
                  + ("" if persisted else " — run install.sh")
                  + (" (reboot required)" if persisted else ""),
                  Tri.TRUE, None)


def check_ups(state=None) -> Result:
    st = state or ups_pkg.read()
    if st.present and st.identified:
        return Result("ups", Outcome.PASS, st.summary(), Tri.FALSE, st.model)
    if st.present:
        return Result("ups", Outcome.WARN,
                      f"present but UNIDENTIFIED at "
                      f"{st.fingerprint.get('addresses')} — battery state "
                      f"deliberately not reported; add a driver to lib/ups/",
                      Tri.UNKNOWN, st.fingerprint)
    if st.confidence == "disabled":
        return Result("ups", Outcome.SKIP, "UPS_ENABLED=0", Tri.UNKNOWN, None)
    return Result("ups", Outcome.FAIL, f"not detected ({st.confidence}): "
                  f"{st.error}", Tri.TRUE, None)


def check_battery(state=None) -> Result:
    st = state or ups_pkg.read()
    if not (st.present and st.identified):
        return Result("battery", Outcome.SKIP,
                      "no identified UPS — battery state unknowable",
                      Tri.UNKNOWN, None)
    low_v = enconfig.get_float("UPS_BATTERY_LOW_V", 3.15)
    r = evaluate_threshold("battery", st.battery_voltage_v,
                           fail_below=low_v, warn_below=low_v + 0.35,
                           unit="V", label="battery")
    if r.outcome is Outcome.PASS:
        r.detail = (f"battery {st.battery_voltage_v}V "
                    f"{st.battery_percent}% {st.battery_current_ma}mA "
                    f"on_battery={st.on_battery}")
    return r


def check_rtc() -> Result:
    dev = enconfig.get("RECOVERY_RTC_DEVICE", "/sys/class/rtc/rtc0/wakealarm")
    if not os.path.exists(dev):
        return Result("rtc", Outcome.SKIP, "no RTC wakealarm on this board",
                      Tri.UNKNOWN, None)
    # A valid RTC clock is what proved the board stayed powered through the
    # 43h37m latch, so it is worth reporting explicitly.
    rtc_time = None
    try:
        with open("/sys/class/rtc/rtc0/time") as fh:
            rtc_time = fh.read().strip()
    except OSError:
        pass
    alarm = ""
    try:
        with open(dev) as fh:
            alarm = fh.read().strip()
    except OSError:
        pass
    return Result("rtc", Outcome.PASS,
                  f"wakealarm available (rtc time {rtc_time or 'unknown'}); "
                  f"alarm={'set ' + alarm if alarm else 'none'}",
                  Tri.FALSE, alarm or None)


def check_gpio() -> Result:
    chips = [p for p in os.listdir("/dev") if p.startswith("gpiochip")]
    if not chips:
        return Result("gpio", Outcome.WARN, "no gpiochip devices", Tri.UNKNOWN,
                      None)
    pin = enconfig.get_int("RECOVERY_GPIO_WAKE_PIN", 3)
    return Result("gpio", Outcome.PASS,
                  f"{len(chips)} gpiochip(s); wake pin GPIO{pin} reserved "
                  f"(nothing drives it — gpio_wake is framework only)",
                  Tri.FALSE, sorted(chips))


def check_watchdog() -> Result:
    wd = sysinfo.watchdog_state()
    if not wd.get("present"):
        return Result("watchdog", Outcome.FAIL, "no /dev/watchdog0",
                      Tri.TRUE, None)
    want = enconfig.get_int("WATCHDOG_EXPECT_TIMEOUT", 60)
    active = wd.get("state") == "active"
    detail = (f"{wd.get('identity')} state={wd.get('state')} "
              f"timeout={wd.get('timeout')}s (expected {want}s) — "
              f"cannot recover an unpowered SoC")
    return Result("watchdog", Outcome.PASS if active else Outcome.FAIL,
                  detail, Tri.FALSE if active else Tri.TRUE, wd.get("state"))


def check_sensor() -> Result:
    d = sensors.discover()
    p = d["primary"]
    if not p.identified:
        return Result("sensor", Outcome.FAIL, p.detail, Tri.TRUE,
                      p.diagnostics)
    if p.reachable is False:
        return Result("sensor", Outcome.FAIL,
                      f"{p.kind}: {p.detail}", Tri.TRUE, p.diagnostics)
    if p.reachable is None:
        return Result("sensor", Outcome.UNKNOWN, f"{p.kind}: {p.detail}",
                      Tri.UNKNOWN, p.diagnostics)
    extra = ""
    if d["expected"] and d["expected"] != p.kind:
        extra = f" — WARNING: config declares SENSOR_KIND={d['expected']}"
        return Result("sensor", Outcome.WARN, f"{p.kind}: {p.detail}{extra}",
                      Tri.UNKNOWN, p.diagnostics)
    return Result("sensor", Outcome.PASS, f"{p.kind}: {p.detail}",
                  Tri.FALSE, p.diagnostics)


# ============================================================ system
def check_systemd_services() -> Result:
    units = ["energy-node-collector.service"]
    if enconfig.get_bool("POWERLOG_ENABLED", True):
        units.append("energy-node-powerlog.service")
    bad = [f"{u}={sysinfo.systemd_is_active(u)}" for u in units
           if sysinfo.systemd_is_active(u) != "active"]
    return Result("systemd_services",
                  Outcome.FAIL if bad else Outcome.PASS,
                  "; ".join(bad) if bad else f"{len(units)} unit(s) active",
                  Tri.TRUE if bad else Tri.FALSE, units)


def check_systemd_failed() -> Result:
    try:
        out = subprocess.run(["systemctl", "--failed", "--no-legend", "--plain"],
                             capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        return Result("systemd_failed", Outcome.UNKNOWN, str(exc),
                      Tri.UNKNOWN, None)
    names = [l.split()[0] for l in out.strip().splitlines() if l.strip()]
    ours = [n for n in names if n.startswith("energy-node")]
    if ours:
        return Result("systemd_failed", Outcome.FAIL,
                      f"energy-node units failed: {', '.join(ours)}",
                      Tri.TRUE, names)
    if names:
        return Result("systemd_failed", Outcome.WARN,
                      f"unrelated failed units: {', '.join(names)}",
                      Tri.FALSE, names)
    return Result("systemd_failed", Outcome.PASS, "none", Tri.FALSE, [])


def check_filesystem() -> Result:
    ro = sysinfo.filesystem_readonly("/")
    r = evaluate_boolean("filesystem", ro, fail_on=Tri.TRUE,
                         label="root filesystem read-only")
    if r.outcome is not Outcome.PASS:
        return r
    probe = os.path.join(enconfig.get("EN_STATE_DIR",
                                      "/opt/energy-node/state"), ".doctor")
    try:
        os.makedirs(os.path.dirname(probe), exist_ok=True)
        with open(probe, "w") as fh:
            fh.write("ok")
        os.unlink(probe)
    except OSError as exc:
        return Result("filesystem", Outcome.FAIL,
                      f"mounted rw but NOT writable: {exc}", Tri.TRUE, False)
    return Result("filesystem", Outcome.PASS, "rw and writable", Tri.FALSE,
                  True)


def check_disk() -> Result:
    d = sysinfo.disk("/")
    return evaluate_threshold(
        "disk", d["disk_percent"],
        warn_above=enconfig.get_int("VERIFY_DISK_MAX_PERCENT", 85) - 5,
        fail_above=enconfig.get_int("VERIFY_DISK_MAX_PERCENT", 85),
        unit="%", label="disk used")


def check_memory() -> Result:
    m = sysinfo.memory()
    return evaluate_threshold("memory", m["memory_percent"],
                              warn_above=enconfig.get_int("DOCTOR_MEM_WARN", 85),
                              fail_above=enconfig.get_int("DOCTOR_MEM_FAIL", 95),
                              unit="%", label="memory used")


def check_cpu() -> Result:
    la = sysinfo.loadavg()[0]
    cores = sysinfo.cpu_count()
    per_core = (la / cores) if la is not None and cores else None
    r = evaluate_threshold("cpu", per_core,
                           warn_above=enconfig.get_float("DOCTOR_LOAD_WARN", 1.5),
                           fail_above=enconfig.get_float("DOCTOR_LOAD_FAIL", 3.0),
                           label="load per core")
    if r.outcome is Outcome.PASS and per_core is not None:
        r.detail = f"load {la:.2f} over {cores} cores ({per_core:.2f}/core)"
    return r


def check_temperature() -> Result:
    t = sysinfo.cpu_temperature_c()
    return evaluate_threshold(
        "temperature", t,
        warn_above=enconfig.get_float("DOCTOR_TEMP_WARN", 70),
        fail_above=enconfig.get_float("DOCTOR_TEMP_FAIL", 80),
        unit="C", applicable=t is not None or sysinfo.capabilities()["vcgencmd"],
        skip_reason="no thermal sensor on this board", label="SoC temperature")


def check_undervoltage() -> Result:
    caps = sysinfo.capabilities()
    if not caps["throttled"]:
        return Result("undervoltage", Outcome.SKIP,
                      "vcgencmd get_throttled unavailable on this board",
                      Tri.UNKNOWN, None)
    mask = sysinfo.throttled_mask()
    if mask is None:
        return Result("undervoltage", Outcome.UNKNOWN,
                      "throttle flags unreadable", Tri.UNKNOWN, None)
    flags = sysinfo.decode_throttle(mask)
    live = bool(mask & 0x1)
    ever = bool(mask & 0x10000)
    if live:
        return Result("undervoltage", Outcome.FAIL,
                      f"UNDERVOLTAGE NOW (0x{mask:x} {','.join(flags)})",
                      Tri.TRUE, mask)
    if ever:
        return Result("undervoltage", Outcome.WARN,
                      f"undervoltage has occurred since boot "
                      f"(0x{mask:x} {','.join(flags)}) — sticky until reboot",
                      Tri.FALSE, mask)
    return Result("undervoltage", Outcome.PASS, f"clean (0x{mask:x})",
                  Tri.FALSE, mask)


# ============================================================ data path
def check_collector() -> Result:
    state = sysinfo.systemd_is_active("energy-node-collector.service")
    if state != "active":
        return Result("collector", Outcome.FAIL, f"unit is {state}", Tri.TRUE,
                      state)
    db = enconfig.get("DB_PATH")
    try:
        conn = _ro(db)
        newest = conn.execute("SELECT MAX(captured_at) FROM measurements").fetchone()[0]
        conn.close()
    except sqlite3.Error as exc:
        return Result("collector", Outcome.FAIL, f"cannot read: {exc}",
                      Tri.TRUE, None)
    age = _age_of(newest)
    limit = enconfig.get_int("VERIFY_MEASUREMENT_MAX_AGE", 300)
    r = evaluate_threshold("collector", age, warn_above=limit * 0.6,
                           fail_above=limit, unit="s",
                           label="newest measurement age")
    if r.outcome is Outcome.UNKNOWN:
        r.detail = "no measurements recorded at all"
        r.outcome = Outcome.FAIL
    return r


def check_time_sync() -> Result:
    """Has NTP disciplined the clock since boot?

    A node whose clock has not been corrected yet will stamp measurements with
    a timestamp that can be days wrong, and attribution is by captured_at, so
    the error is silent and permanent once uploaded.
    """
    synced = sysinfo.time_synchronized()
    return evaluate_boolean("time_sync", synced, fail_on=Tri.FALSE,
                            label="clock disciplined by NTP")


def check_sqlite() -> Result:
    db = enconfig.get("DB_PATH")
    try:
        conn = _ro(db)
        res = conn.execute("PRAGMA quick_check").fetchone()[0]
        conn.close()
    except sqlite3.Error as exc:
        return Result("sqlite", Outcome.FAIL, str(exc), Tri.TRUE, None)
    ok = res == "ok"
    size = os.path.getsize(db) / 1e6 if os.path.exists(db) else None
    wal = db + "-wal"
    walmb = os.path.getsize(wal) / 1e6 if os.path.exists(wal) else 0.0
    return Result("sqlite", Outcome.PASS if ok else Outcome.FAIL,
                  f"quick_check={res}, {size:.1f}MB (wal {walmb:.1f}MB)"
                  if size else f"quick_check={res}",
                  Tri.FALSE if ok else Tri.TRUE, res)


def check_buffer() -> Result:
    db = enconfig.get("DB_PATH")
    try:
        conn = _ro(db)
        pending = conn.execute(
            "SELECT COUNT(*) FROM measurements WHERE sync_status=0").fetchone()[0]
        conn.close()
    except sqlite3.Error as exc:
        return Result("buffer", Outcome.UNKNOWN, str(exc), Tri.UNKNOWN, None)
    limit = enconfig.get_int("VERIFY_BUFFER_MAX_PENDING", 500)
    return evaluate_threshold("buffer", pending, warn_above=limit,
                              fail_above=limit * 10, label="unsent rows")


def check_sync_queue() -> Result:
    """Is the backlog draining, or growing? A queue that only grows is a
    failing sync even when its current depth is under the alert threshold."""
    db = enconfig.get("DB_PATH")
    try:
        conn = _ro(db)
        pending = conn.execute(
            "SELECT COUNT(*) FROM measurements WHERE sync_status=0").fetchone()[0]
        oldest = conn.execute(
            "SELECT MIN(captured_at) FROM measurements WHERE sync_status=0"
        ).fetchone()[0]
        conn.close()
    except sqlite3.Error as exc:
        return Result("sync_queue", Outcome.UNKNOWN, str(exc), Tri.UNKNOWN, None)
    if not pending:
        return Result("sync_queue", Outcome.PASS, "queue empty", Tri.FALSE, 0)
    age = _age_of(oldest)
    interval = enconfig.get_int("SYNC_INTERVAL", 60)
    if age is None:
        return Result("sync_queue", Outcome.UNKNOWN,
                      f"{pending} pending, age unknown", Tri.UNKNOWN, pending)
    if age > interval * 10:
        return Result("sync_queue", Outcome.FAIL,
                      f"{pending} pending; oldest {age:.0f}s old "
                      f"(> 10x sync interval) — queue is not draining",
                      Tri.TRUE, pending)
    if age > interval * 3:
        return Result("sync_queue", Outcome.WARN,
                      f"{pending} pending; oldest {age:.0f}s old",
                      Tri.FALSE, pending)
    return Result("sync_queue", Outcome.PASS,
                  f"{pending} pending; oldest {age:.0f}s old (draining)",
                  Tri.FALSE, pending)


# ============================================================ network
def check_ethernet() -> Result:
    return evaluate_boolean("ethernet", sysinfo._iface_up("eth0"),
                            fail_on=Tri.FALSE, applicable=os.path.exists(
                                "/sys/class/net/eth0"),
                            skip_reason="no eth0 on this node",
                            label="eth0")


def check_wifi() -> Result:
    up = sysinfo._iface_up("wlan0")
    r = evaluate_boolean("wifi", up, fail_on=Tri.FALSE,
                         applicable=os.path.exists("/sys/class/net/wlan0"),
                         skip_reason="no wlan0 on this node", label="wlan0")
    # Wi-Fi down is not fatal when Ethernet carries the node.
    if r.outcome is Outcome.FAIL and tri(sysinfo._iface_up("eth0")) is Tri.TRUE:
        return Result("wifi", Outcome.WARN,
                      "wlan0 down (eth0 is up, so not fatal)", Tri.FALSE, False)
    return r


def check_tailscale() -> Result:
    present = os.path.exists("/sys/class/net/tailscale0")
    if not present and not shutil.which("tailscale"):
        return Result("tailscale", Outcome.SKIP, "tailscale not installed",
                      Tri.UNKNOWN, None)
    up = sysinfo._iface_up("tailscale0")
    r = evaluate_boolean("tailscale", up, fail_on=Tri.FALSE,
                         label="tailscale0")
    # Remote access is degraded, not a data-path failure.
    if r.outcome is Outcome.FAIL:
        return Result("tailscale", Outcome.WARN,
                      "tailscale0 down — remote access unavailable "
                      "(measurement path unaffected)", Tri.FALSE, False)
    return r


def check_backend() -> Result:
    if requests is None:
        return Result("backend", Outcome.SKIP, "requests unavailable",
                      Tri.UNKNOWN, None)
    base = enconfig.api_base()
    if not base:
        return Result("backend", Outcome.FAIL, "CENTRAL_API_URL unset",
                      Tri.TRUE, None)
    try:
        t0 = time.time()
        r = requests.get(base + "/health", timeout=10)
        dt = time.time() - t0
    except Exception as exc:
        return Result("backend", Outcome.FAIL, f"{base} unreachable: {exc}",
                      Tri.TRUE, None)
    if r.status_code >= 400:
        return Result("backend", Outcome.FAIL, f"HTTP {r.status_code}",
                      Tri.TRUE, r.status_code)
    return Result("backend", Outcome.PASS, f"{base} HTTP 200 in {dt:.2f}s",
                  Tri.FALSE, round(dt, 3))


def _monitoring_node() -> Optional[dict]:
    if requests is None:
        return None
    try:
        r = requests.get(enconfig.api_base() + "/api/monitoring/status",
                         timeout=15)
        return next((n for n in r.json().get("nodes", [])
                     if n.get("code") == enconfig.node_id()), None)
    except Exception:
        return None


def check_heartbeat(node=None) -> Result:
    if requests is None:
        return Result("heartbeat", Outcome.SKIP, "requests unavailable",
                      Tri.UNKNOWN, None)
    n = node if node is not None else _monitoring_node()
    if n is None:
        return Result("heartbeat", Outcome.FAIL,
                      f"{enconfig.node_id()} absent from monitoring, or "
                      f"monitoring unreachable", Tri.TRUE, None)
    return evaluate_liveness(
        "heartbeat", n.get("heartbeat_age_seconds"),
        ever_seen=n.get("ever_seen"),
        warn_age=enconfig.get_int("VERIFY_HEARTBEAT_MAX_AGE", 180),
        fail_age=enconfig.get_int("VERIFY_HEARTBEAT_MAX_AGE", 180) * 3,
        registered_age_seconds=1e9,   # a node running doctor is long-registered
        label="heartbeat")


def check_monitoring_registration(node=None) -> Result:
    n = node if node is not None else _monitoring_node()
    if n is None:
        return Result("monitoring_registration", Outcome.FAIL,
                      "node not registered or monitoring unreachable",
                      Tri.TRUE, None)
    return Result("monitoring_registration", Outcome.PASS,
                  f"{n.get('code')} lifecycle={n.get('lifecycle')} "
                  f"severity={n.get('severity')} monitored="
                  f"{n.get('lifecycle') == 'commissioned'}",
                  Tri.FALSE, n.get("lifecycle"))


def check_alert_path() -> Result:
    if requests is None:
        return Result("alert_path", Outcome.SKIP, "requests unavailable",
                      Tri.UNKNOWN, None)
    try:
        cfg = requests.get(enconfig.api_base() + "/api/monitoring/config",
                           timeout=15).json()
    except Exception as exc:
        return Result("alert_path", Outcome.FAIL,
                      f"cannot read monitoring config: {exc}", Tri.TRUE, None)
    enabled = tri(cfg.get("enabled"))
    tg = tri((cfg.get("telegram") or {}).get("enabled"))
    if enabled is Tri.TRUE and tg is Tri.TRUE:
        return Result("alert_path", Outcome.PASS,
                      "monitoring enabled, telegram sender enabled",
                      Tri.FALSE, True)
    return Result("alert_path", Outcome.FAIL,
                  f"monitoring={enabled.value} telegram={tg.value}",
                  Tri.TRUE, False)


# ============================================================ package
def check_configuration() -> Result:
    problems = []
    conf = os.environ.get(enconfig.CONF_ENV, enconfig.DEFAULT_CONF)
    if not os.path.exists(conf):
        problems.append(f"missing {conf}")
    node_env = enconfig.get("EN_NODE_ENV", "/opt/energy-node/config/node.env")
    if not os.path.exists(node_env):
        problems.append(f"missing {node_env}")
    for key in ("NODE_ID", "CENTRAL_API_URL", "DB_PATH"):
        if not enconfig.get(key):
            problems.append(f"{key} unset")
    db = enconfig.get("DB_PATH")
    if db and not os.path.exists(db):
        problems.append(f"DB_PATH does not exist: {db}")
    if problems:
        return Result("configuration", Outcome.FAIL, "; ".join(problems),
                      Tri.TRUE, problems)
    return Result("configuration", Outcome.PASS,
                  f"node={enconfig.node_id()} api={enconfig.api_base()} "
                  f"conf={os.path.basename(conf)}", Tri.FALSE, None)


def check_hardening_version() -> Result:
    return version_mod.doctor_result()


def check_recovery_flags() -> Result:
    if recovery_pkg is None:
        return Result("recovery_flags", Outcome.UNKNOWN,
                      "recovery package not importable", Tri.UNKNOWN, None)
    st = recovery_pkg.status()
    on = [n for n, s in st.items() if s.get("experimental") and s.get("enabled")]
    if on:
        return Result("recovery_flags", Outcome.WARN,
                      f"EXPERIMENTAL ENABLED: {', '.join(on)} — these are "
                      f"UNVALIDATED", Tri.TRUE, on)
    exp = [n for n, s in st.items() if s.get("experimental")]
    return Result("recovery_flags", Outcome.PASS,
                  f"all experimental disabled ({', '.join(exp)})",
                  Tri.FALSE, [])


def check_blackbox() -> Result:
    """Report the last classified reboot reason. An unplanned latch is the
    condition that cost 43h37m and 89m; it must be visible, not buried."""
    if not enconfig.get_bool("BLACKBOX_ENABLED", True):
        return Result("blackbox", Outcome.SKIP, "BLACKBOX_ENABLED=0",
                      Tri.UNKNOWN, None)
    try:
        s = blackbox_mod.summary()
    except Exception as exc:
        return Result("blackbox", Outcome.UNKNOWN, f"unreadable: {exc}",
                      Tri.UNKNOWN, None)
    lb = s.get("last_boot")
    if not lb:
        return Result("blackbox", Outcome.UNKNOWN,
                      "no boot recorded yet", Tri.UNKNOWN, None)
    reason = lb.get("reason")
    unplanned = (s.get("counters") or {}).get("unplanned_total", 0)
    detail = (f"{s['recorded_boots']} boots recorded, {unplanned} unplanned; "
              f"last={reason}")
    if reason in ("latch_or_hang", "power_loss"):
        return Result("blackbox", Outcome.WARN,
                      f"{detail} — last restart was NOT planned", Tri.TRUE,
                      reason)
    return Result("blackbox", Outcome.PASS, detail, Tri.FALSE, reason)


# ============================================================ runner
CHECKS = (
    ("configuration", check_configuration),
    ("hardening_version", check_hardening_version),
    ("board", check_board),
    ("i2c", check_i2c),
    ("ups", check_ups),
    ("battery", check_battery),
    ("rtc", check_rtc),
    ("gpio", check_gpio),
    ("watchdog", check_watchdog),
    ("sensor", check_sensor),
    ("systemd_services", check_systemd_services),
    ("systemd_failed", check_systemd_failed),
    ("collector", check_collector),
    ("sqlite", check_sqlite),
    ("buffer", check_buffer),
    ("sync_queue", check_sync_queue),
    ("filesystem", check_filesystem),
    ("time_sync", check_time_sync),
    ("disk", check_disk),
    ("memory", check_memory),
    ("cpu", check_cpu),
    ("temperature", check_temperature),
    ("undervoltage", check_undervoltage),
    ("ethernet", check_ethernet),
    ("wifi", check_wifi),
    ("tailscale", check_tailscale),
    ("backend", check_backend),
    ("heartbeat", check_heartbeat),
    ("monitoring_registration", check_monitoring_registration),
    ("alert_path", check_alert_path),
    ("recovery_flags", check_recovery_flags),
    ("blackbox", check_blackbox),
)


def run_all() -> list:
    results = []
    # Read shared state once so we do not hammer I2C or the backend.
    ups_state = None
    try:
        ups_state = ups_pkg.read()
    except Exception:
        pass
    node = _monitoring_node()

    for name, fn in CHECKS:
        try:
            if name in ("ups", "battery"):
                r = fn(ups_state)
            elif name in ("heartbeat", "monitoring_registration"):
                r = fn(node)
            else:
                r = fn()
        except Exception as exc:
            r = Result(name, Outcome.UNKNOWN, f"check crashed: {exc}",
                       Tri.UNKNOWN, None)
        results.append(r)
    return results


def to_json(results: list) -> dict:
    counts = {o.value: sum(1 for r in results if r.outcome is o)
              for o in Outcome}
    return {
        "schema": "energy-node.doctor/1",
        "node_id": enconfig.node_id(),
        "hostname": sysinfo.hostname(),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "hardening_version": version_mod.installed_version(),
        "doctor_version": __version__,
        "overall": worst(results).value,
        "ok": not any(r.outcome is Outcome.FAIL for r in results),
        "counts": counts,
        "checks": [r.as_dict() for r in results],
    }
