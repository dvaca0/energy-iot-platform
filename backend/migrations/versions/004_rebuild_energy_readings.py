#!/usr/bin/env python3
# description: rebuild energy_readings — nullable attribution, context, panel, ingested_at (ADR-0003, ADR-0004)
# deep: true
#
# The structural centre of the redesign, and the highest-risk step in the plan.
#
# deployment_id and building_id are NOT NULL today, and SQLite has no ALTER
# COLUMN, so making them nullable means physically rewriting all 225k rows.
# Written in Python rather than SQL for two reasons: the step is instrumented
# (runtime, WAL growth, per-index rebuild time, disk), and it needs PRAGMAs that
# are silent no-ops inside a transaction.
#
# Every existing row keeps context='production', preserving today's semantics
# exactly. Reclassification is M5's job; this step changes no meaning at all.
#
# Three hazards, all verified beforehand on a copy:
#
#   1. Renaming a table rewrites *other* tables' foreign keys to follow it.
#      Without legacy_alter_table=ON, energy_readings' FK would come to point at
#      energy_readings_pre_m4 and the rollback table would silently become the
#      live parent. Confirmed in M3.
#   2. A renamed table keeps its indexes under their original names, so the old
#      indexes must be dropped before the new ones can claim those names.
#   3. INSERT ... SELECT without an explicit ORDER BY can reassign which id
#      belongs to which reading. The copy is ordered by id and INV-16 checks the
#      (id, node_id, captured_at) binding afterwards.
#
# The original table is renamed, never dropped. It stays until cleanup is run
# deliberately, after M5/M6/M7 and the M8 shadow phase have proven stable
# (INV-13 fails if it disappears early).
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from time import perf_counter

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = Path(os.environ.get("ENERGY_DB_PATH", BACKEND_DIR / "energy_platform.db"))
BENCHMARK_PATH = BACKEND_DIR / "migrations" / "m4_benchmark.json"

MEASUREMENT_CONTEXTS = [
    # code, label, sort, counts_in_analytics, may_attribute, description
    ("production", "Production", 10, 1, 1,
     "Real load on a real panel during a real campaign."),
    ("commissioning", "Commissioning", 20, 0, 1,
     "On-site verification before a campaign goes active. Kept as the install record."),
    ("bench", "Bench", 30, 0, 0,
     "Hardware bring-up on a desk; the instrument is under test, not a load."),
    ("laboratory", "Laboratory", 40, 0, 0,
     "Controlled acquisition on a real load, outside any campaign."),
    ("calibration", "Calibration", 50, 0, 0,
     "Measured against a reference instrument or a known source."),
    ("simulation", "Simulation", 60, 0, 0,
     "Synthetic or replayed data; no physical sensor involved."),
]

# Recreated verbatim from the pre-migration table, plus one for context.
INDEXES = [
    ("ix_energy_readings_id", "energy_readings(id)"),
    ("ix_energy_readings_timestamp", "energy_readings(timestamp)"),
    ("idx_readings_timestamp", "energy_readings(timestamp)"),
    ("idx_readings_node_timestamp", "energy_readings(node_id, timestamp)"),
    ("idx_readings_building_timestamp", "energy_readings(building_id, timestamp)"),
    ("idx_readings_deployment_timestamp", "energy_readings(deployment_id, timestamp)"),
    ("idx_readings_context_timestamp", "energy_readings(context, timestamp)"),
]

MEASURED_COLUMNS = [
    "voltage", "current", "power_kw", "energy_kwh", "power_factor", "frequency_hz",
    "phase_a_voltage", "phase_b_voltage", "phase_c_voltage",
    "phase_a_current", "phase_b_current", "phase_c_current",
]

NEW_TABLE = f"""
CREATE TABLE energy_readings_new (
    id                  INTEGER PRIMARY KEY,

    -- Who measured it. Never null: a reading always has a node (ADR-0004).
    node_id             INTEGER NOT NULL REFERENCES nodes(id),

    -- Where it counts. Nullable: a reading that no deployment covers is stored
    -- unattributed rather than rejected.
    deployment_id       INTEGER NULL REFERENCES deployments(id),
    building_id         INTEGER NULL REFERENCES buildings(id),
    electrical_panel_id INTEGER NULL REFERENCES electrical_panels(id),

    -- What kind of measurement it is. Declared, never inferred (ADR-0003).
    context             TEXT NOT NULL DEFAULT 'production'
                        REFERENCES measurement_contexts(code),

    -- When it was measured, and when the server received it. Separate, because
    -- a replayed buffer can deliver a week-old measurement seconds ago.
    timestamp           DATETIME NOT NULL,
    ingested_at         DATETIME NULL,

    {chr(10).join(f'    {c:<19} FLOAT NULL,' for c in MEASURED_COLUMNS)}

    -- A reading attributed to a deployment must also name its building, or the
    -- building-level analytics would silently drop it (INV-08).
    CHECK (deployment_id IS NULL OR building_id IS NOT NULL)
);
"""


