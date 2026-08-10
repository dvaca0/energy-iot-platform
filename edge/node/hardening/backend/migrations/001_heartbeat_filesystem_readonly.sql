-- Canonical heartbeat migration.
-- DEPLOYMENT BLOCKED: not applied. Review against your real schema first;
-- table/column names are inferred from the API contract, not from source.
--
-- WHY: filesystem_readonly was accepted by the API but never stored, so
-- node.filesystem_readonly could only ever read NULL — and the rule mapped
-- NULL onto "read-only", firing CRITICAL forever on a healthy node.

ALTER TABLE monitoring_heartbeats ADD COLUMN filesystem_readonly BOOLEAN;
ALTER TABLE monitoring_heartbeats ADD COLUMN throttle_flags TEXT;
ALTER TABLE monitoring_heartbeats ADD COLUMN source TEXT DEFAULT 'monitoring';
ALTER TABLE monitoring_heartbeats ADD COLUMN clock_drift_seconds REAL;

-- Distinguish "never seen" from "seen, then lost" — different faults.
ALTER TABLE nodes ADD COLUMN first_heartbeat_at TIMESTAMP;
ALTER TABLE nodes ADD COLUMN registered_at TIMESTAMP;

CREATE INDEX IF NOT EXISTS idx_mhb_node_received
    ON monitoring_heartbeats (node_id, received_at DESC);

-- Existing rows predate the column; leave them NULL. The fixed rule treats
-- NULL as UNKNOWN and will not assert a fault, which is the correct
-- behaviour for data we genuinely do not have.
