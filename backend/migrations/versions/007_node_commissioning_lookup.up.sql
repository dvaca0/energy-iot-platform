-- description: node commissioning becomes a lookup table; separate identity from operational state (ADR-0001, ADR-0002)
-- waivers: allow_node_change
--
-- M2 added commission_state as a CHECK constraint. That works, but introducing a
-- sixth node state would require rewriting the constraint and rebuilding this
-- table — exactly the "another architectural refactor" the deployment lifecycle
-- was designed in M3 to avoid. This gives node state the same treatment:
-- semantics live in columns, so a new state is one INSERT.
--
-- Two questions the platform actually asks are now data, not code:
--
--   may_upload    may a node in this state write readings?    (ADR-0002 step 2)
--   is_monitored  should its silence raise an alarm?          (ADR-0001)
--
-- `is_monitored` is what reconnects alerting to reality. The legacy endpoint
-- iterated active deployments, of which there are none, so it emitted nothing
-- at all. Monitoring now follows physically installed nodes, and can never be
-- silenced by a deployment being marked completed.
--
-- measurement_context is converted from CHECK to a foreign key at the same time,
-- pointing at the measurement_contexts table M4 created. One rebuild, both
-- columns.
--
-- nodes holds 3 rows, so the copy is trivial; the risk is entirely in the
-- rename, and legacy_alter_table=ON is used for the reason proven in M3: without
-- it SQLite rewrites the foreign keys in energy_readings, deployments,
-- smart_plugs and smart_plug_readings to follow the renamed table.

PRAGMA foreign_keys = OFF;
PRAGMA legacy_alter_table = ON;

BEGIN IMMEDIATE;

CREATE TABLE node_commission_states (
    code         TEXT PRIMARY KEY,
    label        TEXT    NOT NULL,
    sort_order   INTEGER NOT NULL,
    may_upload   BOOLEAN NOT NULL DEFAULT 0,
    is_monitored BOOLEAN NOT NULL DEFAULT 0,
    is_terminal  BOOLEAN NOT NULL DEFAULT 0,
    description  TEXT
);

INSERT INTO node_commission_states
    (code, label, sort_order, may_upload, is_monitored, is_terminal, description)
VALUES
    ('registered',     'Registered',     10, 0, 0, 0,
     'Known to the platform but not yet verified in the field. Uploads refused; silence is expected, so no alarm.'),
    ('commissioned',   'Commissioned',   20, 1, 1, 0,
     'Verified and in service. The only state that may upload. Silence is an alarm.'),
    ('suspended',      'Suspended',      30, 0, 1, 0,
     'Uploads deliberately revoked (fault, security, theft). Still physically installed, so still monitored.'),
    ('decommissioned', 'Decommissioned', 40, 0, 0, 1,
     'Retired from the fleet. Historical readings are retained; silence is expected.');

-- ---------------------------------------------------------------- rebuild
CREATE TABLE nodes_new (
    id                  INTEGER PRIMARY KEY,
    code                TEXT     NOT NULL,
    name                TEXT     NOT NULL,
    ip_address          TEXT,

    -- Legacy connectivity column. Retired in M9; kept here so M7 changes
    -- structure only, never meaning.
    status              TEXT     NOT NULL,

    last_sync           DATETIME,
    buffer_pending      INTEGER  NOT NULL,
    samples             INTEGER  NOT NULL,

    hardware_kind       TEXT,
    commission_state    TEXT     NOT NULL DEFAULT 'registered'
                        REFERENCES node_commission_states(code),
    measurement_context TEXT     NOT NULL DEFAULT 'production'
                        REFERENCES measurement_contexts(code),
    auth_token_hash     TEXT,
    commissioned_at     DATETIME
);

INSERT INTO nodes_new
    (id, code, name, ip_address, status, last_sync, buffer_pending, samples,
     hardware_kind, commission_state, measurement_context, auth_token_hash, commissioned_at)
SELECT
    id, code, name, ip_address, status, last_sync, buffer_pending, samples,
    hardware_kind, commission_state, measurement_context, auth_token_hash, commissioned_at
FROM nodes
ORDER BY id;

DROP INDEX IF EXISTS ix_nodes_code;
DROP INDEX IF EXISTS ix_nodes_id;
DROP INDEX IF EXISTS idx_nodes_last_sync;

ALTER TABLE nodes     RENAME TO nodes_pre_m7;
ALTER TABLE nodes_new RENAME TO nodes;

CREATE UNIQUE INDEX ix_nodes_code ON nodes (code);
CREATE INDEX ix_nodes_id ON nodes (id);
CREATE INDEX idx_nodes_last_sync ON nodes (last_sync);

COMMIT;

PRAGMA legacy_alter_table = OFF;
PRAGMA foreign_keys = ON;