def _sizes() -> dict:
    def mb(path: Path) -> float:
        return round(path.stat().st_size / 1024 / 1024, 2) if path.exists() else 0.0

    return {
        "db_mb": mb(DB_PATH),
        "wal_mb": mb(Path(str(DB_PATH) + "-wal")),
        "shm_mb": mb(Path(str(DB_PATH) + "-shm")),
    }


def up(conn: sqlite3.Connection) -> None:
    bench: dict = {"started_at": datetime.utcnow().isoformat(), "phases": {}}
    bench["before"] = _sizes()
    t_start = perf_counter()

    # Must be set outside a transaction to take effect.
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")

    conn.execute("BEGIN IMMEDIATE")
    try:
        # ---- lookup table for measurement context -------------------------
        t = perf_counter()
        conn.execute(
            """
            CREATE TABLE measurement_contexts (
                code                TEXT PRIMARY KEY,
                label               TEXT    NOT NULL,
                sort_order          INTEGER NOT NULL,
                counts_in_analytics BOOLEAN NOT NULL DEFAULT 0,
                may_attribute       BOOLEAN NOT NULL DEFAULT 0,
                description         TEXT
            )
            """
        )
        conn.executemany(
            "INSERT INTO measurement_contexts "
            "(code,label,sort_order,counts_in_analytics,may_attribute,description) "
            "VALUES (?,?,?,?,?,?)",
            MEASUREMENT_CONTEXTS,
        )
        bench["phases"]["create_context_table_s"] = round(perf_counter() - t, 3)

        # ---- new table ----------------------------------------------------
        t = perf_counter()
        conn.execute(NEW_TABLE)
        bench["phases"]["create_table_s"] = round(perf_counter() - t, 3)

        source_count = conn.execute("SELECT COUNT(*) FROM energy_readings").fetchone()[0]

        # ---- copy ---------------------------------------------------------
        # ORDER BY id so the copy is deterministic and ids cannot be reordered.
        t = perf_counter()
        measured = ", ".join(MEASURED_COLUMNS)
        conn.execute(
            f"""
            INSERT INTO energy_readings_new
                (id, node_id, deployment_id, building_id, electrical_panel_id,
                 context, timestamp, ingested_at, {measured})
            SELECT
                id, node_id, deployment_id, building_id, NULL,
                'production', timestamp, NULL, {measured}
            FROM energy_readings
            ORDER BY id
            """
        )
        bench["phases"]["copy_rows_s"] = round(perf_counter() - t, 3)
        bench["rows_copied"] = source_count
        bench["wal_after_copy_mb"] = _sizes()["wal_mb"]

        copied = conn.execute("SELECT COUNT(*) FROM energy_readings_new").fetchone()[0]
        if copied != source_count:
            raise RuntimeError(f"copied {copied} rows, expected {source_count}")

        # ---- free the index names, then swap ------------------------------
        t = perf_counter()
        for name, _ in INDEXES:
            conn.execute(f"DROP INDEX IF EXISTS {name}")
        bench["phases"]["drop_old_indexes_s"] = round(perf_counter() - t, 3)

        t = perf_counter()
        conn.execute("ALTER TABLE energy_readings RENAME TO energy_readings_pre_m4")
        conn.execute("ALTER TABLE energy_readings_new RENAME TO energy_readings")
        bench["phases"]["rename_s"] = round(perf_counter() - t, 3)

        # ---- rebuild indexes ----------------------------------------------
        index_times = {}
        t_idx = perf_counter()
        for name, definition in INDEXES:
            t = perf_counter()
            conn.execute(f"CREATE INDEX {name} ON {definition}")
            index_times[name] = round(perf_counter() - t, 3)
        bench["phases"]["build_indexes_s"] = round(perf_counter() - t_idx, 3)
        bench["index_build_s"] = index_times

        bench["wal_peak_mb"] = _sizes()["wal_mb"]

        t = perf_counter()
        conn.execute("COMMIT")
        bench["phases"]["commit_s"] = round(perf_counter() - t, 3)
    except Exception:
        conn.execute("ROLLBACK")
        conn.execute("PRAGMA legacy_alter_table = OFF")
        conn.execute("PRAGMA foreign_keys = ON")
        raise

    conn.execute("PRAGMA legacy_alter_table = OFF")
    conn.execute("PRAGMA foreign_keys = ON")

    # A passive checkpoint folds the WAL back into the database file without
    # blocking readers; reporting before and after shows the true peak.
    t = perf_counter()
    checkpoint = conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
    bench["phases"]["checkpoint_s"] = round(perf_counter() - t, 3)
    # (busy, wal_pages, checkpointed_pages); busy=1 means a reader held it back,
    # which is normal on a live database and simply defers the reclaim.
    bench["checkpoint_result"] = list(checkpoint) if checkpoint else None
    bench["wal_after_checkpoint_mb"] = _sizes()["wal_mb"]

    bench["total_s"] = round(perf_counter() - t_start, 3)
    bench["after"] = _sizes()
    bench["shadow_table_mb"] = round(
        conn.execute(
            "SELECT SUM(pgsize) FROM dbstat WHERE name = 'energy_readings_pre_m4'"
        ).fetchone()[0] / 1024 / 1024, 2
    ) if _has_dbstat(conn) else None

    BENCHMARK_PATH.write_text(json.dumps(bench, indent=2), encoding="utf-8")
    _print_benchmark(bench)


