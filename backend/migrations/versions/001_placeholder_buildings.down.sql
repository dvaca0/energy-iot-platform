-- Rollback for 001. SQLite 3.45 supports DROP COLUMN (verified on this host);
-- the column carries no data that exists anywhere else, so dropping it is
-- lossless.

ALTER TABLE buildings DROP COLUMN is_placeholder;
