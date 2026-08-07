-- description: implement ADR-0002 node identity — credential issuance, producer provenance on heartbeats, and an identity-violation record
-- waivers:
--
-- WHY
--
-- `POST /api/monitoring/heartbeat` and the reading ingest paths accept any
-- payload that names a node code. No credential is checked anywhere. The
-- `nodes.auth_token_hash` column has existed since M2 (ADR-0002) and is read by
-- nothing.
--
-- On 2026-08-06 this was demonstrated, not theorised: an old collector left in
-- `/opt/energy-node/backups/pre-m14-hardening-20260803_082109/app/node_agent.py`
-- published 60-second heartbeats as N001 for eight minutes. It reached the same
-- endpoint as the real collector, was stored identically, and contradicted it
-- on two fields. Nothing in the platform could tell them apart: same node code,
-- same NAT source address, same hostname. Only `software_version` differed, and
-- that is self-declared by the producer.
--
-- NAT source address is not identity. Three nodes share two public addresses
-- here, and those addresses change.
--
-- WHAT THIS ADDS
--
-- 1. `nodes.auth_token_issued_at` — when the credential was issued, so rotation
--    is auditable. The hash column already exists; only its provenance was
--    missing.
--
-- 2. Producer provenance on every heartbeat. `auth_subject` records which
--    credential the request authenticated as (NULL when unauthenticated), and
--    `auth_status` records the outcome. Without these a collision is invisible
--    after the fact — which is exactly the position the 2026-08-06 audit was in.
--
-- 3. `node_identity_violations` — an append-only record of rejected or
--    contradictory identity claims. Alerts are derived state and are pruned;
--    a security record must not be.
--
-- ADD COLUMN and CREATE TABLE only. No table is rebuilt, no foreign key is
-- rewritten, no row is modified. No reading is touched, so no waiver applies.

BEGIN IMMEDIATE;

-- --------------------------------------------------------------- nodes
ALTER TABLE nodes ADD COLUMN auth_token_issued_at DATETIME;

-- ------------------------------------------- heartbeat provenance
-- NULL auth_subject on historical rows is truthful: those heartbeats were
-- genuinely unauthenticated, because no credential existed to present.
ALTER TABLE monitor_node_heartbeats ADD COLUMN auth_subject TEXT;
ALTER TABLE monitor_node_heartbeats ADD COLUMN auth_status  TEXT;

CREATE INDEX IF NOT EXISTS idx_hb_auth
    ON monitor_node_heartbeats (node_code, auth_status, received_at);

-- ------------------------------------------- identity violations
CREATE TABLE node_identity_violations (
    id            INTEGER PRIMARY KEY,
    occurred_at   DATETIME NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ','now')),

    -- What the caller claimed to be.
    claimed_node  TEXT,
    -- What the credential actually maps to. NULL when no valid credential.
    auth_subject  TEXT,

    -- unauthenticated | unknown_credential | subject_mismatch |
    -- not_authorized  | contradictory_producer
    violation     TEXT NOT NULL,

    source_ip     TEXT,
    user_agent    TEXT,
    producer      TEXT,      -- self-declared software/agent version
    endpoint      TEXT,
    detail        TEXT
);

CREATE INDEX idx_identity_violations_time  ON node_identity_violations (occurred_at);
CREATE INDEX idx_identity_violations_node  ON node_identity_violations (claimed_node, occurred_at);

COMMIT;
