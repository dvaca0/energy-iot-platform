"""Invariants that must hold across every migration.

An invariant is not a test of what a migration was *meant* to do — that is the
job of each migration's own verification. An invariant guards against a
migration having done something that *no* migration is ever allowed to do:
lose a historical reading, silently alter a measured value, orphan a reading
from its node.

They run before and after every step. A violation aborts the run and leaves the
backup in place.

Two design points that matter on this platform:

Concurrent ingestion. Readings arrive from the Raspberry Pis every 15 seconds
while migrations run, so a naive "row count is unchanged" check would fail for
an innocent reason and pass for a guilty one. Every reading-level invariant is
therefore bounded by ``id <= max_reading_id`` captured at snapshot time. Rows
that arrive mid-migration are ignored; rows that existed before it are checked
exactly. The result is tolerant of growth and intolerant of loss.

Measured values versus attribution. These are checked separately and on purpose.
A measured value — voltage, current, power, energy, timestamp — must never
change in any migration, ever; that is the thesis data. Attribution —
deployment, building, panel, context — is normally frozen too, but a small
number of supervised migrations exist precisely to correct it. Those declare
``ALLOW_ATTRIBUTION_CHANGE`` and nothing else is waived for them.
"""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta

# Waiver names a migration may declare. Anything not listed here cannot be
# waived at all — there is deliberately no waiver for measured values.
ALLOW_ATTRIBUTION_CHANGE = "allow_attribution_change"
ALLOW_DEPLOYMENT_CHANGE = "allow_deployment_change"
ALLOW_NODE_CHANGE = "allow_node_change"
ALLOW_BUILDING_CHANGE = "allow_building_change"
ALLOW_TIMESTAMP_CHANGE = "allow_timestamp_change"

KNOWN_WAIVERS = {
    ALLOW_ATTRIBUTION_CHANGE,
    ALLOW_DEPLOYMENT_CHANGE,
    ALLOW_NODE_CHANGE,
    ALLOW_BUILDING_CHANGE,
    ALLOW_TIMESTAMP_CHANGE,
}

LEGAL_DEPLOYMENT_STATUS = (
    "planned",
    "installing",
    "active",
    "completed",
    "cancelled",
)

LEGAL_CONTEXT = (
    "production",
    "bench",
    "laboratory",
    "calibration",
    "commissioning",
    "simulation",
)


@dataclass
class Violation:
    invariant: str
    detail: str

    def __str__(self) -> str:
        return f"{self.invariant}: {self.detail}"


@dataclass
class Snapshot:
    """State captured before a migration, compared against after it."""

    taken_at: datetime
    max_reading_id: int
    reading_count: int
    measurement_digest: str
    attribution_digest: str
    timestamp_digest: str = ""
    identity_digest: str = ""
    identity_digest_no_ts: str = ""
    distinct_ids: int = 0
    per_node_counts: dict[int, int] = field(default_factory=dict)
    node_count: int = 0
    building_count: int = 0
    deployment_count: int = 0
    deep: bool = False


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _digest(rows) -> str:
    """Order-independent-free streaming hash of an ordered row set."""
    hasher = hashlib.sha256()
    for row in rows:
        hasher.update(repr(row).encode("utf-8"))
        hasher.update(b"\x1e")
    return hasher.hexdigest()


