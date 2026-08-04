"""Monitoring configuration.

Configuration is layered, lowest precedence first:

1. The typed defaults in this module.
2. ``monitoring_config.json`` next to the backend working directory, so an
   operator can retune thresholds without touching code or redeploying.
3. Environment variables, for secrets only (tokens, chat ids), so credentials
   never live in a file that could be copied into a backup or a tarball.

Everything the rest of the package reads comes from :func:`get_config`. No
module hardcodes a threshold, an interval or a recipient.

Thresholds default to the values already used by the platform
(``runtime_platform_settings.json``) rather than invented numbers, so the
monitoring system and the rest of the application agree on what "abnormal"
means.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, TypeVar

# The backend runs with CWD=/home/manager/energy-platform/backend (systemd
# WorkingDirectory), which is also where energy_platform.db and
# runtime_platform_settings.json live. Keep the monitoring config beside them.
CONFIG_FILE = Path("monitoring_config.json")

# Loaded once at import; the platform's own operational thresholds.
PLATFORM_SETTINGS_FILE = Path("runtime_platform_settings.json")


@dataclass
class TelegramConfig:
    """Telegram delivery settings.

    The token and chat id are deliberately *not* given defaults here: they are
    read from the environment so they never appear in a config file.
    """

    enabled: bool = True
    bot_token: str = ""
    chat_id: str = ""
    #: Telegram rejects messages over 4096 characters; longer reports are split.
    max_message_chars: int = 3900
    #: Seconds to wait on the Telegram HTTP API before treating a send as failed.
    timeout_seconds: float = 15.0
    parse_mode: str = "HTML"


@dataclass
class HeartbeatConfig:
    """Node heartbeat expectations and the missed-beat escalation ladder."""

    #: How often a node is expected to report. Nodes send every 30-60s; the
    #: grace multiplier below absorbs jitter, so this is the nominal period.
    interval_seconds: int = 60
    #: A beat is only counted as missed after interval * grace has elapsed,
    #: so a node that is merely late does not trip a warning.
    grace_multiplier: float = 1.5
    #: Missed-beat counts at which severity escalates. Keys are counts.
    missed_warning: int = 2
    missed_error: int = 5
    missed_critical: int = 10
    #: Missed beats after which the node is considered lost rather than late,
    #: used to phrase recovery messages ("was offline", not "was late").
    missed_emergency: int = 30
    #: Heartbeat rows are pruned beyond this age; the latest row per node is
    #: kept indefinitely in node_heartbeat_latest regardless.
    retention_days: int = 14


@dataclass
class EscalationConfig:
    """Duration-based severity escalation for any open alert.

    Independent of the missed-heartbeat ladder: a problem that persists gets
    louder even if its underlying rule never changes its own severity.
    """

    #: Minutes an alert must stay open before being promoted to each level.
    warning_after_minutes: int = 1
    error_after_minutes: int = 5
    critical_after_minutes: int = 15
    emergency_after_minutes: int = 60
    #: Once an alert is at its terminal severity, remind at this cadence so a
    #: long outage is not forgotten. 0 disables reminders.
    reminder_every_minutes: int = 60


@dataclass
class ServerThresholds:
    """Server-side resource limits. Percentages unless stated otherwise."""

    cpu_warning: float = 80.0
    cpu_critical: float = 95.0
    memory_warning: float = 85.0
    memory_critical: float = 95.0
    swap_warning: float = 50.0
    swap_critical: float = 80.0
    disk_warning: float = 80.0
    disk_critical: float = 90.0
    #: Load average per core.
    load_warning: float = 2.0
    load_critical: float = 4.0
    #: iowait percentage sustained over one sample interval.
    iowait_warning: float = 20.0
    iowait_critical: float = 40.0
    temperature_warning_c: float = 75.0
    temperature_critical_c: float = 85.0
    #: Seconds. Backend API self-probe latency.
    api_latency_warning: float = 2.0
    api_latency_critical: float = 5.0


@dataclass
class NodeThresholds:
    """Per-node health limits, evaluated against heartbeat payloads."""

    cpu_warning: float = 85.0
    cpu_critical: float = 95.0
    memory_warning: float = 85.0
    memory_critical: float = 95.0
    disk_warning: float = 80.0
    disk_critical: float = 90.0
    #: Raspberry Pi SoC throttles at 80 C and hard-limits at 85 C.
    temperature_warning_c: float = 70.0
    temperature_critical_c: float = 80.0
    #: Buffered readings awaiting upload.
    buffer_warning: int = 500
    buffer_critical: int = 5000
    #: Local SQLite buffer size in megabytes.
    sqlite_size_warning_mb: float = 200.0
    sqlite_size_critical_mb: float = 500.0
    #: WAL that never checkpoints indicates a stuck writer.
    wal_size_warning_mb: float = 50.0
    #: Seconds of clock difference between node and server.
    clock_drift_warning_s: float = 30.0
    clock_drift_critical_s: float = 300.0
    #: Round-trip latency to the backend, milliseconds.
    latency_warning_ms: float = 500.0
    latency_critical_ms: float = 2000.0
    #: Seconds without a stored measurement before the sensor path is suspect.
    measurement_stale_warning_s: int = 300
    measurement_stale_critical_s: int = 900


@dataclass
class AlertPolicy:
    """How much evidence a condition needs before it reaches a person.

    Added after three days of production traffic produced 1,386 messages, of
    which 962 came from a single threshold flapping across the boundary of
    normal operation. Two mechanisms fix that class of failure:

    *Sustain* — a condition must hold for a while before anyone is told. A
    breach lasting one poll interval is a load transient, not an incident.
    Measured: 404 of 472 current alerts lasted under two minutes.

    *Hysteresis* — once open, an alert does not close the instant the value
    dips back. Without this, a value oscillating around the threshold produces
    an endless open/resolve stream (two messages per cycle).
    """

    #: Default seconds a condition must persist before notifying. Rules may
    #: raise this individually; genuinely urgent rules set it to 0.
    default_sustain_seconds: int = 600
    #: Seconds a condition must be *absent* before the alert resolves.
    #: Suppresses the resolve/re-open flap.
    resolve_after_seconds: int = 900
    #: Fraction of the trigger threshold a value must fall below to count as
    #: recovered. 0.9 means a 250 A trigger clears at 225 A.
    hysteresis_ratio: float = 0.90


@dataclass
class ElectricalThresholds:
    """Electrical limits.

    Defaults mirror ``runtime_platform_settings.json`` so monitoring agrees
    with the anomaly engine and the settings page. Mexican LV service is
    127/220 V at 60 Hz.
    """

    nominal_voltage: float = 127.0
    #: Percent deviation from nominal before warning / critical.
    #: Widened from 10/20 to 13/20: CFE's own service tolerance for LV supply
    #: is ±10%, and alerting at exactly the contractual edge means alerting on
    #: supply that is technically compliant.
    voltage_deviation_warning: float = 13.0
    voltage_deviation_critical: float = 20.0
    nominal_frequency_hz: float = 60.0
    frequency_deviation_warning: float = 0.5
    frequency_deviation_critical: float = 1.0

    # --- Current -----------------------------------------------------------
    #: Absolute amperage limits. These are a *safety floor*, not the primary
    #: signal: the primary signal is the node's own learned baseline (below).
    #: The old 200 A default sat at roughly the 94th percentile of N001's
    #: normal operation and fired 471 times in three days.
    current_warning: float = 400.0
    current_critical: float = 500.0
    #: Per-node hard limits, keyed by node code — the panel or CT rating where
    #: it is known. This is the correct source for a current threshold and
    #: overrides everything else. Example: {"N001": 250.0}
    current_limit_by_node: dict[str, float] = field(default_factory=dict)
    #: Fraction of the per-node limit at which to warn (0.9 = 90% of rating).
    current_limit_warning_ratio: float = 0.90

    #: When no explicit rating exists, derive the threshold from the node's own
    #: history: alert only above this percentile of its trailing distribution,
    #: multiplied by the margin below. Percentile 99.5 with a 1.15 margin puts
    #: the trigger meaningfully outside anything the panel normally does.
    baseline_percentile: float = 99.5
    baseline_margin: float = 1.15
    #: Minimum samples before a learned baseline is trusted. Below this the
    #: rule stays silent rather than guessing.
    baseline_min_samples: int = 500

    # --- Power factor ------------------------------------------------------
    #: Lowered from 0.90. Alerts fired at 0.89 against a 0.90 threshold —
    #: indistinguishable from noise. 0.85 is where GDMTH penalties begin to
    #: matter, so it is the first value with a financial consequence.
    power_factor_warning: float = 0.85
    power_factor_critical: float = 0.70
    #: Percent spread between phases before an imbalance is flagged.
    voltage_imbalance_warning: float = 2.0
    voltage_imbalance_critical: float = 5.0
    current_imbalance_warning: float = 10.0
    current_imbalance_critical: float = 25.0
    #: Imbalance is only meaningful under real load. Below this current the
    #: readings are ADC noise (observed at ~1e-5 A on an idle panel), and the
    #: percentage spread between noise samples is arbitrarily large — computing
    #: it produced a constant false CRITICAL before this floor was added.
    imbalance_min_current_a: float = 1.0
    #: Percent change against the trailing baseline before a spike is even
    #: considered. Raised from 25%: a university panel routinely moves 25-35%
    #: when air conditioning or machinery starts, and every one of those became
    #: a notification. A spike now also has to be *sustained* and outside the
    #: node's own historical variability before anyone is told.
    consumption_spike_pct: float = 100.0
    consumption_drop_pct: float = 70.0
    #: Standard deviations above the trailing mean required in addition to the
    #: percentage. This is what makes "abnormal" relative to the panel's own
    #: behaviour rather than an arbitrary constant.
    consumption_spike_sigma: float = 4.0
    #: Contracted demand in kW, per node code. A spike that threatens the
    #: contracted limit is the case that genuinely costs money, so it alerts
    #: even when the percentage is modest. Example: {"N001": 100.0}
    contracted_demand_kw: dict[str, float] = field(default_factory=dict)
    #: Fraction of contracted demand that triggers a warning.
    contracted_demand_ratio: float = 0.90
    #: A phase reading below this voltage is treated as missing, not merely low.
    missing_phase_voltage: float = 40.0
    #: Reverse power is only reported below -this value. An idle meter reports
    #: tiny negative noise (~1e-9 kW); a bare sign test called that "reverse
    #: power flow" on a perfectly healthy panel.
    reverse_power_deadband_kw: float = 0.05
    #: Readings outside these absolute bounds are impossible, not anomalous.
    impossible_voltage_max: float = 500.0
    impossible_current_max: float = 2000.0


@dataclass
class DatabaseThresholds:
    """Database growth and responsiveness limits."""

    size_warning_mb: float = 2000.0
    size_critical_mb: float = 5000.0
    #: A WAL this large means checkpoints are not completing.
    wal_warning_mb: float = 100.0
    wal_critical_mb: float = 500.0
    #: Seconds for the probe query used to detect locks and slow queries.
    query_warning_seconds: float = 1.0
    query_critical_seconds: float = 5.0


@dataclass
class QuietHours:
    """Suppression window for non-urgent notifications.

    CRITICAL and EMERGENCY always break through: quiet hours must never hide a
    real outage, only routine noise.
    """

    enabled: bool = False
    #: Local hour (0-23) the window opens and closes. Wraps across midnight.
    start_hour: int = 22
    end_hour: int = 7
    #: Severities suppressed during the window.
    suppress_at_or_below: str = "WARNING"


@dataclass
class NotificationConfig:
    """Delivery behaviour shared by every channel."""

    #: Hard ceiling on messages per hour across all channels, so a storm of
    #: distinct alerts cannot flood the recipient.
    max_messages_per_hour: int = 60
    #: Outbox retry backoff, seconds. Index = attempt number, last value repeats.
    retry_backoff_seconds: tuple[int, ...] = (10, 30, 60, 300, 900, 1800)
    #: An undeliverable message is abandoned after this many attempts, but the
    #: row is retained and marked failed. Nothing is ever deleted silently.
    max_attempts: int = 12
    #: Delivered/failed outbox rows older than this are pruned.
    retention_days: int = 30


@dataclass
class ReportConfig:
    """Scheduled status report."""

    enabled: bool = True
    #: Minute of each hour at which the report is composed and sent.
    minute_of_hour: int = 0
    #: Send the report even when nothing is wrong. Disabling makes the report
    #: exception-only, which is quieter but loses the "still alive" signal.
    send_when_healthy: bool = True


@dataclass
class SchedulerConfig:
    """Monitoring loop cadence."""

    #: How often the rule engine evaluates everything, seconds.
    check_interval_seconds: int = 60
    #: How often the server records its own heartbeat, seconds.
    server_heartbeat_seconds: int = 60
    #: How often the outbox is drained, seconds.
    outbox_interval_seconds: int = 20
    #: The scheduler writes a liveness file at this path; a stale file means
    #: monitoring itself has died and is reported on the next start.
    watchdog_file: str = "monitoring_watchdog.json"
    #: Seconds after which the watchdog file is considered stale.
    watchdog_stale_seconds: int = 300


@dataclass
class StorageConfig:
    """Retention for monitoring's own tables."""

    alert_retention_days: int = 365
    alert_event_retention_days: int = 365
    server_heartbeat_retention_days: int = 30
    #: How often retention runs, in scheduler ticks.
    prune_every_ticks: int = 60


