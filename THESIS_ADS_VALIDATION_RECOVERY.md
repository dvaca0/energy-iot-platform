# THESIS_ADS_VALIDATION_RECOVERY

Targeted evidence-recovery investigation into whether an automated
Shelly-vs-ADS1256 comparison experiment exists or previously existed.

Compiled **2026-08-14** by read-only inspection of the repository, git history,
legacy repositories, local backups, session transcripts, and edge nodes **N003**
and **N002** over SSH. **No code, configuration, database or measurement data was
modified.**

---

## Evidence labels

| Label | Meaning |
|---|---|
| **VERIFIED** | Directly observed by the auditor on 2026-08-14. Command or path given. |
| **DOCUMENTED** | Stated in a project file, not independently re-verified. |
| **HISTORICAL** | True of an earlier state; superseded or no longer running. |
| **USER-CONFIRMED** | Asserted by the project author (Diego) in the task brief. Not independently verifiable from artefacts. |
| **INFERRED** | A reasonable deduction from verified facts. Explicitly *not* a measurement. |
| **UNCERTAIN** | Insufficient evidence. |

---

## HEADLINE RESULT

**An automated Shelly-vs-ADS1256 comparison script EXISTS and is recoverable.**
— **VERIFIED**

It is **not** in the repository, **not** in git history, and **not** on N001 or
N002. It exists in two byte-identical copies on **N003** only.

**Its output does not survive.** No CSV, no log, no dataset, no retained console
capture. The `logs/` and `calibration/` directories created for this work are
**empty**. **Zero numerical results are recoverable.** — **VERIFIED**

Consequently, the honest classification is:

> **Designed as an engineering comparison; the surviving evidence supports only
> informal debugging.**

This is expanded and justified in §15.

---

## 1. Exact path and filename — VERIFIED

| # | Path | Size | mtime | Note |
|---|---|---:|---|---|
| **Primary** | `/home/theblackdie/ads_read_clamp.py` *(node N003)* | 6,704 B | **2026-06-08 09:08** | The working copy, in the user's home directory |
| **Archived copy** | `/home/theblackdie/energy-edge/diagnostics/ads_read_clamp_original.py` *(node N003)* | 6,704 B | 2026-07-22 14:07 | **Byte-identical** — `diff` returns no output |

A second, much smaller helper also survives:

| Path | Size | mtime | Purpose |
|---|---:|---|---|
| `/home/theblackdie/ads_test.py` | 392 B | 2026-06-05 16:50 | DRDY pin liveness probe only. No Shelly, no comparison. |
| `/home/theblackdie/energy-edge/diagnostics/ads_test_original.py` | 392 B | 2026-07-22 14:07 | Byte-identical archived copy |

**Verification:**

```bash
ssh theblackdie@<N003>  'sha256sum /home/theblackdie/ads_read_clamp.py \
   /home/theblackdie/energy-edge/diagnostics/ads_read_clamp_original.py'
```

### Where it is NOT — VERIFIED negatives

| Searched | Result |
|---|---|
| `~/energy-platform` working tree | **Not present** |
| `git log --all --diff-filter=A --name-only` (92 commits) | **Never committed**, under any name |
| `~/energy-platform-legacy-git/{frontend,frontend-src}.git` | **Nothing** matching ads/clamp/calib/compar/metrel/zmpt/noise/diagnost |
| `energy-platform/backups`, `edge/backups`, `backend/backups`, `frontend/backups` | **Nothing** |
| `~/iot_backend`, `~/ai-dashboard`, `~/ai-dashboard-backups` | **Nothing** (only `lodash` false positives) |
| **Node N002** — full `find / -xdev` | **Nothing** (only OS and plugin false positives) |
| Node N001 | **Not surveyed** — see §14 |

**The comparison work is exclusive to N003.** — **VERIFIED**

---

## 2. Git status and history — VERIFIED

**There is none.** The script has never been under version control in any
repository accessible from this server.

What *does* exist is a **filesystem-level version history** created by hand:

| Artefact | mtime | Meaning |
|---|---|---|
| `~/ads_read_clamp.py` | 2026-06-08 09:08 | Original authoring date |
| `diagnostics/ads_read_clamp_original.py` | 2026-07-22 14:07 | Copied into the `energy-edge` tree during the 2026-07-22 refactor, unchanged |
| `drivers/ads1256.py.bak.20260722_141513` … `.20260722_150529.bak` | 2026-07-22 14:15 → 15:05 | **Nine** hand-made driver backups across a ~50-minute debugging session |
| `drivers/ads1256.py.before-debug.20260722_145124` | 2026-07-22 14:51 | Explicitly named "before-debug" |
| `acquisition/sampler.py.bak.20260722_141514`, `.142537` | 2026-07-22 | Sampler split into voltage/current samplers |
| `poller.py.before_ads_20260724_171626` | 2026-07-24 17:16 | The pre-ADS Shelly poller |
| `poller.py.ads_backup_20260724_172613`, `…172701` | 2026-07-24 17:26/17:27 | Two ADS versions saved 48 s apart |

**INFERRED:** the `.bak` cadence (nine driver versions inside 50 minutes) is the
signature of live hardware debugging, not of a planned experiment.

> **Note for the thesis:** the entire custom-acquisition line — driver,
> samplers, engine, processing, diagnostics and the comparison script — is
> **outside version control**. This is a distinct and larger gap than the one
> recorded in `THESIS_TECHNICAL_EVIDENCE.md`, which noted only that the
> collectors were unversioned.

