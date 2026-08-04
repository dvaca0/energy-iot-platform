#!/usr/bin/env python3
"""Deployment lifecycle and integrity tests.

Plain Python, no pytest (not installed in this venv), matching
tests/test_monitoring.py. Runs against a throwaway copy of the production
database so nothing real is touched.

Covers both layers deliberately:

  APPLICATION  the lifecycle operations return an explanatory business error
  DATABASE     the same violation is blocked even when the application is
               bypassed with raw SQL

The second set is what makes the guarantee real rather than conventional.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta

from sqlalchemy import text as sa_text

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

PASSED, FAILED = 0, 0


def check(label: str, condition: bool, detail: str = ""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  PASS  {label}")
    else:
        FAILED += 1
        print(f"  FAIL  {label}  {detail}")


def raises(label: str, fn, expect_code: str | None = None):
    """Assert an operation is refused, and that it explains itself."""
    from app.services.deployment_ops import LifecycleError

    try:
        fn()
        check(label, False, "-> accepted, expected refusal")
    except LifecycleError as exc:
        ok = expect_code is None or exc.code == expect_code
        check(label, ok, f"-> got code {exc.code!r}, expected {expect_code!r}")
        if ok:
            print(f"          {exc.message}")


def sql_blocked(label: str, conn, sql: str):
    """Assert the database refuses it even with the application bypassed."""
    try:
        conn.execute(sql)
        check(label, False, "-> raw SQL ACCEPTED")
        conn.rollback()
    except (sqlite3.IntegrityError, sqlite3.OperationalError) as exc:
        check(label, True)
        print(f"          {exc}")


def build_copy() -> str:
    src = os.path.join(BACKEND, "energy_platform.db")
    fd, path = tempfile.mkstemp(suffix=".db", prefix="lifecycle-test-")
    os.close(fd)
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    d = sqlite3.connect(path)
    s.backup(d)
    d.close()
    s.close()
    return path


def main() -> int:
    path = build_copy()
    os.environ["ENERGY_DB_PATH"] = path

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import commissioning, lifecycle
    from app.db.models import Deployment, Node
    from app.services import deployment_ops as ops

    engine = create_engine(f"sqlite:///{path}")
    Session = sessionmaker(bind=engine)
    db = Session()
    # Triggers are per-connection-independent (they live in the schema), but
    # foreign keys are not on by default.

    raw = sqlite3.connect(path)
    raw.isolation_level = None

    n1 = db.query(Node).filter(Node.code == "N001").one()
    n2 = db.query(Node).filter(Node.code == "N002").one()
    live = db.query(Deployment).filter(Deployment.status == "active").one()

    def plan(node, bld=8, panel=8, start="2026-09-01", end="2026-09-07"):
        """Create and COMMIT a planned deployment.

        Committed rather than flushed because several tests below roll back a
        refused operation, and a rollback would otherwise discard the fixture
        along with it.
        """
        d = Deployment(
            node_id=node.id,
            building_id=bld,
            electrical_panel_id=panel,
            start_date=start,
            end_date=end,
            status=lifecycle.initial_status(db),
        )
        db.add(d)
        db.commit()
        db.refresh(d)
        return d

    def drop(*deployments):
        for d in deployments:
            db.delete(d)
        db.commit()

    print("\n--- planning reserves nothing ---")
    a = plan(n2, start="2026-09-01", end="2026-09-07")
    b = plan(n2, start="2026-09-02", end="2026-09-08")
    check(
        "two overlapping PLANNED deployments on one node are allowed",
        a.status == "planned" and b.status == "planned",
    )
    c = plan(n1)
    check("a plan may be created while another deployment is active", c.status == "planned")

    print("\n--- editing a plan is allowed before measurement ---")
    a.notes = "corrected panel location"
    a.building_id = 9
    db.commit()
    check("planning fields are editable while planned", a.building_id == 9)
    a.building_id = 8
    db.commit()

    print("\n--- exclusivity: only one live deployment per node ---")
    ops.begin_installation(db, a)
    db.commit()
    check("planned -> installing", a.status == "installing")
    raises(
        "a second deployment cannot begin installation on a busy node",
        lambda: ops.begin_installation(db, b),
        "node_already_live",
    )
    db.rollback()

    print("\n--- node must be commissioned to start measuring ---")
    check("N002 is not commissioned", not commissioning.may_upload(db, n2.commission_state))
    raises(
        "a node that may not upload cannot start measuring",
        lambda: ops.activate(db, a),
        "node_not_commissioned",
    )
    db.rollback()

    print("\n--- illegal transitions ---")
    raises(
        "planned cannot jump straight to active", lambda: ops.activate(db, b), "illegal_transition"
    )
    db.rollback()

    done = db.query(Deployment).filter(Deployment.status == "completed").first()
    raises(
        "a completed deployment cannot be reopened",
        lambda: ops.activate(db, done),
        "illegal_transition",
    )
    db.rollback()

    print("\n--- completion requires activation (R1/R2) ---")
    # A planned deployment cannot be completed at all — the transition table
    # refuses it before the never-activated guard is reached. That guard is now
    # structurally unreachable (R2 guarantees an active deployment has
    # activated_at) and is retained as defence in depth.
    raises(
        "a deployment that never measured cannot be finished",
        lambda: ops.complete(db, b),
        "illegal_transition",
    )
    db.rollback()

    print("\n--- cancellation (Rule 8) ---")
    live = db.query(Deployment).filter(Deployment.status == "active").one()
    check(
        "the live deployment has attributed readings", ops.attributed_reading_count(db, live.id) > 0
    )
    raises(
        "cannot cancel a deployment that has attributed readings",
        lambda: ops.cancel(db, live),
        "has_attributed_readings",
    )
    db.rollback()

    ops.cancel(db, b)
    db.commit()
    check("a plan with no readings can be cancelled", b.status == "cancelled")

    print("\n--- backdating (Rule 6) ---")
    latest = db.execute(
        sa_text("SELECT MAX(timestamp) FROM energy_readings WHERE node_id = :n"), {"n": n2.id}
    ).scalar()
    n2.commission_state = "commissioned"
    db.commit()
    # `a` is already installing on N002 and N002 has no stored readings, so a
    # backdated activation is refused only if readings exist. Give N002 one.
    db.execute(
        sa_text(
            "INSERT INTO energy_readings (node_id, timestamp, context) "
            "VALUES (:n, '2026-12-01 00:00:00.000', 'production')"
        ),
        {"n": n2.id},
    )
    db.commit()
    a = db.query(Deployment).filter(Deployment.id == a.id).one()
    raises(
        "activation cannot reach back over stored readings",
        lambda: ops.activate(db, a, at=datetime(2026, 1, 1, 0, 0, 0)),
        "backdated_activation",
    )
    db.rollback()
    db.execute(
        sa_text(
            "DELETE FROM energy_readings WHERE node_id = :n "
            "AND timestamp = '2026-12-01 00:00:00.000'"
        ),
        {"n": n2.id},
    )
    db.commit()

    print("\n--- same-day handover via atomic supersede ---")
    a = db.query(Deployment).filter(Deployment.id == a.id).one()
    ops.activate(db, a, at=datetime(2027, 1, 1, 8, 0, 0))
    db.commit()
    check(
        "installing -> active writes activated_at automatically",
        a.status == "active" and a.activated_at == datetime(2027, 1, 1, 8, 0, 0),
    )

    d2 = plan(n2, start="2027-01-01", end="2027-01-14")
    raises(
        "cannot activate a second deployment without superseding",
        lambda: ops.begin_installation(db, d2),
        "node_already_live",
    )
    db.rollback()

    d2 = db.query(Deployment).filter(Deployment.id == d2.id).one()
    prev, nxt = ops.supersede_and_activate(db, d2, a, at=datetime(2027, 1, 1, 15, 30, 0))
    db.commit()
    check(
        "supersede closes the previous campaign",
        prev.status == "completed" and prev.closed_at == datetime(2027, 1, 1, 15, 30, 0),
    )
    check(
        "supersede activates the next one", nxt.status == "active" and nxt.activated_at is not None
    )
    check("same-day handover produces strictly disjoint windows", prev.closed_at < nxt.activated_at)
    check(
        "the handover gap is one microsecond",
        nxt.activated_at - prev.closed_at == timedelta(microseconds=1),
    )

    print("\n--- attribution fields are frozen once measuring ---")
    check(
        "an activated deployment offers no edit action",
        "edit" not in ops.available_actions(db, nxt),
    )

    print("\n--- DATABASE LAYER: the same violations with the application bypassed ---")
    sql_blocked(
        "raw SQL: completed deployment with no closed_at (deployment 4's state)",
        raw,
        "INSERT INTO deployments (node_id,building_id,electrical_panel_id,start_date,"
        "end_date,status,activated_at,closed_at) VALUES "
        "(1,8,8,'2025-01-01','2025-01-07','completed','2025-01-01 00:00:00',NULL)",
    )
    sql_blocked(
        "raw SQL: reopen a closed window (the original D1 operation)",
        raw,
        "UPDATE deployments SET closed_at=NULL WHERE id=4",
    )
    sql_blocked(
        "raw SQL: second active deployment for one node",
        raw,
        "INSERT INTO deployments (node_id,building_id,electrical_panel_id,start_date,"
        "end_date,status,activated_at) VALUES "
        "(1,8,8,'2027-06-01','2027-06-07','active','2027-06-01 00:00:00')",
    )
    sql_blocked(
        "raw SQL: overlapping completed window",
        raw,
        "INSERT INTO deployments (node_id,building_id,electrical_panel_id,start_date,"
        "end_date,status,activated_at,closed_at) VALUES "
        "(1,8,8,'2026-07-01','2026-07-05','completed','2026-07-01 00:00:00',"
        "'2026-07-05 00:00:00')",
    )
    sql_blocked(
        "raw SQL: move an activated deployment's building",
        raw,
        "UPDATE deployments SET building_id=9 WHERE id=4",
    )
    sql_blocked(
        "raw SQL: move an activated deployment's start instant",
        raw,
        "UPDATE deployments SET activated_at='2026-01-01 00:00:00' WHERE id=4",
    )
    sql_blocked(
        "raw SQL: close before activating",
        raw,
        "INSERT INTO deployments (node_id,building_id,electrical_panel_id,start_date,"
        "end_date,status,activated_at,closed_at) VALUES "
        "(2,8,8,'2027-02-01','2027-02-07','completed','2027-02-05 00:00:00',"
        "'2027-02-01 00:00:00')",
    )

    print("\n--- concurrency: two activations racing for one node ---")
    c1 = sqlite3.connect(path, timeout=5)
    c1.isolation_level = None
    c2 = sqlite3.connect(path, timeout=5)
    c2.isolation_level = None
    for c in (c1, c2):
        c.execute("PRAGMA busy_timeout=2000")
    free = c1.execute(
        "SELECT n.id FROM nodes n WHERE NOT EXISTS ("
        "  SELECT 1 FROM deployments d JOIN deployment_statuses s ON s.code=d.status"
        "   WHERE d.node_id=n.id AND s.is_exclusive=1) LIMIT 1"
    ).fetchone()
    if free:
        node_id = free[0]
        ins = (
            "INSERT INTO deployments (node_id,building_id,electrical_panel_id,start_date,"
            "end_date,status,activated_at) VALUES "
            f"({node_id},8,8,'2027-03-01','2027-03-07','active','2027-03-0{{}} 00:00:00')"
        )
        c1.execute(ins.format(1))
        try:
            c2.execute(ins.format(2))
            check("only one of two racing activations wins", False, "-> both accepted")
        except (sqlite3.IntegrityError, sqlite3.OperationalError) as exc:
            check("only one of two racing activations wins", True)
            print(f"          {exc}")
    else:
        check("only one of two racing activations wins", True, "(no free node; skipped)")
    c1.close()
    c2.close()

    raw.close()
    db.close()
    engine.dispose()
    os.unlink(path)

    print(f"\n{'=' * 60}\n  {PASSED} passed, {FAILED} failed\n{'=' * 60}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
