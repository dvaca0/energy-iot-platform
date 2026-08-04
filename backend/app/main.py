from dotenv import load_dotenv

load_dotenv(dotenv_path=".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import (
    ai,
    ai_center,
    alerts,
    anomalies,
    buildings,
    cost,
    dashboard,
    data_explorer,
    deployments,
    edge,
    infra,
    metrics,
    mining,
    nodes,
    org,
    readings,
    reports,
    settings,
    smart_plugs,
)

app = FastAPI(
    title="University Energy Intelligence Platform API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])
app.include_router(buildings.router, prefix="/api/buildings", tags=["Buildings"])
app.include_router(nodes.router, prefix="/api/nodes", tags=["Nodes"])
app.include_router(deployments.router, prefix="/api/deployments", tags=["Deployments"])
app.include_router(cost.router, prefix="/api/cost", tags=["Cost"])
app.include_router(ai.router, prefix="/api/ai", tags=["AI"])
app.include_router(org.router, prefix="/api/org", tags=["Organization"])
app.include_router(readings.router, prefix="/api/readings", tags=["Readings"])
app.include_router(metrics.router, prefix="/api/metrics", tags=["Metrics"])
app.include_router(edge.router)
app.include_router(anomalies.router, prefix="/api/anomalies", tags=["Anomalies"])
app.include_router(settings.router, prefix="/api/settings", tags=["Settings"])
app.include_router(infra.router, prefix="/api/infra", tags=["Infrastructure"])


@app.get("/health")
def health():
    return {"status": "ok", "service": "energy-platform-backend"}


app.include_router(mining.router, prefix="/api/mining", tags=["Mining"])

app.include_router(ai_center.router, prefix="/api/ai-center", tags=["AI Center"])

app.include_router(reports.router, prefix="/api/reports", tags=["Reports"])

app.include_router(data_explorer.router, prefix="/api/data-explorer", tags=["data-explorer"])

app.include_router(alerts.router, prefix="/api/alerts", tags=["Alerts"])

app.include_router(smart_plugs.router, prefix="/api/smart-plugs", tags=["Smart Plugs"])

# Monitoring subsystem. Importing the package registers every health rule and
# makes its tables known to SQLAlchemy; the tables themselves are created by
# the monitoring service, not here, so the API process never alters the schema.
from app.monitoring.router import router as monitoring_router

app.include_router(monitoring_router, prefix="/api/monitoring", tags=["Monitoring"])
