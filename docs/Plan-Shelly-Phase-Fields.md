# Plan — preserving the Shelly Pro 3EM fields we currently discard

> [!NOTE]
> **Superseded on 2026-08-18.** The capture this plan was blocked on arrived,
> and steps 0, 1, 2, 4, 5 and 6 are **implemented** — migration 015, both ingest
> routes, the contract, the API and the page. The verified field matrix now
> lives in [Live-Monitoring.md](Live-Monitoring.md); prefer it over the
> speculative table below, which is retained only as a record of what was
> assumed before the device was read.
>
> **Step 3, the on-node collector change, is NOT done.** SSH to all three nodes
> is refused from the backend host, so nothing on a Pi was touched. Until it
> lands, every new column is NULL and the interface reports *no disponible* —
> which is the correct rendering of "measured by the meter, not yet forwarded".
>
> Two things in the table below turned out to be **wrong** against the real
> device and were dropped: `errors` / `a_errors` meter-fault flags, which this
> firmware does not return, and the assumption that `total_aprt_power` was not
> already being parsed — it was.

The live-monitoring audit found that the meter publishes per-phase active power,
per-phase apparent power, per-phase power factor, per-phase frequency, total
apparent power and neutral current in the *same RPC response the collector
already parses*, and that all of them are dropped at the edge because the
payload contract does not carry them and `energy_readings` has no columns for
them. See [Live-Monitoring.md](Live-Monitoring.md) for the inventory.

This is the plan to close that gap end to end.

---

## Step 0 — capture the real RPC response first

**Nothing below may be built against an unverified field list.**

What is verified today, by reading `/opt/energy-node/app/collector.py` on N002
on 2026-08-13:

```python
SHELLY_EM_URL  = f"http://{CONFIG['SHELLY_IP']}/rpc/EM.GetStatus?id=0"
SHELLY_SYS_URL = f"http://{CONFIG['SHELLY_IP']}/rpc/Sys.GetStatus"
```

The device is a **Shelly Pro 3EM** (N001, 120 A CT) / **Pro 3EM 400 A** (N002),
on the private segment `192.168.50.0/24` with the meter at `.10` and the node at
`.2`. The meter is reachable **only from the Pi** — not from the backend host.

Independent corroboration that these quantities exist upstream:
`deployment_week.csv` on N003 (22.6 MB, 120,103 rows) carries the header
`captured_at, V_a, I_a, P_a, S_a, PF_a, f, … total_P, total_S, total_I` — the
prototype line already recorded per-phase active power, apparent power and power
factor.

What is **not** verified is the exact key set this firmware returns. SSH to all
three nodes was closed from the backend host on 2026-08-17 (ports 22/2222
refused on every public NAT address, while N001 kept heartbeating outbound), so
the response could not be captured. The field names below are the documented
Gen2 `EM` component contract and must be confirmed before a single column is
created:

```bash
# on the node, not the backend host
curl -s http://192.168.50.10/rpc/EM.GetStatus?id=0 | python3 -m json.tool
curl -s http://192.168.50.10/rpc/EMData.GetStatus?id=0 | python3 -m json.tool
curl -s http://192.168.50.10/rpc/Shelly.GetDeviceInfo | python3 -m json.tool
```

Record the output verbatim in `docs/Fleet-Manifest.md`. **Any key below that the
device does not actually return is dropped from the plan rather than stored as
null-forever.**

### Evidence actually held (searched 2026-08-17, read-only)

| Source | What it establishes | What it does not |
|---|---|---|
| `collector.py` on N002, read 2026-08-13 | The endpoint: `/rpc/EM.GetStatus?id=0` | Which keys it reads out of the response |
| `node.env` on N002 | Meter at `192.168.50.10`, `shellypro3em400-ecc9ffe730f4` | — |
| `docs/Fleet-Manifest.md` | N001 is `shellypro3em-a4f00fd05558` (Pro 3EM, 120 A CT) | — |
| `THESIS_ADS_VALIDATION_RECOVERY.md` | A bench script consumed `a_current`, `b_current`, `c_current` from a Shelly at `192.168.1.190` | That is three keys on a *different* bench network |
| `monitoring/evidence/node03-audit-*.md` | N003's `poller.py` logs `Stored \| A: 0.0W B: 0.0W C: 0.0W` — per-phase **watts** are being read | The key names, and this is N003's meter, not N001's |
| `deployment_week.csv` on N003 | Header carries `P_a`, `S_a`, `PF_a`, `total_P`, `total_S` | CSV column names, not RPC key names |

Per-phase active power is demonstrably being read on at least one node today.
The exact key names on the production firmware are not recorded anywhere.

