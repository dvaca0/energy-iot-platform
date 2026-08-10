# Energy Node Hardening Package

Version **1.1.0** · reference implementation: **N001** (`energy-node-001`)

Everything here is generic. The only per-node differences are configuration
files: `node.env` (identity) and `hardening.conf` (tunables).

---

## 1. Why this exists

On **2026-08-01 11:32:31 CST** N001 stopped. It came back **2026-08-03
07:09:48**, only after someone pressed the button — **43 h 37 m** of lost
measurements.

Two independent failures:

1. **A brownout stopped the SoC while the 5 V rail stayed alive.** The RTC
   kept perfect time across the whole outage, which it can only do while
   powered (there is no RTC backup battery). So there was no power-on-reset
   to restart the board. The hardware watchdog was *already active* and could
   not help — its counter is inside the SoC, which had no power.
2. **Nobody was told for 44 hours.** The collector posted to
   `/api/edge/heartbeat` while monitoring read `/api/monitoring/heartbeat`.
   N001 sat at `ever_seen=false`, `heartbeat_age=null` forever, so
   `node.heartbeat_lost` could never fire. The one alert that did fire said
   *"Heartbeats are arriving normally, so the machine is fine"* — the exact
   opposite of the truth.

This package fixes #2 completely and instruments #1. **It does not fix #1** —
see §9.

---

## 2. Architecture

```
                 hardening.conf  (every tunable)   node.env (identity)
                            |
        +-------------------+-------------------+
        |         |         |         |         |
   enconfig    i2cbus    sysinfo   tristate   version
   config    stdlib I2C  /proc +   NULL is    checksum,
   loader     (ioctl)    caps      not a      dates,
        |         |      probe     state      compat gate
        |         |         |         |
        |    lib/ups/   lib/sensors/  |
        |    registry:  registry:     |
        |    hat_d,     shelly,       |
        |    hat_e,     ads1256,      |
        |    unknown    smart_plugs,  |
        |               unknown       |
        +-------------------+---------+
                            |
                    lib/telemetry.py
                 THE canonical payload
                            |
                    lib/heartbeat.py
              publisher + backend negotiation
                            |
                  collector.py send_heartbeat()
                    *** SOLE PRODUCER ***

   consumers:  lib/doctor.py (30 checks)  ·  lib/selftest.py (37 tests)
               lib/recovery/ (7 modules, 5 experimental all disabled)
```

**Dependency rule:** everything in `lib/` is **stdlib-only** (plus `requests`,
which the collector venv already has). The collector's venv contains no
`psutil` and no `smbus2`, and the canonical heartbeat must run inside it — so
I2C is done through `ioctl` and metrics through `/proc`. The package installs
with **no pip step**, which matters when deploying to field nodes.

---

## 3. Boot sequence

```
power on
  -> boot ROM -> EEPROM -> bootloader -> kernel
  -> systemd
       energy-node-netd          (pre-existing) network supervisor
       energy-node-collector     measures + publishes THE heartbeat
       energy-node-powerlog      1 Hz power/UPS recorder
       energy-node-selfheal.timer    inert unless enabled
       energy-node-verify.timer      boot + daily verification
       energy-node-recovery-arm      inert; ExecStop runs at shutdown only
```

`dtparam=i2c_arm=on` must be set in `/boot/firmware/config.txt` or the UPS is
invisible. The installer sets it; **it needs a reboot to take effect.**

---

## 4. Heartbeat flow — one producer, many consumers

```
collector.py sync_loop()
      |  (unchanged call site, unchanged interval)
      v
send_heartbeat()  --> telemetry.build()  --> ONE canonical payload
      |                    ^
      |                    +-- sysinfo (cpu, mem, disk, net, throttle)
      |                    +-- ups (battery, charge, wake-arm state)
      |                    +-- powerlog events (edge-triggered undervoltage)
      v
heartbeat.publish()
      |
      +--> POST /api/monitoring/heartbeat   CANONICAL. Arms the dead-man
      |                                     switch, node.power, node.*
      |
      `--> POST /api/edge/heartbeat         TRANSITIONAL, remove after the
                                            backend patch. Verified
                                            2026-08-03: the monitoring path
                                            does NOT update last_sync, which
                                            drives the dashboards.
