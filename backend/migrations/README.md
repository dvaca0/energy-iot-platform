# Migrations

Hand-rolled migration runner. There is no Alembic on this deployment and no git
repository, so this provides what would otherwise be missing: a record of what
has been applied, a rollback written alongside each change, and an invariant
gate that catches the failure modes which do not raise exceptions.

See [ADR-0005](../docs/adr/0005-migration-invariants.md) for why it works this way.

## Commands

```bash
cd /home/manager/energy-platform/backend

python3 -m migrations.runner status         # what is applied, what is pending
python3 -m migrations.runner verify         # invariants against current state
python3 -m migrations.runner invariants     # the catalogue
python3 -m migrations.runner backup         # ad-hoc online backup
python3 -m migrations.runner restore-drill  # prove a backup actually restores

python3 -m migrations.runner up             # apply everything pending
python3 -m migrations.runner up --to 4      # apply up to and including 004
python3 -m migrations.runner down --to 3    # roll back down to 003
```

## What every run does

1. Online backup into `backups/db/` — **never `cp`**, the database is WAL with a
   live multi-MB `-wal` file and a plain copy can capture a torn state.
2. Invariant snapshot.
3. Apply inside one transaction.
4. Re-check invariants against the snapshot; **automatic rollback on violation**.
5. Record in `schema_migrations`, or abort leaving the backup in place.

## Writing a migration

Two files in `versions/`, named `NNN_name.up.sql` and `NNN_name.down.sql`. The
runner **refuses to apply a step with no `.down.sql`** — rollback is written at
the same time as the change, not reconstructed under pressure afterwards.

A step that cannot be expressed in SQL may instead be `NNN_name.py` exposing
`up(conn)` and `down(conn)`.

Leading comments declare metadata:

```sql
-- description: what this step does
-- waivers: allow_attribution_change
-- deep: true
```

- `waivers` — invariants this step is permitted to change. Only the five names in
  `invariants.KNOWN_WAIVERS` are accepted, and an unrecognised name aborts the
  run **before** the backup is taken. **Measured values can never be waived.**
- `deep` — switch the measurement digest from fast SQL aggregates to a full
  row-by-row hash. Used by the M4 rebuild, the one step that physically rewrites
  every row.

## Concurrency

The Raspberry Pis write every 15 seconds and gunicorn holds a connection, so
migrations run against a live database. Two consequences:

- Every reading-level invariant is bounded by `id <= max_reading_id` captured at
  snapshot time. Rows arriving mid-migration are ignored; rows that existed
  before it are checked exactly.
- A step needing the write lock may wait for an in-flight insert; `busy_timeout`
  is 30 s. If a collector is blocked it buffers locally and retries, which is
  what the edge buffer exists for. Nothing is lost.

## Rollback tables

High-risk steps rename their table rather than dropping it
(`energy_readings_pre_m4`, `deployments_pre_m3`) so rollback is two renames with
no data movement. `INV-13` fails if such a table disappears before the explicit
cleanup step, so the rollback path cannot be lost by accident.

Cleanup is deliberately a separate migration, run only after a soak period and
only on explicit instruction.