---

## 3. What hardware and sources it reads — VERIFIED

The script reads **two independent instruments in the same process**:

### Source A — the ADS1256 current board (device under test)

| Parameter | Value | Source line |
|---|---|---|
| SPI bus / device | `spi.open(0, 1)` → `/dev/spidev0.1` | VERIFIED |
| SPI clock | `SPI_SPEED = 50000` Hz (50 kHz) | VERIFIED |
| SPI mode | `0b01` (mode 1) | VERIFIED |
| Chip select | **Manual**, `spi.no_cs = True`, CS on **GPIO 8** | VERIFIED |
| DRDY | **GPIO 25** | VERIFIED |
| PDWN | **GPIO 24** | VERIFIED |
| Reference | `VREF = 2.5` | VERIFIED |
| PGA gain | `GAIN = 1.0`; `write_reg(REG_ADCON, 0x00)` | VERIFIED |
| STATUS register | `0x30` | VERIFIED |
| **DRATE register** | **`0xA1`** | VERIFIED |
| Self-calibration | `CMD_SELFCAL` (`0xF0`) issued once at start, then `wait_drdy(2.0)` | VERIFIED |
| Channel MUX | **A = `0x01` (AIN0–AIN1), B = `0x23` (AIN2–AIN3), C = `0x45` (AIN4–AIN5)** — differential | VERIFIED |

The MUX map **exactly matches** the author's stated wiring (brief item 4) —
**USER-CONFIRMED ∧ VERIFIED**.

> ⚠ **DRATE differs from production.** This script uses `0xA1`; the production
> `sources/ads.py` and every later diagnostic use `0xD0`. Any result obtained
> with this script was taken at a **different converter data rate** than the one
> the deployed collector uses. — **VERIFIED**

### Source B — the Shelly reference meter

| Parameter | Value |
|---|---|
| Endpoint | `http://192.168.1.190/rpc/EM.GetStatus?id=0` |
| Transport | `urllib.request.urlopen(..., timeout=2)`, plain HTTP |
| Fields consumed | `a_current`, `b_current`, `c_current` |
| Failure mode | Any exception → `return None`; the script continues and prints ADS-only output |

> ⚠ **The Shelly IP is `192.168.1.190`, not the production sensor segment
> `192.168.50.10`.** This is a **different network** from the one N001/N002 use
> today, consistent with a bench or lab network in June 2026. — **VERIFIED**

### Banner (verbatim, from the script) — VERIFIED

```
========================================
 ADS1256 + METREL A1033 3-PHASE POLLER
========================================
A = AIN0 - AIN1
B = AIN2 - AIN3
C = AIN4 - AIN5
Scale: 1 mV RMS = 1 A RMS
SPI: 50000 Hz, manual CS on GPIO8
========================================
```

**This is the strongest single artefact in the recovery.** It independently
corroborates, in the author's own code and predating the brief by two months:

- the **Metrel A1033** clamp model (brief item 3) — **VERIFIED**
- the **1 mV/A** transfer characteristic (brief item 4) — **VERIFIED**
- the **differential AIN pair assignment** (brief item 4) — **VERIFIED**

**Not found anywhere:** the 100 Ω series resistors and the 1 nF capacitor
experiment (brief items 4–5). No schematic, comment, note or file records them.
These remain **USER-CONFIRMED only**.

---

## 4. Electrical variables compared — VERIFIED

**Current only. One variable.**

| Compared | Not compared |
|---|---|
| RMS current per phase, A vs B vs C | Voltage |
| | Active / reactive / apparent power |
| | Power factor |
| | Frequency |
| | Energy |

The comparison block, verbatim:

```python
shelly_current = shelly.get(f"{phase.lower()}_current")
if shelly_current and data["current_a"] > 0:
    diff  = data["current_a"] - shelly_current
    ratio = shelly_current / data["current_a"]
    print(f"Shelly:        {shelly_current:10.2f} A")
    print(f"Diff:          {diff:10.2f} A")
    print(f"Ratio S/ADS:   {ratio:10.3f}")
```

**`Ratio S/ADS` is the operative quantity.** — **INFERRED:** the script's purpose
was to discover the unknown scale factor between the clamp chain and a trusted
reference. It computes the correction factor but **never applies or stores it**
(see §7).

---

## 5. Sampling methodology — VERIFIED

```
loop forever:
    1. fetch ONE Shelly snapshot (all three phases, single HTTP GET)
    2. for phase in A, B, C:
         select MUX; issue SYNC + WAKEUP; discard 10 settling reads
         sample continuously for 1.0 s of WALL-CLOCK time
         DC-remove, reject outliers, compute RMS
         print ADS result and, if the snapshot succeeded, Diff and Ratio
    3. sleep(1)
```

| Property | Value |
|---|---|
| Per-phase window | `SAMPLE_SECONDS = 1.0` — **time-bounded, not count-bounded** |
| Settling | 10 discarded reads after each MUX change |
| DC removal | Subtract the arithmetic mean of the window |
| **Outlier rejection** | Discard any AC sample with `abs(v) >= 500.0` mV |
| Minimum validity | `< 20` samples before **or after** filtering → phase reported as `NO VALID DATA` |
| RMS | `sqrt(Σv²/N)` over the surviving AC samples |
| Cycle period | ≈ 1 s (Shelly) + 3 × 1 s (phases) + 1 s sleep ≈ **4 s or more** |
| Termination | `KeyboardInterrupt` only — **operator-decided, unbounded** |

