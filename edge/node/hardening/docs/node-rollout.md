# Node Rollout — deploying the hardening package to N002 and N003

Reference implementation: **N001**, verified 2026-08-03.

**No manual edits are required beyond node-specific configuration.**

---

## 0. Fleet differences you must know first

| | N001 | N002 | N003 |
|---|---|---|---|
| hardware_kind | `shelly` | `shelly` | **`ads1256`** |
| context | production | production | **bench** |
| commission state | commissioned | registered | registered |
| `is_monitored` | true | **false** | **false** |
| UPS HAT | **HAT (D), verified** | present, model unknown | present, model unknown |
| Board | Pi 5 | **unverified** | **unverified** |

Three consequences:

1. **The UPS model on N002/N003 has never been fingerprinted.** The driver
   registry probes and identifies. If neither driver matches, the node reports
   `present but UNIDENTIFIED` with a raw I2C fingerprint and **does not invent
   battery values**. That is a successful outcome, not a failure — send me the
   fingerprint and I add a driver.
2. **If either node is a Pi 4**, `vcgencmd pmic_read_adc` does not exist.
   `board_power_w` will be NULL and the capability probe reports it. Nothing
   breaks; the column is honestly empty.
3. **`is_monitored=false` means alerts stay suppressed for N002/N003.** The
   heartbeat will arrive and `ever_seen` will flip true, but you will not get
   paged until the node is commissioned. Verify with
   `/api/monitoring/status`, not by waiting for a Telegram message.

---

## 1. Expected downtime

| Step | Downtime | Notes |
|---|---|---|
| Copy package | none | |
| `install.sh` | **~10 s** | one collector restart; measured 5 s to running, <25 s to measuring |
| Reboot (for I2C) | **~40 s** | only needed if `dtparam=i2c_arm=on` was not already set |
| **Total** | **~10 s**, or ~50 s with the reboot | |

No measurement data is lost. The collector buffers to SQLite and re-syncs;
verified on N001 with a 45 s backend blackhole and **0 rows lost**.

---

## 2. Pre-flight

On the target node:

```bash
cat /proc/device-tree/model; echo
grep -E '^NODE_ID|^CENTRAL_API_URL' /opt/energy-node/config/node.env
systemctl is-active energy-node-collector.service
ls /dev/i2c-* 2>/dev/null || echo "no i2c yet (installer will enable it)"
df -h / | tail -1
```

Confirm `NODE_ID` is the **correct node** — this is the one thing the
installer cannot check for you. It refuses to run if `NODE_ID` is unset.

---

## 3. Install

```bash
# from a machine that can reach the node
rsync -a --delete /opt/energy-node/hardening/ N002:/tmp/hardening/

# on the node
sudo mkdir -p /opt/energy-node/hardening
sudo rsync -a /tmp/hardening/ /opt/energy-node/hardening/
sudo /opt/energy-node/hardening/install.sh --dry-run   # inspect first
sudo /opt/energy-node/hardening/install.sh
```

The installer is **idempotent** — safe to re-run. It:
creates a timestamped backup → creates directories → installs files →
enables `dtparam=i2c_arm=on` → installs and reloads units → enables services →
restarts the collector → **asserts no experimental recovery is enabled** →
runs verification → prints success or failure.

It will **not** overwrite an existing tuned `hardening.conf`; it writes
`hardening.conf.new` beside it instead.

---

## 4. Node-specific configuration

The **only** file you may need to touch:

```bash
sudo nano /opt/energy-node/hardening/config/hardening.conf
```

Realistic per-node changes:

| Key | When to change |
|---|---|
| `UPS_DRIVER_ORDER` | a new driver was added for this node's HAT |
| `POWERLOG_RETENTION_DAYS` | smaller SD card |
| `VERIFY_BUFFER_MAX_PENDING` | a node that syncs less often |
| `HEARTBEAT_LEGACY_EDGE_PUBLISH` | leave at `auto` — the node negotiates this itself |

**Do not enable** `RECOVERY_UPS_ARM_ON_SHUTDOWN`, `RECOVERY_RTC_WAKE`,
`RECOVERY_GPIO_WAKE`, `RECOVERY_RELAY` or `RECOVERY_EXTERNAL_WATCHDOG`. All
five are unvalidated; see `recovery-validation.md`. The installer refuses to
report success quietly if any are on.

---

## 5. Verification

```bash
energy-node doctor      # 30 checks (energy-node-verify is a deprecated alias)
```

Expected on a healthy node: **0 FAIL**. See §9 for the full M15 checklist,
which supersedes the list below.

### Checklist

- [ ] `board` — model correct; note `pmic_adc` true/false
- [ ] `i2c` — `/dev/i2c-N present`. If FAIL, reboot and re-check
- [ ] `ups_hat` — PASS (identified) or **WARN (unidentified)**. WARN is
      acceptable; capture the fingerprint with
      `sudo /opt/energy-node/hardening/bin/energy-node-ups --json`
- [ ] `systemd_services` — all active
- [ ] `collector` — newest measurement < 300 s
- [ ] `sqlite` — `quick_check=ok`
- [ ] `buffer` — unsent below threshold
- [ ] `filesystem` — `rw=True writable=True`
- [ ] `watchdog` — active, timeout 60 s
- [ ] `backend` — HTTP 200
- [ ] **`heartbeat` — age within limit. THE CRITICAL ONE.** If it says
      *"DEAD-MAN SWITCH NOT ARMED"*, the node is invisible to liveness
      monitoring — the exact 43 h 37 m condition. Do not walk away.
- [ ] `monitoring_registration` — node present with expected lifecycle
- [ ] `alert_path` — monitoring + telegram enabled
- [ ] `recovery_flags` — **all experimental disabled**

