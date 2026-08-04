-- Rollback for 009.
--
-- Additive column carrying no data that exists nowhere else; the exclusive set
-- is re-derivable from the lifecycle model. Dropping is lossless.
--
-- Safe only while no index or trigger depends on it — that dependency arrives
-- in M12, whose own rollback removes it first.

ALTER TABLE deployment_statuses DROP COLUMN is_exclusive;