### Expected `EM.GetStatus` fields

| Key | Quantity | Unit | Plan |
|---|---|---|---|
| `a_voltage`, `b_voltage`, `c_voltage` | Phase voltage | V | already stored |
| `a_current`, `b_current`, `c_current` | Phase current | A | already stored |
| `total_current` | Total current | A | already stored |
| `total_act_power` | Total active power | W | already stored as `power_kw` |
| `a_act_power`, `b_act_power`, `c_act_power` | **Active power per phase** | W | **add** |
| `a_aprt_power`, `b_aprt_power`, `c_aprt_power` | **Apparent power per phase** | VA | **add** |
| `total_aprt_power` | **Total apparent power** | VA | **add** |
| `a_pf`, `b_pf`, `c_pf` | **Power factor per phase** | — | **add** |
| `a_freq`, `b_freq`, `c_freq` | **Frequency per phase** | Hz | **add** |
| `n_current` | **Neutral current** | A | **add if non-null** |
| `errors`, `a_errors`, `b_errors`, `c_errors` | Meter fault flags | — | **add** — see below |
| `user_calibrated_phase` | Calibration state | — | not a measurement; skip |

**Reactive power is not in this list, and that is not an omission.** The Pro 3EM
`EM` component does not report Q. It could be computed as √(S² − P²), but that is
arithmetic on two measurements, not a third measurement, and this platform does
not store derived quantities beside measured ones. If reactive power is wanted,
it is a *display-time* derivation, labelled as such — never a column.

`n_current` is null on installations without a neutral CT. Store it nullable and
let the frontend's existing availability rule hide it; do not coerce it to 0.

`errors` / `a_errors` are worth adding precisely because they are the meter's own
statement about measurement validity — the thing that currently has no
representation at all, and the reason a dead ADC on N003 could only be inferred
from the values themselves.

### Optional, second RPC — `EMData.GetStatus`

Per-phase cumulative energy registers (`a_total_act_energy`,
`a_total_act_ret_energy`, …). These are **registers**, not interval energy, and
belong under the existing `meter_energy_kwh` discipline: reconciliation only,
never differenced by an analytic. Defer to a second phase; it costs a second HTTP
round trip per sample.

---

## Step 1 — the payload contract

`backend/docs/collector-contract.md` is normative;
[Collector.md](Collector.md) explains it. Both change together.

The new fields are **optional**, exactly as `phase_*_voltage` already is. That
is what keeps N003's `poller.py` and any older collector working unchanged —
they simply keep sending what they send.

```json
{
  "node_id": "N001",
  "timestamp": "2026-08-18T02:15:00Z",

  "power_kw": 12.4,
  "interval_energy_kwh": 0.0517,
  "interval_seconds": 15.0,
  "energy_source": "counter_delta",

  "phase_a_voltage": 122.4, "phase_b_voltage": 124.6, "phase_c_voltage": 123.5,
  "phase_a_current": 39.176, "phase_b_current": 37.415, "phase_c_current": 35.907,

  "phase_a_power_kw": 4.412, "phase_b_power_kw": 4.398, "phase_c_power_kw": 4.361,
  "phase_a_apparent_kva": 4.795, "phase_b_apparent_kva": 4.662, "phase_c_apparent_kva": 4.434,
  "phase_a_power_factor": 0.920, "phase_b_power_factor": 0.943, "phase_c_power_factor": 0.983,
  "phase_a_frequency_hz": 60.0, "phase_b_frequency_hz": 60.0, "phase_c_frequency_hz": 60.0,

  "apparent_kva": 13.891,
  "neutral_current": null,
  "meter_errors": null
}
```

Two contract rules, both non-negotiable:

**Units are converted once, at the edge.** The Shelly reports watts and
volt-amperes; the platform's existing vocabulary is kW. The collector divides by
1000 so `phase_a_power_kw` is dimensionally consistent with `power_kw`. A column
named `_kw` that sometimes holds watts is the kind of ambiguity ADR-0007 exists
to prevent.

**Nothing is derived to fill a field.** If the meter did not return `a_pf`, the
collector sends nothing for it. It must not send `a_act_power / a_aprt_power`
computed locally — the whole point of adding these columns is that the meter's
own figure accounts for waveform distortion in a way arithmetic does not.

---

## Step 2 — the schema

One hand-rolled migration, in the established form (`backend/migrations/versions/`,
`.up.sql` + `.down.sql`, applied with
`venv/bin/python3 -m migrations.runner up`, which takes a backup, checks 16
invariants before and after, and auto-rolls-back).

`015_shelly_phase_detail.up.sql`:

