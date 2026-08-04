-- Rollback for 003.
--
-- deployments_pre_m3 is the untouched pre-migration table, so this is a swap
-- rather than a reconstruction. Note that it also discards the D1 change
-- (deployment 4's open-ended end_date), which is the intended meaning of
-- rolling back this step.
--
-- Any deployment created after 003 was applied lives only in the new table and
-- would be lost by this rollback. With two deployments and no create traffic
-- that is currently vacuous, but it is the reason to roll back promptly if at
-- all.
--
-- legacy_alter_table=ON for the same reason as the up migration: otherwise the
-- renames rewrite energy_readings' foreign key to follow the discarded table.

PRAGMA foreign_keys = OFF;
PRAGMA legacy_alter_table = ON;

DROP INDEX IF EXISTS idx_deployments_node_dates;
DROP INDEX IF EXISTS ix_deployments_id;

ALTER TABLE deployments         RENAME TO deployments_discarded_m3;
ALTER TABLE deployments_pre_m3  RENAME TO deployments;

DROP TABLE deployments_discarded_m3;

CREATE INDEX ix_deployments_id ON deployments(id);

DROP TABLE deployment_status_transitions;
DROP TABLE deployment_statuses;

PRAGMA legacy_alter_table = OFF;
PRAGMA foreign_keys = ON;
