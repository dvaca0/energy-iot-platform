"""Canonical energy-delta aggregation.

Every analytics endpoint used to do the same thing: load every reading in a
window, walk it in Python computing an energy delta against the previous reading
of the same node, classify each delta into a tariff period, and multiply. Seven
endpoints did it with overlapping windows, so one dashboard page load pulled
446,836 rows out of a 243,065-row table and ran ~90,000 tariff classifications.

This module does it once, in SQL, and hands back hourly buckets.

Two facts make that exact rather than approximate:

**The delta rule is a window function.** For a cumulative-counter era,
``safe_energy_delta`` keeps a delta only when it is positive and at most 100 kWh
— the guard against a lifetime counter resetting or a first-reading-after-
deployment jump. ``LAG`` reproduces the Python loop exactly, including the first
reading of a window contributing nothing.

**Not every era is a counter.** ``energy_kwh`` has carried two meanings
(ADR-0007): a cumulative register until 2026-07-03, and per-interval energy
since 2026-07-25. Differencing the second produces noise — it is what made the
KPIs read ~400x low. The era is resolved from ``measurement_eras`` per reading,
so both encodings are read correctly and no historical row was modified. This
module is the only code permitted to read ``energy_kwh``.

**The tariff period is constant within a local hour.** Every boundary in
``classify_gdmth_period`` is a whole hour (0, 6, 7, 8, 18, 19, 20, 21, 22), and
weekday and summer-schedule are constant within a day. So classification can run
once per bucket instead of once per reading, with identical results — verified
row-by-row in ``tests/test_energy_aggregate.py``.

One deliberate correction is folded in. ``metrics/daily`` used to reset its
"previous reading" at each local midnight, so energy consumed between the last
reading of one day and the first of the next was dropped entirely — 0.15% of a
7-day window, attributed to no day at all. Here the delta carries across
midnight and is assigned to the local hour of the *later* reading, so daily,
weekly and monthly figures reconcile from one calculation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import scope
from app.services.cost_engine import classify_gdmth_period, get_tariff_rate

LOCAL_TZ = ZoneInfo("America/Mexico_City")

#: Same ceiling as ``safe_energy_delta``. A larger jump is a counter reset or a
#: first reading after deployment, not an hour's consumption.
MAX_REASONABLE_DELTA_KWH = 100.0


@dataclass(frozen=True)
class HourBucket:
    """Energy attributed to one (node, building, local hour)."""

    node_id: int
    building_id: int | None
    hour_utc: datetime          # start of the UTC hour
    local_hour: datetime        # same instant, in platform-local time
    kwh: float
    samples: int
    period: str                 # base | intermediate | peak
    price_per_kwh: float
    cost_mxn: float

    @property
    def local_date(self) -> str:
        return self.local_hour.strftime("%Y-%m-%d")

    @property
    def local_hour_of_day(self) -> int:
        return self.local_hour.hour


# The interpretation itself. Every energy figure the platform reports — hourly,
# per reading, dashboard, AI, mining, reports, exports — comes out of this one
# CTE. It is the ONLY place that reads energy_readings.energy_kwh (ADR-0007).
#
# Two historical encodings coexist and neither may be rewritten:
#
#   cumulative_counter  energy_kwh is a lifetime register -> difference
#                       consecutive readings, keeping only a positive delta
#                       within the guard bound (a larger jump is a counter
#                       reset or a first reading after deployment, not
#                       consumption)
#   interval_energy     energy_kwh already IS the energy for this sample -> take
#                       it as-is; differencing it produces noise
#   canonical           the collector populates interval_energy_kwh directly
#   absent              the node reports no energy at all
#
# The era is joined from measurement_eras, so no reading carries its own
# semantics and no historical row was ever modified to add one.
_RESOLVED_CTE = """
WITH windowed AS (
    SELECT
        r.id,
        r.node_id,
        r.building_id,
        r.timestamp,
        r.energy_kwh,
        r.interval_energy_kwh,
        COALESCE(sem.code, 'cumulative_counter')      AS semantics,
        LAG(r.energy_kwh) OVER (
            PARTITION BY r.node_id, COALESCE(sem.code, 'cumulative_counter')
            ORDER BY r.timestamp
        ) AS previous_kwh
    FROM energy_readings r
    LEFT JOIN measurement_eras e
           ON e.node_id = r.node_id
          AND (e.starts_at IS NULL OR r.timestamp >= e.starts_at)
          AND (e.ends_at   IS NULL OR r.timestamp <= e.ends_at)
    LEFT JOIN energy_semantics sem ON sem.code = e.energy_semantics
    WHERE r.context IN ({contexts})
      {time_filter}
),
resolved AS (
    SELECT
        id, node_id, building_id, timestamp, semantics,
        CASE semantics
            WHEN 'canonical' THEN COALESCE(interval_energy_kwh, 0)
            WHEN 'interval_energy' THEN COALESCE(energy_kwh, 0)
            WHEN 'absent' THEN 0
            ELSE CASE
                WHEN previous_kwh IS NULL OR energy_kwh IS NULL THEN 0
                WHEN energy_kwh - previous_kwh > 0
                 AND energy_kwh - previous_kwh <= :max_delta
                THEN energy_kwh - previous_kwh
                ELSE 0
            END
        END AS kwh
    FROM windowed
)
"""

_SQL = _RESOLVED_CTE + """
SELECT
    node_id,
    building_id,
    strftime('%Y-%m-%dT%H', timestamp) AS hour_utc,
    SUM(kwh) AS kwh,
    COUNT(*) AS samples
