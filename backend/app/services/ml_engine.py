from app.services.platform_settings import get_thresholds
from datetime import datetime, timedelta
from collections import defaultdict
import numpy as np

from sklearn.cluster import KMeans
from sklearn.ensemble import IsolationForest, RandomForestRegressor
from sklearn.preprocessing import StandardScaler

from sqlalchemy import text as sa_text

from app.db import scope
from app.db.models import EnergyReading, Building
from app.services.cost_engine import estimate_reading_cost, to_local_time
from app.services import energy_aggregate as agg


#: Representative window for building clustering. Thirty days spans a full
#: billing cycle and several weekday/weekend cycles, so a building's profile is
#: characterised by how it currently behaves rather than by its entire history.
#: Scanning all history made this the single most expensive query on the
#: platform (118,652 rows for one building) and weighted a building's cluster by
#: how long it happened to have been monitored.
CLUSTER_WINDOW_DAYS = 30


def build_hourly_dataset(db, hours_back=168):
    """Per-reading feature rows for the ML models.

    Memoised per request: `random_forest_forecast` and
    `isolation_forest_anomalies` both need the same 168-hour dataset, and used
    to build it twice per /api/ai-center call.

    Deliberately NOT built on energy_aggregate: these rows carry electrical
    features (power, current, voltage, power factor, frequency) that hourly
    energy buckets do not, and this uses a different delta rule (no 100 kWh
    ceiling). Merging them would silently change the model feature space.
    """
    cache = db.info.setdefault("_energy_memo", {})
    key = ("build_hourly_dataset", hours_back)
    if key in cache:
        return cache[key]

    start = datetime.utcnow() - timedelta(hours=hours_back)

    # Column tuples, not ORM entities: these rows are read once to build a
    # feature matrix and never mutated or persisted, so the identity map,
    # instrumentation and lazy-loader machinery are pure overhead at this
    # volume. Same values, same order, same result.
    readings = (
        db.query(
            EnergyReading.id,
            EnergyReading.node_id,
            EnergyReading.building_id,
            EnergyReading.timestamp,
            EnergyReading.energy_kwh,
            EnergyReading.power_kw,
            EnergyReading.current,
            EnergyReading.voltage,
            EnergyReading.power_factor,
            EnergyReading.frequency_hz,
        )
        .filter(
            EnergyReading.context.in_(scope.analytic_contexts(db)),
            EnergyReading.timestamp >= start,
            EnergyReading.energy_kwh.isnot(None),
        )
        .order_by(EnergyReading.node_id.asc(), EnergyReading.timestamp.asc())
        .all()
    )

    # Energy per reading comes from the canonical service (ADR-0007). This used
    # to be `max(energy_kwh - prev, 0)` inline — the counter rule, without even
    # the reset guard — so the forecaster was trained on a different quantity
    # than the dashboard reported.
    energy_by_id = agg.energy_by_reading_id(db, start=start)

    rows = []

    for (reading_id, node_id, building_id, ts, energy_kwh, power_kw,
         current, voltage, power_factor, frequency_hz) in readings:
        delta_kwh = energy_by_id.get(reading_id, 0.0)

        if delta_kwh:
            local = to_local_time(ts)
            cost = estimate_reading_cost(db, ts, delta_kwh)["cost_mxn"]

            rows.append({
                "building_id": building_id,
                "node_id": node_id,
                "timestamp": ts,
                "hour": local.hour,
                "weekday": local.weekday(),
                "power_kw": float(power_kw or 0),
                "current": float(current or 0),
                "voltage": float(voltage or 0),
                "power_factor": float(power_factor or 0),
                "frequency_hz": float(frequency_hz or 0),
                "delta_kwh": float(delta_kwh),
                "cost_mxn": float(cost),
            })

    cache[key] = rows
    return rows


