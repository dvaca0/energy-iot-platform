"""The monitoring runtime.

Runs as its own process, not inside gunicorn. Two reasons, both operational:

* The backend runs ``-w 1`` today. If it ever becomes ``-w 4``, an in-process
  scheduler would evaluate every rule four times and send four copies of every
  alert. Nothing in the alert engine could tell those apart, because they would
  be genuinely concurrent writers of the same fingerprint.
* Monitoring that lives inside the thing it monitors cannot report that thing
  dying. A separate process observes a backend crash and says so.

Self-monitoring
---------------
The scheduler writes a watchdog file every tick. On startup it reads the
previous one: a stale timestamp means monitoring was not running for that
period, and a gap alert is raised for the window nobody was watching. This is
the answer to "who watches the watchman" — the watchman writes down when he was
awake, and notices on waking that he was not.

Every tick is wrapped so a failure in one phase cannot stop the others. In
particular, the outbox is drained even when rule evaluation fails, because a
queued CRITICAL must still reach Telegram if the thing that broke is a rule.
"""

from __future__ import annotations

import json
import logging
import signal
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.monitoring import lifecycle
from app.monitoring.alerts import process_findings
from app.monitoring.config import MonitoringConfig, get_config
from app.monitoring.models import ServerHeartbeat
from app.monitoring.notifications import dispatch_pending, enqueue, notify_alerts
from app.monitoring.rules import RuleContext, evaluate_all
from app.monitoring.severity import Severity
from app.monitoring.storage import create_tables, prune_old_rows, session_scope

log = logging.getLogger("monitoring.scheduler")