**The number of samples per window is not fixed and not knowable retrospectively.**
It is whatever the Python loop achieved in one second at 50 kHz SPI with
per-read DRDY polling. The script *prints* the achieved count
(`clean_samples / samples`) at runtime, but no run output was retained.

---

## 6. Number of samples or duration — **NOT RECOVERABLE**

| Question | Answer |
|---|---|
| Samples per phase per window | **UNCERTAIN** — runtime-dependent, printed but not stored |
| Number of comparison cycles executed | **UNCERTAIN** |
| Total duration of any session | **UNCERTAIN** |
| Number of separate sessions | **UNCERTAIN** |
| Dates of execution | **UNCERTAIN** — see below |

**Execution of `ads_read_clamp.py` is not attested in the surviving shell
history.** N003's `~/.bash_history` is capped at **2,000 lines** and its newest
entry is **2026-07-25**; the script is dated **2026-06-08**. The window has
rolled past the period in which it would have been invoked. — **VERIFIED**

**INFERRED:** the script was run (it is a `while True:` console tool with no
other purpose, it was preserved for six weeks, and it was deliberately copied
into the `diagnostics/` tree on 2026-07-22). But the *fact* of execution, its
dates and its duration are **not evidenced**.

### Contrast — sibling scripts whose execution IS attested

N003's `~/.bash_history` **does** record runs of the later diagnostics
(line numbers within the file) — **VERIFIED**:

| Script | History lines | Runs attested |
|---|---|---:|
| `diagnostics/check_ads.py` | 642 | 1 |
| `diagnostics/test_sampler.py` | 666, 696, 728 | 3 |
| `diagnostics/profile_driver.py` | 768, 790, 857 | 3 |
| `diagnostics/profile_spi.py` | 835, 856 | 2 |
| **`diagnostics/zmpt_calibration.py`** | 922, 924, 988 | **3** |
| **`diagnostics/zmpt_verify_live.py`** | 1072, 1155, 1239 | **3** |
| `diagnostics/test_processing.py` | 1338 | 1 |
| `diagnostics/test_engine.py` | 1451, 1610 | 2 |

All invoked as `PYTHONPATH=. python diagnostics/<name>.py` from
`~/energy-edge`. **None of these commands redirects output to a file** — no
`>`, `>>` or `tee` appears on any of them. — **VERIFIED**

---

## 7. Transformations and calibration constants — VERIFIED

### The full numeric chain

```
raw  = 24-bit two's-complement code from RDATA
volts = (raw / 8388607.0) × (2 × VREF / GAIN)        # VREF=2.5, GAIN=1.0
mv    = volts × 1000.0
ac    = mv − mean(mv)                                 # DC removal
ac    = [v for v in ac if abs(v) < 500.0]             # outlier rejection
rms_mv = sqrt(Σ ac² / N)
current_a = (rms_mv / CLAMP_MV_PER_AMP) × CAL_FACTORS[phase]
```

### The constants, as they stand in the file

```python
VREF = 2.5
GAIN = 1.0
CLAMP_MV_PER_AMP = 1.0
CAL_FACTORS = {"A": 1.0, "B": 1.0, "C": 1.0}
```

> **`current_a` is numerically identical to `rms_mv`.** With
> `CLAMP_MV_PER_AMP = 1.0` and all `CAL_FACTORS = 1.0`, the "amperes" the script
> prints are the millivolt RMS figure relabelled. The only physical assumption is
> the clamp's nominal **1 mV/A** datasheet transfer characteristic. — **VERIFIED**

**`CAL_FACTORS` was never updated.** It stands at identity in both surviving
copies, including the one archived six weeks after authoring. **The measured
`Ratio S/ADS` was never fed back into the code.** — **VERIFIED**

This is decisive for classification: **a calibration procedure that does not
change a calibration constant is not a calibration procedure.**

### The production code inherited the same identity scaling

`/home/theblackdie/udec-edge/processing/electrical.py` — **VERIFIED**:

```python
VOLTAGE_SCALE = {"A": 132.3452, "B": 130.4466, "C": 130.4163}
CURRENT_SCALE = {"A": 1.0, "B": 1.0, "C": 1.0}
```

The current path is uncalibrated in production for the same reason it is
uncalibrated in the comparison script: **no derived factor was ever adopted.**

---

## 8. Output format — VERIFIED

**Console text on stdout. Nothing else.**

No file handle, no `open()`, no CSV writer, no database, no HTTP POST, no logging
module. The script's only outputs are `print()` calls.

Per-phase block emitted each cycle:

```
Phase A | MUX 0x01
Samples:       <clean> clean / <raw> raw
Offset:        <x.xxx> mV
AC Min/Max:    <x.xxx> / <x.xxx> mV
Peak-Peak:     <x.xxx> mV
Clamp RMS:     <x.xxx> mV AC
ADS Current:   <x.xx> A
Shelly:        <x.xx> A
Diff:          <x.xx> A
Ratio S/ADS:   <x.xxx>
```

Preceded once per cycle by a Shelly reference block, and once at startup by
register dumps labelled `Before config:` and `After config:` (STATUS, MUX,
ADCON, DRATE).

**INFERRED:** this format is designed to be *watched*, not *collected*. Every
retained field is a live-debugging readout; nothing is timestamped, and there is
no record identifier.

---