### Independent confirmation from the backend

```bash
curl -s http://148.213.1.15:8010/api/monitoring/status \
 | python3 -c "import json,sys;n=[x for x in json.load(sys.stdin)['nodes'] if x['code']=='N002'][0];print({k:n.get(k) for k in ('ever_seen','heartbeat_age_seconds','missed_beats','severity','collector_status','uptime_seconds')})"
```

`ever_seen` must be `True` and `heartbeat_age_seconds` must be a number.
If either is `false`/`null`, the dead-man switch is not armed.

### Non-destructive recovery tests

```bash
sudo /opt/energy-node/hardening/bin/energy-node-recovery-test safe
```

Runs UPS identification, watchdog, recovery-inert, heartbeat, RTC-alarm
capability, collector crash, collector freeze, backend loss. All must pass.
Takes ~3 min and briefly restarts the collector.

---

## 6. Rollback

```bash
# find the backup the installer made
ls -dt /opt/energy-node/backups/hardening-install-* | head -1

# full rollback including collector.py and config.txt
sudo /opt/energy-node/hardening/uninstall.sh --restore /opt/energy-node/backups/hardening-install-<TS>

# verify the node is still collecting
systemctl is-active energy-node-collector.service
sqlite3 "file:/opt/energy-node/database/edge_buffer.db?mode=ro" \
  "SELECT COUNT(*), MAX(captured_at) FROM measurements;"
```

Rollback **never touches** `edge_buffer.db`, historical readings, deployments
or attribution. Add `--purge` only if you also want `power_telemetry.db` gone.

**After rollback the node stops publishing heartbeats** and becomes invisible
to liveness monitoring again. That is the pre-incident state. Only roll back
if you are replacing this with something better.

---

## 7. Post-rollout

1. Record each node's UPS fingerprint (especially any `UNIDENTIFIED`).
2. Note whether each board reports `pmic_adc=true`.
3. Leave the power logger running for a week, then compare undervoltage
   events across nodes:

```bash
sqlite3 "file:/opt/energy-node/database/power_telemetry.db?mode=ro" \
 "SELECT datetime(ts,'unixepoch','localtime'), printf('%.3f',ext5v_min_60s),
         printf('%.1f',batt_ma), on_battery FROM events ORDER BY ts DESC LIMIT 20;"
```

If N002/N003 show **no** undervoltage events while N001 does, that isolates
the problem to N001's specific power path — the strongest evidence available
without a bench supply, and the next step in the still-open root cause.

---

## 8. Deploying the backend patch (separate, blocked)

`backend/` contains the heartbeat unification and the `filesystem_readonly`
fix. **Not deployed — no SSH access to `148.213.1.15`.** See
`backend/README.md` for the integration spec, migration and the exact
post-deployment regression commands.

Only after that is live should you set `HEARTBEAT_LEGACY_EDGE_PUBLISH=0` on
every node and restart the collectors.

---

## 9. M15 additions to this procedure

The package is now **versioned** and **self-verifying**. Two changes to the
steps above:

### Upgrade path (N001 is already at 1.1.0)

```bash
sudo /opt/energy-node/hardening/install.sh --dry-run   # inspect
sudo /opt/energy-node/hardening/install.sh             # upgrade
```

The installer now **checks compatibility before replacing anything**:

- reinstall of the same version → allowed (idempotent)
- minor upgrade → allowed, warns if the config schema changed
- **downgrade → refused** unless `--force`
- **cross-major upgrade → refused** unless `--force`

It also records install state (version, checksum, dates, driver versions) and
runs the 37-test regression suite plus the 30-check doctor before declaring
success.

### Post-install checklist (replaces the M14 verification list)

```bash
energy-node hardening status     # version + checksum recorded?
energy-node selftest             # 37 tests, expect 0 failed
energy-node doctor               # 30 checks, expect 0 FAIL
energy-node ups --json           # capture the fingerprint for this node
energy-node sensors --json       # confirm the right measurement hardware
cat /opt/energy-node/state/heartbeat_negotiation.json
```

- [ ] `hardening status` shows the expected version and **checksum matches**
- [ ] `selftest` — **0 failed**
- [ ] `doctor` — **0 FAIL** (WARN on `undervoltage` is expected on a node with
      a sticky throttle bit; WARN on unrelated failed units is acceptable)
- [ ] `ups` — identified, **or** UNIDENTIFIED with a fingerprint you have
      recorded and sent back for a driver
- [ ] `sensors` — matches what is physically attached (N003 should report
      `ads1256`, not `shelly`)
- [ ] `heartbeat_negotiation.json` — `legacy_required` reflects backend state
- [ ] backend confirms `ever_seen: true` and a numeric `heartbeat_age_seconds`

### Expected downtime is unchanged

~10 s (one collector restart), or ~50 s if a reboot is needed to enable I2C.
No measurement data is lost.

### Retiring the transitional transport

Once the backend patch is deployed and **every** node reports
`"legacy_required": false`:

1. delete the legacy branch in `lib/heartbeat.py`
2. delete `HEARTBEAT_LEGACY_EDGE_PUBLISH` and `HEARTBEAT_LEGACY_EDGE_PATH`
   from `hardening.conf`
3. bump `PACKAGE_VERSION` and redeploy

Until then the nodes handle it themselves — no manual flag flip is required.

### Fleet drift check

```bash
for n in N001 N002 N003; do
  ssh $n "energy-node hardening status --json" \
    | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['node_id'],d['package_version'],d['package_checksum'][:12],d['checksum_ok'])"
done
```

All three should print the **same version and checksum**. A different checksum
means someone edited a file on that node.