def random_forest_forecast(db):
    rows = build_hourly_dataset(db, 168)

    if not rows:
        return {
            "model": "RandomForestRegressor",
            "trained": False,
            "reason": "No hay lecturas suficientes para pronóstico.",
            "tomorrow_mxn": 0,
            "week_mxn": 0,
            "month_mxn": 0,
            "confidence": 0.0,
            "points": [
                {"label": "Real reciente", "value": 0, "type": "real"},
                {"label": "Mañana", "value": 0, "type": "forecast"},
                {"label": "Semana", "value": 0, "type": "forecast"},
                {"label": "Mes", "value": 0, "type": "forecast"},
            ],
        }

    hourly = defaultdict(float)
    for r in rows:
        local = to_local_time(r["timestamp"])
        key = local.strftime("%Y-%m-%d %H:00")
        hourly[key] += r["cost_mxn"]

    hourly_costs = list(hourly.values())
    today_cost = sum(r["cost_mxn"] for r in rows if to_local_time(r["timestamp"]).date() == to_local_time(datetime.utcnow()).date())

    observed_hours_today = len(set(
        to_local_time(r["timestamp"]).strftime("%Y-%m-%d %H")
        for r in rows
        if to_local_time(r["timestamp"]).date() == to_local_time(datetime.utcnow()).date()
    ))

    avg_hourly_cost = sum(hourly_costs[-24:]) / max(len(hourly_costs[-24:]), 1)
    fallback_tomorrow = avg_hourly_cost * 24

    if len(hourly_costs) < 12:
        tomorrow = fallback_tomorrow
        trained = False
        reason = f"Pronóstico conservador por promedio horario. Horas reales observadas hoy: {observed_hours_today}."
        confidence = 0.35
    else:
        X = []
        y = []

        sorted_hours = sorted(hourly.keys())
        for key in sorted_hours:
            dt = datetime.fromisoformat(key.replace(" ", "T"))
            X.append([dt.hour, dt.weekday()])
            y.append(hourly[key])

        X = np.array(X)
        y = np.array(y)

        model = RandomForestRegressor(
            n_estimators=120,
            random_state=42,
            min_samples_leaf=1,
        )
        model.fit(X, y)

        last_local = to_local_time(rows[-1]["timestamp"])
        preds = []

        for i in range(1, 25):
            future_hour = last_local + timedelta(hours=i)
            features = np.array([[future_hour.hour, future_hour.weekday()]])
            preds.append(max(float(model.predict(features)[0]), 0))

        rf_tomorrow = sum(preds)

        recent_daily_estimate = fallback_tomorrow

        lower = recent_daily_estimate * 0.65
        upper = recent_daily_estimate * 1.35
        tomorrow = min(max(rf_tomorrow, lower), upper)

        trained = True
        reason = f"Random Forest entrenado con {len(hourly_costs)} horas agregadas. Pronóstico limitado para evitar sobreproyección."
        avg_y = sum(y) / len(y)
        confidence = min(0.85, max(0.45, 1 - (np.std(y) / (avg_y + 1e-6))))

    week = tomorrow * 7
    month = tomorrow * 30

    return {
        "model": "RandomForestRegressor",
        "trained": trained,
        "reason": reason,
        "tomorrow_mxn": round(tomorrow, 2),
        "week_mxn": round(week, 2),
        "month_mxn": round(month, 2),
        "confidence": round(float(confidence), 2),
        "points": [
            {"label": "Real reciente", "value": round(today_cost, 2), "type": "real"},
            {"label": "Mañana", "value": round(tomorrow, 2), "type": "forecast"},
            {"label": "Semana", "value": round(week, 2), "type": "forecast"},
            {"label": "Mes", "value": round(month, 2), "type": "forecast"},
        ],
    }


def isolation_forest_anomalies(db):
    rows = build_hourly_dataset(db, 168)

    if len(rows) < 20:
        return {
            "model": "IsolationForest",
            "trained": False,
            "items": [],
            "reason": "Se requieren al menos 20 muestras para detección ML.",
        }

    X = np.array([
        [
            r["power_kw"],
            r["current"],
            r["voltage"],
            r["power_factor"],
            r["delta_kwh"],
            r["hour"],
            r["weekday"],
        ]
        for r in rows
    ])

    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)

    model = IsolationForest(
        n_estimators=120,
        contamination=0.08,
        random_state=42,
    )

    labels = model.fit_predict(Xs)
    scores = model.decision_function(Xs)

    anomalies = []

    for r, label, score in zip(rows, labels, scores):
        if label != -1:
            continue

        building = db.query(Building).filter(Building.id == r["building_id"]).first()
        building_name = building.name if building else "Sin edificio"

        if r["power_factor"] and r["power_factor"] < float(get_thresholds().get('minPowerFactor', 0.90)):
            title = "Factor de potencia bajo"
            detected = f"{r['power_factor']:.2f} FP"
            expected = ">0.90 FP"
            severity = "Info"
            color = "#818cf8"
        elif r["current"] > float(get_thresholds().get('maxCurrent', 200)):
            title = "Corriente elevada"
            detected = f"{r['current']:.2f} A"
            expected = "<200 A"
            severity = "Crítico"
            color = "#ef4444"
        elif r["hour"] < 6 and r["power_kw"] > 5:
            title = "Consumo nocturno anómalo"
            detected = f"{r['power_kw']:.2f} kW"
            expected = "<5 kW"
            severity = "Advertencia"
            color = "#f59e0b"
        else:
            title = "Patrón eléctrico atípico"
            detected = f"score {score:.3f}"
            expected = "comportamiento normal"
            severity = "Info"
            color = "#a78bfa"

        anomalies.append({
            "title": title,
            "building": building_name,
            "time": to_local_time(r["timestamp"]).strftime("%H:%M"),
            "detected": detected,
            "expected": expected,
            "severity": severity,
            "color": color,
            "model": "IsolationForest",
            "score": round(float(score), 4),
        })

    return {
        "model": "IsolationForest",
        "trained": True,
        "items": anomalies[-8:],
        "reason": f"Modelo entrenado con {len(rows)} muestras.",
    }