## 9. Surviving output datasets or logs — **NONE** — VERIFIED

Exhaustive negative result:

| Location | Result |
|---|---|
| `~/energy-edge/logs/` | **Empty directory** (created 2026-07-22 14:07, never written) |
| `~/energy-edge/calibration/` | **Empty directory** (created 2026-07-22 14:07, never written) |
| `~/energy-edge/database/`, `~/energy-edge/uploader/` | **Empty directories** |
| `find /home/theblackdie -maxdepth 2 -name "*.csv|*.log|*.txt|*.json"` | Only `poller.log`, `edge_node.log`, `deployment_week.csv`, `energy-node-inspection-*.log` — **none contains comparison output** |
| Redirects in `~/.bash_history` | **None** on any diagnostics invocation |
| N003 `~/.claude/` (266 MB) | Only `remote-server.log`, a daemon token and a server binary — **no session transcripts, no captured output** |
| N003 `.xsession-errors`, `.xsession-errors.old` | No `Clamp RMS` / `Ratio S/ADS` / `ZMPT` strings |
| **This server's 11 session transcripts (37 MB)** | The strings `Ratio S/ADS`, `Clamp RMS`, `ads_read_clamp`, `ZMPT LIVE`, `ADC_RMS`, `Peak-Peak`, `METREL`, `KNOWN_MAINS_VRMS` appear **only in the current session** — i.e. only in what this audit itself just retrieved |

**Conclusion: no prior assistant session, no log, and no file anywhere captured a
single line of this script's output.** The comparison work was performed
interactively on the node's own console or over a direct SSH session that was
never recorded. — **VERIFIED**

---

## 10. Actual numerical results — **NONE RECOVERABLE** — VERIFIED

**Zero measured values from the comparison survive.** Not one `Ratio S/ADS`, not
one `Clamp RMS`, not one `Diff`.

### What numbers *do* survive, and exactly what they are

**(a) The ADS1256 bench-era readings stored in the platform** — **VERIFIED**,
live query of `backend/energy_platform.db`:

| Era | Context | Rows | mean `phase_a_current` | max abs per-phase current | mean `phase_*_voltage` |
|---|---|---:|---:|---:|---|
| 2026-07-24 23:28 → 07-26 22:39 | `bench` | 3,335 | 2.3 × 10⁻⁴ | **3.664 × 10⁻³** | **128.10 / 129.51 / 128.31 V** |
| 2026-07-26 22:40 → 08-06 14:18 | `production` | 4,499 | 2 × 10⁻⁶ | 1.56 × 10⁻³ | 0.791 / 0.803 / 0.793 V |

Two things follow, both important:

1. **The ZMPT101B voltage chain demonstrably worked.** The bench era records
   plausible mains voltages of **126.9–131.8 V** across all three phases. This is
   the only surviving evidence that the custom voltage acquisition ever produced
   physically meaningful output. — **VERIFIED**
2. **The current chain never left the noise floor in any stored data.** The
   largest per-phase current value ever stored for the ADS era is **3.664 × 10⁻³**
   in the stored unit. Because `CURRENT_SCALE = 1.0`, that unit is **ADC volts**,
   so the maximum stored clamp signal is **≈ 3.7 mV**. — **VERIFIED**

**(b) The Shelly reference dataset** — `deployment_week.csv` on N003, 22.6 MB,
120,103 data rows, written 2026-05-29 — **VERIFIED**. Per-phase Shelly readings
in the first rows: **V ≈ 124.8–125.7 V, I ≈ 59–93 A, PF 0.62–0.84, f = 60.0 Hz.**
This is a Shelly-only export; it contains **no ADS1256 column** and is **not** a
comparison dataset.

---

### The 50–90 mV clamp signals — **NOT PRESERVED** — VERIFIED

The author recalls observing clamp signals of approximately 50–90 mV during
development. **No file preserves them.**

The only place such values could ever have appeared is the `Clamp RMS: … mV AC`
line of `ads_read_clamp.py`, whose output was never captured (§9).

**INFERRED consistency check — offered as a plausibility argument, explicitly not
as a measurement:**

> At the clamp's nominal 1 mV/A, a 50–90 mV RMS signal corresponds to **50–90 A
> RMS** per phase. The Shelly reference on the same installation recorded
> **59–93 A** per phase in `deployment_week.csv`. The remembered figure is
> therefore **physically consistent** with the reference instrument's
> contemporaneous readings.
>
> This supports the recollection. **It is not evidence of agreement**, because
> the two figures come from different dates, were never recorded together, and
> the 50–90 mV value is a memory rather than a datum.

**The gap between ~3.7 mV (stored, July) and 50–90 mV (remembered, June) is
itself informative** — **INFERRED**: it is consistent with the June comparison
having been performed on an **energised, loaded** panel, and the July bench
sessions on an **unloaded or disconnected** one, well before the converters
failed entirely on ~2026-07-26.

---

## 11. Simultaneous or sequential — **SEQUENTIAL** — VERIFIED

This is the most consequential methodological limitation.

```
t=0.0 s   Shelly HTTP GET  → one snapshot of a_current, b_current, c_current
t≈0.0 s   MUX→A, settle, sample 1.0 s  → compared against the t=0 snapshot
t≈1.0 s   MUX→B, settle, sample 1.0 s  → compared against the SAME t=0 snapshot
t≈2.0 s   MUX→C, settle, sample 1.0 s  → compared against the SAME t=0 snapshot
```

