-- description: rollback 015 — drop the per-phase and register columns
-- waivers:
--
-- Drops only additions. Safe for exactly as long as no collector has been
-- switched over to populate them: at that point the columns hold measurements
-- that exist nowhere else, and rolling back would destroy them. The sequencing
-- rule in docs/Plan-Shelly-Phase-Fields.md exists for this reason — schema
-- lands and is verified BEFORE the collector changes.
--
-- No reading is touched on the way down either. DROP COLUMN in SQLite 3.45
-- rewrites the table but preserves every remaining value, and the invariant
-- gate verifies that afterwards.
--
-- meter_energy_kwh is NOT dropped: it predates this migration (012) and is not
-- ours to remove.

BEGIN IMMEDIATE;

ALTER TABLE energy_readings DROP COLUMN phase_a_power_kw;
ALTER TABLE energy_readings DROP COLUMN phase_b_power_kw;
ALTER TABLE energy_readings DROP COLUMN phase_c_power_kw;

ALTER TABLE energy_readings DROP COLUMN phase_a_apparent_kva;
ALTER TABLE energy_readings DROP COLUMN phase_b_apparent_kva;
ALTER TABLE energy_readings DROP COLUMN phase_c_apparent_kva;

ALTER TABLE energy_readings DROP COLUMN phase_a_power_factor;
ALTER TABLE energy_readings DROP COLUMN phase_b_power_factor;
ALTER TABLE energy_readings DROP COLUMN phase_c_power_factor;

ALTER TABLE energy_readings DROP COLUMN phase_a_frequency_hz;
ALTER TABLE energy_readings DROP COLUMN phase_b_frequency_hz;
ALTER TABLE energy_readings DROP COLUMN phase_c_frequency_hz;

ALTER TABLE energy_readings DROP COLUMN apparent_kva;
ALTER TABLE energy_readings DROP COLUMN neutral_current;

ALTER TABLE energy_readings DROP COLUMN phase_a_energy_imported_kwh;
ALTER TABLE energy_readings DROP COLUMN phase_b_energy_imported_kwh;
ALTER TABLE energy_readings DROP COLUMN phase_c_energy_imported_kwh;

ALTER TABLE energy_readings DROP COLUMN phase_a_energy_returned_kwh;
ALTER TABLE energy_readings DROP COLUMN phase_b_energy_returned_kwh;
ALTER TABLE energy_readings DROP COLUMN phase_c_energy_returned_kwh;

ALTER TABLE energy_readings DROP COLUMN meter_energy_returned_kwh;

ALTER TABLE monitor_node_heartbeats DROP COLUMN meter_temperature_c;

COMMIT;
