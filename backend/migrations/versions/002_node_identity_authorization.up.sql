-- description: give Node ownership of identity, commissioning and authorization (ADR-0001, ADR-0002)
--
-- Purely additive. Nothing reads these columns until M7/M8, so this step is a
-- runtime no-op: every node is backfilled to the state that reproduces today's
-- behaviour exactly.
--
-- CHECK constraints are included on the two enum columns. Verified on SQLite
-- 3.45 that ALTER TABLE ADD COLUMN accepts a CHECK, that it is enforced for both
-- INSERT and UPDATE, and that DROP COLUMN removes the constraint cleanly with
-- the column — so the rollback below stays a one-liner.

-- Identity: what kind of collector this is.
ALTER TABLE nodes ADD COLUMN hardware_kind TEXT;

-- Commissioning: the only thing that decides whether an upload is accepted.
-- Deployment lifecycle no longer plays any part in that decision.
ALTER TABLE nodes ADD COLUMN commission_state TEXT NOT NULL DEFAULT 'registered'
    CHECK (commission_state IN ('registered', 'commissioned', 'suspended', 'decommissioned'));

-- Authoritative declared context for everything this node produces. A payload
-- may narrow it but never widen it to 'production' (ADR-0003).
ALTER TABLE nodes ADD COLUMN measurement_context TEXT NOT NULL DEFAULT 'production'
    CHECK (measurement_context IN ('production', 'bench', 'laboratory',
                                   'calibration', 'commissioning', 'simulation'));

-- Authentication material. Left NULL: tokens are not issued yet, and the
-- ingest path treats the token as optional until every node carries one
-- (ADR-0002, phased enforcement).
ALTER TABLE nodes ADD COLUMN auth_token_hash TEXT;
ALTER TABLE nodes ADD COLUMN commissioned_at DATETIME;

-- Backfill. All three existing nodes are genuinely commissioned and in the
-- field, so 'commissioned' preserves current behaviour. Anything registered
-- later starts at 'registered' and must be commissioned deliberately.
UPDATE nodes
   SET commission_state = 'commissioned',
       measurement_context = 'production',
       commissioned_at = COALESCE(commissioned_at, datetime('now'))
 WHERE code IN ('N001', 'N002', 'N003');

-- Hardware. N002 and N003 are confirmed from their deployed collector units
-- (energy-node-collector / udec-edge respectively).
--
-- N001 is inferred, not confirmed: it reports a populated energy_kwh on a
-- 15-second cadence, whereas the ADS1256 node reports energy_kwh NULL on all
-- 123,617 of its rows. That is a Shelly-style collector signature. Recorded as
-- such because the column has to say something; a single UPDATE corrects it.
UPDATE nodes SET hardware_kind = 'shelly'  WHERE code IN ('N001', 'N002');
UPDATE nodes SET hardware_kind = 'ads1256' WHERE code = 'N003';
