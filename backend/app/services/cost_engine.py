from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.services.platform_settings import get_platform_settings

LOCAL_TZ = ZoneInfo("America/Mexico_City")

_RATE_CACHE = {"loaded_at": None, "rates": None}
_RATE_CACHE_SECONDS = 60


def _now_utc():
    return datetime.now(UTC)


def clear_tariff_cache():
    _RATE_CACHE["loaded_at"] = None
    _RATE_CACHE["rates"] = None


def get_active_tariff_rates():
    now = _now_utc()

    if (
        _RATE_CACHE["rates"] is not None
        and _RATE_CACHE["loaded_at"] is not None
        and (now - _RATE_CACHE["loaded_at"]).total_seconds() < _RATE_CACHE_SECONDS
    ):
        return _RATE_CACHE["rates"]

    settings = get_platform_settings()
    tariff = settings.get("tariff", {})

    rates = {
        "base": float(tariff.get("baseRate") or tariff.get("base") or 1.0375),
        "intermediate": float(
            tariff.get("interRate")
            or tariff.get("intermediate")
            or tariff.get("intermedia")
            or 1.8463
        ),
        "intermedia": float(
            tariff.get("interRate")
            or tariff.get("intermedia")
            or tariff.get("intermediate")
            or 1.8463
        ),
        "peak": float(
            tariff.get("peakRate") or tariff.get("peak") or tariff.get("punta") or 2.0789
        ),
        "punta": float(
            tariff.get("peakRate") or tariff.get("punta") or tariff.get("peak") or 2.0789
        ),
        "source": tariff.get("source", "Manual fallback"),
    }

    _RATE_CACHE["loaded_at"] = now
    _RATE_CACHE["rates"] = rates
    return rates


def to_local_time(timestamp: datetime):
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(LOCAL_TZ)


@lru_cache(maxsize=256)
def first_sunday(year: int, month: int):
    d = date(year, month, 1)
    while d.weekday() != 6:
        d += timedelta(days=1)
    return d


@lru_cache(maxsize=256)
def last_sunday(year: int, month: int):
    if month == 12:
        d = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        d = date(year, month + 1, 1) - timedelta(days=1)

    while d.weekday() != 6:
        d -= timedelta(days=1)
    return d


@lru_cache(maxsize=4096)
def _summer_for_date(day: date) -> bool:
    """Whether a calendar date falls in the CFE summer schedule.

    Pure function of the date. It was recomputed for every reading — 76,214
    times per /api/ai-center request, each one walking a day-by-day loop to find
    the first and last Sunday of a month.
    """
    return first_sunday(day.year, 4) <= day < last_sunday(day.year, 10)


def is_summer_schedule(local_dt: datetime):
    return _summer_for_date(local_dt.date())


def classify_gdmth_period(local_dt: datetime):
    hour = local_dt.hour + local_dt.minute / 60
    weekday = local_dt.weekday()
    summer = is_summer_schedule(local_dt)

    if summer:
        if weekday <= 4:
            if 0 <= hour < 6:
                return "base"
            if 20 <= hour < 22:
                return "peak"
            return "intermediate"
        if weekday == 5:
            if 0 <= hour < 7:
                return "base"
            return "intermediate"
        if weekday == 6:
            if 0 <= hour < 19:
                return "base"
            return "intermediate"

    else:
        if weekday <= 4:
            if 0 <= hour < 6:
                return "base"
            if 18 <= hour < 22:
                return "peak"
            return "intermediate"
        if weekday == 5:
            if 0 <= hour < 8:
                return "base"
            if 19 <= hour < 21:
                return "peak"
            return "intermediate"
        if weekday == 6:
            if 0 <= hour < 18:
                return "base"
            return "intermediate"

    return "intermediate"


def get_tariff_rate(db: Session, period_name: str, tariff_name: str = "GDMTH"):
    rates = get_active_tariff_rates()
    return rates.get(period_name, rates.get("intermediate", 0))


def estimate_reading_cost(
    db: Session,
    timestamp: datetime,
    energy_kwh: float | None,
    tariff_name: str = "GDMTH",
):
    if energy_kwh is None:
        energy_kwh = 0

    local_timestamp = to_local_time(timestamp)
    period_name = classify_gdmth_period(local_timestamp)
    price = get_tariff_rate(db, period_name, tariff_name)

    return {
        "tariff_name": tariff_name,
        "period_name": period_name,
        "price_per_kwh_mxn": price,
        "energy_kwh": energy_kwh,
        "cost_mxn": energy_kwh * price,
        "local_hour": local_timestamp.hour,
        "local_timestamp": local_timestamp.isoformat(),
    }
