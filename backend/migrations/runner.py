#!/usr/bin/env python3
"""Migration runner for the energy platform.

There is no Alembic here and no git repository, so this provides the two things
that would otherwise be missing: a record of what has been applied, and a
rollback for each step that is written at the same time as the step itself.

Every run does the same five things, in this order:

    1. back up the database with SQLite's online backup API
    2. take an invariant snapshot
    3. apply the migration inside one transaction
    4. re-check the invariants against the snapshot
    5. record the result, or roll back and abort

Step 4 is what makes this worth having. A migration that succeeds
mechanically but violates an invariant is rolled back automatically, because
the failure modes that matter on this platform — a lost reading, a silently
rewritten measurement — do not raise an exception on their own.

Usage
-----
    python3 -m migrations.runner status
    python3 -m migrations.runner up            # apply everything pending
    python3 -m migrations.runner up --to 4     # apply up to and including 004
    python3 -m migrations.runner down --to 3   # roll back to 003
    python3 -m migrations.runner verify        # invariants against current state
    python3 -m migrations.runner backup        # ad-hoc backup
    python3 -m migrations.runner restore-drill # prove the backup restores
    python3 -m migrations.runner invariants    # list the catalogue

Migrations live in ``migrations/versions`` as ``NNN_name.up.sql`` plus a
matching ``.down.sql``. A step that cannot be expressed in SQL may instead be
``NNN_name.py`` exposing ``up(conn)`` and ``down(conn)``.

A SQL migration may declare metadata in leading comments:

    -- waivers: allow_attribution_change
    -- deep: true
    -- description: what this step does

``waivers`` names invariants this step is permitted to change (see
``invariants.py``; measured values can never be waived). ``deep`` switches the
measurement digest from fast aggregates to a full row-by-row hash, which is
what the M4 rebuild uses.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from migrations import invariants as inv  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent.parent
# Overridable so the harness itself can be exercised against a throwaway copy.
# Production runs leave it unset and act on the real database.
DB_PATH = Path(os.environ.get("ENERGY_DB_PATH", BACKEND_DIR / "energy_platform.db"))
VERSIONS_DIR = Path(os.environ.get("ENERGY_MIGRATIONS_DIR", Path(__file__).resolve().parent / "versions"))
BACKUP_DIR = Path(os.environ.get("ENERGY_BACKUP_DIR", BACKEND_DIR / "backups" / "db"))

# The Pis write every 15 s and gunicorn holds a connection, so a migration that
# needs the write lock may have to wait a moment for an in-flight insert.
BUSY_TIMEOUT_MS = 30_000


# --------------------------------------------------------------------------- io
def connect(path: Path = DB_PATH, read_only: bool = False) -> sqlite3.Connection:
    if read_only:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(str(path))
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_registry(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version        INTEGER NOT NULL,
            name           TEXT    NOT NULL,
            checksum       TEXT    NOT NULL,
            applied_at     TEXT    NOT NULL,
            rolled_back_at TEXT,
            backup_path    TEXT,
            notes          TEXT,
            PRIMARY KEY (version, applied_at)
        );
        """
    )
    conn.commit()


# ---------------------------------------------------------------------- discovery
class Migration:
    def __init__(self, version: int, name: str, up: Path, down: Path | None, py: Path | None):
        self.version = version
        self.name = name
        self.up_path = up
        self.down_path = down
        self.py_path = py

    @property
    def label(self) -> str:
        return f"{self.version:03d}_{self.name}"

    def _text(self, path: Path | None) -> str:
        return path.read_text(encoding="utf-8") if path and path.exists() else ""

    @property
    def checksum(self) -> str:
        body = self._text(self.up_path) + self._text(self.py_path)
        return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]

    def _meta(self, key: str, default: str = "") -> str:
        text = self._text(self.up_path) or self._text(self.py_path)
        # Horizontal whitespace only after the colon: \s* would match the
        # newline and let an empty `-- waivers:` swallow the following line.
        match = re.search(
            rf"^[ \t]*(?:--|#)[ \t]*{key}[ \t]*:[ \t]*(.*)$",
            text,
            re.MULTILINE | re.IGNORECASE,
        )
        if not match:
            return default
        return match.group(1).strip() or default

    @property
    def waivers(self) -> set[str]:
        raw = self._meta("waivers")
        return {w.strip() for w in raw.split(",") if w.strip()}

    @property
    def deep(self) -> bool:
        return self._meta("deep", "false").lower() in ("1", "true", "yes")

    @property
    def description(self) -> str:
        return self._meta("description", self.name.replace("_", " "))

    def has_rollback(self) -> bool:
        return bool(self.down_path and self.down_path.exists()) or bool(self.py_path)


