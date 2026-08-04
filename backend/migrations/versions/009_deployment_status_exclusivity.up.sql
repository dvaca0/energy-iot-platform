-- description: mark which deployment statuses claim a node exclusively
--
-- Prerequisite for the partial unique index that will guarantee a node can
-- never have two live deployments:
--
--   CREATE UNIQUE INDEX ux_deployment_one_live_per_node
--     ON deployments(node_id) WHERE status IN ('installing', 'active');
--
-- `is_exclusive` is the data behind that index. A SQLite partial index cannot
-- join to a lookup table, so its WHERE clause must name the states literally;
-- this column is what the literals are checked against by INV-17 in M12, so the
-- two can never drift apart silently.
--
-- Why not reuse `is_operational`, which selects the same two states today?
--
--   is_operational  should we expect measurements from this node?
--   is_exclusive    can two deployments in this state coexist for one node?
--
-- They coincide now and are not the same question. A future "reserved" state —
-- node allocated to a campaign but not yet measuring — would be exclusive
-- without being operational. Collapsing them would make that state
-- inexpressible and would silently widen the index's meaning.
--
-- Exclusivity is about physical reality: a node is one object and can be in one
-- place. `planned` claims nothing, so any number of plans may coexist; the
-- terminal states are history and claim nothing either.

ALTER TABLE deployment_statuses
    ADD COLUMN is_exclusive BOOLEAN NOT NULL DEFAULT 0;

UPDATE deployment_statuses
   SET is_exclusive = 1
 WHERE code IN ('installing', 'active');
