-- Rollback for 014.
-- waivers:
--
-- Refuses to remove the context while any reading still declares it: deleting
-- it would leave those rows pointing at a context that no longer exists, and
-- INV-07 would fail on the next migration. Reclassify them first if this must
-- be rolled back.

BEGIN IMMEDIATE;

DELETE FROM measurement_contexts
 WHERE code = 'infrastructure_validation'
   AND NOT EXISTS (
       SELECT 1 FROM energy_readings
        WHERE context = 'infrastructure_validation'
   );

COMMIT;
