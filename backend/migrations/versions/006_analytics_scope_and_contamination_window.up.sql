-- description: record the analytics scope cutover and make the M5 contamination window auditable
--
-- M6 is principally a code change (app/db/scope.py, applied at every analytics
-- call site). It is registered here so the ledger records when the analytics
-- boundary moved, and it carries the two database artifacts that change
-- requires.
--
-- 1. migration_markers
--
--    Freeze points that later migrations need to reason about "rows created
--    between X and Y". M8's cutover plan depends on one of these, so it is
--    recorded now rather than reconstructed later from log files.
--
-- 2. v_m5_contamination_window
--
--    N003 continues to write production-attributed rows because the live write
--    path is unchanged by design — M8 is shadow-only until explicitly approved.
--    Rather than patch the write path, the affected rows are made permanently
--    identifiable.
--
--    The view is:
--      deterministic  a fixed predicate over stored columns; the same query
--                     returns the same set for the same data, always
--      idempotent     it is a view, so reading it changes nothing
--      auditable      queryable at any time, by anyone, without this session
--      reversible     it owns no data; dropping it loses nothing
--
--    The boundary is derived, not hard-coded: m5_attribution_backup contains
--    exactly the N003 rows that existed when M5 ran, so any N003 row with a
--    larger id was created afterwards. Nothing to keep in sync.

BEGIN IMMEDIATE;

CREATE TABLE migration_markers (
    name        TEXT PRIMARY KEY,
    reading_id  INTEGER NOT NULL,
    recorded_at TEXT    NOT NULL,
    notes       TEXT
);

INSERT INTO migration_markers (name, reading_id, recorded_at, notes)
VALUES (
    'm5_n003_boundary',
    (SELECT COALESCE(MAX(id), 0) FROM m5_attribution_backup),
    datetime('now'),
    'Highest N003 reading id classified by M5. N003 rows above this were created after classification and are the contamination window.'
);

INSERT INTO migration_markers (name, reading_id, recorded_at, notes)
VALUES (
    'm6_analytics_scope',
    (SELECT COALESCE(MAX(id), 0) FROM energy_readings),
    datetime('now'),
    'Highest reading id when analytics switched to production-scoped queries.'
);

CREATE VIEW v_m5_contamination_window AS
SELECT
    er.id,
    er.node_id,
    n.code AS node_code,
    er.deployment_id,
    er.building_id,
    er.electrical_panel_id,
    er.context,
    er.timestamp,
    er.ingested_at
  FROM energy_readings er
  JOIN nodes n ON n.id = er.node_id
 WHERE er.node_id = (SELECT id FROM nodes WHERE code = 'N003')
   AND er.context = 'production'
   AND er.id > (SELECT reading_id FROM migration_markers WHERE name = 'm5_n003_boundary');

COMMIT;