def discover() -> list[Migration]:
    VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    found: dict[int, dict] = {}

    for path in sorted(VERSIONS_DIR.iterdir()):
        match = re.match(r"^(\d{3})_([a-z0-9_]+)\.(up|down)\.sql$", path.name)
        if match:
            version, name, direction = int(match.group(1)), match.group(2), match.group(3)
            found.setdefault(version, {"name": name})[direction] = path
            continue
        match = re.match(r"^(\d{3})_([a-z0-9_]+)\.py$", path.name)
        if match:
            version, name = int(match.group(1)), match.group(2)
            found.setdefault(version, {"name": name})["py"] = path

    migrations = []
    for version in sorted(found):
        entry = found[version]
        migrations.append(
            Migration(
                version=version,
                name=entry["name"],
                up=entry.get("up"),
                down=entry.get("down"),
                py=entry.get("py"),
            )
        )
    return migrations


def applied_versions(conn: sqlite3.Connection) -> dict[int, str]:
    ensure_registry(conn)
    return {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT version, applied_at FROM schema_migrations WHERE rolled_back_at IS NULL"
        )
    }


# ------------------------------------------------------------------------ backup
def backup(note: str = "adhoc") -> Path:
    """Online backup. Never use cp: the database is WAL with a live -wal file."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = BACKUP_DIR / f"energy_platform-{stamp}-{note}.db"

    source = connect(read_only=True)
    dest = sqlite3.connect(str(target))
    try:
        source.backup(dest)
    finally:
        dest.close()
        source.close()

    size_mb = target.stat().st_size / 1024 / 1024
    print(f"  backup  {target.name}  ({size_mb:.1f} MB)")
    return target


def _aggregates(conn: sqlite3.Connection) -> dict:
    out = {}
    for table in ("energy_readings", "nodes", "buildings", "deployments", "smart_plug_readings"):
        try:
            out[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except sqlite3.Error:
            out[table] = None
    row = conn.execute(
        "SELECT TOTAL(power_kw), TOTAL(energy_kwh), MIN(timestamp), MAX(timestamp) "
        "FROM energy_readings"
    ).fetchone()
    out["power_kw_total"] = round(row[0], 6)
    out["energy_kwh_total"] = round(row[1], 6)
    out["timestamp_min"] = row[2]
    out["timestamp_max"] = row[3]
    return out


def restore_drill() -> bool:
    """Prove the backup is restorable, rather than assuming it.

    Takes a backup, opens the copy, and compares it against the live database
    bounded by the live max reading id — so readings that arrive during the
    drill do not make it look like a mismatch.
    """
    print("restore drill")
    target = backup("drill")

    live = connect(read_only=True)
    copy = connect(target, read_only=True)
    try:
        max_id = copy.execute("SELECT COALESCE(MAX(id), 0) FROM energy_readings").fetchone()[0]
        ok = True

        for table in ("energy_readings", "nodes", "buildings", "deployments"):
            bound = " WHERE id <= ?" if table == "energy_readings" else ""
            args = (max_id,) if bound else ()
            a = live.execute(f"SELECT COUNT(*) FROM {table}{bound}", args).fetchone()[0]
            b = copy.execute(f"SELECT COUNT(*) FROM {table}{bound}", args).fetchone()[0]
            flag = "ok " if a == b else "FAIL"
            print(f"  {flag} {table:<22} live={a:<8} restored={b}")
            ok &= a == b

        a = live.execute(
            "SELECT TOTAL(power_kw), TOTAL(energy_kwh) FROM energy_readings WHERE id <= ?",
            (max_id,),
        ).fetchone()
        b = copy.execute(
            "SELECT TOTAL(power_kw), TOTAL(energy_kwh) FROM energy_readings WHERE id <= ?",
            (max_id,),
        ).fetchone()
        same = tuple(round(v, 6) for v in a) == tuple(round(v, 6) for v in b)
        print(f"  {'ok ' if same else 'FAIL'} measured totals       {tuple(round(v, 3) for v in a)}")
        ok &= same

        violations = inv.check(copy)
        print(f"  {'ok ' if not violations else 'FAIL'} invariants on restored copy ({len(violations)} violation(s))")
        for v in violations:
            print(f"       {v}")
        ok &= not violations
    finally:
        live.close()
        copy.close()

    print(f"\n  drill {'PASSED' if ok else 'FAILED'} — restorable copy at {target}")
    return ok


# ------------------------------------------------------------------------- apply
def _run_sql(conn: sqlite3.Connection, path: Path) -> None:
    conn.executescript(path.read_text(encoding="utf-8"))


def _run_py(path: Path, conn: sqlite3.Connection, direction: str) -> None:
    """Run a Python migration in explicit-transaction mode.

    isolation_level=None turns off the driver's implicit BEGIN, which a table
    rebuild needs: PRAGMA foreign_keys is a silent no-op inside a transaction,
    so the migration has to be able to set it, then open its own transaction.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    previous = conn.isolation_level
    conn.isolation_level = None
    try:
        getattr(module, direction)(conn)
    finally:
        conn.isolation_level = previous