def kmeans_building_clusters(db):
    cluster_start = datetime.utcnow() - timedelta(days=CLUSTER_WINDOW_DAYS)
    buildings = db.query(Building).all()
    features = []
    metadata = []

    # Building profiles trained on bench data were the single worst source of
    # contamination in the audit: 123k noise-floor rows shared a building with
    # real load. Production contexts only (ADR-0003).
    #
    # Every feature here is a mean, a max or a standard deviation, so all of it
    # is computable in SQL for every building at once. This used to load every
    # reading for every building and reduce them in Python — the single most
    # expensive query on the platform.
    #
    # Population standard deviation (numpy's default, ddof=0) is recovered from
    # the first two moments: sqrt(E[x^2] - E[x]^2).
    contexts = scope.analytic_contexts(db)
    placeholders = ", ".join(f":c{i}" for i in range(len(contexts)))
    binds = {f"c{i}": code for i, code in enumerate(contexts)}
    binds["start"] = cluster_start.strftime("%Y-%m-%d %H:%M:%S.%f")

    stats = {
        row[0]: row
        for row in db.execute(sa_text(f"""
            SELECT building_id,
                   COUNT(*)                AS n_rows,
                   COUNT(power_kw)         AS n_power,
                   AVG(power_kw)           AS avg_power,
                   MAX(power_kw)           AS peak_power,
                   AVG(power_kw * power_kw) AS avg_power_sq,
                   AVG(current)            AS avg_current,
                   AVG(power_factor)       AS avg_pf
              FROM energy_readings
             WHERE context IN ({placeholders})
               AND timestamp >= :start
               AND building_id IS NOT NULL
             GROUP BY building_id
        """), binds).fetchall()
    }

    for b in buildings:
        row = stats.get(b.id)
        if row is None or row[1] < 5 or not row[2]:
            continue

        _, _, _, avg_power, peak_power, avg_power_sq, avg_current, avg_pf = row
        avg_power = float(avg_power or 0)
        peak_power = float(peak_power or 0)
        variance = max(float(avg_power_sq or 0) - avg_power * avg_power, 0.0)
        std_power = variance ** 0.5
        cv = std_power / avg_power if avg_power > 0 else 0

        features.append([avg_power, peak_power,
                         float(avg_current or 0), float(avg_pf or 0), cv])
        metadata.append({"id": b.id, "name": b.name})

    if len(features) < 2:
        return {
            "model": "KMeans",
            "trained": False,
            "clusters": [{
                "name": "Sin datos suficientes",
                "description": "Se requieren al menos 2 edificios con lecturas reales.",
                "buildings": [],
                "count": 0,
            }],
        }

    X = np.array(features)
    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)

    k = min(4, len(features))
    model = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels = model.fit_predict(Xs)

    grouped = defaultdict(list)

    for label, meta, row in zip(labels, metadata, features):
        avg_power, peak_power, avg_current, avg_pf, cv = row

        if avg_pf < float(get_thresholds().get('minPowerFactor', 0.90)):
            cluster_name = "Bajo Factor de Potencia"
        elif cv < 0.15:
            cluster_name = "Carga Constante"
        elif peak_power > 50:
            cluster_name = "Alta Demanda"
        else:
            cluster_name = "Uso Variable"

        grouped[cluster_name].append(meta["name"])

    clusters = [
        {
            "name": name,
            "description": f"Cluster ML generado con K-Means. {len(items)} edificio(s) clasificados.",
            "buildings": items,
            "count": len(items),
        }
        for name, items in grouped.items()
    ]

    return {
        "model": "KMeans",
        "trained": True,
        "clusters": clusters,
    }


def group_anomaly_events(items, max_gap_minutes=10):
    if not items:
        return []

    grouped = {}

    for item in items:
        key = (item.get("title"), item.get("building"))
        grouped.setdefault(key, []).append(item)

    result = []

    for (title, building), events in grouped.items():
        events = sorted(events, key=lambda x: x.get("time") or "")

        detected_values = []
        for e in events:
            raw = str(e.get("detected", ""))
            number = ""
            for ch in raw:
                if ch.isdigit() or ch == ".":
                    number += ch
                elif number:
                    break
            try:
                detected_values.append(float(number))
            except:
                pass

        if detected_values:
            min_value = min(detected_values)
            max_value = max(detected_values)
            detected_summary = f"{min_value:.2f}–{max_value:.2f}"
        else:
            detected_summary = events[-1].get("detected", "Sin dato")

        first = events[0]
        last = events[-1]

        result.append({
            "title": title,
            "building": building,
            "time": f"{first.get('time')}–{last.get('time')}" if first.get("time") != last.get("time") else first.get("time"),
            "detected": detected_summary,
            "expected": first.get("expected"),
            "severity": first.get("severity"),
            "color": first.get("color"),
            "model": first.get("model"),
            "score": first.get("score"),
            "count": len(events),
            "description": f"{len(events)} lecturas consecutivas o similares agrupadas como un solo evento.",
        })

    return result
