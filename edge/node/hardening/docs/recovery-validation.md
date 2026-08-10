# Recovery Validation Plan

**Nothing in this document has been executed.** Every recovery mechanism in
the package ships **disabled** and **unvalidated**. This is the plan for
proving each one, later, in an agreed maintenance window.

> An untested recovery mechanism is worse than none: it creates false
> confidence, and it can itself take a node down. That is why none of these
> are enabled today.

---

## Ground truth this plan is built on

| Fact | Evidence |
|---|---|
| A **true power cycle recovers this node** | 2026-07-27: RTC came back at epoch (full power loss) and the node booted unattended |
| A **brownout latch does not** | 2026-07-23 (23 h) and 2026-08-01 (43 h 37 m): RTC retained correct time, so the board stayed powered while the SoC was held off. Both needed a human |
| The **internal watchdog cannot help** | It was active during the 2026-08-01 failure. Its counter is inside the SoC, which had no power |
| The **UPS wake keys off power returning** | On 2026-08-01 power never left, so there was no transition to detect |

**Therefore:** only a mechanism with its own power domain (external watchdog,
relay) or a firmware-level timer that survives the latch (RTC wake) can close
the remaining gap. Everything else shortens outages it was already able to
shorten.

---

## Safety rules for every test below

1. **Someone must be physically present** at the node, able to press the
   button. Several of these tests may leave the node latched.
2. Before starting: `energy-node doctor` must be **PASS**, and
   `sqlite3 ... "PRAGMA integrity_check"` must be `ok`.
3. Stop the collector cleanly and confirm the sync queue has drained, so no
   measurement is lost:
   ```bash
   sudo systemctl stop energy-node-collector.service
   sqlite3 "file:/opt/energy-node/database/edge_buffer.db?mode=ro" \
     "SELECT COUNT(*) FROM measurements WHERE sync_status=0;"   # expect 0
   ```
4. Record the baseline row count and restore it afterwards.
5. **Enable exactly one mechanism at a time.** A test that passes with two
   layers armed proves nothing about either.
6. After every test: `energy-node doctor` and `energy-node selftest` must
   both pass before moving on.

---

## V1 — Hardware watchdog (layer 1)

**Already active; never validated on this node.**

| | |
|---|---|
| Prerequisites | none — armed by the OS (`RuntimeWatchdogSec=1m`) |
| Enable | already on; verify with `energy-node doctor` |
| Method | freeze the kernel: `echo c \| sudo tee /proc/sysrq-trigger` |
| Expected | board resets within ~60 s and boots unattended |
| Success criteria | node returns; `journalctl --list-boots` shows a new boot; measurements resume within 60 s of boot |
| Failure meaning | the watchdog is not actually feeding — investigate `RuntimeWatchdogSec` |
| Rollback | none needed; a reboot is the expected outcome |
| Risk | **Low.** Deliberate kernel panic; unclean FS shutdown, `fsck.repair=yes` handles it |

---

## V2 — Collector self-heal (layer 3)

| | |
|---|---|
| Prerequisites | none |
| Enable | `RECOVERY_SELF_HEAL=1` in `hardening.conf` |
| Method | `sudo kill -STOP $(systemctl show -p MainPID --value energy-node-collector.service)` and wait past `RECOVERY_STALE_SECONDS` |
| Expected | the timer notices stale measurements and restarts the unit; the frozen process is replaced |
| Success criteria | measurements resume; `journalctl -u energy-node-selfheal` shows the restart; consecutive-failure counter returns to 0 |
| Failure meaning | staleness threshold too long, or the timer is not firing |
| Rollback | `RECOVERY_SELF_HEAL=0`; `sudo kill -CONT <pid>` |
| Risk | **Low.** Non-destructive. Already partly demonstrated: the safe suite proves a `SIGSTOP`ed collector still reads `active` to systemd |

---

## V3 — Reboot escalation (layer 4)

| | |
|---|---|
| Prerequisites | V2 passed |
| Enable | `RECOVERY_AUTO_REBOOT=1`, `RECOVERY_AUTO_REBOOT_AFTER_FAILURES=3` |
| Method | keep the collector wedged across three consecutive self-heal cycles |
| Expected | after the third failure the node reboots itself |
| Success criteria | node reboots; collector active after boot; counter reset |
| Failure meaning | escalation counter not persisting across runs |
| Rollback | `RECOVERY_AUTO_REBOOT=0` |
| Risk | **Medium.** A misconfigured threshold could reboot-loop a healthy node. Validate V2 first and watch one full cycle before leaving it on |

---

## V4 — UPS automatic boot (layer 5)

