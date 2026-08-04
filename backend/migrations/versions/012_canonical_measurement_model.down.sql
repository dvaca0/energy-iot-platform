-- Rollback for 012.
--
-- Drops only additions. The four canonical columns hold no data that exists
-- anywhere else at this point (the collector does not yet populate them), and
-- the era tables are derived knowledge, re-derivable from the investigation
-- recorded in ADR-0007.
--
-- No reading is touched on the way down either — DROP COLUMN in SQLite 3.45
-- rewrites the table but preserves every remaining value, and the invariant
-- gate verifies that.
--
-- After this, energy_aggregate falls back to its pre-012 behaviour: it treats
-- energy_kwh as a cumulative counter everywhere, which is wrong for the current
-- era. That is the state we are rolling back *to*, so it is expected.

BEGIN IMMEDIATE;

DROP INDEX IF EXISTS idx_measurement_eras_node;
DROP TABLE IF EXISTS measurement_eras;
DROP TABLE IF EXISTS energy_semantics;

ALTER TABLE energy_readings DROP COLUMN energy_source;
ALTER TABLE energy_readings DROP COLUMN meter_energy_kwh;
ALTER TABLE energy_readings DROP COLUMN interval_seconds;
ALTER TABLE energy_readings DROP COLUMN interval_energy_kwh;

COMMIT;
