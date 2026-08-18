-- description: per-phase power, apparent power, power factor, frequency, neutral current and meter energy registers from the Shelly Pro 3EM
-- waivers:
--
-- WHY
--
-- The meter has always measured these. A read-only capture from N001's
-- production device on 2026-08-18 (SPEM-003CEBEU, Pro3EM, firmware 1.4.2,
-- profile triphase, 120 A CT) confirms every field below is present in the same
-- `EM.GetStatus?id=0` response the collector already parses:
--
--   a_act_power  4632.3 W    a_aprt_power  4679.9 VA   a_pf 0.99   a_freq 60.0
--   b_act_power  4392.3 W    b_aprt_power  4437.9 VA   b_pf 0.99   b_freq 60.0
--   c_act_power  3628.2 W    c_aprt_power  4194.1 VA   c_pf 0.87   c_freq 60.0
--   total_aprt_power 13311.875 VA          n_current   null
--
-- and `EMData.GetStatus?id=0` carries the per-phase and total energy registers.
--
-- The platform stored none of it. `/api/v1/measurements/batch` has *accepted*
-- twelve of these fields since it was written and dropped them on the floor,
-- because EnergyReading had nowhere to put them. This gives them somewhere.
--
-- Proof the meter's own apparent power is already in the collector's hands and
-- being thrown away: `energy_readings.power_factor` on N001 carries 13-16
-- decimal places (e.g. 0.9500164388225734). The meter reports a_pf/b_pf/c_pf at
-- two decimals, so no mean of them can produce that. It is a division —
-- total_act_power / total_aprt_power — which means total_aprt_power is read,
-- used once, and discarded.
--
-- WHAT THIS DOES NOT DO
--
-- ADD COLUMN in SQLite is metadata-only: existing rows return NULL without
-- being rewritten. All 315,000 historical readings keep NULL on every new
-- column, which is the truthful value — those quantities were never stored for
-- those instants. Nothing is backfilled, derived or reconstructed. INV-02,
-- INV-15 and INV-16 verify that no historical value, attribution or timestamp
-- changed.
--
-- It also does NOT touch energy semantics. `measurement_eras` row 2 records
-- that N001's collector derives energy from power (energy_kwh = power_kw *
-- 15/3600 to zero relative error) and says to close that era only when the
-- collector emits canonical fields. The registers added here are stored for
-- reconciliation and are never differenced by an analytic —
-- app/services/energy_aggregate.py reads energy_kwh and interval_energy_kwh
-- only, and is unchanged. Switching N001 to counter_delta is a separate
-- decision that requires its own era row; do not conflate the two.
--
-- UNITS
--
-- The meter speaks W, VA and Wh. The platform speaks kW, kVA and kWh, matching
-- the existing `power_kw`. Every column below names its unit so a reader can
-- never wonder, and the conversion happens exactly once, at the collector
-- boundary, documented in backend/docs/collector-contract.md. `neutral_current`
-- carries no suffix on purpose: amperes pass through unconverted, and it reads
-- as a sibling of `current` and `phase_a_current` rather than as "phase A".

BEGIN IMMEDIATE;

-- ---------------------------------------------- per-phase electrical detail
-- From EM.GetStatus. a_act_power / a_aprt_power are watts and volt-amperes on
-- the wire; stored in kW and kVA.
ALTER TABLE energy_readings ADD COLUMN phase_a_power_kw          REAL;
ALTER TABLE energy_readings ADD COLUMN phase_b_power_kw          REAL;
ALTER TABLE energy_readings ADD COLUMN phase_c_power_kw          REAL;

ALTER TABLE energy_readings ADD COLUMN phase_a_apparent_kva      REAL;
ALTER TABLE energy_readings ADD COLUMN phase_b_apparent_kva      REAL;
ALTER TABLE energy_readings ADD COLUMN phase_c_apparent_kva      REAL;

-- Dimensionless. The meter's own per-phase figure, not P/S recomputed here:
-- the capture shows c_pf 0.87 against a_pf/b_pf 0.99, which the single
-- aggregate power_factor cannot express.
ALTER TABLE energy_readings ADD COLUMN phase_a_power_factor      REAL;
ALTER TABLE energy_readings ADD COLUMN phase_b_power_factor      REAL;
ALTER TABLE energy_readings ADD COLUMN phase_c_power_factor      REAL;

ALTER TABLE energy_readings ADD COLUMN phase_a_frequency_hz      REAL;
ALTER TABLE energy_readings ADD COLUMN phase_b_frequency_hz      REAL;
ALTER TABLE energy_readings ADD COLUMN phase_c_frequency_hz      REAL;

-- ------------------------------------------------------------------ totals
-- total_aprt_power, VA on the wire. The counterpart of the existing power_kw.
ALTER TABLE energy_readings ADD COLUMN apparent_kva              REAL;

-- n_current. NULL on N001's installation today — there is no neutral CT — and
-- that NULL must survive to the screen as "no disponible". It is never 0.
ALTER TABLE energy_readings ADD COLUMN neutral_current           REAL;

-- ------------------------------------------------- meter energy registers
-- From EMData.GetStatus, Wh on the wire, stored kWh. Monotonic lifetime
-- counters for reconciliation against a utility bill. NO ANALYTIC DIFFERENCES
-- THESE — that is the rule meter_energy_kwh was created under (ADR-0007) and it
-- extends unchanged to the per-phase and returned-energy siblings here.
--
-- The existing meter_energy_kwh column takes EMData `total_act`; it was added
-- for exactly this and has been NULL on all 187,598 N001 rows because the
-- collector never polled EMData. No second column is created for it.
ALTER TABLE energy_readings ADD COLUMN phase_a_energy_imported_kwh REAL;
ALTER TABLE energy_readings ADD COLUMN phase_b_energy_imported_kwh REAL;
ALTER TABLE energy_readings ADD COLUMN phase_c_energy_imported_kwh REAL;

ALTER TABLE energy_readings ADD COLUMN phase_a_energy_returned_kwh REAL;
ALTER TABLE energy_readings ADD COLUMN phase_b_energy_returned_kwh REAL;
ALTER TABLE energy_readings ADD COLUMN phase_c_energy_returned_kwh REAL;

-- EMData total_act_ret. The import counterpart is meter_energy_kwh.
ALTER TABLE energy_readings ADD COLUMN meter_energy_returned_kwh   REAL;

-- ------------------------------------------------------- meter health
-- Shelly.GetStatus "temperature:0".tC = 43.6 in the capture — the METER's
-- internal temperature, not the Raspberry Pi's (that is
-- monitor_node_heartbeats.cpu_temperature_c, 37.5 on the same node at the same
-- time; two different devices, two different numbers).
--
-- It is device health, not an electrical measurement, so it does NOT go on
-- energy_readings. Putting it there would make every analytic that iterates
-- reading columns have to know which ones are not electrical, and would write
-- the same slow-moving value 5,760 times a day into the measurement table.
--
-- The correct existing model is the node telemetry the technician already
-- reads: monitor_node_heartbeats, which is where cpu_temperature_c,
-- collector_status and shelly_reachable live. No new architecture.
ALTER TABLE monitor_node_heartbeats ADD COLUMN meter_temperature_c REAL;

COMMIT;
