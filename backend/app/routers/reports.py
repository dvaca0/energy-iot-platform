import csv
from datetime import datetime, timedelta
from io import BytesIO, StringIO

import markdown
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from jinja2 import Template
from openpyxl import Workbook
from sqlalchemy import func
from sqlalchemy.orm import Session
from weasyprint import HTML

from app.db import scope
from app.db.database import get_db
from app.db.models import Building, Deployment, EnergyReading, Node
from app.services import energy_aggregate as agg
from app.services.cost_engine import estimate_reading_cost
from app.services.gemini_engine import ask_gemini, gemini_enabled
from app.services.ml_engine import (
    group_anomaly_events,
    isolation_forest_anomalies,
    kmeans_building_clusters,
    random_forest_forecast,
)
from app.services.platform_settings import get_platform_settings

router = APIRouter()


REPORT_TEMPLATE = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page {
    size: Letter;
    margin: 16mm 14mm 14mm 14mm;
  }

  * { box-sizing: border-box; }

  body {
    margin: 0;
    font-family: Arial, Helvetica, sans-serif;
    color: #151528;
    background: #ffffff;
    font-size: 10.5px;
  }

  .topbar {
    background: #17172A;
    color: white;
    padding: 14px 18px;
    border-bottom: 5px solid #8B7CF6;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .brand {
    font-size: 17px;
    font-weight: 800;
  }

  .brand small {
    display: block;
    font-size: 9px;
    color: #c4bdf0;
    margin-top: 3px;
    font-weight: 500;
  }

  .meta {
    text-align: right;
    font-size: 9px;
    color: #d6d3f5;
    line-height: 1.45;
  }

  .hero {
    padding: 18px 0 10px 0;
    display: grid;
    grid-template-columns: 1.4fr .9fr;
    gap: 14px;
  }

  h1 {
    font-size: 25px;
    margin: 0 0 5px 0;
    letter-spacing: -.5px;
  }

  .subtitle {
    color: #64748b;
    font-size: 11px;
    line-height: 1.45;
  }

  .tagbox {
    border: 1px solid #d8d5ff;
    background: #f6f5ff;
    border-radius: 8px;
    padding: 10px 12px;
    line-height: 1.5;
  }

  .tagbox b { color: #6D5BD0; }

  .kpis {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 8px;
    margin: 10px 0 14px 0;
  }

  .kpi {
    border: 1px solid #d8d5ff;
    border-left: 4px solid #8B7CF6;
    background: #fbfbff;
    border-radius: 7px;
    padding: 9px 10px;
    min-height: 54px;
  }

  .kpi .label {
    color: #64748b;
    font-size: 8.5px;
    text-transform: uppercase;
    letter-spacing: .5px;
    margin-bottom: 5px;
  }

  .kpi .value {
    font-size: 16px;
    font-weight: 800;
    color: #151528;
  }

  .grid-2 {
    display: grid;
    grid-template-columns: 1.1fr .9fr;
    gap: 12px;
    margin-bottom: 12px;
  }

  .section {
    margin-top: 10px;
    page-break-inside: avoid;
  }

  .card {
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 12px;
    background: white;
    page-break-inside: avoid;
  }

  .card h2, .section h2 {
    font-size: 15px;
    margin: 0 0 8px 0;
    color: #151528;
  }

  .ai {
    border: 1px solid #a78bfa;
    background: #eef2ff;
    border-radius: 8px;
    padding: 11px 13px;
    color: #312e81;
    line-height: 1.45;
  }

  .ai h1, .ai h2, .ai h3 {
    font-size: 12px;
    margin: 8px 0 4px 0;
    color: #312e81;
  }

  .ai p { margin: 5px 0; }
  .ai ul, .ai ol { margin: 5px 0 5px 16px; padding: 0; }
  .ai li { margin: 3px 0; }

  table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 6px;
    font-size: 9px;
    page-break-inside: auto;
  }

  thead {
    display: table-header-group;
  }

  th {
    background: #17172A;
    color: white;
    text-align: left;
    padding: 6px 7px;
    font-size: 8.5px;
  }

  td {
    border: 1px solid #e2e8f0;
    padding: 5px 7px;
    vertical-align: top;
  }

  tr:nth-child(even) td {
    background: #f8fafc;
  }

  .bar-row {
    margin: 7px 0;
  }

  .bar-label {
    display: flex;
    justify-content: space-between;
    font-size: 9px;
    margin-bottom: 3px;
  }

  .bar {
    height: 8px;
    background: #e5e7eb;
    border-radius: 99px;
    overflow: hidden;
  }

  .bar-fill {
    height: 100%;
    background: linear-gradient(90deg, #6D5BD0, #8B7CF6);
  }

  .footer-note {
    margin-top: 12px;
    font-size: 8.5px;
    color: #64748b;
    border-top: 1px solid #e2e8f0;
    padding-top: 7px;
  }

  .page-break {
    page-break-before: always;
  }
</style>
</head>
<body>
  <div class="topbar">
    <div class="brand">
      Universidad de Colima
      <small>Energy Intelligence Platform - IoT Monitoring</small>
    </div>
    <div class="meta">
      {{ report_type }}<br>
      {{ generated_at }}<br>
      Tarifa {{ tariff.active }} - {{ tariff.source }}
    </div>
  </div>

  <div class="hero">
    <div>
      <h1>{{ title }}</h1>
      <div class="subtitle">{{ subtitle }}</div>
    </div>
    <div class="tagbox">
      <b>Periodo:</b> {{ period }}<br>
      <b>Fuente:</b> PostgreSQL + modelos locales + CFE<br>
      <b>Última tarifa:</b> {{ tariff.lastUpdate }}
    </div>
  </div>

  {% if kpis %}
  <div class="kpis">
    {% for kpi in kpis %}
    <div class="kpi">
      <div class="label">{{ kpi.label }}</div>
      <div class="value">{{ kpi.value }}</div>
    </div>
    {% endfor %}
  </div>
  {% endif %}

  {% if ai_html %}
  <div class="section">
    <h2>Interpretación ejecutiva</h2>
    <div class="ai">{{ ai_html | safe }}</div>
  </div>
  {% endif %}

  {% if bars %}
  <div class="section card">
    <h2>{{ bars_title }}</h2>
    {% for b in bars %}
    <div class="bar-row">
      <div class="bar-label"><span>{{ b.label }}</span><strong>{{ b.value }}</strong></div>
      <div class="bar"><div class="bar-fill" style="width: {{ b.percent }}%;"></div></div>
    </div>
    {% endfor %}
  </div>
  {% endif %}

  {% for table in tables %}
  <div class="section">
    <h2>{{ table.title }}</h2>
    <table>
      <thead>
        <tr>
          {% for h in table.headers %}
          <th>{{ h }}</th>
          {% endfor %}
        </tr>
      </thead>
      <tbody>
        {% for row in table.rows %}
        <tr>
          {% for cell in row %}
          <td>{{ cell }}</td>
          {% endfor %}
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
  {% endfor %}

  <div class="footer-note">
    Reporte generado automáticamente por Energy Intelligence Platform. Los cálculos usan lecturas reales disponibles al momento de generación.
  </div>
</body>
</html>
"""


def money(v):
    return f"${float(v or 0):,.2f} MXN"


def num(v, d=2):
    return f"{float(v or 0):,.{d}f}"


def get_tariff():
    settings = get_platform_settings()
    return settings.get(
        "tariff",
        {
            "active": "GDMTH",
            "source": "Configuración local",
            "lastUpdate": "Sin fecha",
        },
    )


def md(text):
    return markdown.markdown(
        text or "Sin interpretación disponible.",
        extensions=["extra", "tables", "sane_lists"],
        output_format="html5",
    )


def ask_report_ai(prompt, context):
    if not gemini_enabled():
        return (
            "## Análisis local\n"
            "- Gemini no está habilitado.\n"
            "- El reporte se generó con datos reales disponibles.\n"
            "- Se conservan los cálculos locales de costo, anomalías y monitoreo."
        )
    try:
        return ask_gemini(prompt, context)
    except Exception as e:
        return (
            "## Análisis local\n"
            "- No fue posible consultar Gemini.\n"
            "- El reporte conserva datos reales y modelos locales.\n"
            f"- Detalle: {e!s}"
        )


def reading_building(r):
    # From the reading's own building. Going through r.deployment breaks for a
    # legitimately unattributed reading and reintroduces the coupling ADR-0004
    # removes.
    if r.building:
        return r.building.name
    return "Sin edificio"


def _deployment_energy(db, rows):
    """Canonical interval energy for a deployment's readings, keyed by id.

    The window is narrowed to the readings actually in hand so the resolver does
    not scan all history for an export of one deployment. All contexts are
    included: a deployment export shows exactly the rows attributed to it,
    whatever context they carry.
    """
    if not rows:
        return {}
    stamps = [r.timestamp for r in rows if r.timestamp]
    if not stamps:
        return {}
    return agg.energy_by_reading_id(
        db,
        start=min(stamps),
        end=max(stamps) + timedelta(seconds=1),
        contexts="all",
    )


def cost_between(db, start, end=None):
    q = scope.production_readings(db).filter(
        EnergyReading.timestamp >= start,
        EnergyReading.energy_kwh.isnot(None),
    )
    if end:
        q = q.filter(EnergyReading.timestamp < end)

    rows = q.order_by(EnergyReading.node_id.asc(), EnergyReading.timestamp.asc()).all()

    # Energy from the canonical service (ADR-0007), so a report and the
    # dashboard cannot disagree about the same window.
    energy_by_id = agg.energy_by_reading_id(db, start=start, end=end)

    total_kwh = 0
    total_cost = 0
    by_building = {}

    for r in rows:
        delta = energy_by_id.get(r.id, 0.0)
        if not delta:
            continue

        cost = estimate_reading_cost(db, r.timestamp, delta)["cost_mxn"]
        total_kwh += delta
        total_cost += cost

        name = reading_building(r)
        by_building.setdefault(name, {"kwh": 0, "cost": 0})
        by_building[name]["kwh"] += delta
        by_building[name]["cost"] += cost

    return total_kwh, total_cost, by_building


def recent_rows(db, limit=8):
    rows = scope.production_readings(db).order_by(EnergyReading.timestamp.desc()).limit(limit).all()
    # The column is headed "kWh", so it must show interval energy, not the raw
    # legacy register (ADR-0007).
    energy_by_id = _deployment_energy(db, rows)
    return [
        [
            r.timestamp.strftime("%d/%m/%Y %H:%M") if r.timestamp else "-",
            str(r.node_id),
            reading_building(r),
            num(r.power_kw),
            num(energy_by_id.get(r.id, 0.0), 5),
            num(r.power_factor),
            num(r.frequency_hz),
        ]
        for r in rows
    ]


def render_pdf(payload):
    html = Template(REPORT_TEMPLATE).render(**payload)
    pdf = HTML(string=html).write_pdf()
    buffer = BytesIO(pdf)
    filename = (
        payload["title"]
        .lower()
        .replace(" ", "_")
        .replace("á", "a")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("é", "e")
    )
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'},
    )


def base_payload(title, subtitle, report_type):
    return {
        "title": title,
        "subtitle": subtitle,
        "report_type": report_type,
        "generated_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "period": "Últimos 7 días",
        "tariff": get_tariff(),
        "kpis": [],
        "ai_html": "",
        "bars": [],
        "bars_title": "Distribución",
        "tables": [],
    }


@router.get("/weekly-cost.pdf")
def weekly_cost_pdf(db: Session = Depends(get_db)):
    forecast = random_forest_forecast(db)
    start = datetime.utcnow() - timedelta(days=7)
    week_kwh, week_cost, buildings = cost_between(db, start)

    max_cost = max([v["cost"] for v in buildings.values()] or [1])
    bars = [
        {
            "label": name,
            "value": money(v["cost"]),
            "percent": round((v["cost"] / max_cost) * 100, 1) if max_cost else 0,
        }
        for name, v in sorted(buildings.items(), key=lambda x: x[1]["cost"], reverse=True)[:6]
    ]

    ai = ask_report_ai(
        "Genera un resumen ejecutivo del costo semanal. Incluye hallazgos, riesgos y recomendaciones. Usa Markdown limpio.",
        {
            "week_kwh": week_kwh,
            "week_cost": week_cost,
            "forecast": forecast,
            "buildings": buildings,
        },
    )

    payload = base_payload(
        "Resumen Semanal de Costo",
        "Reporte ejecutivo de consumo, costo y proyección energética.",
        "Ejecutivo · Datos reales",
    )
    payload["kpis"] = [
        {"label": "Costo semana", "value": money(week_cost)},
        {"label": "Energía semana", "value": f"{week_kwh:,.2f} kWh"},
        {"label": "Pronóstico mensual", "value": money(forecast.get("month_mxn", 0))},
        {"label": "Confianza modelo", "value": f"{float(forecast.get('confidence', 0))*100:.0f}%"},
    ]
    payload["ai_html"] = md(ai)
    payload["bars_title"] = "Costo por edificio"
    payload["bars"] = bars
    payload["tables"] = [
        {
            "title": "Resumen por edificio",
            "headers": ["Edificio", "kWh semana", "Costo semana"],
            "rows": [[name, num(v["kwh"]), money(v["cost"])] for name, v in buildings.items()]
            or [["Sin datos suficientes", "-", "-"]],
        },
        {
            "title": "Lecturas recientes",
            "headers": ["Fecha", "Nodo", "Edificio", "kW", "kWh", "FP", "Hz"],
            "rows": recent_rows(db, 8),
        },
    ]
    return render_pdf(payload)


@router.get("/building-comparison.pdf")
def building_comparison_pdf(db: Session = Depends(get_db)):
    clusters = kmeans_building_clusters(db)
    buildings = db.query(Building).all()

    rows = []
    bars = []
    for b in buildings:
        readings = scope.production_readings(db).filter(EnergyReading.building_id == b.id).all()
        powers = [float(r.power_kw) for r in readings if r.power_kw is not None]
        pfs = [float(r.power_factor) for r in readings if r.power_factor is not None]
        avg_kw = sum(powers) / len(powers) if powers else 0
        avg_pf = sum(pfs) / len(pfs) if pfs else 0
        rows.append(
            [
                b.name,
                b.campus.name if b.campus else "-",
                b.organizational_unit.name if b.organizational_unit else "-",
                len(readings),
                num(avg_kw),
                num(avg_pf),
            ]
        )
        bars.append({"label": b.name, "value": f"{avg_kw:.2f} kW", "percent": min(avg_kw * 4, 100)})

    ai = ask_report_ai(
        "Explica la comparación de edificios. Si hay poca cobertura, acláralo y recomienda siguientes pasos.",
        {"buildings": rows, "clusters": clusters},
    )

    payload = base_payload(
        "Comparación de Edificios",
        "Comparativo técnico de eficiencia y cobertura por edificio.",
        "Técnico · Datos reales",
    )
    payload["kpis"] = [
        {"label": "Edificios registrados", "value": str(len(buildings))},
        {"label": "Lecturas acumuladas", "value": f"{scope.production_readings(db).count():,}"},
        {"label": "Modelo", "value": "K-Means"},
        {
            "label": "Cobertura",
            "value": f"{len([r for r in rows if int(r[3]) > 0])}/{len(buildings)}",
        },
    ]
    payload["ai_html"] = md(ai)
    payload["bars_title"] = "Promedio kW por edificio"
    payload["bars"] = bars
    payload["tables"] = [
        {
            "title": "Tabla comparativa",
            "headers": ["Edificio", "Campus", "Unidad", "Lecturas", "Prom. kW", "Prom. FP"],
            "rows": rows or [["Sin edificios", "-", "-", "-", "-", "-"]],
        }
    ]
    return render_pdf(payload)


@router.get("/anomalies.pdf")
def anomalies_pdf(db: Session = Depends(get_db)):
    raw = isolation_forest_anomalies(db)
    grouped = group_anomaly_events(raw.get("items", []))

    rows = [
        [
            a.get("title", "-"),
            a.get("building", "-"),
            a.get("time", "-"),
            a.get("detected", "-"),
            a.get("expected", "-"),
            a.get("model", raw.get("model", "Isolation Forest")),
            a.get("count", 1),
        ]
        for a in grouped
    ]

    ai = ask_report_ai(
        "Explica las anomalías detectadas, posible causa eléctrica y acciones técnicas.",
        {"anomalies": grouped},
    )

    payload = base_payload(
        "Reporte de Anomalías IA",
        "Anomalías agrupadas mediante Isolation Forest y reglas eléctricas.",
        "IA · Isolation Forest",
    )
    payload["kpis"] = [
        {"label": "Eventos agrupados", "value": str(len(grouped))},
        {"label": "Lecturas anómalas", "value": str(len(raw.get("items", [])))},
        {"label": "Modelo", "value": raw.get("model", "Isolation Forest")},
        {"label": "Estado", "value": "Activo"},
    ]
    payload["ai_html"] = md(ai)
    payload["tables"] = [
        {
            "title": "Eventos agrupados",
            "headers": ["Tipo", "Edificio", "Hora", "Detectado", "Esperado", "Modelo", "Eventos"],
            "rows": rows or [["Sin anomalías", "-", "-", "-", "-", "-", "0"]],
        }
    ]
    return render_pdf(payload)


@router.get("/deployments.pdf")
def deployments_pdf(db: Session = Depends(get_db)):
    nodes = db.query(Node).all()
    now = datetime.utcnow()

    rows = []
    online = 0
    for n in nodes:
        last_sync = getattr(n, "last_sync", None)
        is_online = bool(last_sync and last_sync >= now - timedelta(seconds=120))
        online += 1 if is_online else 0
        samples = db.query(EnergyReading).filter(EnergyReading.node_id == n.id).count()
        rows.append(
            [
                getattr(n, "code", None) or n.id,
                getattr(n, "name", "-"),
                "online" if is_online else "offline",
                getattr(n, "ip_address", None) or "-",
                last_sync.strftime("%d/%m/%Y %H:%M") if last_sync else "Sin sincronía",
                getattr(n, "buffer_pending", 0) or 0,
                samples,
            ]
        )

    ai = ask_report_ai(
        "Explica el estado de despliegue de nodos, riesgos y acciones operativas.", {"nodes": rows}
    )

    payload = base_payload(
        "Reporte de Despliegue de Nodos",
        "Estado operativo de nodos IoT, sincronización y buffer.",
        "Técnico · Estado actual",
    )
    payload["kpis"] = [
        {"label": "Nodos registrados", "value": str(len(nodes))},
        {"label": "Nodos online", "value": str(online)},
        {"label": "Nodos offline", "value": str(max(len(nodes) - online, 0))},
        {"label": "Lecturas", "value": f"{db.query(EnergyReading).count():,}"},
    ]
    payload["ai_html"] = md(ai)
    payload["tables"] = [
        {
            "title": "Nodos registrados",
            "headers": ["Nodo", "Nombre", "Estado", "IP", "Última sync", "Buffer", "Muestras"],
            "rows": rows or [["Sin nodos", "-", "-", "-", "-", "-", "-"]],
        }
    ]
    return render_pdf(payload)


@router.get("/sustainability.pdf")
def sustainability_pdf(db: Session = Depends(get_db)):
    start = datetime.utcnow() - timedelta(days=30)
    total_kwh, total_cost, _ = cost_between(db, start)
    factor = 0.438
    co2 = total_kwh * factor
    trees = co2 / 21.77 if co2 else 0

    ai = ask_report_ai(
        "Genera interpretación ejecutiva de sostenibilidad y recomendaciones de reducción.",
        {"kwh": total_kwh, "co2": co2, "cost": total_cost},
    )

    payload = base_payload(
        "Reporte de Sostenibilidad",
        "Consumo energético, emisiones estimadas y oportunidades de reducción.",
        "Ejecutivo · Datos reales",
    )
    payload["period"] = "Últimos 30 días"
    payload["kpis"] = [
        {"label": "Energía 30 días", "value": f"{total_kwh:,.2f} kWh"},
        {"label": "CO₂ estimado", "value": f"{co2:,.2f} kg"},
        {"label": "Costo 30 días", "value": money(total_cost)},
        {"label": "Árboles equivalentes", "value": f"{trees:,.1f}"},
    ]
    payload["ai_html"] = md(ai)
    payload["tables"] = [
        {
            "title": "Detalle de cálculo",
            "headers": ["Métrica", "Valor", "Nota"],
            "rows": [
                ["Energía", f"{total_kwh:,.2f} kWh", "Lecturas reales"],
                ["CO₂", f"{co2:,.2f} kg", "Factor 0.438 kg/kWh"],
                ["Costo", money(total_cost), "Tarifa GDMTH activa"],
                ["Árboles equivalentes", f"{trees:,.1f}", "Referencia anual aproximada"],
            ],
        }
    ]
    return render_pdf(payload)


@router.get("/raw-readings.pdf")
def raw_readings_pdf(db: Session = Depends(get_db)):
    payload = base_payload(
        "Dataset Completo",
        "Vista previa del dataset. Para análisis externo use CSV.",
        "Datos · Lecturas reales",
    )
    payload["kpis"] = [
        {"label": "Lecturas", "value": f"{db.query(EnergyReading).count():,}"},
        {"label": "Nodos", "value": str(db.query(Node).count())},
        {"label": "Edificios", "value": str(db.query(Building).count())},
        {"label": "Formato", "value": "CSV"},
    ]
    payload["tables"] = [
        {
            "title": "Vista previa",
            "headers": ["Fecha", "Nodo", "Edificio", "kW", "kWh", "FP", "Hz"],
            "rows": recent_rows(db, 12),
        }
    ]
    return render_pdf(payload)


def readings_csv_response(db, contexts=None):
    """Export readings. Production contexts by default; ?context= widens it.

    `context` is emitted as a column so an exported file is self-describing —
    a downstream analysis can tell production rows from bench or laboratory
    rows without having to know how the export was parameterised.
    """
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "timestamp",
            "node_id",
            "node_code",
            "building",
            "deployment_id",
            "context",
            "voltage",
            "current",
            "power_kw",
            "energy_kwh",
            "power_factor",
            "frequency_hz",
        ]
    )

    rows = scope.production_readings(db, contexts).order_by(EnergyReading.timestamp.asc()).all()
    for r in rows:
        writer.writerow(
            [
                r.id,
                r.timestamp.isoformat() if r.timestamp else "",
                r.node_id,
                r.node.code if r.node else "",
                reading_building(r),
                r.deployment_id,
                r.context,
                r.voltage,
                r.current,
                r.power_kw,
                r.energy_kwh,
                r.power_factor,
                r.frequency_hz,
            ]
        )

    buffer = BytesIO(output.getvalue().encode("utf-8-sig"))
    return StreamingResponse(
        buffer,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="dataset_completo_lecturas.csv"'},
    )


CONTEXT_QUERY = Query(
    None,
    description=(
        "Measurement contexts to include, comma separated, or 'all'. "
        "Defaults to production contexts only."
    ),
)


@router.get("/raw-readings.csv")
def raw_readings_csv(context: str | None = CONTEXT_QUERY, db: Session = Depends(get_db)):
    return readings_csv_response(db, context)


@router.get("/dataset.csv")
def dataset_csv(context: str | None = CONTEXT_QUERY, db: Session = Depends(get_db)):
    return readings_csv_response(db, context)


def deployment_readings_csv(db, deployment_id: int):
    deployment = db.query(Deployment).filter(Deployment.id == deployment_id).first()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    rows = (
        db.query(EnergyReading)
        .filter(EnergyReading.deployment_id == deployment_id)
        .order_by(EnergyReading.timestamp.asc())
        .all()
    )

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "deployment_id",
            "node",
            "building",
            "timestamp",
            "voltage",
            "current",
            "power_kw",
            "energy_delta_kwh",
            "meter_energy_kwh",
            "power_factor",
            "frequency_hz",
            "tariff_period",
            "cost_mxn",
        ]
    )

    energy_by_id = _deployment_energy(db, rows)
    total_kwh = 0
    total_cost = 0

    for r in rows:
        delta = energy_by_id.get(r.id, 0.0)

        cost_info = estimate_reading_cost(db, r.timestamp, delta)
        total_kwh += delta
        total_cost += cost_info["cost_mxn"]

        writer.writerow(
            [
                deployment.id,
                deployment.node.code,
                deployment.building.name,
                r.timestamp.isoformat() if r.timestamp else "",
                r.voltage,
                r.current,
                r.power_kw,
                delta,
                r.meter_energy_kwh,
                r.power_factor,
                r.frequency_hz,
                cost_info["period_name"],
                cost_info["cost_mxn"],
            ]
        )

    buffer = BytesIO(output.getvalue().encode("utf-8-sig"))
    filename = f"deployment_{deployment.id}_{deployment.node.code}_{deployment.building.name.replace(' ', '_')}.csv"

    return StreamingResponse(
        buffer,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def deployment_pdf_payload(db, deployment_id: int):
    deployment = db.query(Deployment).filter(Deployment.id == deployment_id).first()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    rows = (
        db.query(EnergyReading)
        .filter(EnergyReading.deployment_id == deployment_id)
        .order_by(EnergyReading.timestamp.asc())
        .all()
    )

    energy_by_id = _deployment_energy(db, rows)
    total_kwh = 0
    total_cost = 0
    powers = []
    currents = []
    voltages = []
    pfs = []

    preview_rows = []

    for r in rows:
        delta = energy_by_id.get(r.id, 0.0)

        cost_info = estimate_reading_cost(db, r.timestamp, delta)

        total_kwh += delta
        total_cost += cost_info["cost_mxn"]

        if r.power_kw is not None:
            powers.append(float(r.power_kw))
        if r.current is not None:
            currents.append(float(r.current))
        if r.voltage is not None:
            voltages.append(float(r.voltage))
        if r.power_factor is not None:
            pfs.append(float(r.power_factor))

    for r in rows[-12:]:
        preview_rows.append(
            [
                r.timestamp.strftime("%d/%m/%Y %H:%M") if r.timestamp else "-",
                deployment.node.code,
                num(r.power_kw),
                num(r.current),
                num(r.voltage),
                num(r.power_factor),
                num(r.frequency_hz),
            ]
        )

    avg_pf = sum(pfs) / len(pfs) if pfs else 0
    avg_kw = sum(powers) / len(powers) if powers else 0
    max_current = max(currents) if currents else 0
    min_voltage = min(voltages) if voltages else 0

    ai = ask_report_ai(
        "Genera un análisis técnico y ejecutivo de este despliegue eléctrico. Incluye hallazgos, riesgos y recomendaciones de ahorro.",
        {
            "deployment_id": deployment.id,
            "node": deployment.node.code,
            "building": deployment.building.name,
            "start_date": deployment.start_date,
            "end_date": deployment.end_date,
            "status": deployment.status,
            "reading_count": len(rows),
            "total_kwh": total_kwh,
            "total_cost": total_cost,
            "avg_power_kw": avg_kw,
            "avg_power_factor": avg_pf,
            "max_current": max_current,
            "min_voltage": min_voltage,
        },
    )

    payload = base_payload(
        f"Reporte de Despliegue #{deployment.id}",
        f"{deployment.building.name} · Nodo {deployment.node.code} · {deployment.start_date} a {deployment.end_date}",
        "Técnico · Despliegue histórico",
    )

    payload["period"] = f"{deployment.start_date} – {deployment.end_date}"
    payload["kpis"] = [
        {"label": "Lecturas", "value": f"{len(rows):,}"},
        {"label": "Energía", "value": f"{total_kwh:,.2f} kWh"},
        {"label": "Costo", "value": money(total_cost)},
        {"label": "FP promedio", "value": f"{avg_pf:.2f}"},
    ]
    payload["ai_html"] = md(ai)
    payload["tables"] = [
        {
            "title": "Información del despliegue",
            "headers": ["Campo", "Valor"],
            "rows": [
                ["Nodo", deployment.node.code],
                ["Edificio", deployment.building.name],
                ["Campus", deployment.building.campus.name if deployment.building.campus else "-"],
                [
                    "Unidad",
                    (
                        deployment.building.organizational_unit.name
                        if deployment.building.organizational_unit
                        else "-"
                    ),
                ],
                ["Tablero", deployment.electrical_panel.name],
                ["Estado", deployment.status],
                ["Inicio", deployment.start_date],
                ["Fin", deployment.end_date],
                ["Notas", deployment.notes or "Sin notas"],
            ],
        },
        {
            "title": "Resumen eléctrico",
            "headers": ["Métrica", "Valor"],
            "rows": [
                ["Potencia promedio", f"{avg_kw:.2f} kW"],
                ["Corriente máxima", f"{max_current:.2f} A"],
                ["Voltaje mínimo", f"{min_voltage:.2f} V"],
                ["Factor de potencia promedio", f"{avg_pf:.2f}"],
            ],
        },
        {
            "title": "Últimas lecturas del despliegue",
            "headers": ["Fecha", "Nodo", "kW", "A", "V", "FP", "Hz"],
            "rows": preview_rows or [["Sin lecturas", "-", "-", "-", "-", "-", "-"]],
        },
    ]

    return payload


def deployment_real_period(db, deployment_id: int):
    first_ts, last_ts, count = (
        db.query(
            func.min(EnergyReading.timestamp),
            func.max(EnergyReading.timestamp),
            func.count(EnergyReading.id),
        )
        .filter(EnergyReading.deployment_id == deployment_id)
        .first()
    )

    return first_ts, last_ts, int(count or 0)


def fmt_dt(value):
    return value.strftime("%Y-%m-%d %H:%M") if value else None


def deployment_xlsx_response(db, deployment_id: int):
    deployment = db.query(Deployment).filter(Deployment.id == deployment_id).first()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    rows = (
        db.query(EnergyReading)
        .filter(EnergyReading.deployment_id == deployment_id)
        .order_by(EnergyReading.timestamp.asc())
        .all()
    )

    wb = Workbook()
    ws = wb.active
    ws.title = "Readings"

    ws.append(
        [
            "deployment_id",
            "node",
            "building",
            "timestamp",
            "voltage",
            "current",
            "power_kw",
            "energy_delta_kwh",
            "meter_energy_kwh",
            "power_factor",
            "frequency_hz",
            "tariff_period",
            "cost_mxn",
        ]
    )

    energy_by_id = _deployment_energy(db, rows)

    for r in rows:
        delta = energy_by_id.get(r.id, 0.0)

        cost_info = estimate_reading_cost(db, r.timestamp, delta)

        ws.append(
            [
                deployment.id,
                deployment.node.code,
                deployment.building.name,
                r.timestamp.isoformat() if r.timestamp else "",
                r.voltage,
                r.current,
                r.power_kw,
                delta,
                r.meter_energy_kwh,
                r.power_factor,
                r.frequency_hz,
                cost_info["period_name"],
                cost_info["cost_mxn"],
            ]
        )

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    filename = f"deployment_{deployment.id}_{deployment.node.code}_{deployment.building.name.replace(' ', '_')}.xlsx"

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/deployments")
def list_deployment_reports(db: Session = Depends(get_db)):
    deployments = db.query(Deployment).order_by(Deployment.id.desc()).all()

    result = []
    for d in deployments:
        real_start, real_end, count = deployment_real_period(db, d.id)
        result.append(
            {
                "id": d.id,
                "node_id": d.node.code,
                "building_name": d.building.name,
                "campus": d.building.campus.name if d.building.campus else None,
                "organizational_unit": (
                    d.building.organizational_unit.name if d.building.organizational_unit else None
                ),
                "electrical_panel": d.electrical_panel.name,
                "status": d.status,
                "start_date": d.start_date,
                "end_date": d.end_date,
                "real_start": fmt_dt(real_start),
                "real_end": fmt_dt(real_end),
                "reading_count": count,
                "pdf": f"/deployment/{d.id}.pdf",
                "csv": f"/deployment/{d.id}.csv",
                "xlsx": f"/deployment/{d.id}.xlsx",
            }
        )

    return result


@router.get("/deployment/{deployment_id}.pdf")
def deployment_pdf(deployment_id: int, db: Session = Depends(get_db)):
    payload = deployment_pdf_payload(db, deployment_id)
    return render_pdf(payload)


@router.get("/deployment/{deployment_id}.csv")
def deployment_csv(deployment_id: int, db: Session = Depends(get_db)):
    return deployment_readings_csv(db, deployment_id)


@router.get("/deployment/{deployment_id}.xlsx")
def deployment_xlsx(deployment_id: int, db: Session = Depends(get_db)):
    return deployment_xlsx_response(db, deployment_id)


@router.post("/deployment/{deployment_id}/generate")
def generate_deployment_report_files(deployment_id: int, db: Session = Depends(get_db)):
    deployment = db.query(Deployment).filter(Deployment.id == deployment_id).first()
    if not deployment:
        raise HTTPException(status_code=404, detail="Deployment not found")

    out_dir = "generated_reports"
    import os

    os.makedirs(out_dir, exist_ok=True)

    payload = deployment_pdf_payload(db, deployment_id)

    pdf_path = os.path.join(out_dir, f"deployment_{deployment_id}.pdf")
    csv_path = os.path.join(out_dir, f"deployment_{deployment_id}.csv")
    xlsx_path = os.path.join(out_dir, f"deployment_{deployment_id}.xlsx")

    html = Template(REPORT_TEMPLATE).render(**payload)
    HTML(string=html).write_pdf(pdf_path)

    rows = (
        db.query(EnergyReading)
        .filter(EnergyReading.deployment_id == deployment_id)
        .order_by(EnergyReading.timestamp.asc())
        .all()
    )

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "id",
                "timestamp",
                "node",
                "building",
                "voltage",
                "current",
                "power_kw",
                "energy_kwh",
                "power_factor",
                "frequency_hz",
            ]
        )
        for r in rows:
            writer.writerow(
                [
                    r.id,
                    r.timestamp.isoformat() if r.timestamp else "",
                    deployment.node.code,
                    deployment.building.name,
                    r.voltage,
                    r.current,
                    r.power_kw,
                    r.energy_kwh,
                    r.power_factor,
                    r.frequency_hz,
                ]
            )

    wb = Workbook()
    ws = wb.active
    ws.title = "Readings"
    ws.append(
        [
            "id",
            "timestamp",
            "node",
            "building",
            "voltage",
            "current",
            "power_kw",
            "energy_kwh",
            "power_factor",
            "frequency_hz",
        ]
    )
    for r in rows:
        ws.append(
            [
                r.id,
                r.timestamp.isoformat() if r.timestamp else "",
                deployment.node.code,
                deployment.building.name,
                r.voltage,
                r.current,
                r.power_kw,
                r.energy_kwh,
                r.power_factor,
                r.frequency_hz,
            ]
        )
    wb.save(xlsx_path)

    return {
        "ok": True,
        "deployment_id": deployment_id,
        "pdf_path": pdf_path,
        "csv_path": csv_path,
        "xlsx_path": xlsx_path,
        "reading_count": len(rows),
    }