def apply_one(migration: Migration, direction: str = "up") -> bool:
    """Apply one migration with backup, invariant gate and automatic rollback."""
    print(f"\n{'=' * 72}\n{direction.upper()}  {migration.label}\n{'=' * 72}")
    print(f"  {migration.description}")

    if direction == "up" and not migration.has_rollback():
        print("  ABORT: no .down.sql — every migration must ship its own rollback")
        return False

    # Validate waivers before touching anything. Deferring this to the
    # post-apply check would surface a typo only after the write had landed.
    unknown = migration.waivers - inv.KNOWN_WAIVERS
    if unknown:
        print(f"  ABORT: unknown waiver(s) {sorted(unknown)}")
        print(f"  known waivers: {sorted(inv.KNOWN_WAIVERS)}")
        return False

    if migration.waivers:
        print(f"  waivers: {', '.join(sorted(migration.waivers))}")

    backup_path = backup(f"pre-{migration.version:03d}-{direction}")

    conn = connect()
    ensure_registry(conn)

    print("  snapshot" + ("  (deep)" if migration.deep else ""))
    before = inv.take_snapshot(conn, deep=migration.deep)
    print(f"    readings <= id {before.max_reading_id}: {before.reading_count:,}")

    pre_violations = inv.check(conn)
    if pre_violations:
        print("  ABORT: the database already violates its invariants before this step:")
        for v in pre_violations:
            print(f"    {v}")
        conn.close()
        return False

    try:
        conn.execute("BEGIN IMMEDIATE")
        if migration.py_path:
            _run_py(migration.py_path, conn, direction)
        else:
            path = migration.up_path if direction == "up" else migration.down_path
            # executescript() commits any open transaction, so the explicit
            # BEGIN above is released; the script owns its own atomicity.
            conn.commit()
            _run_sql(conn, path)
        conn.commit()
    except Exception as exc:  # noqa: BLE001
        conn.rollback()
        print(f"  FAILED: {type(exc).__name__}: {exc}")
        print(f"  database rolled back; backup at {backup_path}")
        conn.close()
        return False

    violations = inv.check(conn, before, waivers=migration.waivers)
    if violations:
        print(f"  INVARIANT VIOLATION ({len(violations)}):")
        for v in violations:
            print(f"    {v}")
        print("  attempting automatic rollback...")
        try:
            if migration.py_path:
                _run_py(migration.py_path, conn, "down" if direction == "up" else "up")
            else:
                back = migration.down_path if direction == "up" else migration.up_path
                if back and back.exists():
                    _run_sql(conn, back)
            conn.commit()
            print("  rolled back.")
        except Exception as exc:  # noqa: BLE001
            print(f"  ROLLBACK FAILED: {exc}")
            print(f"  RESTORE MANUALLY FROM: {backup_path}")
        conn.close()
        return False

    now = datetime.utcnow().isoformat()
    if direction == "up":
        conn.execute(
            "INSERT INTO schema_migrations (version, name, checksum, applied_at, backup_path) "
            "VALUES (?, ?, ?, ?, ?)",
            (migration.version, migration.name, migration.checksum, now, str(backup_path)),
        )
    else:
        conn.execute(
            "UPDATE schema_migrations SET rolled_back_at = ? "
            " WHERE version = ? AND rolled_back_at IS NULL",
            (now, migration.version),
        )
    conn.commit()

    after = inv.take_snapshot(conn, deep=False)
    grew = after.reading_count - before.reading_count
    print(f"  invariants  {len(inv.describe())} checked, 0 violations")
    print(f"  readings    {before.reading_count:,} -> {after.reading_count:,}"
          + (f"  (+{grew} arrived during the step)" if grew else ""))
    print(f"  OK          {migration.label} {direction}")
    conn.close()
    return True


