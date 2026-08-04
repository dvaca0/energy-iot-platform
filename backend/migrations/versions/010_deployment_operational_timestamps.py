#!/usr/bin/env python3
# description: add activated_at/closed_at as the operational attribution window; backfill the three approved rows
#
# Separates the campaign *schedule* from what actually happened:
#
#   start_date / end_date   planning metadata. Never authoritative for
#                           attribution. Retained unchanged.
#   activated_at            when measurement actually began. Written by the
#   closed_at               transition, never typed by an operator.
#
# The pair is what the resolver range-matches on from here. Day-granular
# planning dates cannot express a mid-afternoon node handover, which is the
# normal case for this platform — deployment 4 handed over to deployment 6 at
# 21:09 on 2026-07-30, one 15-second sample apart.
#
# IDEMPOTENT BY CONSTRUCTION
#
# Values are the ones explicitly approved, held in EXPECTED below. They are not
# recomputed at run time: deployment 6 is still active and accumulating, so a
# derived value could drift between runs. On every execution each row is either
#
#   NULL            -> populated with the approved value
#   already equal   -> left alone, counted as already-applied
#   already differs -> ABORT, nothing written
#
# A populated timestamp is never silently overwritten. Running this twice, or
# resuming after an interruption, converges to the same state and writes nothing
# the second time.
from __future__ import annotations

import sqlite3

# Approved 2026-07-30. Each value and its justification are recorded in
# docs/m11-backfill-validation.md.
EXPECTED: dict[int, tuple[str, str | None]] = {
    # id: (activated_at, closed_at)
    4: ("2026-06-14 21:57:34.692460", "2026-07-30 21:09:15.426000"),
    5: ("2026-06-14 00:00:00.000", "2026-06-21 23:59:59.999"),
    6: ("2026-07-30 21:09:30.425000", None),
}

# Fields that must not change. Compared before and after.
IDENTITY = ("id", "node_id", "building_id", "electrical_panel_id",
            "start_date", "end_date", "status", "notes")

# Evidence the approved values were derived from, re-checked at run time. If the
# data no longer supports them, that is an unexpected condition and we stop.
DERIVATION_EVIDENCE = {
    4: ("last", "2026-07-30 21:09:15.426000"),
    6: ("first", "2026-07-30 21:09:30.425000"),
}


def _columns(conn) -> set[str]:
    return {row[1] for row in conn.execute("PRAGMA table_info(deployments)")}


def _identity(conn) -> dict[int, tuple]:
    return {
        row[0]: row
        for row in conn.execute(f"SELECT {','.join(IDENTITY)} FROM deployments ORDER BY id")
    }


def _abort(message: str):
    raise RuntimeError(message)


def up(conn: sqlite3.Connection) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        # ---- preconditions ------------------------------------------------
        present = {row[0] for row in conn.execute("SELECT id FROM deployments")}
        unknown = present - set(EXPECTED)
        if unknown:
            _abort(
                f"deployments {sorted(unknown)} exist but have no approved backfill values. "
                "Every row must have an approved activated_at before this migration runs."
            )

        identity_before = _identity(conn)

        # ---- add the columns, only if absent ------------------------------
        cols = _columns(conn)
        added = []
        if "activated_at" not in cols:
            conn.execute("ALTER TABLE deployments ADD COLUMN activated_at DATETIME")
            added.append("activated_at")
        if "closed_at" not in cols:
            conn.execute("ALTER TABLE deployments ADD COLUMN closed_at DATETIME")
            added.append("closed_at")
        print(f"  columns added: {added or 'none (already present)'}")

        # ---- re-check the evidence behind each approved value -------------
        for dep_id, (which, expected_ts) in DERIVATION_EVIDENCE.items():
            agg = "MAX" if which == "last" else "MIN"
            actual = conn.execute(
                f"SELECT {agg}(timestamp) FROM energy_readings WHERE deployment_id = ?",
                (dep_id,),
            ).fetchone()[0]
            if actual != expected_ts:
                _abort(
                    f"deployment {dep_id}: approved value was derived from its {which} "
                    f"attributed reading {expected_ts!r}, but that is now {actual!r}. "
                    "The data has changed since approval; stopping."
                )
        print("  derivation evidence re-verified against current readings")

        # ---- apply, idempotently ------------------------------------------
        applied, already, skipped = 0, 0, 0
        for dep_id, (want_activated, want_closed) in sorted(EXPECTED.items()):
            if dep_id not in present:
                skipped += 1
                continue

            have_activated, have_closed = conn.execute(
                "SELECT activated_at, closed_at FROM deployments WHERE id = ?", (dep_id,)
            ).fetchone()

            for field, have, want in (
                ("activated_at", have_activated, want_activated),
                ("closed_at", have_closed, want_closed),
            ):
                if have is None:
                    if want is None:
                        continue  # nothing to derive; correctly stays NULL
                    conn.execute(
                        f"UPDATE deployments SET {field} = ? WHERE id = ?", (want, dep_id)
                    )
                    print(f"  deployment {dep_id}: {field} := {want}")
                    applied += 1
                elif have == want:
                    print(f"  deployment {dep_id}: {field} already {have} — unchanged")
                    already += 1
                else:
                    _abort(
                        f"deployment {dep_id}: {field} is already {have!r} but the approved "
                        f"value is {want!r}. Refusing to overwrite a populated timestamp."
                    )

        print(f"  applied={applied} already_correct={already} absent_rows={skipped}")

        # ---- identity must be byte-identical ------------------------------
        identity_after = _identity(conn)
        if identity_after != identity_before:
            changed = [
                k for k in identity_before
                if identity_before[k] != identity_after.get(k)
            ]
            _abort(f"identity fields changed for deployment(s) {changed}; aborting")
        print("  identity fields byte-identical for all deployments")

        # ---- coherence: R1 and R2 ------------------------------------------
        bad = conn.execute(
            """
            SELECT d.id, d.status, d.activated_at, d.closed_at
              FROM deployments d JOIN deployment_statuses s ON s.code = d.status
             WHERE (s.allows_attribution = 1 AND d.activated_at IS NULL)
                OR (s.allows_attribution = 1 AND s.is_terminal = 1 AND d.closed_at IS NULL)
            """
        ).fetchall()
        if bad:
            _abort(f"coherence violation after backfill: {bad}")
        print("  R1/R2 coherence satisfied")

        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def down(conn: sqlite3.Connection) -> None:
    """Drop both columns. The planning dates were never touched, so nothing else
    needs restoring."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        cols = _columns(conn)
        if "closed_at" in cols:
            conn.execute("ALTER TABLE deployments DROP COLUMN closed_at")
        if "activated_at" in cols:
            conn.execute("ALTER TABLE deployments DROP COLUMN activated_at")
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
