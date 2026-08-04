-- description: flag development placeholder buildings as non-authoritative (ADR-0006)
-- waivers:
-- deep: false
--
-- Building 8 "Edificio de prueba" was created by the technician deployment form
-- during development and is not authoritative production metadata. Both N001 and
-- N003 are attributed to it.
--
-- This does NOT make the readings themselves non-production: N001's are real
-- measurements of a real load, and what is unreliable is the label on where they
-- were taken. Measurement classification is a separate axis (`context`, M4/M5).
-- Conflating the two would discard 101,682 valid readings to fix a metadata
-- error.
--
-- Matched on `code` rather than `id` so the intent survives any future reseed.

ALTER TABLE buildings ADD COLUMN is_placeholder BOOLEAN NOT NULL DEFAULT 0;

UPDATE buildings
   SET is_placeholder = 1
 WHERE code = 'B-MANUAL-72-edificio-de-prueba';
