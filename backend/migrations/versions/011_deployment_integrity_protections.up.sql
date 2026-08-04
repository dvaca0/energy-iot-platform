-- description: database-level deployment integrity — exclusivity index, coherence and immutability triggers
--
-- Makes the class of failure that produced deployment 4 structurally
-- impossible, not merely rejected by the API. Everything here enforces below
-- the application, so raw SQL and future migrations are bound by it too.
--
-- Three protections, each closing a different hole. The audit of 2026-07-30
-- established that none of them subsumes another:
--
--   1. ux_deployment_one_live_per_node
--      At most one deployment per node in an exclusive state. Atomic and
--      race-proof: uniqueness is enforced at the storage layer, so two
--      concurrent activations cannot both win.
--
--      It does NOT catch deployment 4's original defect. Deployment 4 was
--      `completed` — not live — so it was never in the index's scope. Its
--      overlap with deployment 6 was between a terminal unbounded window and a
--      live one.
--
--   2. Coherence triggers (R1, R2)
--      R2: a status that attributes must have been activated.
--      R1: a terminal status that attributes must be bounded.
--
--      R1 is what makes deployment 4's state unreachable. A completed campaign
--      can no longer claim every future instant.
--
--   3. Immutability trigger
--      The fields that define attribution stop moving once attribution can
--      begin. Editing them afterwards would silently diverge stored attribution
--      from what the resolver would now produce.
--
-- Together: a window can only open when no other is open (1), must close when
-- its campaign ends (2), and cannot be moved afterwards (3). Overlap has no
-- remaining route in.
--
-- The index names its states literally because a SQLite partial index cannot
-- join to a lookup table. INV-17 checks those literals against
-- deployment_statuses.is_exclusive, so the two cannot drift apart unnoticed.

BEGIN IMMEDIATE;

-- ------------------------------------------------------- 1. exclusivity
CREATE UNIQUE INDEX ux_deployment_one_live_per_node
    ON deployments(node_id)
    WHERE status IN ('installing', 'active');

-- --------------------------------------------------------- 2. coherence
CREATE TRIGGER trg_deployment_window_coherent_insert
BEFORE INSERT ON deployments
BEGIN
    SELECT RAISE(ABORT, 'R2: a deployment whose status attributes must have activated_at set')
     WHERE (SELECT allows_attribution FROM deployment_statuses WHERE code = NEW.status) = 1
       AND NEW.activated_at IS NULL;

    SELECT RAISE(ABORT, 'R1: a terminal attributing deployment must have closed_at set')
     WHERE (SELECT allows_attribution FROM deployment_statuses WHERE code = NEW.status) = 1
       AND (SELECT is_terminal FROM deployment_statuses WHERE code = NEW.status) = 1
       AND NEW.closed_at IS NULL;

    SELECT RAISE(ABORT, 'a deployment cannot close before it was activated')
     WHERE NEW.activated_at IS NOT NULL AND NEW.closed_at IS NOT NULL
       AND NEW.closed_at < NEW.activated_at;

    -- No overlap with any existing attribution window for the same node.
    -- The row does not exist yet, so no self-exclusion is needed.
    SELECT RAISE(ABORT, 'attribution window overlaps an existing deployment for this node')
     WHERE (SELECT allows_attribution FROM deployment_statuses WHERE code = NEW.status) = 1
       AND NEW.activated_at IS NOT NULL
       AND EXISTS (
           SELECT 1 FROM deployments d
             JOIN deployment_statuses s ON s.code = d.status
            WHERE d.node_id = NEW.node_id
              AND s.allows_attribution = 1
              AND d.activated_at IS NOT NULL
              AND d.activated_at <= COALESCE(NEW.closed_at, '9999-12-31 23:59:59')
              AND NEW.activated_at <= COALESCE(d.closed_at, '9999-12-31 23:59:59')
       );
END;

CREATE TRIGGER trg_deployment_window_coherent_update
BEFORE UPDATE ON deployments
BEGIN
    SELECT RAISE(ABORT, 'R2: a deployment whose status attributes must have activated_at set')
     WHERE (SELECT allows_attribution FROM deployment_statuses WHERE code = NEW.status) = 1
       AND NEW.activated_at IS NULL;

    SELECT RAISE(ABORT, 'R1: a terminal attributing deployment must have closed_at set')
     WHERE (SELECT allows_attribution FROM deployment_statuses WHERE code = NEW.status) = 1
       AND (SELECT is_terminal FROM deployment_statuses WHERE code = NEW.status) = 1
       AND NEW.closed_at IS NULL;

    SELECT RAISE(ABORT, 'a deployment cannot close before it was activated')
     WHERE NEW.activated_at IS NOT NULL AND NEW.closed_at IS NOT NULL
       AND NEW.closed_at < NEW.activated_at;

    SELECT RAISE(ABORT, 'attribution window overlaps an existing deployment for this node')
     WHERE (SELECT allows_attribution FROM deployment_statuses WHERE code = NEW.status) = 1
       AND NEW.activated_at IS NOT NULL
       AND EXISTS (
           SELECT 1 FROM deployments d
             JOIN deployment_statuses s ON s.code = d.status
            WHERE d.node_id = NEW.node_id
              AND d.id <> NEW.id
              AND s.allows_attribution = 1
              AND d.activated_at IS NOT NULL
              AND d.activated_at <= COALESCE(NEW.closed_at, '9999-12-31 23:59:59')
              AND NEW.activated_at <= COALESCE(d.closed_at, '9999-12-31 23:59:59')
       );
END;

-- ------------------------------------------------------ 3. immutability
-- Frozen from the moment a reading can be attributed. `closed_at` may still be
-- written once (NULL -> value) because that is exactly what the transition to a
-- terminal state does; it may not be changed afterwards.
CREATE TRIGGER trg_deployment_immutable_after_activation
BEFORE UPDATE ON deployments
WHEN OLD.activated_at IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'deployment attribution fields are immutable once activated; create a new deployment instead')
     WHERE NEW.node_id             IS NOT OLD.node_id
        OR NEW.building_id         IS NOT OLD.building_id
        OR NEW.electrical_panel_id IS NOT OLD.electrical_panel_id
        OR NEW.activated_at        IS NOT OLD.activated_at
        OR (OLD.closed_at IS NOT NULL AND NEW.closed_at IS NOT OLD.closed_at);
END;

COMMIT;