def _measurement_digest(conn: sqlite3.Connection, max_id: int, deep: bool) -> str:
    """Hash of every measured value for rows that existed at snapshot time.

    ``deep`` streams every row and is exact; the default uses SQL aggregates and
    is fast. The rebuild in M4 uses deep, since that is the one migration that
    physically rewrites every row.
    """
    # `timestamp` is deliberately excluded here — it has its own invariant
    # (INV-15) with its own waiver, so that a timezone or clock-skew correction
    # can be made deliberately without needing a waiver over every measured
    # value. Keeping it in both places would make the INV-15 waiver ineffective,
    # since INV-02 would still fire.
    if deep:
        rows = conn.execute(
            """
            SELECT id, node_id, voltage, current, power_kw, energy_kwh,
                   power_factor, frequency_hz,
                   phase_a_voltage, phase_b_voltage, phase_c_voltage,
                   phase_a_current, phase_b_current, phase_c_current
              FROM energy_readings
             WHERE id <= ?
             ORDER BY id
            """,
            (max_id,),
        )
        return _digest(rows)

    row = conn.execute(
        """
        SELECT COUNT(*), TOTAL(id), TOTAL(node_id),
               TOTAL(voltage), TOTAL(current), TOTAL(power_kw), TOTAL(energy_kwh),
               TOTAL(power_factor), TOTAL(frequency_hz),
               TOTAL(phase_a_current), TOTAL(phase_b_current), TOTAL(phase_c_current)
          FROM energy_readings
         WHERE id <= ?
        """,
        (max_id,),
    ).fetchone()
    # TOTAL() returns a float; round to fold away any last-bit drift that a
    # pure copy could introduce through text round-tripping.
    normalised = tuple(round(v, 6) if isinstance(v, float) else v for v in row)
    return _digest([normalised])


def _timestamp_digest(conn: sqlite3.Connection, max_id: int, deep: bool) -> str:
    """Hash of the measurement instant for rows that existed at snapshot time.

    The collector calls this field ``captured_at``; it is stored as
    ``energy_readings.timestamp``. It is the axis every analysis is indexed on,
    so a silent shift — a timezone applied twice, a clock correction backfilled —
    would invalidate every time-series result while leaving all the values
    themselves looking perfectly correct.
    """
    if deep:
        rows = conn.execute(
            "SELECT id, timestamp FROM energy_readings WHERE id <= ? ORDER BY id",
            (max_id,),
        )
        return _digest(rows)

    row = conn.execute(
        """
        SELECT COUNT(*), MIN(timestamp), MAX(timestamp),
               TOTAL(julianday(timestamp))
          FROM energy_readings
         WHERE id <= ?
        """,
        (max_id,),
    ).fetchone()
    # julianday() folds the whole column into one number, so any shift in any
    # row moves the total even when min and max are unchanged.
    normalised = tuple(round(v, 9) if isinstance(v, float) else v for v in row)
    return _digest([normalised])


def _identity_digests(conn: sqlite3.Connection, max_id: int) -> tuple[str, str]:
    """Hash the (id, node_id, captured_at) binding for pre-existing rows.

    Returns two digests from one pass: with and without the timestamp. The
    second exists so that a migration legitimately declaring
    ``allow_timestamp_change`` does not also have to waive row identity — the
    id-to-node binding stays enforced either way.

    This is the guarantee the table rebuild most needs and that no other
    invariant makes. INV-01 counts rows and INV-02 hashes values, but neither
    would notice if a rebuild preserved every row and every value while
    reassigning which id belonged to which reading — which is exactly what an
    ``INSERT ... SELECT`` without a deterministic order can do.
    """
    with_ts = hashlib.sha256()
    without_ts = hashlib.sha256()
    for row_id, node_id, ts in conn.execute(
        "SELECT id, node_id, timestamp FROM energy_readings WHERE id <= ? ORDER BY id",
        (max_id,),
    ):
        base = f"{row_id}|{node_id}".encode("utf-8")
        without_ts.update(base)
        without_ts.update(b"\x1e")
        with_ts.update(base)
        with_ts.update(f"|{ts}".encode("utf-8"))
        with_ts.update(b"\x1e")
    return with_ts.hexdigest(), without_ts.hexdigest()


def _attribution_digest(conn: sqlite3.Connection, max_id: int) -> str:
    cols = _columns(conn, "energy_readings")
    has_context = "context" in cols
    has_panel = "electrical_panel_id" in cols

    context_expr = "context" if has_context else "'production'"
    panel_expr = "COALESCE(electrical_panel_id, -1)" if has_panel else "-1"

    # Aggregates only. An earlier version selected bare deployment_id and
    # building_id alongside a GROUP BY, which makes SQLite pick an arbitrary row
    # from each group — so the digest changed across a table rebuild that had
    # altered nothing, and reported a false INV-03 violation. Every term here is
    # order-independent, and the context histogram is explicitly sorted.
    totals = conn.execute(
        f"""
        SELECT COUNT(*),
               TOTAL(COALESCE(deployment_id, -1)),
               TOTAL(COALESCE(building_id, -1)),
               TOTAL({panel_expr}),
               COUNT(deployment_id),
               COUNT(building_id)
          FROM energy_readings
         WHERE id <= ?
        """,
        (max_id,),
    ).fetchone()

    histogram = conn.execute(
        f"""
        SELECT {context_expr} AS ctx, COUNT(*)
          FROM energy_readings
         WHERE id <= ?
         GROUP BY ctx
         ORDER BY ctx
        """,
        (max_id,),
    ).fetchall()

    return _digest([totals, tuple(histogram)])


