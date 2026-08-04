-- Rollback for 008.
-- waivers:
--
-- Everything 008 did was additive, so the rollback is a straight removal: drop
-- the two new tables, drop the fifteen added columns.
--
-- SQLite is 3.45.1 here, well past the 3.35 that introduced ALTER TABLE DROP
-- COLUMN, so no table rebuild is needed. That matters: rebuilding `deployments`
-- would rewrite the foreign keys pointing at it from energy_readings, exactly
-- the hazard M3 and M7 had to work around with legacy_alter_table. Dropping a
-- column touches neither the row data nor any foreign key.
--
-- Any ratings an operator entered are lost by this rollback, which is correct —
-- they are configuration for a feature being removed, not measurement data.
-- Node commission history is lost with node_commission_events for the same
-- reason. No reading is touched by any statement here.

BEGIN IMMEDIATE;

DROP INDEX IF EXISTS idx_node_commission_events_node;
DROP TABLE IF EXISTS node_commission_events;
DROP TABLE IF EXISTS node_commission_transitions;

ALTER TABLE deployments DROP COLUMN sustained_seconds;
ALTER TABLE deployments DROP COLUMN emergency_current_a;
ALTER TABLE deployments DROP COLUMN critical_current_a;
ALTER TABLE deployments DROP COLUMN warning_current_a;
ALTER TABLE deployments DROP COLUMN phase_count;
ALTER TABLE deployments DROP COLUMN nominal_voltage_v;
ALTER TABLE deployments DROP COLUMN ct_max_current_a;
ALTER TABLE deployments DROP COLUMN panel_main_breaker_a;

ALTER TABLE nodes DROP COLUMN sustained_seconds;
ALTER TABLE nodes DROP COLUMN emergency_current_a;
ALTER TABLE nodes DROP COLUMN critical_current_a;
ALTER TABLE nodes DROP COLUMN warning_current_a;
ALTER TABLE nodes DROP COLUMN phase_count;
ALTER TABLE nodes DROP COLUMN nominal_voltage_v;
ALTER TABLE nodes DROP COLUMN ct_max_current_a;

COMMIT;