```

**This is one producer with one payload over two transports, not two
heartbeat concepts — and it deactivates itself.**

`HEARTBEAT_LEGACY_EDGE_PUBLISH=auto` (the default) makes the node *negotiate*.
The patched backend returns `last_sync` from the canonical endpoint; the
unpatched one does not. When the node sees that key it stops publishing to the
legacy path by itself — no config change, no redeploy, no downtime. The
transitional branch therefore has a defined, automatic end-of-life.

Check what a node currently believes:

```bash
cat /opt/energy-node/state/heartbeat_negotiation.json
```

Once every node reports `"legacy_required": false`, delete the branch in
`lib/heartbeat.py` and the two config keys. That is the only remaining
transitional code in the package.

Two subtleties that were bugs and are now fixed:

- **UTC.** The payload timestamp is `time.gmtime()`. Local time produced a
  bogus `-21602s` (−6 h CST) `node.clock_drift` CRITICAL.
- **`buffered_readings` means UNSENT backlog**, not total rows. This node
  retains ~64 k synced rows as history; sending the total pinned
  `node.buffer` CRITICAL against a threshold of 500.

---

## 4b. Tri-state monitoring — NULL is not a state

Every optional value resolves to exactly `TRUE`, `FALSE` or `UNKNOWN`
(`lib/tristate.py`). `UNKNOWN` is **never** silently coerced.

This exists because the platform had the same bug twice, pointing opposite ways:

| rule | NULL was treated as | consequence |
|---|---|---|
| `node.heartbeat_lost` | healthy | silently never fired — 43 h 37 m unnoticed |
| `node.filesystem_readonly` | faulty | permanent CRITICAL "the SD card has almost certainly failed" on a healthy node |

A monitoring system that cannot say "I don't know" will either cry wolf or stay
silent. This one did both.

`Tri.__bool__` **raises** — implicit coercion is a programming error, not a
fallback. That guard caught a real bug in `Result.as_dict()` during
development, where `if self.state` would have silently coerced.

Outcomes: `PASS` · `FAIL` · `WARN` (degraded, or unknown past a grace period)
· `UNKNOWN` (not reported, no assertion made) · `SKIP` (not applicable to this
hardware). Evaluators: `evaluate_boolean`, `evaluate_threshold`,
`evaluate_liveness`. The same module backs the undeployed backend patch, so
there is exactly one implementation of this logic in the platform.

**A missing temperature never reads as "nice and cool".**

## 5. Monitoring flow

```
heartbeat -> monitoring store -> alert evaluation -> telegram
                                       |
      node.heartbeat_lost  <-----------+  now armed (was structurally dead)
      node.undervoltage    <-----------+  now fires (never fired in 180 events)
      node.buffer / node.clock_drift / node.filesystem_readonly
