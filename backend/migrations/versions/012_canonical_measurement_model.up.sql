-- description: canonical measurement contract — interval energy, provenance, and historical eras (ADR-0007)
--
-- `energy_kwh` has carried two meanings: a cumulative meter register until
-- 2026-07-03, and per-interval energy since 2026-07-25. Every consumer computes
-- current-minus-previous, which is right for the first and meaningless for the
-- second, so KPIs read ~400x low.
--
-- This establishes one contract that every present and future collector maps
-- onto, and records which meaning each historical era used WITHOUT touching a
-- single reading.
--
-- ADD COLUMN in SQLite is metadata-only: existing rows return NULL without being
-- rewritten. No historical value, attribution or timestamp changes, which
-- INV-02, INV-15 and INV-16 verify after this runs.

BEGIN IMMEDIATE;

-- ------------------------------------------------ the semantics vocabulary
-- Semantics as data, as for deployment_statuses and measurement_contexts: a
-- future encoding is one INSERT, not a code change.
CREATE TABLE energy_semantics (
    code            TEXT PRIMARY KEY,
    label           TEXT    NOT NULL,
    reads_legacy    BOOLEAN NOT NULL,  -- interpret energy_readings.energy_kwh?
    requires_delta  BOOLEAN NOT NULL,  -- must consecutive values be differenced?
    description     TEXT
);

INSERT INTO energy_semantics (code, label, reads_legacy, requires_delta, description) VALUES
    ('cumulative_counter', 'Cumulative counter', 1, 1,
     'energy_kwh is a lifetime register. Interval energy is the guarded difference between consecutive readings.'),
    ('interval_energy',    'Interval energy',    1, 0,
     'energy_kwh already holds the energy for this sample interval. Summed directly; never differenced.'),
    ('canonical',          'Canonical',          0, 0,
     'The collector populates interval_energy_kwh directly. energy_kwh is ignored.'),
    ('absent',             'No energy',          0, 0,
     'The node reports no energy at all — the batch endpoint stores NULL. Contributes nothing.');

-- --------------------------------------------------- canonical columns
-- Nullable and additive. Historical rows keep NULL, which is correct: they
-- predate the contract and are interpreted through measurement_eras below.
ALTER TABLE energy_readings ADD COLUMN interval_energy_kwh REAL;
ALTER TABLE energy_readings ADD COLUMN interval_seconds    REAL;
ALTER TABLE energy_readings ADD COLUMN meter_energy_kwh    REAL;
ALTER TABLE energy_readings ADD COLUMN energy_source       TEXT;

-- --------------------------------------------------------- the eras
-- How to read legacy energy_kwh, per node, per time range. Three rows describe
-- the platform's entire history. This is the ONLY mechanism that distinguishes
-- the eras, and it touches no reading.
CREATE TABLE measurement_eras (
    id              INTEGER PRIMARY KEY,
    node_id         INTEGER NOT NULL REFERENCES nodes(id),
    starts_at       DATETIME,          -- NULL = from the beginning of time
    ends_at         DATETIME,          -- NULL = still open
    energy_semantics TEXT   NOT NULL REFERENCES energy_semantics(code),
    nominal_interval_seconds REAL,
    discovered_by   TEXT,
    notes           TEXT,
    CHECK (ends_at IS NULL OR starts_at IS NULL OR ends_at >= starts_at)
);

CREATE INDEX idx_measurement_eras_node ON measurement_eras(node_id, starts_at);

-- N001 — the counter era. Bounded at its own last reading in that régime.
INSERT INTO measurement_eras
    (node_id, starts_at, ends_at, energy_semantics, nominal_interval_seconds, discovered_by, notes)
SELECT id, NULL, '2026-07-03 15:32:39.518617', 'cumulative_counter', 15,
       'investigation 2026-07-31',
       'Monotonic lifetime register 17283.8189 -> 26259.2423 kWh over 19 days; 0.0% negative deltas. Interval energy is the guarded difference.'
  FROM nodes WHERE code = 'N001';

-- N001 — the interval era. Opens at its first reading after a 21-day silence.
INSERT INTO measurement_eras
    (node_id, starts_at, ends_at, energy_semantics, nominal_interval_seconds, discovered_by, notes)
SELECT id, '2026-07-25 00:01:01.228000', NULL, 'interval_energy', 15,
       'investigation 2026-07-31',
       'energy_kwh = power_kw * 15.000/3600 to zero relative error; 51.6% of deltas negative. Collector derives energy from power; it does not read the meter register. Close this era when the collector emits canonical fields.'
  FROM nodes WHERE code = 'N001';

-- N003 — never reports energy: it posts to /api/v1/measurements/batch, which
-- stores energy_kwh = NULL by construction (edge.py).
INSERT INTO measurement_eras
    (node_id, starts_at, ends_at, energy_semantics, nominal_interval_seconds, discovered_by, notes)
SELECT id, NULL, NULL, 'absent', NULL, 'investigation 2026-07-31',
       'ADS1256 node on the batch endpoint; energy_kwh is NULL on all rows.'
  FROM nodes WHERE code = 'N003';

-- N002 — has produced no readings, but declaring the era means a future first
-- reading is interpreted deliberately rather than by a default.
INSERT INTO measurement_eras
    (node_id, starts_at, ends_at, energy_semantics, nominal_interval_seconds, discovered_by, notes)
SELECT id, NULL, NULL, 'absent', NULL, 'investigation 2026-07-31',
       'No readings yet. Replace with the correct semantics when this node is commissioned.'
  FROM nodes WHERE code = 'N002';

COMMIT;
