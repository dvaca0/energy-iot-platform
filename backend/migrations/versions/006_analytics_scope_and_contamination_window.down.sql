-- Rollback for 006.
--
-- Drops only derived objects. The view owns no data and the markers are
-- re-derivable from m5_attribution_backup, so nothing is lost.
--
-- The code half of M6 rolls back separately: restore the timestamped copies in
-- backups/ (*-before-m6-*) and send SIGHUP to the gunicorn master.

BEGIN IMMEDIATE;

DROP VIEW IF EXISTS v_m5_contamination_window;
DROP TABLE IF EXISTS migration_markers;

COMMIT;