```sql
-- description: per-phase power, apparent power, power factor and frequency from the Shelly Pro 3EM
-- waivers:
--
-- The meter has always measured these; the collector discarded them. ADD COLUMN
-- in SQLite is metadata-only, so no historical row is rewritten and every one
-- of the 314,000 existing readings keeps NULL — which is the truthful value.
-- They were never measured, and a backfill of any kind would be fabrication.

BEGIN IMMEDIATE;

ALTER TABLE energy_readings ADD COLUMN phase_a_power_kw       REAL;
ALTER TABLE energy_readings ADD COLUMN phase_b_power_kw       REAL;
ALTER TABLE energy_readings ADD COLUMN phase_c_power_kw       REAL;

ALTER TABLE energy_readings ADD COLUMN phase_a_apparent_kva   REAL;
ALTER TABLE energy_readings ADD COLUMN phase_b_apparent_kva   REAL;
ALTER TABLE energy_readings ADD COLUMN phase_c_apparent_kva   REAL;
ALTER TABLE energy_readings ADD COLUMN apparent_kva           REAL;

ALTER TABLE energy_readings ADD COLUMN phase_a_power_factor   REAL;
ALTER TABLE energy_readings ADD COLUMN phase_b_power_factor   REAL;
ALTER TABLE energy_readings ADD COLUMN phase_c_power_factor   REAL;

ALTER TABLE energy_readings ADD COLUMN phase_a_frequency_hz   REAL;
ALTER TABLE energy_readings ADD COLUMN phase_b_frequency_hz   REAL;
ALTER TABLE energy_readings ADD COLUMN phase_c_frequency_hz   REAL;

ALTER TABLE energy_readings ADD COLUMN neutral_current        REAL;
ALTER TABLE energy_readings ADD COLUMN meter_errors           TEXT;

COMMIT;
```

The rollback drops only the additions, and is safe for exactly as long as the
collector has not yet been switched over — which is why **Step 2 ships and is
verified before Step 3**.

Three constraints this respects:

- **No existing field is redefined.** CONTRIBUTING.md's rule. `power_kw` keeps
  meaning total active power; the per-phase columns are new names.
- **No `measurement_era` row is needed.** An era records a *change of meaning* in
  an existing column. Nothing here changes meaning.
- **Nullable, always.** 314,000 historical rows and every future reading from a
  node whose meter does not report these stay null. Null is "not measured", and
  the frontend already renders that as *no disponible*.

Storage cost: 15 REAL/TEXT columns × ~315k rows ≈ 19 MB on a 39 MB database,
growing ~5 MB/month at the current cadence. Check `disk_free_mb` (51 GB free on
N001, 16 GB on the server) before applying.

---

## Step 3 — the collector

**The base collector is not in this repository** — `docs/Collector.md` says so
explicitly, and the file lives at `/opt/energy-node/app/collector.py` on each Pi.
This step is an on-node change, applied to N001 and N002, whose `collector.py`
files are byte-identical apart from one log line.

The change is small: the RPC response is already parsed, so it is a mapping
addition, not new I/O.

```python
# The meter's own figures. Watts and volt-amperes on the wire; the platform
# speaks kW and kVA, so the conversion happens here and only here.
for phase in ("a", "b", "c"):
    payload[f"phase_{phase}_power_kw"]     = _kw(em.get(f"{phase}_act_power"))
    payload[f"phase_{phase}_apparent_kva"] = _kw(em.get(f"{phase}_aprt_power"))
    payload[f"phase_{phase}_power_factor"] = em.get(f"{phase}_pf")
    payload[f"phase_{phase}_frequency_hz"] = em.get(f"{phase}_freq")

payload["apparent_kva"]   = _kw(em.get("total_aprt_power"))
payload["neutral_current"] = em.get("n_current")
payload["meter_errors"]    = _join_errors(em)
```

`_kw` returns `None` for a missing key — never 0.0. That single detail is what
keeps "the meter did not report this" distinguishable from "the meter reported
zero", all the way to the screen.

Rollout, in this order:

1. Apply on **N002 first**. It is `registered`, its uploads are refused with 403
   by design, and its buffer already holds 32,402 rows — so a malformed payload
   costs nothing and reaches no production data.
2. Verify the buffered rows on-node contain the new keys.
3. Apply on **N001** during a low-load window. Its edge buffer makes this safe:
   samples are written locally before any upload, so even a failed restart
   delays data rather than losing it.
4. Keep the previous `collector.py` beside it; the hardening package's checksum
   mismatch on both Pi 5 nodes (recorded `fd660f9d7fb9`, actual `5a70bee18bf1`)
   means rollback targets are already ambiguous — do not add to that. Record the
   new SHA-256 in `docs/Fleet-Manifest.md`.