class MonitoringScheduler:
    """Periodic evaluation loop."""

    def __init__(self, config: MonitoringConfig | None = None) -> None:
        self.config = config or get_config()
        self._stop = threading.Event()
        self._tick = 0
        self._last_report_hour: int | None = None
        self._started_at = datetime.utcnow()

    # -- lifecycle --------------------------------------------------------

    def stop(self) -> None:
        """Ask the loop to exit after the current tick."""
        self._stop.set()

    def run(self) -> None:
        """Run until stopped. Blocks."""
        log.info("Monitoring scheduler starting")

        created = create_tables()
        if created:
            log.info("Created tables: %s", ", ".join(created))

        self._check_previous_shutdown()

        interval = max(10, self.config.scheduler.check_interval_seconds)

        while not self._stop.is_set():
            started = time.monotonic()
            self._tick += 1

            try:
                self.tick()
            except Exception:  # noqa: BLE001 - the loop must never die
                log.exception("Tick %d failed", self._tick)
                self._report_self_failure()

            elapsed = time.monotonic() - started
            # Subtract the work time so cadence stays true rather than drifting
            # by however long each tick took.
            self._stop.wait(max(1.0, interval - elapsed))

        log.info("Monitoring scheduler stopped")

    # -- one iteration ----------------------------------------------------

    def tick(self, now: datetime | None = None) -> dict[str, Any]:
        """One full evaluation cycle."""
        from app.monitoring.health import collect_server_snapshot
        from app.monitoring.heartbeat import collect_node_state
        from app.monitoring.metrics import collect_metrics

        now = now or datetime.utcnow()
        summary: dict[str, Any] = {"tick": self._tick, "at": now.isoformat()}

        # Collected outside the transaction: probing takes seconds and holding
        # a SQLite write transaction open that long would block ingestion.
        server = collect_server_snapshot(self.config)

        with session_scope() as session:
            nodes = collect_node_state(session, self.config, now)
            # Classify every node before any rule runs, so all rules share one
            # view of what each node is supposed to be doing.
            lifecycle.annotate(session, nodes, self.config, now)
            metrics = collect_metrics(session, self.config, now)

            context = RuleContext(
                session=session,
                config=self.config,
                now=now,
                server=server,
                nodes=nodes,
                metrics=metrics,
            )

            findings = evaluate_all(context)
            summary["findings"] = len(findings)
            summary["problems"] = sum(1 for f in findings if f.is_problem)

            transitions = process_findings(session, findings, now=now, config=self.config)
            summary["transitions"] = len(transitions)

            queued = notify_alerts(session, transitions, now=now, config=self.config)
            summary["queued"] = queued

            self._record_server_heartbeat(session, server, now)

            if self._report_due(now):
                self._queue_report(session, server, nodes, metrics, findings, now)
                summary["report"] = True

            if self._tick % max(1, self.config.storage.prune_every_ticks) == 0:
                summary["pruned"] = prune_old_rows(session, now)

        # Delivery runs in its own transaction so a channel that blocks cannot
        # hold the evaluation write lock, and so a queued alert still goes out
        # if the evaluation transaction had to roll back.
        with session_scope() as session:
            summary["delivery"] = dispatch_pending(session, config=self.config, now=now)

        self._write_watchdog(now, summary)
        log.info("Tick %d: %s", self._tick, summary)
        return summary

    # -- periodic report --------------------------------------------------

    def _report_due(self, now: datetime) -> bool:
        """True once per hour, at or after the configured minute."""
        if not self.config.report.enabled:
            return False
        if now.minute < self.config.report.minute_of_hour:
            return False
        if self._last_report_hour == now.hour:
            return False
        return True

    def _queue_report(
        self,
        session,
        server: dict[str, Any],
        nodes: dict[str, Any],
        metrics: dict[str, Any],
        findings: list,
        now: datetime,
    ) -> None:
        from app.monitoring.status import build_status, render_report

        status = build_status(
            session,
            server=server,
            nodes=nodes,
            metrics=metrics,
            findings=findings,
            config=self.config,
            now=now,
        )

        if not self.config.report.send_when_healthy and status["overall"] == "OK":
            self._last_report_hour = now.hour
            return

        message = render_report(status, self.config)
        enqueue(
            session,
            message,
            dedupe_key=f"report:{now:%Y%m%d%H}",
            now=now,
            config=self.config,
            # The report is the periodic proof of life. Rate limiting it would
            # mean an alert storm silences the one message that summarises it.
            bypass_policy=True,
        )
        self._last_report_hour = now.hour

    # -- self monitoring --------------------------------------------------

    def _watchdog_path(self) -> Path:
        return Path(self.config.scheduler.watchdog_file)

    def _write_watchdog(self, now: datetime, summary: dict[str, Any]) -> None:
        """Record that monitoring was alive at this moment."""
        try:
            self._watchdog_path().write_text(
                json.dumps(
                    {
                        "updated_at": now.isoformat(),
                        "started_at": self._started_at.isoformat(),
                        "tick": self._tick,
                        "pid": __import__("os").getpid(),
                        "last_summary": summary,
                    },
                    default=str,
                )
            )
        except OSError:
            log.warning("Could not write watchdog file", exc_info=True)

    def _check_previous_shutdown(self) -> None:
        """Detect and report a period where monitoring was not running.

        A gap here means alerts were not being evaluated and problems could
        have come and gone unseen. That is worth saying out loud, because the
        absence of alerts during the gap does not mean the absence of problems.
        """
        path = self._watchdog_path()
        if not path.exists():
            log.info("No previous watchdog file; first start")
            return

        try:
            data = json.loads(path.read_text())
            last = datetime.fromisoformat(data["updated_at"])
        except (OSError, ValueError, KeyError):
            log.warning("Watchdog file unreadable; treating as first start")
            return

        gap = (datetime.utcnow() - last).total_seconds()
        if gap < self.config.scheduler.watchdog_stale_seconds:
            return

        log.warning("Monitoring was not running for %.0f seconds", gap)

        from app.monitoring.channels import OutboundMessage
        from app.monitoring.notifications import humanize_duration

        body = (
            f"⚠️ <b>WARNING</b>\n"
            f"<b>Monitoring was not running</b>\n\n"
            f"<b>Gap:</b> {humanize_duration(gap)}\n"
            f"<b>Last seen:</b> {last.isoformat()}\n"
            f"<b>Resumed:</b> {datetime.utcnow().isoformat()}\n\n"
            f"No checks were evaluated during this window, so any problem that "
            f"started and ended within it was not reported.\n\n"
            f"<b>Check first</b>\n"
            f"<code>systemctl status energy-platform-monitoring.service</code>\n"
            f"<code>journalctl -u energy-platform-monitoring.service -n 100</code>"
        )

        try:
            with session_scope() as session:
                enqueue(
                    session,
                    OutboundMessage(
                        body=body,
                        html_body=body,
                        severity=Severity.WARNING,
                        subject="Monitoring gap detected",
                        kind="selftest",
                    ),
                    dedupe_key=f"monitoring-gap:{last.isoformat()}",
                    bypass_policy=True,
                    config=self.config,
                )
        except Exception:  # noqa: BLE001
            log.exception("Could not queue monitoring-gap notification")

    def _report_self_failure(self) -> None:
        """Queue an alert about the scheduler's own failure.

        Best-effort by definition: if the database is the thing that broke,
        this cannot be persisted, and the journal is the remaining record.
        """
        import traceback

        from app.monitoring.channels import OutboundMessage

        body = (
            f"❌ <b>ERROR</b>\n"
            f"<b>Monitoring tick failed</b>\n\n"
            f"<b>Tick:</b> {self._tick}\n"
            f"<b>When:</b> {datetime.utcnow().isoformat()}\n\n"
            f"<pre>{traceback.format_exc(limit=8)[:1500]}</pre>"
        )

        try:
            with session_scope() as session:
                enqueue(
                    session,
                    OutboundMessage(
                        body=body,
                        html_body=body,
                        severity=Severity.ERROR,
                        subject="Monitoring tick failed",
                        kind="selftest",
                    ),
                    dedupe_key=f"tick-failure:{datetime.utcnow():%Y%m%d%H%M}",
                    bypass_policy=True,
                    config=self.config,
                )
        except Exception:  # noqa: BLE001
            log.exception("Could not persist self-failure alert")

    def _record_server_heartbeat(
        self, session, server: dict[str, Any], now: datetime
    ) -> None:
        """Persist the server's own health snapshot."""
        disks = server.get("disks") or {}
        root = disks.get("/") or next(iter(disks.values()), {})
        database = server.get("database") or {}
        api = server.get("api") or {}

        session.add(
            ServerHeartbeat(
                recorded_at=now,
                cpu_percent=(server.get("cpu") or {}).get("percent"),
                memory_percent=(server.get("memory") or {}).get("percent"),
                swap_percent=(server.get("memory") or {}).get("swap_percent"),
                disk_percent=root.get("percent"),
                disk_free_gb=root.get("free_gb"),
                load_1=(server.get("load") or {}).get("load_1"),
                load_5=(server.get("load") or {}).get("load_5"),
                load_15=(server.get("load") or {}).get("load_15"),
                iowait_percent=(server.get("cpu") or {}).get("iowait"),
                temperature_c=(server.get("temperature") or {}).get("celsius"),
                uptime_seconds=(server.get("uptime") or {}).get("uptime_seconds"),
                db_size_mb=database.get("db_mb"),
                db_wal_mb=database.get("wal_mb"),
                db_query_seconds=database.get("query_seconds"),
                api_ok=api.get("ok"),
                api_latency_seconds=api.get("latency_seconds"),
                internet_ok=(server.get("internet") or {}).get("ok"),
                dns_ok=(server.get("dns") or {}).get("ok"),
                time_synchronized=(server.get("time_sync") or {}).get("synchronized"),
                reboot_required=(server.get("reboot") or {}).get("required"),
                raw_payload=json.dumps(server, default=str)[:200000],
            )
        )


