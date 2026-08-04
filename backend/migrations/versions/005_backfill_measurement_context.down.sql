-- Rollback for 005.
-- waivers: allow_attribution_change
--
-- Restores each affected row's exact prior attribution by primary key from the
-- snapshot taken in the same transaction as the change. Rows that arrived after
-- 005 was applied have no backup entry and are deliberately left alone: they
-- were never modified by this step.

BEGIN IMMEDIATE;

UPDATE energy_readings
   SET context = (SELECT b.context FROM m5_attribution_backup b WHERE b.id = energy_readings.id),
       deployment_id = (SELECT b.deployment_id FROM m5_attribution_backup b WHERE b.id = energy_readings.id),
       building_id = (SELECT b.building_id FROM m5_attribution_backup b WHERE b.id = energy_readings.id),
       electrical_panel_id = (SELECT b.electrical_panel_id FROM m5_attribution_backup b WHERE b.id = energy_readings.id)
 WHERE EXISTS (SELECT 1 FROM m5_attribution_backup b WHERE b.id = energy_readings.id);

UPDATE nodes
   SET measurement_context = (
        SELECT b.measurement_context FROM m5_node_context_backup b WHERE b.id = nodes.id)
 WHERE EXISTS (SELECT 1 FROM m5_node_context_backup b WHERE b.id = nodes.id);

DROP INDEX IF EXISTS ix_m5_attribution_backup_id;
DROP TABLE m5_attribution_backup;
DROP TABLE m5_node_context_backup;

COMMIT;