FROM resolved
GROUP BY node_id, building_id, hour_utc
ORDER BY hour_utc, node_id
"""

_SQL_PER_READING = _RESOLVED_CTE + """
SELECT id, node_id, building_id, timestamp, semantics, kwh
FROM resolved
ORDER BY node_id, timestamp
"""

# Just the two columns needed to key energy by reading id. Callers that only
# want the lookup should not pay for parsing a timestamp and allocating a
# dataclass per reading — at 33,000 readings (the AI feature window) that
# allocation cost dominated the query itself.
_SQL_ID_KWH = _RESOLVED_CTE + """
SELECT id, kwh FROM resolved WHERE kwh != 0
"""


def _assert_whole_hour_offset(moment: datetime) -> None:
    """Bucketing by UTC hour is only sound if the local offset is whole hours.

    America/Mexico_City has been a fixed UTC-6 since Mexico abolished DST in
    2022, so this holds — but it is asserted rather than assumed, because a
    half-hour zone would silently split buckets across two local hours and
    misclassify the tariff period.
    """
    offset = moment.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ).utcoffset()
    if offset is None or offset % timedelta(hours=1) != timedelta(0):
        raise RuntimeError(
            f"local timezone offset {offset} is not a whole number of hours; "
            "hourly bucketing would split a local hour across two buckets"
        )


def _memo(db: Session, key, build):
    """Memoise within one request.

    ``get_db`` yields a Session per request and closes it afterwards, so the
    cache lifetime is exactly the request lifetime. There is no cross-request
    staleness to reason about and nothing to invalidate — which is the only
    reason caching is acceptable here at all.
    """
    cache = db.info.setdefault("_energy_memo", {})
    if key not in cache:
        cache[key] = build()
    return cache[key]


def _bind(sql: str, contexts: tuple[str, ...], start, end, deployment_id=None) -> tuple[str, dict]:
    """Fill the context list and row filter, returning SQL plus bind values.

    The filter must be built with binds rather than interpolation: `timestamp`
    and `deployment_id` are user-influenced values on some call paths.

    ``deployment_id`` narrows the aggregate to the readings one deployment owns.
    It restricts the rows the window function sees, so the first reading of the
    deployment contributes no delta — the same rule that already applies at the
    start of any window, and the reason a deployment's first sample is not
    counted twice when it also opens a time window.
    """
    binds: dict[str, object] = {"max_delta": MAX_REASONABLE_DELTA_KWH}
    context_binds = []
    for i, code in enumerate(contexts):
        key = f"ctx{i}"
        binds[key] = code
        context_binds.append(f":{key}")

    filters = []
    if start is not None:
        filters.append("AND r.timestamp >= :start")
        binds["start"] = start.strftime("%Y-%m-%d %H:%M:%S.%f")
    if end is not None:
        filters.append("AND r.timestamp < :end")
        binds["end"] = end.strftime("%Y-%m-%d %H:%M:%S.%f")
    if deployment_id is not None:
        filters.append("AND r.deployment_id = :deployment_id")
        binds["deployment_id"] = int(deployment_id)

    return sql.format(contexts=", ".join(context_binds), time_filter=" ".join(filters)), binds


@dataclass(frozen=True)
class ReadingEnergy:
    """Canonical interval energy for one individual reading."""

    reading_id: int
    node_id: int
    building_id: int | None
    timestamp: datetime
    kwh: float
    semantics: str


def reading_energy(
    db: Session,
    start: datetime | None = None,
    end: datetime | None = None,
    contexts: str | list[str] | None = None,
) -> list[ReadingEnergy]:
    """Per-reading interval energy, under the same rule as ``hourly_energy``.

    For consumers that genuinely need row granularity — CSV exports, the data
    explorer, per-reading ML features, night-hour analysis that also inspects
    power. They must not recompute the delta themselves: that is what left the
    platform with several competing interpretations of ``energy_kwh``.

    Prefer ``hourly_energy`` where buckets suffice; this returns one row per
    reading and is correspondingly larger.
    """
    resolved = scope.resolve_contexts(db, contexts)
    if not resolved:
        return []

    memo_key = ("reading_energy", start, end, resolved)
    cached = db.info.get("_energy_memo", {}).get(memo_key)
    if cached is not None:
        return cached

    sql, binds = _bind(_SQL_PER_READING, resolved, start, end)
    rows = [
        ReadingEnergy(
            reading_id=row[0],
            node_id=row[1],
            building_id=row[2],
            timestamp=(row[3] if isinstance(row[3], datetime)
                       else datetime.fromisoformat(row[3])),
            kwh=float(row[5] or 0.0),
            semantics=row[4],
        )
        for row in db.execute(text(sql), binds)
    ]

    db.info.setdefault("_energy_memo", {})[memo_key] = rows
    return rows


def energy_by_reading_id(
    db: Session,
    start: datetime | None = None,
    end: datetime | None = None,
    contexts: str | list[str] | None = None,
) -> dict[int, float]:
    """``{reading id: canonical interval kWh}``.

    Lets a caller that has already loaded ORM readings attach the canonical
    energy to each one by primary key, instead of differencing them itself.
    Readings resolving to zero are omitted; look them up with ``.get(id, 0.0)``.
    """
    resolved = scope.resolve_contexts(db, contexts)
    if not resolved:
        return {}

    memo_key = ("energy_by_reading_id", start, end, resolved)
    cached = db.info.get("_energy_memo", {}).get(memo_key)
    if cached is not None:
        return cached

    sql, binds = _bind(_SQL_ID_KWH, resolved, start, end)
    out = {row[0]: float(row[1]) for row in db.execute(text(sql), binds)}

    db.info.setdefault("_energy_memo", {})[memo_key] = out
    return out


def hourly_energy(
    db: Session,
    start: datetime | None = None,
    end: datetime | None = None,
    contexts: str | list[str] | None = None,
    deployment_id: int | None = None,
) -> list[HourBucket]:
    """Energy delta per (node, building, hour), with tariff already applied.

    One SQL statement. Returns roughly ``nodes x hours`` rows — about 500 for a
    seven-day window, against tens of thousands of raw readings.

    ``start`` is inclusive, ``end`` exclusive. Omitting ``start`` scans all
    history, which is rarely what a caller wants.

    ``deployment_id`` restricts the aggregate to one deployment's readings.
    ``None`` — the default — keeps the fleet-wide behaviour every existing
    caller relies on, including readings no deployment has claimed.
    """
    resolved = scope.resolve_contexts(db, contexts)
    if not resolved:
        return []

    # deployment_id belongs in the memo key: without it a scoped call would be
    # served the fleet-wide result cached earlier in the same request.
    memo_key = ("hourly_energy", start, end, resolved, deployment_id)
    cached = db.info.get("_energy_memo", {}).get(memo_key)
    if cached is not None:
        return cached

    sql, binds = _bind(_SQL, resolved, start, end, deployment_id)
    rows = db.execute(text(sql), binds).fetchall()

    buckets: list[HourBucket] = []
    # Tariff classification is memoised per local hour: within one request the
    # same hour recurs once per node, and the period depends only on the hour.
    tariff_cache: dict[datetime, tuple[str, float]] = {}
    checked_offset = False

    for node_id, building_id, hour_utc_str, kwh, samples in rows:
        hour_utc = datetime.strptime(hour_utc_str, "%Y-%m-%dT%H")

        if not checked_offset:
            _assert_whole_hour_offset(hour_utc)
            checked_offset = True

        local_hour = hour_utc.replace(tzinfo=timezone.utc).astimezone(LOCAL_TZ)

        cached = tariff_cache.get(local_hour)
        if cached is None:
            period = classify_gdmth_period(local_hour)
            cached = (period, get_tariff_rate(db, period))
            tariff_cache[local_hour] = cached
        period, price = cached

        kwh = float(kwh or 0.0)
        buckets.append(
            HourBucket(
                node_id=node_id,
                building_id=building_id,
                hour_utc=hour_utc,
                local_hour=local_hour,
                kwh=kwh,
                samples=int(samples or 0),
                period=period,
                price_per_kwh=price,
                cost_mxn=kwh * price,
            )
        )

    db.info.setdefault("_energy_memo", {})[memo_key] = buckets
    return buckets


# ------------------------------------------------------------------ reducers
def totals(buckets: list[HourBucket]) -> tuple[float, float]:
    """(kWh, cost) over a set of buckets."""
    return (
        sum(b.kwh for b in buckets),
        sum(b.cost_mxn for b in buckets),
    )


def between(buckets: list[HourBucket], start: datetime, end: datetime | None = None) -> list[HourBucket]:
    """Buckets whose UTC hour falls in [start, end).

    Bucketing is hourly, so a window boundary that falls mid-hour includes the
    whole hour containing it. Callers that need exact boundaries should request
    a narrower window from ``hourly_energy`` instead.
    """
    lo = start.replace(minute=0, second=0, microsecond=0)
    return [
        b for b in buckets
        if b.hour_utc >= lo and (end is None or b.hour_utc < end)
    ]


def by_local_date(buckets: list[HourBucket]) -> dict[str, list[HourBucket]]:
    out: dict[str, list[HourBucket]] = {}
    for b in buckets:
        out.setdefault(b.local_date, []).append(b)
    return out


def by_local_hour_of_day(buckets: list[HourBucket]) -> dict[int, list[HourBucket]]:
    out: dict[int, list[HourBucket]] = {}
    for b in buckets:
        out.setdefault(b.local_hour_of_day, []).append(b)
    return out


def by_building(buckets: list[HourBucket]) -> dict[int | None, list[HourBucket]]:
    out: dict[int | None, list[HourBucket]] = {}
    for b in buckets:
        out.setdefault(b.building_id, []).append(b)
    return out


def by_period(buckets: list[HourBucket]) -> dict[str, list[HourBucket]]:
    out: dict[str, list[HourBucket]] = {}
    for b in buckets:
        out.setdefault(b.period, []).append(b)
    return out
