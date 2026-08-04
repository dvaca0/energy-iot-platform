# ADR-0005 — Migrations are gated by invariants, not by review alone

- **Status:** accepted
- **Date:** 2026-07-26

## Context

The platform holds real historical data collected during development — 225,000+
readings that cannot be regenerated. There is no Alembic, no git repository, and
schema changes had previously been made by hand with timestamped `.bak` files.

The failure modes that matter here do not raise exceptions. A migration that
drops rows, silently rewrites a measured value, or orphans readings from their
node completes successfully and reports nothing. Review catches some of these;
review of a 12-step table rebuild under concurrent ingestion catches fewer.

## Decision

Every migration runs through `migrations/runner.py`, which performs five steps in
order: online backup, invariant snapshot, apply within a transaction, re-check
invariants against the snapshot, then record or automatically roll back.

Fifteen invariants are checked before and after every step
(`migrations/invariants.py`). The catalogue is available via
`python3 -m migrations.runner invariants`.

Four design points:

**Bounded by snapshot id.** The Pis write every 15 seconds while migrations run,
so a naive "row count unchanged" check would fail for an innocent reason and pass
for a guilty one. Every reading-level invariant is bounded by
`id <= max_reading_id` captured at snapshot time — tolerant of growth,
intolerant of loss.

**Measured values and attribution are checked separately.** Measured values may
never change under any migration; `INV-02` has no waiver. Attribution is normally
frozen too, but a small number of supervised migrations exist to correct it, and
those declare `allow_attribution_change`. Nothing else is waived for them.

**Rollback ships with the migration.** The runner refuses to apply a step that
has no `.down.sql`. Rollback is written at the same time as the change, not
reconstructed under pressure afterwards.

**The measurement instant is its own invariant.** `INV-15` covers
`captured_at` (stored as `energy_readings.timestamp`) separately from the
measured values, with its own `allow_timestamp_change` waiver. It is the axis
every analysis is indexed on, so a silent shift — a timezone applied twice, a
clock correction backfilled — would invalidate every time-series result while
leaving the values themselves looking correct. Because the waiver has to be
effective, `timestamp` is excluded from `INV-02`; this is a deliberate and
slight loosening, traded for the ability to make a timezone correction
deliberately rather than by waiving every measured value at once.

## Consequences

- Backups use SQLite's online backup API, never `cp`. The database runs in WAL
  mode with a live multi-megabyte `-wal` file, and a plain copy can capture a
  torn state.
- `restore-drill` restores a backup to a scratch path and compares counts,
  measured totals and invariants against the live database. The drill must pass
  before the high-risk table rebuild is permitted to run — the rollback path is
  proven rather than assumed.
- High-risk migrations retain their pre-migration table (`energy_readings_pre_m4`,
  `deployments_pre_m3`) rather than dropping it. Rollback is two renames.
  `INV-13` fails if that table disappears before the explicit cleanup step, so
  the rollback path cannot be lost by accident.
- Automatic rollback on invariant violation means a migration that looks
  successful but corrupts data does not survive to be discovered later.

## Alternatives considered

**Adopt Alembic.** Rejected for now: it adds a dependency to a deployment with no
package manager access and no root, and its autogenerate would not have caught
any of the failure modes above. The registry table here is deliberately
Alembic-compatible in spirit, so migrating later is possible.

**Rely on backups alone.** Rejected: a backup detects nothing. Without
invariants, a corrupting migration is discovered when someone notices a wrong
number weeks later, by which point the backup predates other legitimate work.