**The vendor mechanism. Will NOT recover the Aug 1 failure — see below.**

| | |
|---|---|
| Prerequisites | identified UPS HAT with a wake register (`energy-node ups` shows `armed=False`, register `0x0b`) |
| Enable | `RECOVERY_UPS_ARM_ON_SHUTDOWN=1` |
| Method | 1. `sudo systemctl poweroff` (the shutdown hook writes `0x55`) 2. confirm the node is off 3. **remove the HAT's Type-C input power** 4. wait 60 s 5. **restore input power** |
| Expected | the MCU detects power at the charging port and pulls GPIO3 low; the node boots unattended |
| Success criteria | node boots with no button press; `energy-node doctor` PASS; the arm register has returned to `0x0b` |
| Failure meaning | either the hook did not run before power-off, or GPIO3 wake does not work on Pi 5 with this HAT |
| Rollback | `RECOVERY_UPS_ARM_ON_SHUTDOWN=0`; press the button to recover |
| Risk | **Medium.** If the wake fails the node stays off until someone presses the button — hence the physical-presence rule |
| **Scope limit** | This validates **mains-outage recovery only**. It cannot recover the 2026-08-01 latch, where power never went away and there was no transition for the MCU to detect |

---

## V5 — RTC wake (layer 6) — **the highest-value experiment**

**The only mechanism that might close the Aug 1 gap with no new hardware.**

| | |
|---|---|
| Prerequisites | `energy-node doctor` shows `rtc` PASS; `POWER_OFF_ON_HALT` unset (Pi 5 default 0) |
| Enable | `RECOVERY_RTC_WAKE=1` |
| Method | **Phase A (halt):** set an alarm 5 min out, then `sudo systemctl halt`. **Phase B (the real question):** reproduce a brownout latch (V7) and see whether a pre-armed alarm wakes it |
| Expected A | board wakes and boots at the alarm time |
| Expected B | **genuinely unknown.** RTC wake is documented for a firmware-controlled halt; whether firmware honours it from an *unexpected* PMIC latch is undocumented either way |
| Success criteria | Phase A: node boots within 60 s of the alarm. Phase B: node boots without a button press |
| Failure meaning | Phase A failing means RTC wake is unusable here; Phase B failing means **the Aug 1 gap cannot be closed in software** and hardware is required |
| Rollback | `RECOVERY_RTC_WAKE=0`; `energy-node recovery rtc-clear`; press the button |
| Risk | **Medium-High** for Phase B — it deliberately reproduces the failure that cost 44 h |
| **Why it might work** | The RTC provably kept accurate time across the entire 43 h 37 m latch, so its power domain survives the condition |

---

## V6 — GPIO wake (layer 6b)

| | |
|---|---|
| Prerequisites | **an external device able to pull GPIO3 low.** None exists on N001 |
| Enable | `RECOVERY_GPIO_WAKE=1` (framework only — nothing drives the pin) |
| Method | with the node halted, have the external device pull GPIO3 low for ~100 ms |
| Expected | board wakes |
| Success criteria | node boots without a button press |
| Failure meaning | GPIO3 wake is not honoured on Pi 5 in this state |
| Rollback | `RECOVERY_GPIO_WAKE=0` |
| Risk | **Low** once the hardware exists |
| **Blocked by** | **A halted Pi cannot pull its own wake pin.** This test is not runnable until an external wake source is fitted |

---

## V7 — Brownout reproduction — **run this LAST**

**This is the test that reproduces the 2026-08-01 failure.**

| | |
|---|---|
| Prerequisites | bench PSU or variable supply feeding the HAT input; someone physically present; all other tests complete |
| Enable | nothing — this characterises the fault |
| Method | with the power logger running at 1 Hz, sag the HAT input toward ~4.7 V for 1–3 s and observe |
| Expected | either the node rides through, or the PMIC latches (red LED, no boot) |
| Success criteria | the *latch* is reproduced on demand — that is what makes V5 Phase B meaningful |
| Failure meaning | if it cannot be reproduced, the trigger is more specific than a simple input sag |
| Rollback | press the button |
| Risk | **High.** May latch the node. Do not run without someone at the node |
| Data to capture | `power_telemetry.db` `events` + `samples` burst around the sag; `vcgencmd get_throttled`; whether the RTC retained time afterwards (the discriminator between "power lost" and "latched") |

---

## V8 — Power removal and battery behaviour

