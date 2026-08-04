#!/usr/bin/env python3
"""Generate an immutable pre-migration baseline report.

Captures the state of the database at a moment, plus — while both the rebuilt
table and its pre-rebuild original still exist — a complete row-by-row
verification that the M4 rebuild altered nothing.

The report is written once and never modified. A SHA-256 of the report body is
recorded inside the report itself, so any later edit is detectable:

    python3 -m migrations.baseline --verify docs/migration-baselines/<file>.md

Usage:
    python3 -m migrations.baseline --label pre-m5
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("ENERGY_DB_PATH", BACKEND_DIR / "energy_platform.db"))
REPORT_DIR = BACKEND_DIR / "docs" / "migration-baselines"

# Measurement columns the schema actually has. apparent_power_va and
# reactive_power_var were requested but do not exist on this platform, so they
# are omitted rather than fabricated.
MEASUREMENT_TOTALS = ["energy_kwh", "power_kw"]
ABSENT_BY_REQUEST = ["apparent_power_va", "reactive_power_var"]

SAMPLE_SIZE = 500  # well above the 100 minimum


def connect() -> sqlite3.Connection:
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


def _columns(conn, table) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def _table_exists(conn, table) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def collect(conn) -> dict:
    data: dict = {"generated_at": datetime.utcnow().isoformat() + "Z", "database": str(DB_PATH)}
    cols = _columns(conn, "energy_readings")

    # ------------------------------------------------------------- database
    data["counts"] = {
        "energy_readings": conn.execute("SELECT COUNT(*) FROM energy_readings").fetchone()[0],
        "nodes": conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
        "deployments": conn.execute("SELECT COUNT(*) FROM deployments").fetchone()[0],
        "buildings": conn.execute("SELECT COUNT(*) FROM buildings").fetchone()[0],
    }

    # ------------------------------------------------------------- readings
    data["rows_per_node"] = [
        {"node_id": r[0], "code": r[1], "rows": r[2]}
        for r in conn.execute(
            "SELECT n.id, n.code, COUNT(er.id) FROM nodes n "
            " LEFT JOIN energy_readings er ON er.node_id = n.id "
            " GROUP BY n.id, n.code ORDER BY n.code"
        )
    ]
    data["rows_per_deployment"] = [
        {"deployment_id": r[0], "rows": r[1]}
        for r in conn.execute(
            "SELECT deployment_id, COUNT(*) FROM energy_readings "
            " GROUP BY deployment_id ORDER BY deployment_id IS NULL, deployment_id"
        )
    ]
    data["rows_per_building"] = [
        {"building_id": r[0], "rows": r[1]}
        for r in conn.execute(
            "SELECT building_id, COUNT(*) FROM energy_readings "
            " GROUP BY building_id ORDER BY building_id IS NULL, building_id"
        )
    ]
    if "context" in cols:
        data["rows_per_context"] = [
            {"context": r[0], "rows": r[1]}
            for r in conn.execute(
                "SELECT context, COUNT(*) FROM energy_readings GROUP BY context ORDER BY context"
            )
        ]

    nulls = {
        "deployment_id_null": "SELECT COUNT(*) FROM energy_readings WHERE deployment_id IS NULL",
        "building_id_null": "SELECT COUNT(*) FROM energy_readings WHERE building_id IS NULL",
    }
    if "electrical_panel_id" in cols:
        nulls["electrical_panel_id_null"] = (
            "SELECT COUNT(*) FROM energy_readings WHERE electrical_panel_id IS NULL"
        )
    if "ingested_at" in cols:
        nulls["ingested_at_null"] = (
            "SELECT COUNT(*) FROM energy_readings WHERE ingested_at IS NULL"
        )
    data["null_counts"] = {k: conn.execute(q).fetchone()[0] for k, q in nulls.items()}

    span = conn.execute("SELECT MIN(timestamp), MAX(timestamp) FROM energy_readings").fetchone()
    data["captured_at"] = {"min": span[0], "max": span[1]}

    # --------------------------------------------------------- measurements
    totals = {}
    for column in MEASUREMENT_TOTALS:
        if column in cols:
            value, non_null = conn.execute(
                f"SELECT TOTAL({column}), COUNT({column}) FROM energy_readings"
            ).fetchone()
            totals[column] = {"total": round(value, 6), "non_null_rows": non_null}
    data["measurement_totals"] = totals
    data["measurement_fields_absent"] = [
        c for c in ABSENT_BY_REQUEST if c not in cols
    ]

    return data


def verify_rebuild(conn, sample_size: int = SAMPLE_SIZE) -> dict:
    """Compare every common column between the rebuilt table and its original."""
    result: dict = {"performed": False}
    if not _table_exists(conn, "energy_readings_pre_m4"):
        result["reason"] = "energy_readings_pre_m4 no longer exists"
        return result

    new_cols = _columns(conn, "energy_readings")
    old_cols = _columns(conn, "energy_readings_pre_m4")
    common = [c for c in old_cols if c in new_cols]

    max_pre = conn.execute("SELECT COALESCE(MAX(id),0) FROM energy_readings_pre_m4").fetchone()[0]
    projection = ", ".join(common)

    # ---- exhaustive: every row, every common column, both directions ------
    forward = conn.execute(
        f"SELECT COUNT(*) FROM ("
        f"  SELECT {projection} FROM energy_readings WHERE id <= ?"
        f"  EXCEPT"
        f"  SELECT {projection} FROM energy_readings_pre_m4)",
        (max_pre,),
    ).fetchone()[0]
    backward = conn.execute(
        f"SELECT COUNT(*) FROM ("
        f"  SELECT {projection} FROM energy_readings_pre_m4"
        f"  EXCEPT"
        f"  SELECT {projection} FROM energy_readings WHERE id <= ?)",
        (max_pre,),
    ).fetchone()[0]

    old_n = conn.execute("SELECT COUNT(*) FROM energy_readings_pre_m4").fetchone()[0]
    new_n = conn.execute(
        "SELECT COUNT(*) FROM energy_readings WHERE id <= ?", (max_pre,)
    ).fetchone()[0]

    # ---- explicit random sample, compared column by column ----------------
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM energy_readings_pre_m4 ORDER BY RANDOM() LIMIT ?", (sample_size,)
    )]
    mismatches = []
    for row_id in ids:
        a = conn.execute(
            f"SELECT {projection} FROM energy_readings_pre_m4 WHERE id = ?", (row_id,)
        ).fetchone()
        b = conn.execute(
            f"SELECT {projection} FROM energy_readings WHERE id = ?", (row_id,)
        ).fetchone()
        if a is None or b is None:
            mismatches.append({"id": row_id, "column": "<row>", "old": a, "new": b})
            continue
        for column, x, y in zip(common, a, b):
            if x != y:
                mismatches.append({"id": row_id, "column": column, "old": x, "new": y})

    result.update({
        "performed": True,
        "common_columns": common,
        "columns_only_in_new": [c for c in new_cols if c not in old_cols],
        "bounded_by_max_id": max_pre,
        "row_count_original": old_n,
        "row_count_rebuilt_bounded": new_n,
        "exhaustive_rows_in_rebuilt_not_in_original": forward,
        "exhaustive_rows_in_original_not_in_rebuilt": backward,
        "sample_size": len(ids),
        "sample_mismatches": mismatches,
        "identical": (forward == 0 and backward == 0
                      and old_n == new_n and not mismatches),
    })
    return result


def render(data: dict, verification: dict, label: str) -> str:
    lines: list[str] = []
    add = lines.append

    add(f"# Migration baseline — {label}")
    add("")
    add("**This report is immutable. Do not edit it.**")
    add("")
    add(f"- Generated: `{data['generated_at']}`")
    add(f"- Database: `{data['database']}`")
    add("")
    add("## Database")
    add("")
    add("| Table | Rows |")
    add("|---|---:|")
    for name, value in data["counts"].items():
        add(f"| `{name}` | {value:,} |")

    add("")
    add("## Readings")
    add("")
    add("### Rows per node")
    add("")
    add("| Node | id | Rows |")
    add("|---|---:|---:|")
    for row in data["rows_per_node"]:
        add(f"| {row['code']} | {row['node_id']} | {row['rows']:,} |")

    add("")
    add("### Rows per deployment")
    add("")
    add("| Deployment | Rows |")
    add("|---|---:|")
    for row in data["rows_per_deployment"]:
        key = row["deployment_id"] if row["deployment_id"] is not None else "NULL"
        add(f"| {key} | {row['rows']:,} |")

    add("")
    add("### Rows per building")
    add("")
    add("| Building | Rows |")
    add("|---|---:|")
    for row in data["rows_per_building"]:
        key = row["building_id"] if row["building_id"] is not None else "NULL"
        add(f"| {key} | {row['rows']:,} |")

    if "rows_per_context" in data:
        add("")
        add("### Rows per context")
        add("")
        add("| Context | Rows |")
        add("|---|---:|")
        for row in data["rows_per_context"]:
            add(f"| `{row['context']}` | {row['rows']:,} |")

    add("")
    add("### Null counts")
    add("")
    add("| Field | NULL rows |")
    add("|---|---:|")
    for name, value in data["null_counts"].items():
        add(f"| `{name}` | {value:,} |")

    add("")
    add("### captured_at span")
    add("")
    add(f"- minimum: `{data['captured_at']['min']}`")
    add(f"- maximum: `{data['captured_at']['max']}`")

    add("")
    add("## Measurements")
    add("")
    add("| Field | Total | Non-null rows |")
    add("|---|---:|---:|")
    for name, value in data["measurement_totals"].items():
        add(f"| `{name}` | {value['total']:,.6f} | {value['non_null_rows']:,} |")
    if data["measurement_fields_absent"]:
        add("")
        add("Not present in this schema, so omitted rather than invented: "
            + ", ".join(f"`{c}`" for c in data["measurement_fields_absent"]) + ".")

    add("")
    add("## Row-by-row verification of the M4 rebuild")
    add("")
    if not verification.get("performed"):
        add(f"Not performed: {verification.get('reason')}")
    else:
        add(f"Compared `energy_readings_pre_m4` against `energy_readings` across all "
            f"{len(verification['common_columns'])} common columns, bounded by "
            f"`id <= {verification['bounded_by_max_id']}` so readings that arrived after "
            f"the rebuild are excluded.")
        add("")
        add("| Check | Result |")
        add("|---|---:|")
        add(f"| Rows in original | {verification['row_count_original']:,} |")
        add(f"| Rows in rebuilt (bounded) | {verification['row_count_rebuilt_bounded']:,} |")
        add(f"| Exhaustive: in rebuilt but not original | {verification['exhaustive_rows_in_rebuilt_not_in_original']:,} |")
        add(f"| Exhaustive: in original but not rebuilt | {verification['exhaustive_rows_in_original_not_in_rebuilt']:,} |")
        add(f"| Random sample size | {verification['sample_size']:,} |")
        add(f"| Sample mismatches | {len(verification['sample_mismatches']):,} |")
        add("")
        add("Common columns: " + ", ".join(f"`{c}`" for c in verification["common_columns"]))
        add("")
        add("Columns only in the rebuilt table: "
            + ", ".join(f"`{c}`" for c in verification["columns_only_in_new"]))
        add("")
        if verification["identical"]:
            add("**Result: ZERO MISMATCHES.** Every row of the original table is present in "
                "the rebuilt table, identical across every common column. The exhaustive "
                "set comparison is empty in both directions, and the random sample found no "
                "differing value in any column.")
        else:
            add("**Result: MISMATCHES FOUND.**")
            add("")
            for m in verification["sample_mismatches"][:50]:
                add(f"- id={m['id']} `{m['column']}`: original={m['old']!r} rebuilt={m['new']!r}")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--verify", metavar="PATH", help="check a report's recorded digest")
    args = parser.parse_args()

    if args.verify:
        path = Path(args.verify)
        text = path.read_text(encoding="utf-8")
        marker = "\n<!-- sha256:"
        if marker not in text:
            print("no digest recorded in that report")
            return 1
        body, _, tail = text.rpartition(marker)
        recorded = tail.split("-->")[0].strip()
        actual = hashlib.sha256(body.encode("utf-8")).hexdigest()
        ok = recorded == actual
        print(f"recorded : {recorded}")
        print(f"actual   : {actual}")
        print("UNMODIFIED" if ok else "MODIFIED SINCE GENERATION")
        return 0 if ok else 1

    random.seed()
    conn = connect()
    try:
        data = collect(conn)
        verification = verify_rebuild(conn)
    finally:
        conn.close()

    body = render(data, verification, args.label)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = REPORT_DIR / f"{stamp}-{args.label}.md"
    json_path = REPORT_DIR / f"{stamp}-{args.label}.json"

    md_path.write_text(body + f"\n<!-- sha256:{digest} -->\n", encoding="utf-8")
    json_path.write_text(
        json.dumps({"baseline": data, "rebuild_verification": verification,
                    "body_sha256": digest}, indent=2, default=str),
        encoding="utf-8",
    )

    # Read-only on disk, as a guard against casual modification.
    md_path.chmod(0o444)
    json_path.chmod(0o444)

    print(body)
    print(f"written: {md_path}")
    print(f"written: {json_path}")
    print(f"sha256 : {digest}")
    return 0 if verification.get("identical", False) else 2


if __name__ == "__main__":
    sys.exit(main())
