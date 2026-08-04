from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

CFE_GDMTH_URL = (
    "https://app.cfe.mx/Aplicaciones/CCFE/Tarifas/TarifasCRENegocio/Tarifas/GranDemandaMTH.aspx"
)

MONTHS_ES = {
    1: "ENE",
    2: "FEB",
    3: "MAR",
    4: "ABR",
    5: "MAY",
    6: "JUN",
    7: "JUL",
    8: "AGO",
    9: "SEP",
    10: "OCT",
    11: "NOV",
    12: "DIC",
}


def current_cfe_period():
    now = datetime.now(ZoneInfo("America/Mexico_City"))
    return now.year, MONTHS_ES[now.month]


def _num(text: str) -> float | None:
    cleaned = text.replace("$", "").replace(",", "").strip()
    try:
        return float(cleaned)
    except Exception:
        return None


def _valid_option(text: str, value: str | None) -> bool:
    t = (text or "").strip().lower()
    return bool(value) and "seleccione" not in t and "--" not in t and t != ""


def _wait(page):
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(1200)


def _select_by_text_or_first(page, wanted: str | None = None) -> str | None:
    selects = page.locator("select")

    # First try exact/contains match across all selects.
    if wanted:
        wanted_low = wanted.lower()
        for i in range(selects.count()):
            sel = selects.nth(i)
            opts = sel.locator("option")
            for j in range(opts.count()):
                txt = opts.nth(j).inner_text().strip()
                val = opts.nth(j).get_attribute("value")
                if val and wanted_low in txt.lower():
                    sel.select_option(val)
                    _wait(page)
                    return txt

    # Then pick first valid option from the first select that has one.
    for i in range(selects.count()):
        sel = selects.nth(i)
        opts = sel.locator("option")
        for j in range(opts.count()):
            txt = opts.nth(j).inner_text().strip()
            val = opts.nth(j).get_attribute("value")
            if _valid_option(txt, val):
                sel.select_option(val)
                _wait(page)
                return txt

    return None


def _select_specific_select(page, select_index: int, wanted: str | None = None) -> str | None:
    selects = page.locator("select")
    if select_index >= selects.count():
        return None

    sel = selects.nth(select_index)
    opts = sel.locator("option")

    if wanted:
        wanted_low = wanted.lower()
        for j in range(opts.count()):
            txt = opts.nth(j).inner_text().strip()
            val = opts.nth(j).get_attribute("value")
            if val and wanted_low in txt.lower():
                sel.select_option(val)
                _wait(page)
                return txt

    for j in range(opts.count()):
        txt = opts.nth(j).inner_text().strip()
        val = opts.nth(j).get_attribute("value")
        if _valid_option(txt, val):
            sel.select_option(val)
            _wait(page)
            return txt

    return None


def _extract_from_rows(rows: list[list[str]], month_label: str) -> dict[str, float | None]:
    out = {
        "fixed_charge_mxn_month": None,
        "base_mxn_kwh": None,
        "intermediate_mxn_kwh": None,
        "peak_mxn_kwh": None,
        "distribution_mxn_kw": None,
        "capacity_mxn_kw": None,
    }

    for cells in rows:
        joined = " ".join(cells)
        value = _num(cells[-1]) if cells else None

        if "Fijo" in joined:
            out["fixed_charge_mxn_month"] = value
        elif "Base" in joined and "$/kWh" in joined:
            out["base_mxn_kwh"] = value
        elif "Intermedia" in joined and "$/kWh" in joined:
            out["intermediate_mxn_kwh"] = value
        elif "Punta" in joined and "$/kWh" in joined:
            out["peak_mxn_kwh"] = value
        elif "Distribución" in joined:
            out["distribution_mxn_kw"] = value
        elif "Capacidad" in joined:
            out["capacity_mxn_kw"] = value

    return out


def scrape_gdmth_tariff(
    year: int | None = None,
    month: str | None = None,
    state: str = "Colima",
    municipality: str | None = "Colima",
    division: str | None = None,
    headless: bool = True,
) -> dict[str, Any]:
    auto_year, auto_month = current_cfe_period()
    year = year or auto_year
    month = (month or auto_month).upper()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        page.goto(CFE_GDMTH_URL, wait_until="domcontentloaded", timeout=60000)
        _wait(page)

        # Usually: select 0 = year, select 1 = month, select 2 = estado, select 3 = municipio, select 4 = division.
        _select_specific_select(page, 0, str(year))
        _select_specific_select(page, 1, month)
        _select_specific_select(page, 2, state)
        selected_municipality = _select_specific_select(page, 3, municipality)
        selected_division = _select_specific_select(page, 4, division)

        _wait(page)

        html = page.content()
        text = page.locator("body").inner_text(timeout=10000)

        with open("/tmp/cfe_scraper_last.html", "w", encoding="utf-8") as f:
            f.write(html)
        page.screenshot(path="/tmp/cfe_scraper_last.png", full_page=True)

        browser.close()

    soup = BeautifulSoup(html, "lxml")
    rows: list[list[str]] = []

    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if cells:
            rows.append(cells)

    values = _extract_from_rows(rows, month)

    # Fallback: parse raw page text if CFE renders table in unusual markup.
    if not values["base_mxn_kwh"]:
        patterns = {
            "fixed_charge_mxn_month": r"Fijo\s+\$/mes\s+([0-9]+(?:\.[0-9]+)?)",
            "base_mxn_kwh": r"Base\s+Variable\s*\(Energía\)\s+\$/kWh\s+([0-9]+(?:\.[0-9]+)?)",
            "intermediate_mxn_kwh": r"Intermedia\s+Variable\s*\(Energía\)\s+\$/kWh\s+([0-9]+(?:\.[0-9]+)?)",
            "peak_mxn_kwh": r"Punta\s+Variable\s*\(Energía\)\s+\$/kWh\s+([0-9]+(?:\.[0-9]+)?)",
            "distribution_mxn_kw": r"Distribución\s+\$/kW\s+([0-9]+(?:\.[0-9]+)?)",
            "capacity_mxn_kw": r"Capacidad\s+\$/kW\s+([0-9]+(?:\.[0-9]+)?)",
        }
        compact = re.sub(r"\s+", " ", text)
        for key, pat in patterns.items():
            m = re.search(pat, compact, re.I)
            if m:
                values[key] = _num(m.group(1))

    if not values["base_mxn_kwh"]:
        raise RuntimeError(
            "No se encontró la tabla GDMTH. Se guardó debug en /tmp/cfe_scraper_last.png y /tmp/cfe_scraper_last.html"
        )

    return {
        "tariff": "GDMTH",
        "region": "Centro Occidente" if "Centro Occidente" in text else None,
        "year": year,
        "month_label": month,
        "state": state,
        "municipality": selected_municipality,
        "division": selected_division,
        "source_url": CFE_GDMTH_URL,
        **values,
        "raw_rows": rows,
    }
