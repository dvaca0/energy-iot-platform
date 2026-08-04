from datetime import datetime, timedelta
from statistics import mean

from sqlalchemy.orm import Session

from app.services import energy_aggregate as agg


def _daily_costs(db: Session, days: int = 30):
    """Daily cost series used to score forecast confidence (MAPE).

    Now derived from the canonical hourly aggregate, so the series that scores
    the forecast reconciles with the daily, weekly and monthly figures shown
    elsewhere. Two consequences, both deliberate:

    * days are LOCAL days, as everywhere else in the platform. This function
      used to group by UTC date, so its "days" were offset by six hours from
      every other daily figure.
    * the delta spanning local midnight is counted, rather than dropped by a
      per-day reset — the same correction applied to /api/metrics/daily.
    """
    end = datetime.utcnow()
    buckets = agg.hourly_energy(db, start=end - timedelta(days=days))

    grouped = {}
    for day, rows in agg.by_local_date(buckets).items():
        grouped[day] = agg.totals(rows)[1]

    return [v for _, v in sorted(grouped.items()) if v > 0]


def real_forecast_confidence(db: Session):
    values = _daily_costs(db, 30)

    if len(values) < 7:
        return {
            "confidence": None,
            "confidence_pct": None,
            "method": "Insufficient historical data. At least 7 complete daily cost points are required.",
            "samples": len(values),
            "mape": None,
        }

    errors = []
    for i in range(3, len(values)):
        predicted = mean(values[max(0, i - 3) : i])
        actual = values[i]
        if actual > 0:
            errors.append(abs(actual - predicted) / actual)

    if not errors:
        return {
            "confidence": None,
            "confidence_pct": None,
            "method": "Unable to calculate confidence because recent actual values are zero.",
            "samples": len(values),
            "mape": None,
        }

    mape = mean(errors)
    confidence = max(0, min(1, 1 - mape))

    return {
        "confidence": round(confidence, 4),
        "confidence_pct": round(confidence * 100, 2),
        "method": "Backtesting confidence based on rolling historical daily-cost prediction error.",
        "samples": len(values),
        "mape": round(mape * 100, 2),
    }