def _has_dbstat(conn: sqlite3.Connection) -> bool:
    try:
        conn.execute("SELECT 1 FROM dbstat LIMIT 1")
        return True
    except sqlite3.Error:
        return False


def _print_benchmark(bench: dict) -> None:
    print("  " + "-" * 60)
    print(f"  BENCHMARK  {bench['rows_copied']:,} rows")
    for phase, seconds in bench["phases"].items():
        print(f"    {phase:<28} {seconds:>8.3f} s")
    print(f"    {'TOTAL':<28} {bench['total_s']:>8.3f} s")
    print("    index build:")
    for name, seconds in bench.get("index_build_s", {}).items():
        print(f"      {name:<38} {seconds:>7.3f} s")
    before, after = bench["before"], bench["after"]
    print(f"    db      {before['db_mb']:>8.2f} MB -> {after['db_mb']:>8.2f} MB")
    print(f"    wal     {before['wal_mb']:>8.2f} MB -> {after['wal_mb']:>8.2f} MB "
          f"(peak {bench.get('wal_peak_mb', 0):.2f} MB)")
    if bench.get("shadow_table_mb") is not None:
        print(f"    retained rollback table: {bench['shadow_table_mb']:.2f} MB")
    print("  " + "-" * 60)


def down(conn: sqlite3.Connection) -> None:
    """Swap the original table back, carrying forward anything that arrived since.

    A naive two-rename swap would silently destroy every reading ingested
    between the rebuild and the rollback — roughly five a minute on this fleet.
    So the newer rows are copied back into the original table first.

    That copy can only succeed while those rows are expressible in the old
    schema, which requires deployment_id and building_id to be non-null. If any
    unattributed reading has been written — which is what M8's live write path
    would produce — the rollback is genuinely lossy and aborts instead, leaving
    the operator to restore from the backup that the runner took.
    """
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")

    conn.execute("BEGIN IMMEDIATE")
    try:
        max_pre = conn.execute(
            "SELECT COALESCE(MAX(id), 0) FROM energy_readings_pre_m4"
        ).fetchone()[0]

        arrived = conn.execute(
            "SELECT COUNT(*) FROM energy_readings WHERE id > ?", (max_pre,)
        ).fetchone()[0]

        if arrived:
            unattributable = conn.execute(
                "SELECT COUNT(*) FROM energy_readings "
                " WHERE id > ? AND (deployment_id IS NULL OR building_id IS NULL)",
                (max_pre,),
            ).fetchone()[0]

            if unattributable:
                raise RuntimeError(
                    f"{unattributable} of {arrived} reading(s) written since the rebuild "
                    "have no attribution and cannot be represented in the pre-M4 schema. "
                    "Rolling back would lose them — restore from the pre-004 backup instead."
                )

            measured = ", ".join(MEASURED_COLUMNS)
            conn.execute(
                f"""
                INSERT INTO energy_readings_pre_m4
                    (id, node_id, deployment_id, building_id, timestamp, {measured})
                SELECT id, node_id, deployment_id, building_id, timestamp, {measured}
                  FROM energy_readings
                 WHERE id > ?
                 ORDER BY id
                """,
                (max_pre,),
            )
            print(f"  carried {arrived} post-rebuild reading(s) back into the original table")

        for name, _ in INDEXES:
            conn.execute(f"DROP INDEX IF EXISTS {name}")

        conn.execute("ALTER TABLE energy_readings RENAME TO energy_readings_discarded_m4")
        conn.execute("ALTER TABLE energy_readings_pre_m4 RENAME TO energy_readings")
        conn.execute("DROP TABLE energy_readings_discarded_m4")

        # Exactly the six indexes that existed before the rebuild; the seventh
        # (context) has no meaning once the column is gone.
        for name, definition in INDEXES:
            if name == "idx_readings_context_timestamp":
                continue
            conn.execute(f"CREATE INDEX {name} ON {definition}")

        conn.execute("DROP TABLE IF EXISTS measurement_contexts")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA legacy_alter_table = OFF")
        conn.execute("PRAGMA foreign_keys = ON")
