from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import TariffPeriod
from app.routers.metrics import tariff_metrics
from app.routers.dashboard import dashboard_summary

router = APIRouter()


@router.get("/summary")
def cost_summary(db: Session = Depends(get_db)):
    summary = dashboard_summary(db)
    tariffs = tariff_metrics(db)
    periods = db.query(TariffPeriod).filter(TariffPeriod.is_active == True).all()

    rates = {}
    for p in periods:
        rates[p.period_name] = p.price_per_kwh_mxn

    return {
        "tariff": "GDMTH",
        "currency": "MXN",
        "source": "manual_fallback",
        "last_updated": "manual",
        "cost_today_mxn": summary["estimated_cost_today_mxn"],
        "cost_week_mxn": summary["estimated_cost_week_mxn"],
        "projected_month_mxn": summary["projected_monthly_cost_mxn"],
        "peak_cost_share_pct": next((x["share_pct"] for x in tariffs if x["period"] == "peak"), 0),
        "periods": tariffs,
        "rates": {
            "base": rates.get("base", 0),
            "intermediate": rates.get("intermediate", 0),
            "peak": rates.get("peak", 0),
        },
    }


@router.get("/hourly")
def hourly_cost():
    return []