Three distinct defects, all VERIFIED from the control flow:

1. **The ADS phases are sampled sequentially, not concurrently.** One converter,
   one MUX. Phases A, B and C are measured in three different one-second windows.
2. **One Shelly snapshot is reused for all three phases.** Phase C's comparison
   uses a reference reading taken **roughly two to three seconds earlier**.
3. **No timestamps are recorded**, so the offset cannot be reconstructed or
   corrected after the fact.

**Consequence:** on a load that varies at all within a ~3-second window, the
`Diff` and `Ratio S/ADS` figures conflate instrument disagreement with genuine
load variation, and the two cannot be separated. Any agreement observed would be
**suggestive, not quantitative.**

---

## 12. Did the Shelly and the ADS measure the same physical load? — **UNCERTAIN**

| Evidence | Status |
|---|---|
| The script queries a Shelly EM at `192.168.1.190` and prints it as *"Shelly reference"* | **VERIFIED** |
| That the Metrel clamps were installed on the **same three conductors** as the Shelly's own CTs | **NO EVIDENCE** — no note, comment, photograph or file |
| That both were installed **at the same time** as each other | **NO EVIDENCE** |
| Clamp orientation / phase-to-channel correspondence | **NO EVIDENCE** |

The script's structure — labelling the Shelly *"reference"* and computing
`Ratio S/ADS` per matched phase — **INFERRED** shows the author's *intent* was a
same-load, phase-matched comparison. Intent is not verification.

> ⚠ **A phase-mapping error would be invisible.** If clamp A sat on the
> conductor the Shelly calls phase B, the script would print a plausible ratio
> and nothing would flag it. Nothing in the recovered evidence excludes this.

**One corroborating detail** — **VERIFIED**: `SHELLY_IP = 192.168.1.190` is the
address N003's own `poller.py` uses to this day (`Environment=SHELLY_IP=192.168.1.190`
in the `udec-edge` systemd unit). So the reference was **N003's own production
meter**, not a borrowed or bench instrument. That makes a same-panel comparison
plausible — but still does not establish same-conductor placement.

---

## 13. Was a multimeter or other instrument involved? — **NO, in the comparison**

**No multimeter, oscilloscope, calibrator or reference source appears anywhere in
`ads_read_clamp.py`.** The only reference is the Shelly Pro 3EM, read over HTTP.
— **VERIFIED**

### However — a reference instrument WAS consulted, for voltage

`~/energy-edge/diagnostics/zmpt_verify_live.py` (1,908 B, 2026-07-22 21:38) —
**VERIFIED**:

```python
KNOWN_MAINS_VRMS = 128.6   # Change this only if your reference meter reads differently.
SAMPLES = 1500
...
scale = KNOWN_MAINS_VRMS / adc_rms if adc_rms > 0 else 0.0
```

**This is how the `VOLTAGE_SCALE` constants were derived** — **INFERRED, strongly
supported**:

- The method is exactly a **single-point scale derivation**: divide an assumed
  true mains RMS by the measured ADC RMS.
- `128.6` V sits squarely inside the 126.9–131.8 V band the platform later
  recorded from this hardware — **VERIFIED**.
- The resulting constants (132.3452, 130.4466, 130.4163) are per-phase and
  four-decimal, which is what this computation produces.
- The script was **run three times** (history lines 1072, 1155, 1239) — **VERIFIED**.

The comment *"Change this only if your reference meter reads differently"*
implies **a reference meter existed and was read**. **Its make, model, accuracy
class and the reading's date are nowhere recorded.** — **UNCERTAIN**

> This is fully consistent with the author's statement (brief item 6) that the
> voltage channels have **not** undergone a formal final calibration. A
> single-point scaling against an unrecorded reference is **not** a calibration
> procedure, and this report does not describe it as one.

### The rest of the recovered diagnostics suite

`~/energy-edge/diagnostics/` — **25 files, 2026-07-22 14:07 → 2026-07-24 17:05**
— **VERIFIED**. None writes output to a file.

| Script | Size | Purpose | Run attested? |
|---|---:|---|---|
| `ads_read_clamp_original.py` | 6,704 | **The Shelly-vs-ADS comparison** | Not in surviving history |
| `zmpt_verify_live.py` | 1,908 | Voltage scale derivation, 1,500 samples/phase | **Yes ×3** |
| `zmpt_calibration.py` | 1,111 | **Hardware potentiometer alignment** — targets 2.500 V bias per channel, 100 samples | **Yes ×3** |
| `test_engine.py` | 997 | Full V/I/PF/P/Q/S measurement through the engine | **Yes ×2** |
| `dual_noise_test.py` | 833 | 20 raw codes/phase, **both** boards | No |
| `profile_readraw.py` | 810 | `read_raw()` throughput | No |
| `zmpt_live.py` | 800 | Live single-ended voltage readout | No |
| `noise_test.py` | 710 | **5,000 samples/phase**, min/max/P-P/RMS to 9 dp, current board | No |
| `profile_spi.py` | 688 | SPI throughput | **Yes ×2** |
| `check_ads.py` | 684 | Register check | **Yes ×1** |
| `test_dual_ads.py` | 652 | Both boards | No |
| `test_sampler.py` | 605 | Sampler check | **Yes ×3** |
| `profile_driver.py` | 586 | Driver throughput | **Yes ×3** |
| `raw_dump.py` | 586 | 100 raw codes/phase, first 20 printed | No |
| `test_processing.py` | 516 | DSP check | **Yes ×1** |
| `check_registers.py` | 499 | Register dump | No |
| `check_voltage_ads.py` | 468 | Voltage-board registers + 10 raw reads | No |
| `ads_test_original.py` | 392 | DRDY probe | No |
| `spi_probe.py` | 359 | SPI presence | No |
| `test_voltage_raw.py` | 317 | Raw voltage | No |
| `ads_single_read.py` | 306 | Single read | No |
| `voltage_debug.py`, `profile_ads.py` (+1 `.bak`) | — | Voltage/ADS debug | No |

