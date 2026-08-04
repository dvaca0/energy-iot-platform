"""Seed the platform's lifecycle reference tables into a throwaway database.

``node_commission_states``, ``deployment_statuses``,
``deployment_status_transitions``, ``node_commission_transitions``,
``node_commission_events`` and ``measurement_contexts`` are created by SQL
migrations rather than by the ORM metadata, so ``Base.metadata.create_all()`` does not produce them. Any
suite that exercises a code path touching ``app.db.lifecycle`` — which now
includes ingest, discovery, the dashboard and monitoring — needs them present.

Values mirror the production rows exactly, so a test asserting on
``is_operational`` or ``is_monitored`` is asserting on real semantics.
"""

from sqlalchemy import text

#: (code, label, sort_order, may_upload, is_monitored, is_terminal, description)
NODE_COMMISSION_STATES = [
    (
        "registered",
        "Registered",
        10,
        0,
        0,
        0,
        "Known to the platform but not yet verified in the field. "
        "Uploads refused; silence is expected, so no alarm.",
    ),
    (
        "commissioned",
        "Commissioned",
        20,
        1,
        1,
        0,
        "Verified and in service. The only state that may upload. " "Silence is an alarm.",
    ),
    (
        "suspended",
        "Suspended",
        30,
        0,
        1,
        0,
        "Uploads deliberately revoked (fault, security, theft). "
        "Still physically installed, so still monitored.",
    ),
    (
        "decommissioned",
        "Decommissioned",
        40,
        0,
        0,
        1,
        "Retired from the fleet. Historical readings are retained; " "silence is expected.",
    ),
]

#: (code, label, sort_order, is_terminal, allows_attribution, is_operational, description)
DEPLOYMENT_STATUSES = [
    ("planned", "Planned", 10, 0, 0, 0, "Campaign scheduled; no hardware in the field yet."),
    (
        "installing",
        "Installing",
        20,
        0,
        0,
        1,
        "Technician on site; verification readings may be taken.",
    ),
    (
        "active",
        "Active",
        30,
        0,
        1,
        1,
        "Verified and measuring. Readings in range are attributed here.",
    ),
    (
        "completed",
        "Completed",
        40,
        1,
        1,
        0,
        "Campaign ended. Still attributes its own historical readings.",
    ),
    ("cancelled", "Cancelled", 50, 1, 0, 0, "Called off or aborted. Attributes nothing."),
]

#: (from_code, to_code) for node commission state (M8)
NODE_COMMISSION_TRANSITIONS = [
    ("registered", "commissioned"),
    ("registered", "decommissioned"),
    ("commissioned", "suspended"),
    ("commissioned", "registered"),
    ("commissioned", "decommissioned"),
    ("suspended", "commissioned"),
    ("suspended", "registered"),
    ("suspended", "decommissioned"),
]

#: (code, label, sort_order, counts_in_analytics, may_attribute, description)
MEASUREMENT_CONTEXTS = [
    ("production", "Production", 10, 1, 1, "Real load on a real panel during a real campaign."),
    (
        "commissioning",
        "Commissioning",
        20,
        0,
        1,
        "On-site verification before a campaign goes active.",
    ),
    (
        "bench",
        "Bench",
        30,
        0,
        0,
        "Hardware bring-up on a desk; the instrument is under test, not a load.",
    ),
    (
        "laboratory",
        "Laboratory",
        40,
        0,
        0,
        "Controlled acquisition on a real load, outside any campaign.",
    ),
    (
        "calibration",
        "Calibration",
        50,
        0,
        0,
        "Measured against a reference instrument or a known source.",
    ),
    (
        "simulation",
        "Simulation",
        60,
        0,
        0,
        "Synthetic or replayed data; no physical sensor involved.",
    ),
]

DEPLOYMENT_TRANSITIONS = [
    ("planned", "installing"),
    ("planned", "cancelled"),
    ("installing", "active"),
    ("installing", "cancelled"),
    ("active", "completed"),
    ("active", "cancelled"),
]


def seed_lifecycle_tables(engine) -> None:
    """Create and populate the reference tables. Idempotent."""
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS node_commission_states (
                code TEXT PRIMARY KEY, label TEXT, sort_order INTEGER,
                may_upload INTEGER, is_monitored INTEGER, is_terminal INTEGER,
                description TEXT)"""))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS deployment_statuses (
                code TEXT PRIMARY KEY, label TEXT, sort_order INTEGER,
                is_terminal INTEGER, allows_attribution INTEGER,
                is_operational INTEGER, description TEXT)"""))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS deployment_status_transitions (
                from_code TEXT, to_code TEXT)"""))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS node_commission_transitions (
                from_code TEXT, to_code TEXT,
                PRIMARY KEY (from_code, to_code))"""))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS node_commission_events (
                id INTEGER PRIMARY KEY, node_id INTEGER NOT NULL,
                node_code TEXT NOT NULL, from_state TEXT, to_state TEXT NOT NULL,
                reason TEXT, actor TEXT,
                occurred_at DATETIME NOT NULL
                    DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ','now')))"""))

        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS measurement_contexts (
                code TEXT PRIMARY KEY, label TEXT, sort_order INTEGER,
                counts_in_analytics INTEGER, may_attribute INTEGER,
                description TEXT)"""))
        for row in MEASUREMENT_CONTEXTS:
            conn.execute(
                text("INSERT OR REPLACE INTO measurement_contexts " "VALUES (:c,:l,:s,:a,:m,:d)"),
                dict(c=row[0], l=row[1], s=row[2], a=row[3], m=row[4], d=row[5]),
            )

        for row in NODE_COMMISSION_STATES:
            conn.execute(
                text(
                    "INSERT OR REPLACE INTO node_commission_states " "VALUES (:c,:l,:s,:u,:m,:t,:d)"
                ),
                dict(c=row[0], l=row[1], s=row[2], u=row[3], m=row[4], t=row[5], d=row[6]),
            )
        for row in DEPLOYMENT_STATUSES:
            conn.execute(
                text("INSERT OR REPLACE INTO deployment_statuses " "VALUES (:c,:l,:s,:t,:a,:o,:d)"),
                dict(c=row[0], l=row[1], s=row[2], t=row[3], a=row[4], o=row[5], d=row[6]),
            )
        conn.execute(text("DELETE FROM node_commission_transitions"))
        for from_code, to_code in NODE_COMMISSION_TRANSITIONS:
            conn.execute(
                text("INSERT INTO node_commission_transitions VALUES (:f,:t)"),
                dict(f=from_code, t=to_code),
            )
        conn.execute(text("DELETE FROM deployment_status_transitions"))
        for from_code, to_code in DEPLOYMENT_TRANSITIONS:
            conn.execute(
                text("INSERT INTO deployment_status_transitions VALUES (:f,:t)"),
                dict(f=from_code, t=to_code),
            )

    # app.db.lifecycle caches the reference data process-wide; a suite that
    # seeds after an earlier import would otherwise see an empty cache.
    try:
        from app.db import lifecycle as db_lifecycle

        db_lifecycle.refresh()
    except Exception:
        pass
    try:
        from app.monitoring import lifecycle as monitoring_lifecycle

        monitoring_lifecycle.refresh()
    except Exception:
        pass
    try:
        from app.db import commissioning

        commissioning.refresh()
    except Exception:
        pass


__all__ = ["seed_lifecycle_tables"]
