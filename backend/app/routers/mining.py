from collections import defaultdict
from datetime import datetime, timedelta
from math import sqrt

from fastapi import APIRouter, Depends
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.db import scope
from app.db.database import get_db
from app.db.models import Building
from app.services import energy_aggregate as agg
from app.services.cost_engine import to_local_time
from app.services.platform_settings import get_thresholds

router = APIRouter()


def pearson(xs, ys):
    n = min(len(xs), len(ys))
    if n < 3:
        return None

    xs = xs[:n]
    ys = ys[:n]

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = sqrt(sum((x - mean_x) ** 2 for x in xs))
    den_y = sqrt(sum((y - mean_y) ** 2 for y in ys))

    if den_x == 0 or den_y == 0:
        return None

    return num / (den_x * den_y)


@router.get("")
def mining_analytics(db: Session = Depends(get_db)):
    start = datetime.utcnow() - timedelta(days=7)

    buildings = db.query(Building).all()
    building_results = []

    # Energy comes from the canonical service, never from a local delta: this
    # endpoint used to difference energy_kwh itself, which is the counter rule
    # and is wrong for the interval era (ADR-0007). Power and power factor are
    # instantaneous and still read per reading below.
    buckets_by_building = agg.by_building(agg.hourly_energy(db, start=start))

    # Power and power-factor statistics as one grouped aggregate. This used to
    # load every reading of every building into ORM objects — 33,000 rows per
    # request, materialised only to average them. Population variance comes from
    # E[p^2] - E[p]^2, which is what the Python loop computed.
    contexts = scope.analytic_contexts(db)
    stats_by_building = {
        row[0]: row
        for row in db.execute(
            sa_text(f"""
                SELECT building_id,
                       COUNT(*)                  AS samples,
                       AVG(power_kw)             AS avg_power,
                       MAX(power_kw)             AS peak_power,
                       AVG(power_factor)         AS avg_pf,
                       AVG(power_kw * power_kw)  AS avg_power_sq
                  FROM energy_readings
                 WHERE context IN ({", ".join(f":c{i}" for i in range(len(contexts)))})
                   AND timestamp >= :start
                   AND energy_kwh IS NOT NULL
                 GROUP BY building_id
                """),
            {**{f"c{i}": code for i, code in enumerate(contexts)}, "start": start},
        )
    }

    for building in buildings:
        stats = stats_by_building.get(building.id)
        sample_count = int(stats[1]) if stats else 0

        if sample_count < 2:
            building_results.append(
                {
                    "id": building.id,
                    "name": building.name,
                    "campus": building.campus.name,
                    "organizational_unit": building.organizational_unit.name,
                    "status": "insufficient_data",
                    "samples": sample_count,
                    "total_kwh": 0,
                    "avg_power_kw": 0,
                    "peak_power_kw": 0,
                    "night_kwh": 0,
                    "avg_pf": 0,
                    "cluster": "Sin datos suficientes",
                    "cluster_reason": "Se requieren al menos 2 lecturas reales.",
                }
            )
            continue

        building_buckets = buckets_by_building.get(building.id, [])
        total_kwh = agg.totals(building_buckets)[0]
        night_kwh = agg.totals([b for b in building_buckets if b.local_hour_of_day < 6])[0]

        avg_power = float(stats[2] or 0)
        peak_power = float(stats[3] or 0)
        avg_pf = float(stats[4] or 0)

        # Population variance, the same quantity the per-reading loop computed.
        # Clamped at zero: floating-point cancellation can make E[p^2] - E[p]^2
        # very slightly negative when every sample is near-identical.
        variance = max(float(stats[5] or 0) - avg_power**2, 0.0)
        std_power = sqrt(variance)
        cv = std_power / avg_power if avg_power > 0 else 0

        night_ratio = night_kwh / total_kwh if total_kwh > 0 else 0

        if avg_pf and avg_pf < float(get_thresholds().get("minPowerFactor", 0.90)):
            cluster = "Bajo Factor de Potencia"
            reason = f"Factor de potencia promedio {avg_pf:.2f}, menor al umbral configurado."
        elif night_ratio > 0.25:
            cluster = "Consumo Nocturno Alto"
            reason = f"{night_ratio * 100:.1f}% del consumo ocurrió entre 00:00 y 06:00."
        elif cv < 0.15 and sample_count >= 20:
            cluster = "Carga Constante"
            reason = f"Variación baja de carga; CV={cv:.2f}."
        elif peak_power > 50:
            cluster = "Alta Demanda"
            reason = f"Pico de demanda detectado: {peak_power:.2f} kW."
        else:
            cluster = "Uso Variable"
            reason = "Patrón variable detectado con lecturas reales."

        building_results.append(
            {
                "id": building.id,
                "name": building.name,
                "campus": building.campus.name,
                "organizational_unit": building.organizational_unit.name,
                "status": "ok",
                "samples": sample_count,
                "total_kwh": round(total_kwh, 4),
                "avg_power_kw": round(avg_power, 4),
                "peak_power_kw": round(peak_power, 4),
                "night_kwh": round(night_kwh, 4),
                "night_ratio_pct": round(night_ratio * 100, 2),
                "avg_pf": round(avg_pf, 4),
                "power_cv": round(cv, 4),
                "cluster": cluster,
                "cluster_reason": reason,
            }
        )

    monitored = [b for b in building_results if b["status"] == "ok"]

    clusters = defaultdict(list)
    for b in monitored:
        clusters[b["cluster"]].append(b)

    cluster_cards = [
        {
            "name": name,
            "description": f"{len(items)} edificio(s) clasificados con datos reales.",
            "buildings": [item["name"] for item in items],
            "count": len(items),
        }
        for name, items in clusters.items()
    ]

    if not cluster_cards:
        cluster_cards = [
            {
                "name": "Sin datos suficientes",
                "description": "Aún no hay suficientes edificios monitoreados para clustering.",
                "buildings": [],
                "count": 0,
            }
        ]

    correlation = {
        "available": False,
        "title": "Correlación no disponible",
        "message": "Se requieren al menos 2 edificios con lecturas reales.",
        "coefficient": None,
        "series_a": [],
        "series_b": [],
    }

    contexts = scope.analytic_contexts(db)

    if len(monitored) >= 2:
        a = monitored[0]
        b = monitored[1]

        def hourly_power(building_id):
            """Mean power per local hour, aggregated in SQL.

            Deliberately not part of energy_aggregate: this averages an
            instantaneous quantity, where that module differences a cumulative
            counter. Same principle applied separately — group in SQL, return
            hours instead of readings.

            Grouping by UTC hour is equivalent to grouping by local hour because
            the local offset is a whole number of hours, so each UTC hour maps
            onto exactly one local hour and the mean is over the same set.
            """
            placeholders = ", ".join(f":c{i}" for i in range(len(contexts)))
            binds = {f"c{i}": code for i, code in enumerate(contexts)}
            binds.update({"bid": building_id, "start": start})

            rows = db.execute(
                sa_text(f"""
                SELECT strftime('%Y-%m-%dT%H', timestamp) AS h, AVG(power_kw)
                  FROM energy_readings
                 WHERE context IN ({placeholders})
                   AND building_id = :bid
                   AND timestamp >= :start
                   AND power_kw IS NOT NULL
                 GROUP BY h
            """),
                binds,
            ).fetchall()

            out = {}
            for hour_utc, avg_kw in rows:
                local = to_local_time(datetime.strptime(hour_utc, "%Y-%m-%dT%H"))
                out[local.strftime("%Y-%m-%d %H:00")] = float(avg_kw or 0)
            return out

        sa = hourly_power(a["id"])
        sb = hourly_power(b["id"])
        common = sorted(set(sa.keys()) & set(sb.keys()))

        xs = [sa[k] for k in common]
        ys = [sb[k] for k in common]
        coeff = pearson(xs, ys)

        correlation = {
            "available": coeff is not None,
            "title": f"Correlación {a['name']} vs {b['name']}",
            "message": (
                "Correlación calculada con potencia horaria real."
                if coeff is not None
                else "No hay suficientes puntos horarios comunes."
            ),
            "coefficient": round(coeff, 4) if coeff is not None else None,
            "series_a": [{"label": k, "value": round(sa[k], 4)} for k in common[-12:]],
            "series_b": [{"label": k, "value": round(sb[k], 4)} for k in common[-12:]],
            "building_a": a["name"],
            "building_b": b["name"],
        }

    patterns = []

    for b in monitored:
        if b["avg_pf"] and b["avg_pf"] < float(get_thresholds().get("minPowerFactor", 0.90)):
            patterns.append(
                {
                    "title": "Bajo factor de potencia",
                    "building": b["name"],
                    "description": f"PF promedio {b['avg_pf']:.2f}. Revisar cargas inductivas o compensación.",
                    "severity": "medium",
                }
            )

        if b["night_ratio_pct"] > 25:
            patterns.append(
                {
                    "title": "Consumo nocturno alto",
                    "building": b["name"],
                    "description": f"{b['night_ratio_pct']:.1f}% del consumo ocurrió entre 00:00 y 06:00.",
                    "severity": "warning",
                }
            )

        if b["peak_power_kw"] > 50:
            patterns.append(
                {
                    "title": "Pico de demanda",
                    "building": b["name"],
                    "description": f"Pico detectado de {b['peak_power_kw']:.2f} kW.",
                    "severity": "high",
                }
            )

        if b["power_cv"] < 0.15 and b["samples"] >= 20:
            patterns.append(
                {
                    "title": "Carga constante",
                    "building": b["name"],
                    "description": f"Variación baja de potencia; CV={b['power_cv']:.2f}.",
                    "severity": "info",
                }
            )

    if not patterns:
        patterns.append(
            {
                "title": "Sin patrones concluyentes",
                "building": "Sistema",
                "description": "Se requieren más lecturas o más edificios monitoreados.",
                "severity": "info",
            }
        )

    insights = [
        {
            "priority": "medium" if p["severity"] in ["medium", "warning"] else "info",
            "category": "Minería de Datos",
            "building": p["building"],
            "title": p["title"],
            "description": p["description"],
        }
        for p in patterns[:4]
    ]

    return {
        "buildings": building_results,
        "clusters": cluster_cards,
        "correlation": correlation,
        "patterns": patterns[:8],
        "insights": insights,
    }