```

**Undervoltage is edge-triggered, not sticky.** Firmware bits 16/18 only clear
on reboot; reporting them would pin `node.undervoltage` at ERROR forever. The
sag lasts 2–4 s — far shorter than the 60 s heartbeat — so `telemetry.py` asks
the 1 Hz power logger's `events` table instead.

---

## 6. Power logger

1 Hz sampling into a 300 s ring; a row persisted every 5 s; on any throttle
flag change the **entire ring is flushed at full resolution** so the run-up to
the sag is captured, not just the sag. 14-day retention, hourly pruning,
`Nice=10` and `IOSchedulingClass=idle`.

**First captured event (N001, 2026-08-03 08:27:40):**

| signal | value | conclusion |
|---|---|---|
| `batt_ma` | ±1–3 mA | battery never discharged |
| `on_battery` | 0 | input never dropped out |
| `batt_v` | 4.188 V steady | battery healthy |
| `ext5v_min_60s` | **4.942 V** | the rail *is* dipping |
| `load1` | 0.13 → 0.20 | trivial load step |

Rules out charger contention and input dropout. Points at the HAT's 5 V
regulator transient response — consistent with 3× average headroom yet deep
dips on fast steps. **n=1; not a conclusion yet.**

Per-rail board power requires `vcgencmd pmic_read_adc`, which is **Pi 5 only**.
On a Pi 4 that column is NULL and the capability probe says so — never faked.

---

## 7. Watchdog

The bcm2835 watchdog is armed by the OS (`RuntimeWatchdogSec=1m`). This
package **verifies it, does not arm it**, because it was already active during
the failure and did not help.

- **Recovers:** kernel freeze / deadlock, ~60 s.
- **Cannot recover:** an unpowered SoC. Also cannot recover a wedged
  *userspace* process — a `SIGSTOP`ed collector is still `active` to systemd,
  which is why layer 3 exists.

---

## 8. UPS HAT integration

Driver registry with strict probing:

```
UPSDriver
  |- waveshare_hat_d   VERIFIED on N001 (MCU 0x2d -> 0x0a,0x0b,0x0c;
  |                    INA219 0x43 cfg 0x399F; 21700 cell 4.192 V)
  |- waveshare_hat_e   from vendor register map, UNVERIFIED on hardware
  `- (unknown)         reports present-but-unidentified with a raw
                       fingerprint; NEVER guesses battery values
```

