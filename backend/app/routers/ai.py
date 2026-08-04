from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.routers.dashboard import dashboard_summary
from app.services.anomaly_engine import ACTIVE, detect_all_anomalies

router = APIRouter()


@router.get("/insights")
def ai_insights(db: Session = Depends(get_db)):
    summary = dashboard_summary(db)
    # Live conditions only. This payload has no status field of its own, so a
    # recovered finding here would read as a current one.
    anomalies = [a for a in detect_all_anomalies(db) if a.get("status") == ACTIVE]

    recommendations = summary.get("savings_recommendations", [])

    return {
        "recommendations": recommendations,
        "anomalies": anomalies,
        "summary": {
            "potential_savings_mxn_month": summary.get("potential_savings_mxn_month", 0),
            "most_expensive_building": summary.get("most_expensive_building"),
            "energy_today_kwh": summary.get("energy_today_kwh", 0),
            "estimated_cost_today_mxn": summary.get("estimated_cost_today_mxn", 0),
        },
    }