**`noise_test.py` is the closest thing to a characterisation experiment in the
suite** — 5,000 samples per phase, reporting min, max, peak-to-peak and RMS to
nine decimal places. Its execution is **not attested** and its output is **not
retained**.

---

### ⚠ A discrepancy that materially affects the voltage constants — VERIFIED

The diagnostics and the production sampler address the voltage board on
**different MUX configurations**:

| File | Phase A | Phase B | Phase C | Configuration |
|---|---|---|---|---|
| `diagnostics/zmpt_calibration.py` | `0x08` | `0x28` | `0x48` | **Single-ended** (AIN0/2/4 – AINCOM) |
| `diagnostics/zmpt_verify_live.py` | `0x08` | `0x28` | `0x48` | **Single-ended** |
| `diagnostics/zmpt_live.py` | `0x08` | `0x28` | `0x48` | **Single-ended** |
| `diagnostics/dual_noise_test.py` (voltage) | `0x08` | `0x28` | `0x48` | **Single-ended** |
| **`acquisition/voltage_sampler.py` (production)** | **`0x01`** | **`0x23`** | **`0x45`** | **Differential** |

**The `VOLTAGE_SCALE` constants were derived under a single-ended MUX
configuration, but the production collector samples the voltage board
differentially.** Nothing in the recovered evidence establishes that a scale
factor derived one way transfers to the other. — **VERIFIED (the discrepancy);
UNCERTAIN (its numerical consequence)**

This is an independent reason — beyond the author's own statement — not to treat
the existing `VOLTAGE_SCALE` values as calibrated.

---

## 14. Known limitations of this recovery

| # | Limitation |
|---|---|
| L-1 | **No output of any kind survives.** Every numerical result is lost. This bounds every conclusion below. |
| L-2 | **Execution of `ads_read_clamp.py` is not attested.** N003's `~/.bash_history` is capped at 2,000 lines ending 2026-07-25; the script dates from 2026-06-08. |
| L-3 | **N001 was not surveyed.** SSH port 22 is filtered on its current public NAT address (`148.213.168.238`) and on the previous one (`148.213.2.186`), while its heartbeats continue normally. N001 has no ADS hardware, so the expected yield is low — but this is an untested assumption. |
| L-4 | **Tailscale addresses do not route from this server** (not installed here), so all node access used public NAT addresses taken from `monitor_node_heartbeats.source_ip`. |
| L-5 | **The 100 Ω series resistors and the 1 nF capacitor experiment are unattested.** No schematic, comment, commit or note records the analogue front end. |
| L-6 | **No photograph, schematic or bill of materials** exists for the N003 signal path. |
| L-7 | **Deleted files were not recovered.** No filesystem forensics (undelete, journal recovery) was attempted — it would require root and carries write risk to the node. Files deleted before 2026-08-14 are outside this recovery. |
| L-8 | **The node's own `.claude` directory holds no session transcripts**, only a remote daemon log — so any assistant-assisted work done *on* N003 left no recoverable record. |
| L-9 | The `deployment_week.csv` ↔ stored-rows discrepancy (120,103 CSV rows vs 120,361 stored `laboratory` rows) noted in `THESIS_TECHNICAL_EVIDENCE.md` remains unexplained and was not pursued here. |

---

## 15. Classification — **conservative**

### What the evidence supports

| Candidate classification | Verdict | Reasoning |
|---|---|---|
| **Informal debugging** | ✅ **SUPPORTED** | A `while True:` console tool, no output retention, no timestamps, operator-terminated, sitting in a home directory beside a DRDY-pin probe, amid nine hand-made driver backups from a 50-minute debugging session. |
| **Engineering comparison** | ⚠ **SUPPORTED AS DESIGN INTENT ONLY** | The script *is* structurally a comparison: it reads a reference instrument, matches phases, and computes both an absolute difference and a ratio. That design is deliberate and non-trivial. But a comparison whose results were never recorded cannot be reported as one having been *performed*. |
| **Calibration procedure** | ❌ **NOT SUPPORTED** | `CAL_FACTORS` remains `{A:1.0, B:1.0, C:1.0}` in both surviving copies, including the one archived six weeks later. **No derived factor was ever adopted into any code path.** The production `CURRENT_SCALE` is likewise `1.0`. A procedure that changes no constant is not a calibration. |
| **Formal validation experiment** | ❌ **NOT SUPPORTED** | Fails on every count: no retained data; no fixed sample size; no repetitions; no stated hypothesis, acceptance criterion or uncertainty budget; **non-simultaneous** measurement (§11); unverified same-conductor placement (§12); no traceable reference instrument (§13); and a converter data rate (`0xA1`) that differs from production (`0xD0`). |

### The recommended wording

