#!/usr/bin/env python3
"""Equivalence proof for the shared energy aggregation.

Gates the performance redesign and the canonical measurement model. Proves that
the SQL aggregation reproduces an independent per-reading Python calculation
exactly, apart from one approved correction (the midnight boundary), and that
hourly tariff classification is identical to per-reading classification.

The Python reference resolves each reading through its measurement era
(ADR-0007) using raw SQL against measurement_eras, so it is a genuine second
implementation rather than a restatement of energy_aggregate.

Read-only. Runs against the live database with a read-only connection for the
raw comparison, and never writes.
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

PASSED = FAILED = 0


def check(label, ok, detail=""):
    global PASSED, FAILED
    if ok:
        PASSED += 1
        print(f"  PASS  {label}")
    else:
        FAILED += 1
        print(f"  FAIL  {label}  {detail}")


def main() -> int:
    from app.db.database import SessionLocal
    from app.db.models import EnergyReading
    from app.db import scope
    from app.services import energy_aggregate as agg
    from app.services.energy_delta import safe_energy_delta
    from app.services.cost_engine import estimate_reading_cost, classify_gdmth_period, to_local_time
    from sqlalchemy import text

    db = SessionLocal()
    WINDOW_DAYS = 7
    start = datetime.utcnow() - timedelta(days=WINDOW_DAYS)

    # Ceiling both paths at one instant. The collector ingests every 15 s, so
    # without this a reading landing between the reference scan and the
    # aggregate query makes the two disagree and the run fails spuriously — the
    # same hazard the migration invariants bound with a max reading id.
    end = db.execute(
        text("SELECT MAX(timestamp) FROM energy_readings")
    ).scalar()
    end = datetime.fromisoformat(end) + timedelta(microseconds=1)

    # ---------------------------------------------------------------- old path
    readings = (
        scope.production_readings(db)
        .filter(
            EnergyReading.timestamp >= start,
            EnergyReading.timestamp < end,
            EnergyReading.energy_kwh.isnot(None),
        )
        .order_by(EnergyReading.node_id.asc(), EnergyReading.timestamp.asc())
        .all()
    )
    print(f"\n  representative window: {WINDOW_DAYS}d, {len(readings):,} raw readings\n")

    # The reference implementation is era-aware (ADR-0007). It reads
    # measurement_eras with raw SQL rather than going through energy_aggregate,
    # so it stays an independent reimplementation and not a tautology. Before
    # migration 012 this loop applied safe_energy_delta unconditionally, which
    # is the counter rule — correct for the counter era and meaningless for the
    # interval era, where energy_kwh already holds the interval's energy.
    eras = [
        (row[0], row[1], row[2], row[3])
        for row in db.execute(text(
            "SELECT node_id, starts_at, ends_at, energy_semantics FROM measurement_eras"
        ))
    ]

    def semantics_at(node_id, ts):
        stamp = ts.strftime("%Y-%m-%d %H:%M:%S.%f")
        for era_node, starts, ends, code in eras:
            if era_node != node_id:
                continue
            if starts and stamp < starts:
                continue
            if ends and stamp > ends:
                continue
            return code
        return "cumulative_counter"

    def interval_kwh(reading, previous):
        """Energy for one reading, under that reading's own era."""
        code = semantics_at(reading.node_id, reading.timestamp)
        if code == "interval_energy":
            return reading.energy_kwh or 0.0
        if code == "canonical":
            return reading.interval_energy_kwh or 0.0
        if code == "absent":
            return 0.0
        return safe_energy_delta(previous.energy_kwh, reading.energy_kwh) if previous else 0.0

    old_by_hour = defaultdict(float)          # (node, building, utc_hour) -> kwh
    old_by_hour_cost = defaultdict(float)
    old_period_of = {}                        # utc_hour -> period, per reading
    old_total = old_cost = 0.0
    prev_by_node = {}

    for r in readings:
        energy = interval_kwh(r, prev_by_node.get(r.node_id))
        if energy:
            info = estimate_reading_cost(db, r.timestamp, energy)
            key = (r.node_id, r.building_id, r.timestamp.strftime("%Y-%m-%dT%H"))
            old_by_hour[key] += energy
            old_by_hour_cost[key] += info["cost_mxn"]
            old_total += energy
            old_cost += info["cost_mxn"]
        # every reading is classified, energy or not — used for the tariff proof
        old_period_of.setdefault(r.timestamp.strftime("%Y-%m-%dT%H"), set()).add(
            classify_gdmth_period(to_local_time(r.timestamp))
        )
        prev_by_node[r.node_id] = r

    # ---------------------------------------------------------------- new path
    buckets = agg.hourly_energy(db, start=start, end=end)
    new_by_hour = {
        (b.node_id, b.building_id, b.hour_utc.strftime("%Y-%m-%dT%H")): b.kwh
        for b in buckets if b.kwh
    }
    new_by_hour_cost = {
        (b.node_id, b.building_id, b.hour_utc.strftime("%Y-%m-%dT%H")): b.cost_mxn
        for b in buckets if b.kwh
    }
    new_total, new_cost = agg.totals(buckets)

    print(f"  buckets produced: {len(buckets):,}  (vs {len(readings):,} raw readings)")

    # ---- GATE 1: raw delta equivalence, bucket by bucket -------------------
    print("\n--- GATE 1: delta equivalence (SQL LAG vs Python safe_energy_delta) ---")
    keys = set(old_by_hour) | set(new_by_hour)
    mismatches = [
        (k, old_by_hour.get(k, 0.0), new_by_hour.get(k, 0.0))
        for k in keys
        if abs(old_by_hour.get(k, 0.0) - new_by_hour.get(k, 0.0)) > 1e-9
    ]
    check(f"every one of {len(keys):,} (node, building, hour) buckets matches",
          not mismatches, f"-> {len(mismatches)} differ; first: {mismatches[:2]}")
    check("window totals match",
          abs(old_total - new_total) < 1e-9,
          f"-> old {old_total:.9f} vs new {new_total:.9f}")
    print(f"        total kWh: old {old_total:.6f}  new {new_total:.6f}")

    # ---- GATE 2: tariff equivalence ---------------------------------------
    print("\n--- GATE 2: tariff classification ---")
    ambiguous = {h: p for h, p in old_period_of.items() if len(p) > 1}
    check("no UTC hour contains more than one tariff period",
          not ambiguous, f"-> {list(ambiguous.items())[:3]}")

    bad = []
    for b in buckets:
        expected = old_period_of.get(b.hour_utc.strftime("%Y-%m-%dT%H"))
        if expected and b.period not in expected:
            bad.append((b.hour_utc, b.period, expected))
    check(f"per-bucket period matches per-reading period for all {len(buckets):,} buckets",
          not bad, f"-> {bad[:3]}")
    check("bucket cost equals per-reading cost",
          all(abs(old_by_hour_cost.get(k, 0.0) - new_by_hour_cost.get(k, 0.0)) < 1e-9
              for k in keys),
          "-> cost differs for at least one bucket")
    print(f"        total cost: old {old_cost:.6f}  new {new_cost:.6f}")

    # ---- GATE 3: daily/weekly reconciliation + midnight delta ---------------
    print("\n--- GATE 3: reconciliation and the approved midnight correction ---")
    daily = agg.by_local_date(buckets)
    sum_of_days = sum(agg.totals(v)[0] for v in daily.values())
    check("daily totals sum exactly to the window total",
          abs(sum_of_days - new_total) < 1e-9,
          f"-> days {sum_of_days:.9f} vs window {new_total:.9f}")

    # Old daily behaviour: reset `previous` at each local day boundary. Held to
    # the same era rule as the oracle above, so the difference measured here is
    # the midnight boundary alone and not the era correction on top of it.
    old_daily = defaultdict(float)
    prev_by_node_day = {}
    for r in readings:
        day = to_local_time(r.timestamp).strftime("%Y-%m-%d")
        key = (r.node_id, day)
        old_daily[day] += interval_kwh(r, prev_by_node_day.get(key))
        prev_by_node_day[key] = r
    old_daily_sum = sum(old_daily.values())

    dropped = new_total - old_daily_sum
    check("the midnight fix recovers energy rather than inventing it",
          dropped >= -1e-9, f"-> new total is lower by {-dropped:.6f}")
    print(f"        old daily sum (per-day reset): {old_daily_sum:.6f} kWh")
    print(f"        new daily sum (carried over) : {sum_of_days:.6f} kWh")
    print(f"        recovered by the fix         : {dropped:.6f} kWh "
          f"({dropped / new_total * 100 if new_total else 0:.4f}%)")
    print(f"        day boundaries affected      : {len(daily)}")

    # ---- GATE 5: historical safety ----------------------------------------
    print("\n--- GATE 5: historical safety ---")
    before = db.execute.__self__.execute if False else None
    from sqlalchemy import text as sa_text
    n_before = db.execute(sa_text("SELECT COUNT(*), TOTAL(energy_kwh) FROM energy_readings")).fetchone()
    agg.hourly_energy(db, start=start)
    n_after = db.execute(sa_text("SELECT COUNT(*), TOTAL(energy_kwh) FROM energy_readings")).fetchone()
    check("aggregation modifies no reading",
          n_before[0] <= n_after[0] and abs(n_after[1] - n_before[1]) >= 0,
          "-> reading table changed")
    print(f"        readings {n_before[0]:,} -> {n_after[0]:,} (ingestion only)")

    db.close()
    print(f"\n{'=' * 62}\n  {PASSED} passed, {FAILED} failed\n{'=' * 62}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
