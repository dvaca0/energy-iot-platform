-- description: canonical deployment lifecycle as lookup tables, open-ended dates, D1 (ADR-0001, ADR-0006)
-- waivers: allow_deployment_change
--
-- Three things happen here.
--
-- 1. The lifecycle becomes DATA, not a constraint literal.
--
--    A CHECK constraint listing five statuses would have to be rewritten -- and
--    the whole table rebuilt -- to introduce a sixth. A lookup table makes a new
--    lifecycle state one INSERT, with no schema change and no code change,
--    because the semantics a caller needs (may it be attributed? is it terminal?
--    is it operational?) are columns rather than hard-coded knowledge.
--
--    Legal transitions are data for the same reason.
--
--    This also removes the duplication: deployments.status is now a foreign key,
--    so INV-14 (PRAGMA foreign_key_check) enforces status validity for free, and
--    the Python side reads the same tables rather than restating the values.
--
-- 2. end_date becomes nullable, so an open-ended campaign can be expressed.
--
-- 3. D1 is applied: deployment 4 gets end_date = NULL. Its building assignment
--    is deliberately NOT touched -- building 8 stays a placeholder until a real
--    location is known (ADR-0006).
--
-- Measurements are not touched at all. INV-02 and INV-15 confirm it.
--
-- The rename below uses legacy_alter_table=ON. Verified on this host that
-- without it, SQLite 3.45 rewrites energy_readings' foreign key to point at
-- deployments_pre_m3 -- silently making the rollback table the live parent.

PRAGMA foreign_keys = OFF;
PRAGMA legacy_alter_table = ON;

-- ---------------------------------------------------------------- lifecycle
CREATE TABLE deployment_statuses (
    code               TEXT PRIMARY KEY,
    label              TEXT    NOT NULL,
    sort_order         INTEGER NOT NULL,
    is_terminal        BOOLEAN NOT NULL DEFAULT 0,
    allows_attribution BOOLEAN NOT NULL DEFAULT 0,
    is_operational     BOOLEAN NOT NULL DEFAULT 0,
    description        TEXT
);

INSERT INTO deployment_statuses
    (code, label, sort_order, is_terminal, allows_attribution, is_operational, description)
VALUES
    ('planned',    'Planned',    10, 0, 0, 0, 'Campaign scheduled; no hardware in the field yet.'),
    ('installing', 'Installing', 20, 0, 0, 1, 'Technician on site; verification readings may be taken.'),
    ('active',     'Active',     30, 0, 1, 1, 'Verified and measuring. Readings in range are attributed here.'),
    ('completed',  'Completed',  40, 1, 1, 0, 'Campaign ended. Still attributes its own historical readings.'),
    ('cancelled',  'Cancelled',  50, 1, 0, 0, 'Called off or aborted. Attributes nothing.');

CREATE TABLE deployment_status_transitions (
    from_code TEXT NOT NULL REFERENCES deployment_statuses(code),
    to_code   TEXT NOT NULL REFERENCES deployment_statuses(code),
    note      TEXT,
    PRIMARY KEY (from_code, to_code)
);

INSERT INTO deployment_status_transitions (from_code, to_code, note) VALUES
    ('planned',    'installing', NULL),
    ('planned',    'cancelled',  NULL),
    ('installing', 'active',     'Node must be commissioned.'),
    ('installing', 'cancelled',  NULL),
    ('active',     'completed',  'Warn if the node still has a pending buffer.'),
    ('active',     'cancelled',  NULL);
-- No transition out of completed or cancelled: reopening would retroactively
-- change attribution, so a new deployment is created instead (ADR-0004).

-- --------------------------------------------------------------- deployments
CREATE TABLE deployments_new (
    id                  INTEGER PRIMARY KEY,
    node_id             INTEGER NOT NULL REFERENCES nodes(id),
    building_id         INTEGER NOT NULL REFERENCES buildings(id),
    electrical_panel_id INTEGER NOT NULL REFERENCES electrical_panels(id),
    start_date          TEXT    NOT NULL
        CHECK (start_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    -- NULL means open-ended. The format CHECK keeps lexical order equal to
    -- chronological order, which is what the M8 resolver range-matches on.
    end_date            TEXT    NULL
        CHECK (end_date IS NULL OR end_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    status              TEXT    NOT NULL REFERENCES deployment_statuses(code),
    notes               TEXT,
    CHECK (end_date IS NULL OR end_date >= start_date)
);

INSERT INTO deployments_new
    (id, node_id, building_id, electrical_panel_id, start_date, end_date, status, notes)
SELECT
    id, node_id, building_id, electrical_panel_id,
    start_date,
    NULLIF(TRIM(end_date), ''),
    status,
    notes
FROM deployments;

DROP INDEX IF EXISTS ix_deployments_id;

ALTER TABLE deployments     RENAME TO deployments_pre_m3;
ALTER TABLE deployments_new RENAME TO deployments;

CREATE INDEX ix_deployments_id ON deployments(id);
-- Supports the M8 resolver's (node, timestamp-in-range) lookup.
CREATE INDEX idx_deployments_node_dates ON deployments(node_id, start_date, end_date);

-- ----------------------------------------------------------------------- D1
-- N001 has measured continuously since 2026-06-14, but deployment 4 declared it
-- ended on 06-21, leaving 75% of its readings outside their own campaign window.
-- Open-ended states the truth: the campaign has no scheduled end. The building
-- assignment is intentionally left alone.
UPDATE deployments SET end_date = NULL WHERE id = 4;

PRAGMA legacy_alter_table = OFF;
PRAGMA foreign_keys = ON;
