-- Rollback for 013.
-- waivers:
--
-- Everything 013 added was additive. Dropping the columns is safe on SQLite
-- 3.45 (DROP COLUMN since 3.35) and rewrites no foreign key.
--
-- Issued credentials are NOT revoked by this rollback: `auth_token_hash`
-- predates 013 and is left intact, so rolling back the enforcement machinery
-- does not silently invalidate every node's credential. Only the issuance
-- timestamp is lost.
--
-- node_identity_violations is a security record. Dropping it discards evidence,
-- which is acceptable only because rolling back this migration removes the
-- mechanism that produces it.

BEGIN IMMEDIATE;

DROP INDEX IF EXISTS idx_identity_violations_node;
DROP INDEX IF EXISTS idx_identity_violations_time;
DROP TABLE IF EXISTS node_identity_violations;

DROP INDEX IF EXISTS idx_hb_auth;
ALTER TABLE monitor_node_heartbeats DROP COLUMN auth_status;
ALTER TABLE monitor_node_heartbeats DROP COLUMN auth_subject;

ALTER TABLE nodes DROP COLUMN auth_token_issued_at;

COMMIT;
