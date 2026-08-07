-- description: add the infrastructure_validation measurement context
-- waivers:
--
-- WHY
--
-- Nodes are powered for infrastructure validation with no operational
-- deployment. They produce real, useful measurements — the collector runs, the
-- sensors read — but those measurements describe a bench, not a building.
--
-- The six existing contexts cannot express this. `bench` means hardware under
-- test on a desk; `commissioning` means on-site verification for a campaign
-- that is about to start and may still attribute. Neither is true of a node
-- sitting powered in a lab between campaigns.
--
-- Rather than overload an existing context (which would silently redefine data
-- already stored under it — forbidden by CONTRIBUTING), this adds a seventh
-- with the semantics actually required:
--
--   counts_in_analytics = 0   never in dashboards, costs, AI or reports
--   may_attribute       = 0   never attaches to a deployment or a building
--
-- One INSERT, no schema change — which is the point of M6 making contexts a
-- lookup table.

BEGIN IMMEDIATE;

INSERT OR IGNORE INTO measurement_contexts
    (code, label, sort_order, counts_in_analytics, may_attribute, description)
VALUES
    ('infrastructure_validation', 'Infrastructure validation', 25, 0, 0,
     'Node powered and collecting for platform validation, with no operational deployment. Real measurements, retained for diagnostics, never attributed to a building and never counted in analytics.');

COMMIT;
