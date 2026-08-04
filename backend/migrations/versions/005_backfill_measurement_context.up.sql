-- description: classify N003's prototype and bench data, de-attributing both (ADR-0003, ADR-0006)
-- waivers: allow_attribution_change
--
-- Applies the platform owner's determination:
--
--   N003's May-June data is real historical acquisition from the prototype. It
--   predates the deployment model and must not be retroactively attributed.
--   Real signal on a real load, outside any campaign => `laboratory`.
--
--   N003's data from 2026-07-24 onward is the ADS1256 bring-up at the noise
--   floor (~1e-3 A, ~0 kW). The instrument was under test, not a load =>
--   `bench`.
--
-- Both are de-attributed. Neither is deleted, and both stay queryable and
-- exportable through the explicit ?context= parameter added in M6.
--
-- N001 is not touched. Its 101,943 readings are genuine production measurement;
-- that they point at a placeholder building is a metadata problem, addressed by
-- buildings.is_placeholder in M1, not a measurement-classification problem.
--
-- The 2026-07-01 split is safe rather than arbitrary: N003 has no data at all
-- between 2026-06-20 and 2026-07-24, so the boundary falls inside a five-week
-- gap and cannot bisect a run.
--
-- Rollback is exact, not approximate: every affected row's prior attribution is
-- captured by primary key first, inside the same transaction, so concurrent
-- ingestion cannot produce a row that is modified but unrecorded.

BEGIN IMMEDIATE;

-- ---------------------------------------------------------------- rollback
CREATE TABLE m5_attribution_backup AS
SELECT id, deployment_id, building_id, electrical_panel_id, context
  FROM energy_readings
 WHERE node_id = (SELECT id FROM nodes WHERE code = 'N003');

CREATE UNIQUE INDEX ix_m5_attribution_backup_id ON m5_attribution_backup(id);

CREATE TABLE m5_node_context_backup AS
SELECT id, code, measurement_context FROM nodes;

-- ------------------------------------------------------- prototype capture
UPDATE energy_readings
   SET context       = 'laboratory',
       deployment_id = NULL,
       building_id   = NULL
 WHERE node_id = (SELECT id FROM nodes WHERE code = 'N003')
   AND timestamp < '2026-07-01';

-- ------------------------------------------------------------ ADS1256 bench
UPDATE energy_readings
   SET context       = 'bench',
       deployment_id = NULL,
       building_id   = NULL
 WHERE node_id = (SELECT id FROM nodes WHERE code = 'N003')
   AND timestamp >= '2026-07-01';

-- --------------------------------------------------- declared node context
-- N003 is still on the bench and still producing noise-floor data. Declaring it
-- keeps the node's own statement consistent with how its data has just been
-- classified, and is what makes the M8 resolver behave correctly the moment it
-- is switched on.
--
-- It changes nothing today: no code reads nodes.measurement_context until M8,
-- so readings arriving between now and then still land as 'production'. That
-- window is reported, not hidden.
UPDATE nodes SET measurement_context = 'bench' WHERE code = 'N003';

COMMIT;