@dataclass
class MonitoringConfig:
    """Root configuration object."""

    enabled: bool = True
    #: IANA timezone used for every human-facing timestamp. The database stores
    #: UTC throughout; only presentation is localised.
    timezone: str = "America/Mexico_City"
    #: Name shown in alerts to identify this deployment.
    deployment_name: str = "University Energy Intelligence Platform"
    #: Base URL the monitoring service uses to self-probe the API.
    api_base_url: str = "http://127.0.0.1:8010"
    #: Systemd units whose state is reported.
    watched_services: tuple[str, ...] = (
        "energy-platform-backend.service",
        "energy-platform-frontend.service",
    )
    #: Filesystem mount points checked for capacity.
    watched_mounts: tuple[str, ...] = ("/",)
    #: Host used to confirm outbound internet, and the DNS name resolved.
    internet_probe_host: str = "1.1.1.1"
    dns_probe_name: str = "api.telegram.org"

    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    heartbeat: HeartbeatConfig = field(default_factory=HeartbeatConfig)
    escalation: EscalationConfig = field(default_factory=EscalationConfig)
    policy: AlertPolicy = field(default_factory=AlertPolicy)
    server: ServerThresholds = field(default_factory=ServerThresholds)
    node: NodeThresholds = field(default_factory=NodeThresholds)
    electrical: ElectricalThresholds = field(default_factory=ElectricalThresholds)
    database: DatabaseThresholds = field(default_factory=DatabaseThresholds)
    quiet_hours: QuietHours = field(default_factory=QuietHours)
    notifications: NotificationConfig = field(default_factory=NotificationConfig)
    report: ReportConfig = field(default_factory=ReportConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)

    #: Rule ids that are administratively disabled. A disabled rule is not
    #: evaluated at all, and any alert it owns is closed on the next tick.
    disabled_rules: tuple[str, ...] = ()

    #: Severity at which a report-only rule breaks out and notifies anyway.
    #: Report-only is a statement about the *routine* case, not a permanent gag:
    #: a power factor of 0.89 is noise, but 0.55 is a real problem on the same
    #: metric, and muting it because its rule is usually boring would be a
    #: monitoring failure.
    report_only_escalates_at: str = "CRITICAL"

    #: Rule ids that are evaluated and recorded, but never sent to a channel.
    #: They appear in the status report and the alerts API. This is the
    #: "interesting, not urgent" tier — the answer to "would I get out of bed
    #: at 3 AM for this?" being no.
    report_only_rules: tuple[str, ...] = (
        # Electrical conditions worth seeing in context, never worth a push.
        "electrical.consumption_spike",
        "electrical.consumption_drop",
        "electrical.power_factor",
        "electrical.current_imbalance",
        "electrical.voltage_imbalance",
        "electrical.reverse_energy",
        # Fleet state that changes on human timescales.
        "node.heartbeat_never",
        "node.standby",
        "node.latency",
        "node.sqlite_size",
        "node.sqlite_wal",
        "node.cpu_percent",
        "node.memory_percent",
        "node.access_point",
        "node.internet",
        "node.clock_drift",
        # An accessory being unplugged is not an incident.
        "smart_plug.offline",
        "smart_plug.overtemperature",
        "node.shelly_unreachable",
        # Server telemetry that is diagnostic context, not a page.
        "server.cpu",
        "server.load",
        "server.iowait",
        "server.memory",
        "server.swap",
        "server.failed_units",
        "server.reboot_required",
        "server.time_sync",
        "backend.api_latency",
        "database.size",
        "network.tailscale",
        "server.firewall",
    )

    #: Explicit lifecycle override per node code, e.g. {"N003": "retired"}.
    #: Values: active, commissioning, standby, maintenance, retired, offline.
    node_lifecycle: dict[str, str] = field(default_factory=dict)

    #: Seconds of total silence (no heartbeat, no readings) after which a node
    #: with no active deployment is considered switched off rather than broken.
    #: Six hours: long enough to survive a network outage, short enough that a
    #: shelved node stops alerting the same working day.
    lifecycle_offline_after_seconds: int = 21600