Current comes from the raw INA219 shunt register, so a read **never writes** to
the chip: 10 µV LSB over a 0.01 Ω shunt = 1 mA/count (0.01 Ω confirmed from
the vendor's own `INA219.py`).

`hat_d` requires *both* the MCU signature and a responding INA219; `hat_e`
explicitly rejects a board that presents an INA219. That keeps the two models
from being confused on N002/N003.

**A wrong battery reading is worse than none** — it would let the platform
believe a node has headroom it does not have.

---

## 9. Recovery framework — and what is still unsolved

| Layer | Module | Flag | Recovers | Cannot recover |
|---|---|---|---|---|
| 1 | watchdog | `WATCHDOG_VERIFY` | kernel freeze | unpowered SoC |
| 2 | systemd | *(built in)* | collector crash — **5 s measured** | wedged process |
| 3 | selfheal | `RECOVERY_SELF_HEAL` | stalled collector | node fully down |
| 4 | selfheal | `RECOVERY_AUTO_REBOOT` | wedged userspace | unpowered SoC |
| 5 | ups_wake | `RECOVERY_UPS_ARM_ON_SHUTDOWN` | mains outage → return | **the Aug 1 latch** |
| 6 | rtc_wake | `RECOVERY_RTC_WAKE` | **UNPROVEN** | unknown |
| 6b | gpio_wake | `RECOVERY_GPIO_WAKE` | nothing — framework only | everything |
| 7 | relay | `RECOVERY_RELAY` | the Aug 1 latch, **if wired** | anything unwired |
| 8 | external_watchdog | `RECOVERY_EXTERNAL_WATCHDOG` | kernel freeze **and** unpowered SoC | anything unwired |

**Layers 7 and 8 are the only two that can recover the Aug 1 latch**, because
they act from outside the SoC's power domain. Both are implemented as modules,
both ship disabled, and **neither is wired on any node**. Their prerequisites
are documented in the module docstrings and in `recovery-validation.md`.

Two things worth stating plainly about them:

- **Layer 7 must cut the UPS HAT's *input*, not the Pi's 5 V rail.** Cutting
  downstream of the UPS achieves nothing — the battery keeps the Pi alive.
- **A latched node cannot command its own recovery.** The decision to cycle
  power must come from a peer node or the backend observing missed heartbeats.
  That is why layer 7 is only the node-side half.

**Layers 5, 6 and 6b are DISABLED and UNVALIDATED. Do not enable them without
a maintenance-window test.**

### Future: RTC wake (the only remaining software hope)

The RTC provably kept time through the entire 43 h 37 m latch, so its power
domain survives. If firmware honours an RTC alarm from that state, a rolling
dead-man alarm recovers the node **with no new hardware**. Whether it does is
undocumented. Test `halt-rtc-wake` before enabling.

### Future: GPIO wake

The HAT MCU wakes the Pi by pulling GPIO3 low. **A halted Pi cannot pull its
own wake pin** — closing this gap needs an *external* device. The framework is
prepared; nothing drives the pin.

### The honest bottom line

**The Aug 1 failure mode is not fixed.** Detection went from 43 h 37 m to
~2–5 min, which is not the same as recovery. If a brownout latches the SoC
while the rail stays alive, the node still needs a human. No code running on
an unpowered CPU can restart that CPU.

---

## 10. Configuration

Everything tunable is in `config/hardening.conf` — intervals, timeouts,
sampling rates, retention, thresholds, every recovery flag. No module hardcodes
a threshold or a path. Identity stays in `node.env`, which this package never
modifies.

---

## 11. Operator tooling

```bash
energy-node doctor              # 30 checks, PASS/WARN/FAIL/UNKNOWN/SKIP
energy-node doctor --json       # the contract the backend will consume
energy-node hardening status    # version, checksum, dates, driver versions
energy-node selftest            # 37-test non-destructive regression suite
energy-node ups                 # UPS discovery / raw fingerprint
energy-node sensors             # measurement hardware discovery
energy-node recovery status     # every module, its flag, what it can/cannot do
```

`energy-node-verify` remains as a deprecated alias for `doctor`.

**Doctor covers 30 subsystems:** configuration, hardening_version, board, i2c,
ups, battery, rtc, gpio, watchdog, sensor, systemd_services, systemd_failed,
collector, sqlite, buffer, sync_queue, filesystem, disk, memory, cpu,
temperature, undervoltage, ethernet, wifi, tailscale, backend, heartbeat,
monitoring_registration, alert_path, recovery_flags.

Exit 0 if no FAIL. Runs automatically 3 min after boot and daily. Checks that
do not apply to a board are **SKIP**, never a silent pass.

`sync_queue` is deliberately separate from `buffer`: a queue whose depth is
under threshold but whose oldest row keeps ageing is a *failing sync*, and
depth alone would not show it.

## 11b. Hardening versioning

`energy-node hardening status` reports package version, config schema version,
install date, last upgrade, package checksum, doctor version and every driver
version. State lives in `/opt/energy-node/state/hardening.json`, written only
by the installer.

The **checksum covers every file in `lib/`, `bin/` and `systemd/`**, is
path-relative and sorted, so two nodes running identical code produce an
identical checksum. That makes fleet drift — a hand-edited file on one node —
detectable, and the doctor WARNs on a mismatch.

`install.sh` calls `version.check_upgrade()` **before replacing anything**. It
refuses a downgrade or a cross-major upgrade unless `--force` is given, because
a config written for a newer schema can silently mean something different to
older code.

## 11c. Hardware abstraction

Nothing assumes a Pi 5, a Waveshare HAT (D), a Shelly, or an ADS1256.

- **Board:** `sysinfo.capabilities()` probes model, `vcgencmd`, PMIC ADC,
  throttle flags, watchdog, RTC wakealarm. `pmic_read_adc` is **Pi 5 only** —
  on a Pi 4 `board_power_w` is recorded NULL and reported as unavailable,
  never fabricated.
- **UPS:** driver registry (`hat_d` verified, `hat_e` from the vendor register
  map, unknown → fingerprint only). `hat_d` requires *both* the MCU signature
  **and** a responding INA219; `hat_e` explicitly rejects a board presenting an
  INA219. That keeps the two from being confused.
- **Sensors:** `lib/sensors.py` probes Shelly (HTTP), ADS1256 (SPI transport
  only — the ADC is never driven, to avoid disturbing measurements) and the
  smart-plug store. `SENSOR_KIND` optionally declares the expected kind so a
  mismatch between declared and discovered is visible.

Unknown hardware is reported as **unidentified with diagnostics**, never
forced into a known shape. A wrong reading is worse than no reading.

---

## 12. Deployment and rollback

See `node-rollout.md`. Rollback is:

```bash
sudo /opt/energy-node/hardening/uninstall.sh --restore <backup-dir>
```

`edge_buffer.db`, historical readings, deployments and attribution are never
touched. The only collector change is inside `send_heartbeat()`.