| | |
|---|---|
| Prerequisites | UPS identified and charged (`energy-node ups`) |
| Enable | nothing |
| Method | remove the HAT's Type-C input while the node runs |
| Expected | battery carries the load; `batt_ma` goes **strongly negative**; `on_battery` becomes true |
| Success criteria | node keeps running; the discharge sign convention is confirmed |
| Failure meaning | if the node drops immediately, path management is not working |
| Rollback | restore input power |
| Risk | **Low-Medium** |
| **Why this matters** | The INA219 **discharge sign convention has never executed** — the battery has floated at ~4.19 V for the entire observation period. Across **7 captured undervoltage events**, `batt_ma` stayed between −2 and +1 mA and `on_battery` was 0 every time. This test is what turns that convention from assumed into verified |

---

## V9 — Battery depletion

| | |
|---|---|
| Prerequisites | V8 passed |
| Enable | optionally `RECOVERY_UPS_ARM_ON_SHUTDOWN=1` to chain into V4 |
| Method | run on battery until the vendor trip (~3.15 V) |
| Expected | clean shutdown, not a crash |
| Success criteria | ordered shutdown in the journal; FAT dirty bit **not** set at next boot; measurements intact |
| Failure meaning | the node browns out instead of shutting down — data loss risk on every mains outage |
| Rollback | restore power, recharge |
| Risk | **Medium.** Deep-discharges the cell; do not repeat often |
| Data to capture | runtime vs battery voltage curve, for sizing the real ride-through |

---

## V10 — Relay power cycle (layer 7)

| | |
|---|---|
| Prerequisites | **relay fitted in series with the HAT's Type-C INPUT** (cutting the Pi's 5 V rail achieves nothing — the battery keeps it alive); relay commandable by a **peer or the backend**, not by this node |
| Enable | `RECOVERY_RELAY=1`, `RECOVERY_RELAY_BACKEND=<driver>` |
| Method | latch the node via V7, then command the relay to cut input, wait, restore |
| Expected | a true power-on-reset; node boots unattended |
| Success criteria | node recovers **from a latched state with no human** — this is the outcome the whole programme is aimed at |
| Failure meaning | off-time too short to drain UPS hold-up — increase it and retry |
| Rollback | manual button |
| Risk | **Medium** |
| **Open question** | how long the input must stay off for the battery to stop holding the Pi up. **Unverified — must be measured**, and it is the main uncertainty in this approach |

---

## V11 — External hardware watchdog (layer 8)

| | |
|---|---|
| Prerequisites | external MCU/HAT with **its own power domain**; pet path (I2C/UART/GPIO); reset path wired to RUN or input power |
| Enable | `RECOVERY_EXTERNAL_WATCHDOG=1`, set device and pet interval |
| Method | stop petting (kill the petting service), and separately reproduce a V7 latch |
| Expected | the MCU asserts reset and the board restarts in both cases |
| Success criteria | recovery from **both** a kernel freeze **and** a latched/unpowered SoC |
| Failure meaning | reset line not wired correctly, or timeout shorter than a legitimate busy period |
| Rollback | `RECOVERY_EXTERNAL_WATCHDOG=0` |
| Risk | **Medium.** Too-aggressive a timeout reboots a healthy node mid-sync, which is its own outage |
| **Why this is the strongest option** | Its counter lives **outside** the SoC. That is precisely why the internal watchdog failed on 2026-08-01, and precisely why this one would not |

---

## Recommended order

1. **V1** watchdog — cheap, already armed, never proven
2. **V2** self-heal → **V3** escalation — low risk, real value
3. **V8** power removal — confirms the battery actually carries the node
4. **V4** UPS auto-boot — closes the mains-outage gap
5. **V5 Phase A** RTC wake from halt — cheap, and gates Phase B
6. **V9** battery depletion — only if V8 passed
7. **V7** brownout reproduction — **the pivot**
8. **V5 Phase B** RTC wake from a real latch — the decisive experiment
9. **V10 / V11** — only if V5 Phase B fails, i.e. only if hardware is proven necessary

**Decision point:** if V5 Phase B succeeds, the Aug 1 failure mode is solvable
in software and no new hardware is required. If it fails, V10 or V11 is
mandatory for unattended field deployment, and that should be treated as a
procurement requirement rather than an optimisation.

---

## What must be recorded for each test

```
test id · date · operator · node · hardening version (energy-node hardening status)
pre-test doctor result · action taken · observed outcome · recovery time
post-test doctor result · post-test selftest result
data integrity: row count before/after, PRAGMA integrity_check
RTC value at next boot   <-- the discriminator between power loss and latch
```

That last line matters more than it looks: a valid RTC at boot means the board
stayed powered (a latch); an epoch RTC means power genuinely went away. It is
the single cheapest signal for telling the two failure modes apart.