T = TypeVar("T")


def _coerce(value: Any, target_type: Any) -> Any:
    """Best-effort coercion of a JSON value to the dataclass field type.

    JSON has no tuple and no int/float distinction worth relying on, so tuples
    arrive as lists and numbers arrive loosely typed. Anything that cannot be
    coerced is returned unchanged rather than raising: a malformed config entry
    must not prevent monitoring from starting.
    """
    origin = getattr(target_type, "__origin__", None)
    if origin is tuple:
        return tuple(value) if isinstance(value, (list, tuple)) else value
    if target_type is bool:
        return bool(value)
    if target_type is int and isinstance(value, (int, float, str)):
        try:
            return int(value)
        except (TypeError, ValueError):
            return value
    if target_type is float and isinstance(value, (int, float, str)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    if target_type is str:
        return str(value)
    return value


def _apply_overrides(instance: T, overrides: dict[str, Any]) -> T:
    """Recursively apply a plain dict onto a dataclass instance, in place.

    Unknown keys are ignored so a config file written for a newer version does
    not break an older one.
    """
    if not isinstance(overrides, dict):
        return instance

    by_name = {f.name: f for f in fields(instance)}  # type: ignore[arg-type]
    for key, value in overrides.items():
        spec = by_name.get(key)
        if spec is None:
            continue
        current = getattr(instance, key)
        if is_dataclass(current) and isinstance(value, dict):
            _apply_overrides(current, value)
        else:
            setattr(instance, key, _coerce(value, spec.type))
    return instance


def _platform_threshold_overrides() -> dict[str, Any]:
    """Deliberately empty. Monitoring owns its own alerting thresholds.

    This previously inherited ``runtime_platform_settings.json`` so the
    Settings page and monitoring would "agree". That turned out to be the wrong
    call, and it was the direct cause of the worst noise in the first
    production run:

    * ``maxCurrent: 200`` sat at roughly the **94th percentile** of N001's
      normal operation. It produced 471 alerts and 962 Telegram messages in
      three days.
    * ``minPowerFactor: 0.90`` produced alerts at 0.89 — indistinguishable from
      measurement noise.
    * ``demandSpike: 25`` fired on every air-conditioning start.

    Those values are **display and anomaly-shading defaults for the UI**, not
    statements about operational risk. Paging a human is a different decision
    from colouring a chart, and it deserves its own thresholds: a panel rating
    where one is known, otherwise the node's own learned envelope.

    Kept as a function rather than deleted so the layering in
    :func:`load_config` stays explicit, and so re-enabling a *specific*
    inherited value later is a one-line change with this rationale attached.
    """
    return {}


def _env_overrides() -> dict[str, Any]:
    """Secrets and per-host settings from the environment.

    Only credentials and host-specific values are read here. Thresholds stay in
    the JSON file where they are reviewable.
    """
    out: dict[str, Any] = {}
    telegram: dict[str, Any] = {}

    token = os.getenv("MONITORING_TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    if token:
        telegram["bot_token"] = token.strip()

    chat_id = os.getenv("MONITORING_TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
    if chat_id:
        telegram["chat_id"] = chat_id.strip()

    if os.getenv("MONITORING_TELEGRAM_ENABLED") is not None:
        telegram["enabled"] = os.getenv("MONITORING_TELEGRAM_ENABLED", "").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

    if telegram:
        out["telegram"] = telegram

    if os.getenv("MONITORING_ENABLED") is not None:
        out["enabled"] = os.getenv("MONITORING_ENABLED", "").lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

    if os.getenv("MONITORING_API_BASE_URL"):
        out["api_base_url"] = os.getenv("MONITORING_API_BASE_URL", "")

    if os.getenv("MONITORING_TIMEZONE"):
        out["timezone"] = os.getenv("MONITORING_TIMEZONE", "")

    return out


_cached: MonitoringConfig | None = None


def load_config() -> MonitoringConfig:
    """Build a fresh configuration from all layers.

    Never raises. A missing or malformed config file degrades to defaults,
    because monitoring that refuses to start is worse than monitoring with
    default thresholds.
    """
    config = MonitoringConfig()

    _apply_overrides(config, _platform_threshold_overrides())

    if CONFIG_FILE.exists():
        try:
            _apply_overrides(config, json.loads(CONFIG_FILE.read_text()))
        except (OSError, ValueError):
            # Malformed file: keep defaults rather than crash. The rule engine
            # raises a self-monitoring alert about it separately.
            pass

    _apply_overrides(config, _env_overrides())
    return config


def get_config(refresh: bool = False) -> MonitoringConfig:
    """Return the process-wide configuration.

    Cached, because it is read on every rule evaluation. Pass ``refresh=True``
    to pick up an edited config file without restarting the service.
    """
    global _cached
    if _cached is None or refresh:
        _cached = load_config()
    return _cached


def config_as_dict(config: MonitoringConfig | None = None) -> dict[str, Any]:
    """Serialise the configuration, redacting secrets.

    Used by the API so the settings can be inspected from the frontend without
    exposing the bot token.
    """
    config = config or get_config()

    def _dump(obj: Any) -> Any:
        if is_dataclass(obj):
            return {f.name: _dump(getattr(obj, f.name)) for f in fields(obj)}
        if isinstance(obj, tuple):
            return list(obj)
        return obj

    data = _dump(config)
    telegram = data.get("telegram") or {}
    if telegram.get("bot_token"):
        telegram["bot_token"] = "***redacted***"
    if telegram.get("chat_id"):
        # Keep the last 4 digits so an operator can confirm which chat is
        # configured without the value being useful if the response leaks.
        telegram["chat_id"] = "***" + str(telegram["chat_id"])[-4:]
    return data


def write_default_config_file(path: Path | None = None) -> Path:
    """Materialise a fully-populated config file for an operator to edit.

    Secrets are omitted deliberately: they belong in the environment.
    """
    target = path or CONFIG_FILE
    data = config_as_dict(MonitoringConfig())
    data.pop("telegram", None)
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return target


__all__ = [
    "DatabaseThresholds",
    "ElectricalThresholds",
    "EscalationConfig",
    "HeartbeatConfig",
    "MonitoringConfig",
    "NodeThresholds",
    "NotificationConfig",
    "QuietHours",
    "ReportConfig",
    "SchedulerConfig",
    "ServerThresholds",
    "StorageConfig",
    "TelegramConfig",
    "config_as_dict",
    "get_config",
    "load_config",
    "write_default_config_file",
]
