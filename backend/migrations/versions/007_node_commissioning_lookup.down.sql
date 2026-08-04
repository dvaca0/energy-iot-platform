-- Rollback for 007.
-- waivers: allow_node_change
--
-- nodes_pre_m7 is the untouched pre-migration table, so this is a swap rather
-- than a reconstruction.
--
-- Unlike the M4 rollback there is no carry-forward step: nodes are created by
-- an operator, not by ingestion, so no row can appear between the migration and
-- its rollback without someone deliberately adding it. If that has happened,
-- INV-12 fails the rollback rather than discarding the new node.

PRAGMA foreign_keys = OFF;
PRAGMA legacy_alter_table = ON;

BEGIN IMMEDIATE;

DROP INDEX IF EXISTS ix_nodes_code;
DROP INDEX IF EXISTS ix_nodes_id;
DROP INDEX IF EXISTS idx_nodes_last_sync;

ALTER TABLE nodes         RENAME TO nodes_discarded_m7;
ALTER TABLE nodes_pre_m7  RENAME TO nodes;

DROP TABLE nodes_discarded_m7;

CREATE UNIQUE INDEX ix_nodes_code ON nodes (code);
CREATE INDEX ix_nodes_id ON nodes (id);
CREATE INDEX idx_nodes_last_sync ON nodes (last_sync);

DROP TABLE IF EXISTS node_commission_states;

COMMIT;

PRAGMA legacy_alter_table = OFF;
PRAGMA foreign_keys = ON;