> **A purpose-built automated comparison tool was developed (2026-06-08) that
> read the ADS1256/Metrel current chain and a Shelly Pro 3EM reference
> concurrently in one process and reported per-phase difference and ratio. The
> tool survives in full. Its results do not. The surviving evidence therefore
> supports describing this as instrument-comparison tooling used during
> development debugging — not as a calibration or a validation experiment.**

**Do not** write that the ADS1256 was "validated against" or "calibrated against"
the Shelly. Neither is supported.

---

## Thesis-safe conclusions

Each of the following is defensible from artefacts recovered on 2026-08-14, and
carries its evidence label.

1. **A custom three-phase acquisition chain was designed and implemented on
   N003**, comprising two ADS1256 converters (voltage and current) on
   `/dev/spidev0.0` and `/dev/spidev0.1`, with manual GPIO chip-select, a
   register-level driver, per-phase samplers, a measurement engine and a DSP
   layer. — **VERIFIED**

2. **The current front end used Metrel A1033 clamps with a nominal 1 mV/A
   transfer characteristic, on differential ADS1256 input pairs AIN0/AIN1,
   AIN2/AIN3 and AIN4/AIN5** — stated in the author's own code banner and channel
   map, dated 2026-06-08, and independently confirmed by the author.
   — **VERIFIED ∧ USER-CONFIRMED**

3. **A purpose-built automated comparison tool was developed** that reads the
   ADS1256 current chain and a Shelly Pro 3EM reference in the same process and
   reports, per phase, the absolute difference and the ratio between them.
   — **VERIFIED**

4. **The comparison was structurally non-simultaneous.** A single Shelly snapshot
   is reused across three sequentially-sampled one-second phase windows, so the
   reference for phase C precedes its measurement by roughly two to three
   seconds. — **VERIFIED**

5. **No calibration factor was ever derived, adopted or recorded for the current
   channel.** `CAL_FACTORS` and the production `CURRENT_SCALE` both stand at
   identity. The current channel is therefore **uncalibrated**, and figures
   derived from it carry the clamp's nominal datasheet characteristic as their
   only physical basis. — **VERIFIED**

6. **No output from any comparison run survives**, in any file, log, database or
   session record on the node, the application server, or in any repository.
   **No numerical agreement, disagreement, error or uncertainty figure can be
   quoted.** — **VERIFIED**

7. **A supporting diagnostics suite of 25 scripts was developed** (2026-07-22 →
   07-24) covering register verification, SPI and driver throughput profiling,
   raw-code dumping, noise characterisation at up to 5,000 samples per phase,
   dual-board checks and voltage verification. Eight of them have attested
   execution in the node's shell history. **None writes output to a file.**
   — **VERIFIED**

8. **The voltage channel's scale constants were obtained by single-point scaling
   against an assumed mains RMS of 128.6 V**, using
   `scale = KNOWN_MAINS_VRMS / adc_rms` over 1,500 samples per phase, in a script
   run three times. The reference instrument is referred to in a comment but is
   **not identified**. — **VERIFIED (method); UNCERTAIN (reference)**

9. **The scale constants were derived on a single-ended MUX configuration
   (`0x08/0x28/0x48`) while the production sampler reads the same board
   differentially (`0x01/0x23/0x45`).** Their transferability between
   configurations is unestablished. — **VERIFIED**

10. **The ZMPT101B voltage acquisition chain demonstrably produced physically
    plausible mains measurements**: 3,335 readings stored 2026-07-24 → 07-26
    record per-phase voltages of 126.9–131.8 V. This is the only surviving
    evidence that any part of the custom chain produced meaningful physical
    output. — **VERIFIED**

11. **The current chain never left the millivolt noise floor in any stored data.**
    The largest per-phase current value in the platform for the entire ADS era is
    3.664 × 10⁻³ in ADC volts (≈ 3.7 mV). — **VERIFIED**

12. **The entire custom-acquisition line is outside version control.** Driver,
    samplers, engine, DSP, diagnostics and the comparison tool exist only on
    N003's filesystem, versioned by hand-made timestamped `.bak` files.
    — **VERIFIED**

13. **The custom chain was developed to extend measurement toward ~1000 A using
    high-current clamps already available at the university from decommissioned
    equipment**, the Shelly hardware not covering that range. The ADS1256
    architecture was therefore **additive to**, not a replacement for, the Shelly
    production solution. — **USER-CONFIRMED**, and *consistent with* the artefact
    record: the comparison script treats the Shelly as the trusted *reference*
    while the ADS chain is the *device under test*, which is the correct polarity
    for extending an established solution rather than superseding it.

> **Correction to `THESIS_TECHNICAL_EVIDENCE.md`.** That document's question 16
> asked *"Why was the ADS1256 path abandoned in favour of the Shelly Pro 3EM?"*
> and its §T12/§D-03 framed the ADS work as a possible predecessor. **That framing
> was wrong.** The chronology is the reverse: Shelly was already in production
> from 2026-05-13; the ADS1256 line began later (script dated 2026-06-08,
> package built 2026-07-22 → 07-24) as a **high-current extension**. The
> comparison script's own polarity — Shelly labelled *"reference"* — corroborates
> this. Question 16 should be struck and §T12/§D-03 re-framed accordingly.

---

## Missing evidence

Exactly what would still be required before **any** claim of measurement accuracy
or uncertainty could be made.

### Blocking — nothing can be claimed without these