# -------------------------------------------------------------------- commands
def cmd_status() -> None:
    conn = connect(read_only=True)
    done = applied_versions(conn) if _has_registry(conn) else {}
    migrations = discover()
    print(f"database  {DB_PATH}")
    print(f"readings  {conn.execute('SELECT COUNT(*) FROM energy_readings').fetchone()[0]:,}\n")
    if not migrations:
        print("no migrations found in migrations/versions/")
    for m in migrations:
        mark = "applied " if m.version in done else "pending "
        when = done.get(m.version, "")
        roll = "" if m.has_rollback() else "  [NO ROLLBACK]"
        print(f"  [{mark}] {m.label:<44} {when[:19]}{roll}")
    conn.close()


def _has_registry(conn: sqlite3.Connection) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
        ).fetchone()
        is not None
    )


def cmd_up(to: int | None) -> int:
    conn = connect()
    done = applied_versions(conn)
    conn.close()

    pending = [m for m in discover() if m.version not in done]
    if to is not None:
        pending = [m for m in pending if m.version <= to]

    if not pending:
        print("nothing to apply")
        return 0

    for m in pending:
        if not apply_one(m, "up"):
            print("\nstopped — nothing further was applied")
            return 1
    return 0


def cmd_down(to: int) -> int:
    conn = connect()
    done = applied_versions(conn)
    conn.close()

    targets = sorted((m for m in discover() if m.version in done and m.version > to),
                     key=lambda m: m.version, reverse=True)
    if not targets:
        print("nothing to roll back")
        return 0

    for m in targets:
        if not apply_one(m, "down"):
            return 1
    return 0


def cmd_verify() -> int:
    conn = connect(read_only=True)
    violations = inv.check(conn)
    agg = _aggregates(conn)
    conn.close()

    print("current state")
    for key, value in agg.items():
        printable = f"{value:,}" if isinstance(value, int) else value
        print(f"  {key:<22} {printable}")

    print(f"\ninvariants: {len(inv.describe())} checked, {len(violations)} violation(s)")
    for v in violations:
        print(f"  FAIL {v}")
    if not violations:
        print("  all invariants hold")
    return 1 if violations else 0


def cmd_invariants() -> None:
    print("invariant catalogue\n")
    for name, description in inv.describe():
        print(f"  {name:<36} {description}")
    print("\nwaivable by a migration: " + ", ".join(sorted(inv.KNOWN_WAIVERS)))
    print("never waivable:          INV-02-measurements-immutable")


def main() -> int:
    parser = argparse.ArgumentParser(prog="migrations.runner", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    p_up = sub.add_parser("up")
    p_up.add_argument("--to", type=int, default=None)
    p_down = sub.add_parser("down")
    p_down.add_argument("--to", type=int, required=True)
    sub.add_parser("verify")
    sub.add_parser("backup")
    sub.add_parser("restore-drill")
    sub.add_parser("invariants")

    args = parser.parse_args()

    if args.command == "status":
        cmd_status()
        return 0
    if args.command == "up":
        return cmd_up(args.to)
    if args.command == "down":
        return cmd_down(args.to)
    if args.command == "verify":
        return cmd_verify()
    if args.command == "backup":
        backup("manual")
        return 0
    if args.command == "restore-drill":
        return 0 if restore_drill() else 1
    if args.command == "invariants":
        cmd_invariants()
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