def take_snapshot(conn: sqlite3.Connection, deep: bool = False) -> Snapshot:
    max_id = conn.execute("SELECT COALESCE(MAX(id), 0) FROM energy_readings").fetchone()[0]
    count = conn.execute(
        "SELECT COUNT(*) FROM energy_readings WHERE id <= ?", (max_id,)
    ).fetchone()[0]

    per_node = {
        node_id: n
        for node_id, n in conn.execute(
            "SELECT node_id, COUNT(*) FROM energy_readings WHERE id <= ? GROUP BY node_id",
            (max_id,),
        )
    }

    identity_with_ts, identity_without_ts = _identity_digests(conn, max_id)
    distinct_ids = conn.execute(
        "SELECT COUNT(DISTINCT id) FROM energy_readings WHERE id <= ?", (max_id,)
    ).fetchone()[0]

    return Snapshot(
        taken_at=datetime.utcnow(),
        max_reading_id=max_id,
        reading_count=count,
        identity_digest=identity_with_ts,
        identity_digest_no_ts=identity_without_ts,
        distinct_ids=distinct_ids,
        measurement_digest=_measurement_digest(conn, max_id, deep),
        attribution_digest=_attribution_digest(conn, max_id),
        timestamp_digest=_timestamp_digest(conn, max_id, deep),
        per_node_counts=per_node,
        node_count=conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0],
        building_count=conn.execute("SELECT COUNT(*) FROM buildings").fetchone()[0],
        deployment_count=conn.execute("SELECT COUNT(*) FROM deployments").fetchone()[0],
        deep=deep,
    )