| # | Required | Why |
|---|---|---|
| **B-1** | **Repair or replace the N003 ADS1256 front end.** Both converters read `STATUS = 0x00` and return constant zero; writes do not stick. | No measurement of any kind is currently possible. Everything below depends on this. |
| **B-2** | **A simultaneous, timestamped comparison run.** Both instruments sampled in the same window, with every sample pair written to a file with an ISO timestamp. | The existing tool is sequential and retains nothing. Without simultaneity, instrument disagreement cannot be separated from load variation. |
| **B-3** | **Documented same-conductor placement**, with a photograph and a written phase-to-channel map. | Nothing currently excludes a silent phase-mapping error. |

### Required for a defensible accuracy claim

| # | Required | Specification |
|---|---|---|
| **A-1** | **A current calibration** | Derive and adopt per-phase `CURRENT_SCALE` factors. At minimum a two-point fit (near-zero and near-full-scale); preferably 5+ points spanning the intended range. Record the date, the reference, and the residuals. |
| **A-2** | **A traceable reference instrument** | Make, model, accuracy class and calibration certificate. The Shelly Pro 3EM is a revenue-grade meter, not a calibrated reference; using it as the standard bounds any claim to *"agreement with a commercial meter"*, never to *absolute accuracy*. |
| **A-3** | **A fixed, stated sample size and duration** | Time-bounded windows must be replaced by count-bounded ones, with the achieved rate recorded. |
| **A-4** | **Repetition** | A minimum of three independent runs at each load point, on separate occasions, to separate systematic offset from run-to-run variation. |
| **A-5** | **A load sweep** | Measurements across the range of interest — the 50–90 A region the remembered signals imply, and points approaching the 1000 A design target. A single operating point demonstrates nothing about linearity. |
| **A-6** | **An uncertainty budget** | Contributions from the clamp (ratio and phase error), the burden/series resistors, the ADC (INL, DNL, gain error, reference drift), the DC-removal and RMS estimators, and the sampling window. Currently **none** of these is characterised. |
| **A-7** | **Time-aligned V and I sampling, or an explicit disclaimer** | The production `MeasurementEngine.measure_phase()` acquires 2,500 voltage samples *then* 2,500 current samples. Any power-factor or real-power figure from that path is not physically meaningful. Either interleave acquisition or state plainly that PF and P are not reported. |
| **A-8** | **Frequency measurement** | `sources/ads.py` emits the literal `60.0`. A measured frequency is required before any frequency-dependent claim. |
| **A-9** | **Voltage calibration under the production MUX configuration** | Re-derive `VOLTAGE_SCALE` differentially (`0x01/0x23/0x45`), against a documented reference, and record the procedure. The present single-ended-derived constants should not be described as calibrated. |
| **A-10** | **Noise-floor and resolution characterisation, retained** | `noise_test.py` already implements this at 5,000 samples/phase. It needs to be **run with its output written to a file** — the cheapest single improvement available, and it requires no new hardware beyond B-1. |

### Cheap, high-value, and currently absent

| # | Action | Cost |
|---|---|---|
| **C-1** | **Add file output to every diagnostic.** One `csv.writer` per script. The suite is otherwise sound; its only fatal flaw is that it prints to a terminal that no longer exists. | Minutes |
| **C-2** | **Bring `energy-edge/` under version control.** The whole custom-acquisition line currently exists on one SD card in one building. | Minutes |
| **C-3** | **Photograph the N003 analogue front end** and draw the schematic: clamp → 100 Ω series resistors → ADS1256 differential inputs, and the ZMPT101B modules. This is the only record that would ever exist of items 4–5 of the brief. | Hours |
| **C-4** | **Record the reference meter's identity** used for `KNOWN_MAINS_VRMS = 128.6`. | Minutes, if still known |

---

## Appendix — verification commands

```bash
# Node addresses are campus DHCP and move. Get the current one from the platform:
cd ~/energy-platform/backend && python3 -c "
import sqlite3; c=sqlite3.connect('file:energy_platform.db?mode=ro',uri=True)
print(list(c.execute('''select node_code,source_ip,max(received_at)
  from monitor_node_heartbeats where received_at>datetime(\"now\",\"-3 hours\")
  group by node_code,source_ip''')))"

# The comparison script and its archived twin (must be identical):
ssh theblackdie@<N003> 'sha256sum ~/ads_read_clamp.py \
  ~/energy-edge/diagnostics/ads_read_clamp_original.py'

# The full diagnostics suite with timestamps:
ssh theblackdie@<N003> 'ls -la --time-style=long-iso ~/energy-edge/diagnostics/'

# Proof that no output was ever retained:
ssh theblackdie@<N003> 'ls -la ~/energy-edge/logs ~/energy-edge/calibration'

# Attested runs (note: no redirects on any of them):
ssh theblackdie@<N003> 'grep -nE "diagnostics/" ~/.bash_history'

# Stored ADS-era values in the platform:
cd ~/energy-platform/backend && python3 -c "
import sqlite3; c=sqlite3.connect('file:energy_platform.db?mode=ro',uri=True)
print(list(c.execute('''select context,count(*),max(abs(phase_a_current)),
  avg(phase_a_voltage) from energy_readings
  where node_id=3 and timestamp>=\"2026-07-24\" group by 1''')))"
```

---

*End of report. Compiled 2026-08-14 by read-only inspection of
`/home/manager/energy-platform`, its git history, the legacy repositories, local
backups, 11 session transcripts (37 MB), the live production database, and edge
nodes N003 and N002 over SSH. N001 was not reachable. Nothing was modified.*