---

## Step 4 — ingestion

Both ingest paths take the new optional fields, and they must be added to **both
at once**. `/api/readings` and `/api/v1/measurements/batch` have already diverged
once — the batch route averages phases server-side with `(a or 0 + b or 0 + c or
0)/3`, counting a missing phase as zero volts, while the readings path uses the
node's floor-excluding average. That divergence is why N003 data is not
comparable to N001/N002, and adding a field to one route only would repeat it.

- `ReadingCreate` in `backend/app/routers/readings.py`: 15 new optional floats.
- The batch model in `backend/app/routers/edge.py`: the same 15.
- `EnergyReading` in `backend/app/db/models.py`: the same 15 columns, all
  `nullable=True`.
- Regression test in `backend/tests/`, comparing the two routes **against each
  other** for an identical payload — the pattern `tests/test_monitoring.py` §3g
  already uses for the auth policy, and the only kind of test that catches
  divergence rather than describing it.

---

## Step 5 — the historical API

Almost nothing to do, by design.

`backend/app/services/live_view.py` declares its series in one place:

```python
SERIES_FIELDS: tuple[tuple[str, str], ...] = (
    ("va", "phase_a_voltage"),
    ...
)
```

Adding a quantity is one tuple, plus one entry in `PRECISION` and, where the
extremes matter, one in `EXTREMA_FIELDS`. The bucketing, the null-skipping, the
rounding and the incremental `since=` path all work on whatever is in that
tuple. `METRIC_GROUPS` gains `phase_power`, `phase_apparent`, `apparent`,
`phase_power_factor`, `phase_frequency` and `neutral_current`.

Payload impact at the 1 h raw window: 11 series today → 26. Measured 41.3 KB
becomes roughly 95 KB for the initial load, and the 3 s incremental request goes
from ~370 B to ~800 B. Both are acceptable; re-measure and record.

---

## Step 6 — Monitoreo en Vivo

The page needs no structural change. `CHARTS` in
`frontend-src/src/components/livemonitor/types.ts` is a list, and availability is
already computed per node from its own newest reading — so a node begins
advertising the new magnitudes within one sample of the collector being updated,
and nodes that never report them keep saying *no disponible* without a branch.

New charts, all per-phase:

| Chart | Series | Requires |
|---|---|---|
| Potencia activa por fase | `pa`, `pb`, `pc` | `phase_power` |
| Potencia aparente por fase | `sa`, `sb`, `sc` | `phase_apparent` |
| Factor de potencia por fase | `pfa`, `pfb`, `pfc` | `phase_power_factor` |
| Frecuencia por fase | `fa`, `fb`, `fc` | `phase_frequency` |
| Potencia aparente total | `kva` | `apparent` |
| Corriente de neutro | `in` | `neutral_current` |

Two existing charts lose their apology note, because the data will exist:
*Potencia activa total* and *Factor de potencia total* currently carry "el
medidor reporta por fase, pero la plataforma sólo almacena el total."

The summary card's per-phase table grows from two columns (V, A) to five
(V, A, kW, kVA, PF), which is the layout the original request sketched and which
was not buildable until now.

New conditions become possible and should reuse existing limits — per-phase
power factor against `power_factor_warning`, and a real **power-factor
imbalance** check, which is the one N001 diagnosis currently impossible: the
prototype CSV shows phase C consistently carrying the worst PF, and today the
platform stores only the aggregate that hides it.

---

## Sequencing and risk

| Step | Reversible | Blocking |
|---|---|---|
| 0 capture RPC | yes | everything |
| 1 contract | yes | 2 |
| 2 migration | yes — `runner down` | 3 |
| 3 collector (N002 → N001) | yes — previous file retained | 4 |
| 4 ingestion | yes | 5 |
| 5 API | yes | 6 |
| 6 frontend on :5175 | yes | production review |

The order matters in one specific way: **the schema must land before the
collector**, or the new keys arrive at an endpoint that silently ignores them —
Pydantic drops unknown fields by default, so the loss would be invisible rather
than an error. Between Step 2 and Step 3 the columns exist and stay null, which
is harmless and fully reversible.

Nothing here is urgent. The meter has been discarding these values since the
installation, and one more week of it costs a week of per-phase history — not
correctness of anything already stored.

---

Related: [Live-Monitoring.md](Live-Monitoring.md), [Collector.md](Collector.md),
[API.md](API.md), [Database.md](Database.md), [Fleet-Manifest.md](Fleet-Manifest.md).
