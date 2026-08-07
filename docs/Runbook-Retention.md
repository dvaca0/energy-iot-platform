# Runbook — storage retention

Reclaims disk without destroying the ability to recover. Implemented by
[`scripts/retention.py`](../scripts/retention.py); tuned by
`backend/retention_config.json`.

## Commands

```bash
python3 scripts/retention.py report   # inventory + journal + docker, no changes
python3 scripts/retention.py plan     # exactly what apply would delete (dry run)
python3 scripts/retention.py apply    # delete, with confirmation
python3 scripts/retention.py apply --yes           # non-interactive (cron)
sudo python3 scripts/retention.py apply --yes --journal   # also cap journald
```

`plan` is the default posture. `apply` re-derives the plan rather than trusting
a stored one, so a stale plan cannot delete the wrong file.

## What is retained, and why

| Class | Rule | Rationale |
|---|---|---|
| **Milestone** `pre-NNN-up.db` | **Never deleted.** Newest per migration kept forever | It is the restore point for migration NNN. Losing it means that migration can never be rolled back. |
| Superseded milestone duplicate | Deleted | A migration that failed and rolled back leaves two; only the successful one is a restore point. |
| **Drill** `-drill.db` | Newest 2, plus anything < 7 days | A verification artefact proving a restore works — *not* a recovery point. The milestone it came from still exists. These were 22 of 37 files and most of the 4.9 GB. |
| Generated reports | Newest 20, plus anything < 90 days | Regenerable from the database. |
| Test temporaries | < 7 days, only under `/tmp/energy-platform-tests` | Never touches anything outside that path. |

**Three floors, checked before any deletion:**

1. the newest backup overall is never removed, whatever its class;
2. at least `min_total_keep` (3) backups always survive;
3. if a rule would breach either floor, the rule is skipped and the rescue is
   logged.

> [!WARNING]
> `keep_milestones: false` is accepted by the config but should never be set.
> It exists so that disabling milestone protection is a conscious, visible act
> rather than an accident. Verify with the check under "Before enabling" below.

## Journal

Needs root. The tool reports what it would do and prints the exact commands
when it cannot act:

```bash
sudo mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nSystemMaxUse=200M\n' | sudo tee /etc/systemd/journald.conf.d/99-energy-platform.conf
sudo systemctl restart systemd-journald
sudo journalctl --vacuum-size=200M
```

200 MB keeps roughly two weeks of history at current volume — enough for
incident analysis, against 1.0 GB uncapped.

## Docker — deliberately not automated

`docker system df` on this host reports:

```
Images         3  ACTIVE 3   7.509GB
Local Volumes  2  ACTIVE 2   9.611GB
Build Cache   30  ACTIVE 0   314.3MB (1.018MB reclaimable)
```

Every image and volume is referenced by a running container (OpenWebUI).
`RECLAIMABLE 100%` on images is misleading — Docker counts an image as
reclaimable when no *stopped* container needs it, not when nothing is using it.

**Never run `docker system prune` here.** It would take the 9.6 GB volume.
The only safe action is:

```bash
docker builder prune -f     # build cache only; ~1 MB here
```

Docker is ~17 GB of the disk and belongs to a different application. Reclaiming
it is an OpenWebUI decision, not a platform-retention one.

## Scheduling

```
30 3 * * * /usr/bin/python3 /home/manager/energy-platform/scripts/retention.py apply --yes >> monitoring/retention.log 2>&1
```

Daily at 03:30, user crontab (no root). Output appends to
`monitoring/retention.log`.

## Rollback

There is **no undelete.** That is why the milestone rule has no exceptions.

Every deletion is logged with path, byte size and the SHA-256 of the first
64 KiB:

```
2026-08-07T13:17:05	DELETE	/…/energy_platform-20260806_141655-pre-014-up.db	218161152	sha256:12444131111d26c7	superseded duplicate…
```

**To undo a retention run:** you cannot restore the deleted files, but you do
not need to — recovery uses a *retained milestone*:

```bash
# 1. Confirm which migration you need to return to
venv/bin/python3 -m migrations.runner status

# 2. Roll back through the runner (it takes its own backup first)
venv/bin/python3 -m migrations.runner down --to <version>

# 3. Or restore a milestone directly, backend stopped
systemctl stop energy-platform-backend      # needs root
cp backend/backups/db/energy_platform-<stamp>-pre-<NNN>-up.db backend/energy_platform.db
systemctl start energy-platform-backend
```

**To disable retention entirely:** `crontab -e`, remove the `retention.py` line.
Existing files are untouched.

**To make retention less aggressive** without code changes, edit
`backend/retention_config.json` — e.g. `drill_max_age_days: 30`.

## Before enabling on a new host

```bash
python3 scripts/retention.py plan          # read every DELETE line
python3 - <<'PY'
import sys; sys.path.insert(0,'scripts')
from retention import Policy, build_plan
plan = build_plan(Policy.load())
kept = {c.version for c in plan.candidates if c.kind=="milestone" and c.verdict=="keep"}
print("milestones retained:", sorted(kept))
PY
```

Every applied migration must appear in that list. If one does not, **stop** —
that migration would lose its only restore point.

## Disk alerting

Retention alone does not fix alerting. `server.disk` was replaced at the same
time — see `app/monitoring/health.py::check_disk`:

| | Old | New |
|---|---|---|
| Denominator | `used/total` (80.4%) | **`used/(used+avail)`** — matches `df` (80.2%) |
| Second axis | none | **days-to-full**, least-squares over 72 h of heartbeats |
| Severity | worse of percent, then **escalated by elapsed time** | worse of percent and days; **time never raises it** |
| EMERGENCY | reachable after 60 minutes | only ≥98%, or below the 1 GB absolute reserve |
| Hysteresis | none | clears only 3 points below the warning line |

`max_severity` is set to the finding's *own* computed severity, so the generic
duration ladder cannot raise it at all — not merely stop it short of EMERGENCY.
If the disk genuinely worsens the rule emits a higher severity and the cap rises
with it, so this suppresses the clock, never the disk.

Live result: `server.disk` went **EMERGENCY (71 notifications) → WARNING**,
reporting `80.2% used, 8.7 GB free, 23 days to full at 0.378 GB/day`.

Regression coverage: `tests/test_monitoring.py` §27 — both axes independently,
the worse-axis rule, the absolute reserve, both hysteresis branches, and the
2026-08-04 regression itself (2 hours open, still not EMERGENCY).

## Result of the first run (2026-08-07)

| | Before | After |
|---|---|---|
| Disk (df) | 85.9 % | **80.2 %** |
| Free | 6.2 GB | **8.7 GB** |
| Backup files | 37 | 17 |
| Backup size | 4.9 GB | 2.4 GB |

58 files removed (19 stale drills, 1 superseded milestone duplicate, and their
`-wal`/`-shm` sidecars), 2.5 GB freed. All 14 migration restore points intact,
verified before and after.
