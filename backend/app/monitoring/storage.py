"""Persistence layer for the monitoring package.

Two responsibilities, both deliberately isolated from the rest of the backend:

**Session ownership.** The monitoring scheduler runs outside the request cycle
and its work units outlive any HTTP request, so it must never borrow the
request-scoped ``get_db`` dependency. This module owns a session factory bound
to the same engine, handed out through :func:`session_scope`, which commits on
success and rolls back on failure.

**Table lifecycle.** Only the six monitoring tables are ever created, by
explicit table list. A blanket ``Base.metadata.create_all()`` would also touch
the operational schema, which is not this package's to manage.

SQLite specifics
----------------
The database is SQLite in WAL mode with a 30 s busy timeout. WAL allows one
writer with concurrent readers, so the monitoring writer and the API writer can
coexist — but a write that collides still raises ``database is locked`` once the
timeout expires. Writes here are therefore retried with backoff rather than
allowed to kill a scheduler tick.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, TypeVar

from sqlalchemy import delete, inspect
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.db.database import engine
from app.monitoring.config import get_config
from app.monitoring.models import (
    MONITORING_TABLES,
    AlertEvent,
    MonitorAlert,
    NodeHeartbeat,
    NotificationOutbox,
    ServerHeartbeat,
)

log = logging.getLogger("monitoring.storage")

#: Independent of the API's SessionLocal so monitoring can never be affected by
#: a change to request-handling session policy.
MonitoringSession = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

T = TypeVar("T")

#: Retry schedule for writes that hit SQLite's single-writer lock.
_LOCK_RETRY_DELAYS = (0.2, 0.5, 1.0, 2.0, 4.0)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope around a monitoring unit of work.

    Commits on clean exit, rolls back on any exception, and always closes.
    The exception is re-raised: callers decide whether a failed unit of work
    should abort the tick, and the scheduler isolates each check so one failure
    cannot stop the rest.
    """
    session = MonitoringSession()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def with_write_retry(operation: Any, *args: Any, **kwargs: Any) -> Any:
    """Run a callable, retrying only SQLite lock contention.

    Any other ``OperationalError`` (a missing table, a schema mismatch) is a
    real fault and is raised immediately — retrying it would only delay the
    report by the full backoff.
    """
    last_error: Exception | None = None

    for delay in (*_LOCK_RETRY_DELAYS, None):
        try:
            return operation(*args, **kwargs)
        except OperationalError as exc:
            if "database is locked" not in str(exc).lower():
                raise
            last_error = exc
            if delay is None:
                break
            log.warning("SQLite lock contention, retrying in %.1fs", delay)
            time.sleep(delay)

    assert last_error is not None
    raise last_error


def create_tables() -> list[str]:
    """Create the monitoring tables if absent. Returns those actually created.

    Idempotent and additive. Existing tables — operational or monitoring — are
    never dropped, altered or recreated.
    """
    inspector = inspect(engine)
    existing = set(inspector.get_table_names())

    missing = [table for table in MONITORING_TABLES if table.name not in existing]
    if not missing:
        return []

    for table in missing:
        table.create(bind=engine, checkfirst=True)

    created = [table.name for table in missing]
    log.info("Created monitoring tables: %s", ", ".join(created))
    return created


def tables_present() -> bool:
    """True when every monitoring table exists."""
    existing = set(inspect(engine).get_table_names())
    return all(table.name in existing for table in MONITORING_TABLES)


def prune_old_rows(session: Session, now: datetime | None = None) -> dict[str, int]:
    """Delete monitoring rows past their retention window.

    Only monitoring tables are touched. Energy readings and any other
    operational history are never pruned by this package — the platform's rule
    is that historical readings are never deleted.

    Resolved alerts are pruned on ``resolved_at``, so a still-open alert is
    retained no matter how old it is: an outage running for a year must not
    vanish from the alert list because it started a year ago.
    """
    config = get_config()
    now = now or datetime.utcnow()
    removed: dict[str, int] = {}

    heartbeat_cutoff = now - timedelta(days=config.heartbeat.retention_days)
    result = session.execute(
        delete(NodeHeartbeat).where(NodeHeartbeat.received_at < heartbeat_cutoff)
    )
    removed["node_heartbeats"] = result.rowcount or 0

    server_cutoff = now - timedelta(days=config.storage.server_heartbeat_retention_days)
    result = session.execute(
        delete(ServerHeartbeat).where(ServerHeartbeat.recorded_at < server_cutoff)
    )
    removed["server_heartbeats"] = result.rowcount or 0

    # Events must go before their parent alerts, or the delete would orphan
    # rows that the foreign key still references.
    event_cutoff = now - timedelta(days=config.storage.alert_event_retention_days)
    result = session.execute(
        delete(AlertEvent).where(AlertEvent.occurred_at < event_cutoff)
    )
    removed["alert_events"] = result.rowcount or 0

    alert_cutoff = now - timedelta(days=config.storage.alert_retention_days)
    stale_alert_ids = [
        row[0]
        for row in session.query(MonitorAlert.id)
        .filter(
            MonitorAlert.resolved_at.isnot(None),
            MonitorAlert.resolved_at < alert_cutoff,
        )
        .all()
    ]
    if stale_alert_ids:
        session.execute(
            delete(AlertEvent).where(AlertEvent.alert_id.in_(stale_alert_ids))
        )
        session.execute(
            delete(NotificationOutbox).where(
                NotificationOutbox.alert_ref.in_(stale_alert_ids)
            )
        )
        result = session.execute(
            delete(MonitorAlert).where(MonitorAlert.id.in_(stale_alert_ids))
        )
        removed["alerts"] = result.rowcount or 0
    else:
        removed["alerts"] = 0

    # Only settled outbox rows are pruned. A pending row is kept regardless of
    # age, because dropping it would be the silent discard this system forbids.
    outbox_cutoff = now - timedelta(days=config.notifications.retention_days)
    result = session.execute(
        delete(NotificationOutbox).where(
            NotificationOutbox.status.in_(("delivered", "failed")),
            NotificationOutbox.created_at < outbox_cutoff,
        )
    )
    removed["outbox"] = result.rowcount or 0

    total = sum(removed.values())
    if total:
        log.info("Pruned %d monitoring rows: %s", total, removed)
    return removed


def database_file_sizes() -> dict[str, float]:
    """Size of the SQLite database and its WAL, in megabytes.

    Returns zeros rather than raising when the path cannot be resolved, so a
    non-file-backed database (an in-memory test engine) does not break the
    server health probe.
    """
    from pathlib import Path

    url = engine.url
    if url.drivername.startswith("sqlite") and url.database:
        db_path = Path(url.database)
        try:
            main = db_path.stat().st_size / 1024 / 1024
        except OSError:
            main = 0.0
        try:
            wal = Path(str(db_path) + "-wal").stat().st_size / 1024 / 1024
        except OSError:
            wal = 0.0
        return {"db_mb": round(main, 2), "wal_mb": round(wal, 2)}

    return {"db_mb": 0.0, "wal_mb": 0.0}


__all__ = [
    "MonitoringSession",
    "session_scope",
    "with_write_retry",
    "create_tables",
    "tables_present",
    "prune_old_rows",
    "database_file_sizes",
]
