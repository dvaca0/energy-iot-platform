-- description: physical equipment ratings on nodes and deployments; legal node commission transitions and their audit trail
-- waivers:
--
-- Two additions, both driven by the alerting review of 2026-07-29.
--
-- 1. PHYSICAL RATINGS
--
-- Alert thresholds were being derived from a learned percentile of whatever the
-- node happened to have measured. That is a reasonable fallback and a poor
-- primary source: it describes what a panel *has done*, not what its wiring can
-- *survive*. A learned baseline can also drift upward indefinitely — if a panel
-- is genuinely overloaded for a week, the baseline learns the overload and stops
-- reporting it.
--
-- The authoritative limit is physical: the CT's measurement ceiling, the main
-- breaker, the conductor. None of it existed anywhere in the schema, so there
-- was nothing for a threshold to be derived from.
--
-- Ratings live at two levels because they belong to two different things:
--
--   nodes        the measurement hardware that travels with the Pi
--                (the clamp, and any per-node limits an operator sets)
--   deployments  the installation it is attached to for one campaign
--                (the panel, its breaker, its service voltage and phase count)
--
-- Deployment values win, because the same node measures a 100 A panel one month
-- and a 400 A panel the next. Every column is NULLABLE: nothing is known today,
-- and a guessed rating would be worse than an absent one. Resolution falls
-- through to the next source when a value is NULL.
--
-- 2. NODE COMMISSION TRANSITIONS
--
-- M7 gave node state a lookup table but no transition machinery, so
-- `commission_state` had no legal-move definition, no audit trail, and no write
-- path anywhere in the application. The only way to change it was raw SQL —
-- exactly the bypass ADR-0001 set out to remove for deployments.
--
-- This mirrors `deployment_status_transitions` (M3) so both lifecycles work the
-- same way, and adds the audit table deployments never needed because their
-- history is reconstructable from readings. A node's state history is not
-- reconstructable from anything, so it is recorded explicitly.
--
-- ADD COLUMN only: no table is rebuilt, no index is dropped, no foreign key is
-- rewritten. The two new tables are additive. Nothing existing is touched, so
-- no invariant waiver is required and reading data is untouchable by
-- construction.

BEGIN IMMEDIATE;

-- ---------------------------------------------------------------- nodes
-- Ratings belonging to the measurement hardware itself.

ALTER TABLE nodes ADD COLUMN ct_max_current_a    REAL;
ALTER TABLE nodes ADD COLUMN nominal_voltage_v   REAL;
ALTER TABLE nodes ADD COLUMN phase_count         INTEGER;
ALTER TABLE nodes ADD COLUMN warning_current_a   REAL;
ALTER TABLE nodes ADD COLUMN critical_current_a  REAL;
ALTER TABLE nodes ADD COLUMN emergency_current_a REAL;
ALTER TABLE nodes ADD COLUMN sustained_seconds   INTEGER;

-- ---------------------------------------------------------- deployments
-- Ratings belonging to the installation. These override the node's own values
-- for the duration of the campaign.

ALTER TABLE deployments ADD COLUMN panel_main_breaker_a REAL;
ALTER TABLE deployments ADD COLUMN ct_max_current_a     REAL;
ALTER TABLE deployments ADD COLUMN nominal_voltage_v    REAL;
ALTER TABLE deployments ADD COLUMN phase_count          INTEGER;
ALTER TABLE deployments ADD COLUMN warning_current_a    REAL;
ALTER TABLE deployments ADD COLUMN critical_current_a   REAL;
ALTER TABLE deployments ADD COLUMN emergency_current_a  REAL;
ALTER TABLE deployments ADD COLUMN sustained_seconds    INTEGER;

-- ------------------------------------------- node commission transitions
-- Which moves are legal. Same shape as deployment_status_transitions, so the
-- same reasoning applies: adding a state later is INSERTs, not a code change.

CREATE TABLE node_commission_transitions (
    from_code TEXT NOT NULL REFERENCES node_commission_states(code),
    to_code   TEXT NOT NULL REFERENCES node_commission_states(code),
    PRIMARY KEY (from_code, to_code)
);

INSERT INTO node_commission_transitions (from_code, to_code) VALUES
    -- Commissioning a node that has been verified in the field.
    ('registered',     'commissioned'),
    -- Straight to retirement without ever entering service.
    ('registered',     'decommissioned'),
    -- Revoking uploads on a node that stays physically installed.
    ('commissioned',   'suspended'),
    -- Returning a node to the pool: still owned, no longer in service, will be
    -- deployed again. This is the reversible "stored on a shelf" move, and the
    -- reason `registered` is not terminal.
    ('commissioned',   'registered'),
    ('commissioned',   'decommissioned'),
    -- A suspension is always reversible in both directions.
    ('suspended',      'commissioned'),
    ('suspended',      'registered'),
    ('suspended',      'decommissioned');
    -- Deliberately absent: anything FROM 'decommissioned'. It is the only
    -- terminal state (is_terminal = 1) and the model must keep it that way.

-- ------------------------------------------------ node commission events
-- The audit trail. A node's lifecycle history cannot be reconstructed from any
-- other table, so every change records who moved it, when, and why.

CREATE TABLE node_commission_events (
    id          INTEGER PRIMARY KEY,
    node_id     INTEGER  NOT NULL REFERENCES nodes(id),
    node_code   TEXT     NOT NULL,
    from_state  TEXT,
    to_state    TEXT     NOT NULL REFERENCES node_commission_states(code),
    reason      TEXT,
    actor       TEXT,
    occurred_at DATETIME NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX idx_node_commission_events_node ON node_commission_events (node_id, occurred_at);

COMMIT;
