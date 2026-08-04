#!/usr/bin/env python3
"""Render the route tables in docs/API.md from a live OpenAPI schema.

Usage::

    curl -s http://127.0.0.1:8010/openapi.json -o /tmp/openapi.json
    python3 scripts/gen_api_docs.py /tmp/openapi.json > /tmp/routes.md

The output is the "Routes" section of docs/API.md. Splicing it in by hand is
deliberate: the prose around it is written, not generated, and regenerating the
whole file would discard it.

`scripts/check_api_docs.py` verifies in CI that the documented route count still
matches the schema, so an undocumented route fails the build.
"""

import json
import sys

d = json.load(open(sys.argv[1]))
TITLES={
 'api/v1':('Ingestion','The canonical measurement endpoint. Contract: [Collector.md](Collector.md).'),
 'api/edge':('Edge heartbeat','Node health reporting — ~50 fields every 45 s.'),
 'api/readings':('Readings (legacy)','Retained so existing collectors keep working. New collectors use `/api/v1/measurements/batch`.'),
 'api/dashboard':('Dashboard','Executive rollups.'),
 'api/metrics':('Metrics','Live and historical electrical metrics.'),
 'api/cost':('Cost','CFE GDMTH tariff arithmetic.'),
 'api/org':('Organisation','Delegations, campuses, units, buildings, panels.'),
 'api/buildings':('Buildings','Building inventory and coverage.'),
 'api/nodes':('Nodes','Identity, commissioning and physical ratings.'),
 'api/deployments':('Deployments','Installation-campaign lifecycle.'),
 'api/monitoring':('Monitoring','Alerts, rules, health and Telegram configuration. See [Monitoring.md](Monitoring.md).'),
 'api/alerts':('Alerts (legacy)','Deployment-gated legacy surface — silent by design.'),
 'api/anomalies':('Anomalies','Threshold-rule anomalies. **Not** the alerting system.'),
 'api/ai':('AI insights','Narrative insights.'),
 'api/ai-center':('AI Centre','Forecasting, clustering and optional narration. See [AI.md](AI.md).'),
 'api/mining':('Data mining','Clustering and pattern analysis.'),
 'api/data-explorer':('Data explorer','Ad-hoc query surface.'),
 'api/reports':('Reports','PDF, CSV and XLSX generation.'),
 'api/smart-plugs':('Smart plugs','See [Smart-Plugs.md](Smart-Plugs.md).'),
 'api/settings':('Settings','Runtime platform settings and CFE tariff sync.'),
 'api/infra':('Infrastructure','Infrastructure status.'),
 'health':('Health','Liveness probe. No authentication, no database access.')}
ORDER=['health','api/v1','api/edge','api/readings','api/dashboard','api/metrics','api/cost',
 'api/org','api/buildings','api/nodes','api/deployments','api/monitoring','api/alerts',
 'api/anomalies','api/ai','api/ai-center','api/mining','api/data-explorer','api/reports',
 'api/smart-plugs','api/settings','api/infra']
g={}
for p,ops in sorted(d['paths'].items()):
    k='/'.join(p.strip('/').split('/')[:2])
    for m,op in ops.items():
        if m in ('get','post','put','patch','delete'):
            g.setdefault(k,[]).append((m.upper(),p,op.get('summary','')))
for k in ORDER:
    if k not in g: continue
    t,desc=TITLES[k]
    print(f"### {t}\n")
    if desc: print(desc+"\n")
    print("| Method | Path | Purpose |\n|---|---|---|")
    for m,p,s in g[k]: print(f"| `{m}` | `{p}` | {s} |")
    print()