def watchdog_status(config: MonitoringConfig | None = None) -> dict[str, Any]:
    """Whether the scheduler is currently alive, for the API.

    Lets the backend report on the monitoring service even though it does not
    run it — which is how a user finds out that monitoring is down rather than
    that everything is fine.
    """
    config = config or get_config()
    path = Path(config.scheduler.watchdog_file)

    if not path.exists():
        return {"running": False, "reason": "watchdog file does not exist"}

    try:
        data = json.loads(path.read_text())
        last = datetime.fromisoformat(data["updated_at"])
    except (OSError, ValueError, KeyError) as exc:
        return {"running": False, "reason": f"watchdog file unreadable: {exc}"}

    age = (datetime.utcnow() - last).total_seconds()
    return {
        "running": age < config.scheduler.watchdog_stale_seconds,
        "last_tick_at": last.isoformat(),
        "age_seconds": round(age, 1),
        "tick": data.get("tick"),
        "pid": data.get("pid"),
        "started_at": data.get("started_at"),
    }


def main() -> int:
    """Entry point for the systemd service."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # The scheduler is a separate process from the API, so it must load the
    # environment itself; the credentials live in backend/.env.
    try:
        from dotenv import load_dotenv

        load_dotenv(dotenv_path=".env")
    except ImportError:
        log.warning("python-dotenv unavailable; relying on the ambient environment")

    scheduler = MonitoringScheduler(get_config(refresh=True))

    def handle_signal(signum, _frame):
        log.info("Received signal %s, shutting down", signum)
        scheduler.stop()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    scheduler.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["MonitoringScheduler", "watchdog_status", "main"]
