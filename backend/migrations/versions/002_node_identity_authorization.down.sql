-- Rollback for 002. None of these columns is the sole home of any data: the
-- pre-migration behaviour derived everything from Node.last_sync and
-- Deployment.status, both untouched here. Dropping is therefore lossless.

ALTER TABLE nodes DROP COLUMN commissioned_at;
ALTER TABLE nodes DROP COLUMN auth_token_hash;
ALTER TABLE nodes DROP COLUMN measurement_context;
ALTER TABLE nodes DROP COLUMN commission_state;
ALTER TABLE nodes DROP COLUMN hardware_kind;
