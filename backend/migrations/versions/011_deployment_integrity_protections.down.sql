-- Rollback for 011.
--
-- Drops only enforcement. No data is touched, and the deployments themselves
-- remain exactly as they are — the protections describe what may happen next,
-- not what already happened.
--
-- A later supervised migration that must legitimately correct an activated
-- deployment drops these, acts within its own backed-up reversible step, and
-- reinstates them — the same pattern the immutability trigger on
-- energy_readings uses.

BEGIN IMMEDIATE;

DROP TRIGGER IF EXISTS trg_deployment_immutable_after_activation;
DROP TRIGGER IF EXISTS trg_deployment_window_coherent_update;
DROP TRIGGER IF EXISTS trg_deployment_window_coherent_insert;
DROP INDEX   IF EXISTS ux_deployment_one_live_per_node;

COMMIT;
