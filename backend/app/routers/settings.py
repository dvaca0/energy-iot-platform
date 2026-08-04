from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.platform_settings import get_platform_settings, save_platform_settings

router = APIRouter()


class SettingsPayload(BaseModel):
    thresholds: dict[str, Any] | None = None
    retention: dict[str, Any] | None = None
    tariff: dict[str, Any] | None = None
    ai: dict[str, Any] | None = None
    system: dict[str, Any] | None = None


@router.get("")
def read_settings():
    return get_platform_settings()


@router.put("")
def update_settings(payload: SettingsPayload):
    clean = {k: v for k, v in payload.model_dump().items() if v is not None}
    return save_platform_settings(clean)


from fastapi import Query

from app.services.cfe_scraper import scrape_gdmth_tariff


@router.post("/cfe/scrape")
def scrape_cfe_gdmth(
    year: int | None = Query(None),
    month: str | None = Query(None),
    state: str = Query("Colima"),
    municipality: str | None = Query("Colima"),
    division: str | None = Query(None),
):
    scraped = scrape_gdmth_tariff(
        year=year,
        month=month,
        state=state,
        municipality=municipality,
        division=division,
        headless=True,
    )

    tariff = {
        "active": "GDMTH",
        "source": "CFE web scraper",
        "baseRate": scraped.get("base_mxn_kwh"),
        "interRate": scraped.get("intermediate_mxn_kwh"),
        "peakRate": scraped.get("peak_mxn_kwh"),
        "fixedCharge": scraped.get("fixed_charge_mxn_month"),
        "distributionRate": scraped.get("distribution_mxn_kw"),
        "capacityRate": scraped.get("capacity_mxn_kw"),
        "lastUpdate": f"{scraped.get('month_label')}-{str(scraped.get('year'))[-2:]} · {scraped.get('region') or scraped.get('division') or 'CFE'}",
        "apiStatus": "Scraper CFE activo",
        "apiNote": "Tarifa sincronizada desde CFE",
        "year": scraped.get("year"),
        "month": scraped.get("month_label"),
        "state": scraped.get("state"),
        "municipality": scraped.get("municipality"),
        "division": scraped.get("division"),
        "sourceUrl": scraped.get("source_url"),
    }

    current = get_platform_settings()
    updated = save_platform_settings(
        {
            **current,
            "tariff": {
                **current.get("tariff", {}),
                **tariff,
            },
        }
    )

    return {
        **scraped,
        "saved": True,
        "settings_tariff": updated.get("tariff", {}),
    }


@router.get("/cfe/status")
def cfe_scraper_status():
    from app.services.cfe_scraper import current_cfe_period

    year, month = current_cfe_period()

    return {
        "enabled": True,
        "mode": "scraper",
        "status": "ready",
        "label": "Scraper CFE activo",
        "source": "CFE web scraper",
        "tariff": "GDMTH",
        "year": year,
        "month": month,
        "state": "Colima",
        "municipality": "Colima",
        "division": "Centro Occidente",
        "endpoint": "/api/settings/cfe/scrape",
        "manual_fallback": True,
    }