def check(
    conn: sqlite3.Connection,
    before: Snapshot | None = None,
    waivers: set[str] | None = None,
) -> list[Violation]:
    """Run every applicable invariant. Returns violations; empty means healthy."""
    waivers = waivers or set()
    unknown = waivers - KNOWN_WAIVERS
    if unknown:
        raise ValueError(f"unknown waiver(s): {sorted(unknown)}")

    violations: list[Violation] = []
    cols = _columns(conn, "energy_readings")

    # ---- INV-01  No historical reading is ever lost -----------------------
    if before is not None:
        now_count = conn.execute(
            "SELECT COUNT(*) FROM energy_readings WHERE id <= ?",
            (before.max_reading_id,),
        ).fetchone()[0]
        if now_count != before.reading_count:
            violations.append(
                Violation(
                    "INV-01-no-reading-lost",
                    f"rows with id <= {before.max_reading_id} went from "
                    f"{before.reading_count} to {now_count} "
                    f"({before.reading_count - now_count:+d})",
                )
            )

    # ---- INV-02  Measured values are immutable, without exception ---------
    if before is not None:
        now_digest = _measurement_digest(conn, before.max_reading_id, before.deep)
        if now_digest != before.measurement_digest:
            violations.append(
                Violation(
                    "INV-02-measurements-immutable",
                    "a measured value changed for a pre-existing reading "
                    f"({'deep' if before.deep else 'aggregate'} digest mismatch). "
                    "No migration is permitted to do this.",
                )
            )

    # ---- INV-03  Attribution is immutable unless explicitly waived --------
    if before is not None and ALLOW_ATTRIBUTION_CHANGE not in waivers:
        now_digest = _attribution_digest(conn, before.max_reading_id)
        if now_digest != before.attribution_digest:
            violations.append(
                Violation(
                    "INV-03-attribution-immutable",
                    "attribution or context changed for pre-existing readings and "
                    f"this step did not declare {ALLOW_ATTRIBUTION_CHANGE}",
                )
            )

    # ---- INV-04  Every reading belongs to a node that exists --------------
    orphans = conn.execute(
        """
        SELECT COUNT(*) FROM energy_readings r
         WHERE r.node_id IS NULL
            OR NOT EXISTS (SELECT 1 FROM nodes n WHERE n.id = r.node_id)
        """
    ).fetchone()[0]
    if orphans:
        violations.append(
            Violation("INV-04-reading-has-node", f"{orphans} reading(s) with no valid node")
        )

    # ---- INV-05  Node codes stay unique -----------------------------------
    dupes = conn.execute(
        "SELECT COUNT(*) FROM (SELECT code FROM nodes GROUP BY code HAVING COUNT(*) > 1)"
    ).fetchone()[0]
    if dupes:
        violations.append(Violation("INV-05-node-code-unique", f"{dupes} duplicated node code(s)"))

    # ---- INV-06  Deployment status is always a legal value ----------------
    # Once `deployment_statuses` exists it is the single authoritative
    # definition, so this reads it rather than restating the values. The module
    # constant is only the pre-M3 fallback and must not be treated as a second
    # source of truth.
    if _table_exists(conn, "deployment_statuses"):
        illegal = conn.execute(
            "SELECT COUNT(*) FROM deployments d "
            " WHERE NOT EXISTS (SELECT 1 FROM deployment_statuses s WHERE s.code = d.status)"
        ).fetchone()[0]
    else:
        placeholders = ",".join("?" * len(LEGAL_DEPLOYMENT_STATUS))
        illegal = conn.execute(
            f"SELECT COUNT(*) FROM deployments WHERE status NOT IN ({placeholders})",
            LEGAL_DEPLOYMENT_STATUS,
        ).fetchone()[0]
    if illegal:
        violations.append(
            Violation("INV-06-deployment-status-legal", f"{illegal} deployment(s) with illegal status")
        )

    # ---- INV-07  Context is always a legal value (once the column exists) --
    # As with INV-06, the lookup table is authoritative once it exists; the
    # module constant is only the pre-M4 fallback.
    if "context" in cols:
        if _table_exists(conn, "measurement_contexts"):
            illegal = conn.execute(
                "SELECT COUNT(*) FROM energy_readings r "
                " WHERE NOT EXISTS (SELECT 1 FROM measurement_contexts m WHERE m.code = r.context)"
            ).fetchone()[0]
        else:
            placeholders = ",".join("?" * len(LEGAL_CONTEXT))
            illegal = conn.execute(
                f"SELECT COUNT(*) FROM energy_readings WHERE context NOT IN ({placeholders})",
                LEGAL_CONTEXT,
            ).fetchone()[0]
        if illegal:
            violations.append(
                Violation("INV-07-context-legal", f"{illegal} reading(s) with illegal context")
            )

    # ---- INV-08  Attribution is coherent ----------------------------------
    # A reading attributed to a deployment must also name the building, or the
    # building-level analytics would silently drop it.
    if "context" in cols:
        incoherent = conn.execute(
            "SELECT COUNT(*) FROM energy_readings "
            " WHERE deployment_id IS NOT NULL AND building_id IS NULL"
        ).fetchone()[0]
        if incoherent:
            violations.append(
                Violation(
                    "INV-08-attribution-coherent",
                    f"{incoherent} reading(s) have a deployment but no building",
                )
            )

    # ---- INV-09  Non-production data is never attributed ------------------
    # This is the invariant that makes bench contamination structurally
    # impossible rather than merely filtered out at query time.
    if "context" in cols:
        if _table_exists(conn, "measurement_contexts"):
            leaked = conn.execute(
                """
                SELECT COUNT(*) FROM energy_readings r
                  JOIN measurement_contexts m ON m.code = r.context
                 WHERE m.may_attribute = 0
                   AND (r.deployment_id IS NOT NULL OR r.building_id IS NOT NULL)
                """
            ).fetchone()[0]
        else:
            leaked = conn.execute(
                """
                SELECT COUNT(*) FROM energy_readings
                 WHERE context NOT IN ('production', 'commissioning')
                   AND (deployment_id IS NOT NULL OR building_id IS NOT NULL)
                """
            ).fetchone()[0]
        if leaked:
            violations.append(
                Violation(
                    "INV-09-nonproduction-unattributed",
                    f"{leaked} non-production reading(s) carry a deployment or building",
                )
            )

    # ---- INV-10  Referential sanity for attribution ------------------------
    dangling = conn.execute(
        """
        SELECT COUNT(*) FROM energy_readings r
         WHERE (r.building_id IS NOT NULL
                AND NOT EXISTS (SELECT 1 FROM buildings b WHERE b.id = r.building_id))
            OR (r.deployment_id IS NOT NULL
                AND NOT EXISTS (SELECT 1 FROM deployments d WHERE d.id = r.deployment_id))
        """
    ).fetchone()[0]
    if dangling:
        violations.append(
            Violation("INV-10-attribution-refs-exist", f"{dangling} reading(s) point at a missing row")
        )

    # ---- INV-11  No reading is dated implausibly far in the future --------
    horizon = (datetime.utcnow() + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    future = conn.execute(
        "SELECT COUNT(*) FROM energy_readings WHERE timestamp > ?", (horizon,)
    ).fetchone()[0]
    if future:
        violations.append(
            Violation("INV-11-no-future-readings", f"{future} reading(s) dated more than a day ahead")
        )

    # ---- INV-12  Reference tables never shrink unexpectedly ---------------
    if before is not None:
        for label, key, waiver in (
            ("nodes", "node_count", ALLOW_NODE_CHANGE),
            ("buildings", "building_count", ALLOW_BUILDING_CHANGE),
            ("deployments", "deployment_count", ALLOW_DEPLOYMENT_CHANGE),
        ):
            if waiver in waivers:
                continue
            now = conn.execute(f"SELECT COUNT(*) FROM {label}").fetchone()[0]
            was = getattr(before, key)
            if now < was:
                violations.append(
                    Violation(
                        "INV-12-reference-tables-intact",
                        f"{label} shrank from {was} to {now}",
                    )
                )

    # ---- INV-14  Referential integrity across every foreign key -----------
    # PRAGMA foreign_key_check walks every declared FK in the schema, not just
    # the ones named in INV-04 and INV-10. Those two stay because they give a
    # precise message for the two cases most likely to break; this is the
    # catch-all that also covers smart plugs, panels, campuses and any table
    # added later without anyone remembering to extend this file.
    fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_rows:
        by_pair: dict[tuple, int] = {}
        for row in fk_rows:
            by_pair[(row[0], row[2])] = by_pair.get((row[0], row[2]), 0) + 1
        detail = "; ".join(
            f"{child} -> {parent}: {n}" for (child, parent), n in sorted(by_pair.items())
        )
        violations.append(
            Violation("INV-14-referential-integrity", f"{len(fk_rows)} orphaned row(s) — {detail}")
        )

    # ---- INV-15  The measurement instant is immutable ---------------------
    if before is not None and ALLOW_TIMESTAMP_CHANGE not in waivers:
        now_digest = _timestamp_digest(conn, before.max_reading_id, before.deep)
        if before.timestamp_digest and now_digest != before.timestamp_digest:
            violations.append(
                Violation(
                    "INV-15-timestamps-immutable",
                    "the measurement instant (captured_at) changed for pre-existing "
                    f"readings and this step did not declare {ALLOW_TIMESTAMP_CHANGE}",
                )
            )

    # ---- INV-16  Row identity is preserved exactly -------------------------
    # (id, node_id, captured_at) must be identical before and after: no
    # duplicated reading, no reordered id, no reassigned id.
    #
    # The id-to-node binding is never waivable. The captured_at component
    # follows ALLOW_TIMESTAMP_CHANGE so that INV-15's waiver stays coherent —
    # a deliberate timezone correction should not be forced to also waive
    # identity.
    if before is not None:
        now_with_ts, now_without_ts = _identity_digests(conn, before.max_reading_id)

        if before.identity_digest_no_ts and now_without_ts != before.identity_digest_no_ts:
            violations.append(
                Violation(
                    "INV-16-row-identity-preserved",
                    "the (id, node_id) binding changed for pre-existing readings — "
                    "an id was reassigned, reordered or duplicated",
                )
            )
        elif (
            ALLOW_TIMESTAMP_CHANGE not in waivers
            and before.identity_digest
            and now_with_ts != before.identity_digest
        ):
            violations.append(
                Violation(
                    "INV-16-row-identity-preserved",
                    "(id, node_id, captured_at) changed for pre-existing readings and "
                    f"this step did not declare {ALLOW_TIMESTAMP_CHANGE}",
                )
            )

        now_distinct = conn.execute(
            "SELECT COUNT(DISTINCT id) FROM energy_readings WHERE id <= ?",
            (before.max_reading_id,),
        ).fetchone()[0]
        if before.distinct_ids and now_distinct != before.distinct_ids:
            violations.append(
                Violation(
                    "INV-16-row-identity-preserved",
                    f"distinct reading ids went from {before.distinct_ids} to {now_distinct}",
                )
            )

    # A rebuild that lost the INTEGER PRIMARY KEY would make duplicate ids
    # possible in the first place, so the structure is checked too.
    pk_cols = [row[1] for row in conn.execute("PRAGMA table_info(energy_readings)") if row[5]]
    if pk_cols != ["id"]:
        violations.append(
            Violation(
                "INV-16-row-identity-preserved",
                f"energy_readings primary key is {pk_cols or 'absent'}, expected ['id']",
            )
        )

    # ---- INV-17  No two attribution windows overlap for one node ----------
    # The integrity property the whole deployment redesign exists to guarantee:
    # every reading must resolve to at most one deployment, so the resolver is
    # never forced to guess. MULTIPLE_MATCHES becomes an integrity violation
    # rather than a runtime possibility.
    #
    # Overlap is `a.activated_at <= b.closed_at AND b.activated_at <=
    # a.closed_at`, with a NULL close meaning unbounded. Only statuses that
    # attribute participate — a cancelled campaign claims nothing.
    if _table_exists(conn, "deployments") and "activated_at" in _columns(conn, "deployments"):
        overlaps = conn.execute(
            """
            SELECT a.node_id, a.id, b.id
              FROM deployments a
              JOIN deployments b
                ON b.node_id = a.node_id AND b.id > a.id
              JOIN deployment_statuses sa ON sa.code = a.status
              JOIN deployment_statuses sb ON sb.code = b.status
             WHERE sa.allows_attribution = 1 AND sb.allows_attribution = 1
               AND a.activated_at IS NOT NULL AND b.activated_at IS NOT NULL
               AND a.activated_at <= COALESCE(b.closed_at, '9999-12-31 23:59:59')
               AND b.activated_at <= COALESCE(a.closed_at, '9999-12-31 23:59:59')
            """
        ).fetchall()
        if overlaps:
            detail = "; ".join(f"node {n}: deployments {x} and {y}" for n, x, y in overlaps)
            violations.append(
                Violation("INV-17-deployment-windows-exclusive",
                          f"{len(overlaps)} overlapping attribution window(s) — {detail}")
            )

        # At most one deployment per node may hold an exclusive status.
        live = conn.execute(
            """
            SELECT d.node_id, COUNT(*)
              FROM deployments d JOIN deployment_statuses s ON s.code = d.status
             WHERE s.is_exclusive = 1
             GROUP BY d.node_id HAVING COUNT(*) > 1
            """
        ).fetchall() if "is_exclusive" in _columns(conn, "deployment_statuses") else []
        if live:
            violations.append(
                Violation("INV-17-deployment-windows-exclusive",
                          f"node(s) with more than one live deployment: {live}")
            )

    # ---- INV-18  Window coherence: status and window must agree -----------
    # R2: a status that attributes must have been activated.
    # R1: a terminal status that attributes must be bounded. This is exactly
    #     what deployment 4 violated after M3 opened its end_date — a completed
    #     campaign claiming every future instant.
    if _table_exists(conn, "deployments") and "activated_at" in _columns(conn, "deployments"):
        incoherent = conn.execute(
            """
            SELECT d.id, d.status,
                   CASE WHEN d.activated_at IS NULL THEN 'no activated_at'
                        ELSE 'terminal without closed_at' END
              FROM deployments d JOIN deployment_statuses s ON s.code = d.status
             WHERE s.allows_attribution = 1
               AND (d.activated_at IS NULL
                    OR (s.is_terminal = 1 AND d.closed_at IS NULL))
            """
        ).fetchall()
        if incoherent:
            detail = "; ".join(f"deployment {i} ({st}): {why}" for i, st, why in incoherent)
            violations.append(
                Violation("INV-18-deployment-window-coherent", detail)
            )

        # A closed window may not end before it began.
        inverted = conn.execute(
            "SELECT COUNT(*) FROM deployments "
            " WHERE activated_at IS NOT NULL AND closed_at IS NOT NULL "
            "   AND closed_at < activated_at"
        ).fetchone()[0]
        if inverted:
            violations.append(
                Violation("INV-18-deployment-window-coherent",
                          f"{inverted} deployment(s) closed before they were activated")
            )

    # ---- INV-13  The rollback table survives until cleanup ----------------
    # The rebuild keeps its pre-migration table as the rollback path; losing it
    # early would leave the highest-risk migration irreversible.
    #
    # Keyed on the migration *name*, not its version number. An earlier draft
    # tested `version == 4` and produced a false positive the moment an
    # unrelated migration happened to be numbered 004.
    #
    # Conditioned on the rebuild actually being *in effect* — the presence of
    # the `context` column — rather than on the ledger saying it was applied.
    # The runner records rolled_back_at only after this check passes, so keying
    # on the ledger made a legitimate rollback fail: it demands the very table
    # the rollback has just consumed.
    applied = _applied_names(conn)
    rebuild_in_effect = "context" in cols
    if rebuild_in_effect and any("rebuild_energy_readings" in name for name in applied):
        if not any("cleanup" in name for name in applied):
            if not _table_exists(conn, "energy_readings_pre_m4"):
                violations.append(
                    Violation(
                        "INV-13-rollback-path-present",
                        "energy_readings_pre_m4 is missing but cleanup has not run — "
                        "the rebuild's rollback path is gone",
                    )
                )

    return violations


def _applied_names(conn: sqlite3.Connection) -> set[str]:
    if not _table_exists(conn, "schema_migrations"):
        return set()
    return {
        row[0]
        for row in conn.execute("SELECT name FROM schema_migrations WHERE rolled_back_at IS NULL")
    }


def describe() -> list[tuple[str, str]]:
    """Human-readable catalogue, used by ``runner.py invariants``."""
    return [
        ("INV-01-no-reading-lost", "No reading that existed before a step is missing after it"),
        ("INV-02-measurements-immutable", "No measured value ever changes — never waivable"),
        ("INV-03-attribution-immutable", "Attribution changes only in a step that declares it"),
        ("INV-04-reading-has-node", "Every reading names a node that exists"),
        ("INV-05-node-code-unique", "Node codes are unique"),
        ("INV-06-deployment-status-legal", "Deployment status is one of the five legal values"),
        ("INV-07-context-legal", "Context is one of the six legal values"),
        ("INV-08-attribution-coherent", "A reading with a deployment also names a building"),
        ("INV-09-nonproduction-unattributed", "Bench/lab/calibration/simulation data is never attributed"),
        ("INV-10-attribution-refs-exist", "Attribution never points at a deleted row"),
        ("INV-11-no-future-readings", "No reading is dated more than a day ahead"),
        ("INV-12-reference-tables-intact", "Nodes, buildings and deployments never shrink unexpectedly"),
        ("INV-13-rollback-path-present", "energy_readings_pre_m4 survives until cleanup is deliberately run"),
        ("INV-14-referential-integrity", "Every foreign key in the schema resolves (PRAGMA foreign_key_check)"),
        ("INV-15-timestamps-immutable", "captured_at never changes without an explicit waiver"),
        ("INV-16-row-identity-preserved", "(id, node_id, captured_at) is identical: no duplicate, reordered or reassigned id"),
        ("INV-17-deployment-windows-exclusive", "No node has two overlapping attribution windows or two live deployments"),
        ("INV-18-deployment-window-coherent", "Attributing deployments are activated; terminal ones are bounded"),
    ]
