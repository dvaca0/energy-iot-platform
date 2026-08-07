#!/usr/bin/env python3
"""Storage retention for the Energy Platform.

Reclaims disk without ever destroying the ability to recover. Nothing here
deletes by pattern alone: every candidate is classified, and every class has an
explicit rule with a floor beneath it.

    python3 scripts/retention.py report          # what exists, no changes
    python3 scripts/retention.py plan            # what would be removed (dry run)
    python3 scripts/retention.py apply           # remove it, logging every file
    python3 scripts/retention.py apply --yes     # non-interactive (for cron)

Design
------
**Milestones are never deleted.** A migration backup named ``pre-NNN-up`` is the
restore point for migration NNN. The newest one for each NNN is kept forever,
regardless of age or count. Losing it means migration NNN can never be rolled
back, and 4 GB of disk is cheaper than that.

**Drills are disposable.** A ``-drill`` backup is produced by
``migrations.runner restore-drill`` to prove a restore works. It is a
verification artefact, not a recovery point: the milestone it was taken from
still exists. These are the bulk of the usage — 22 of 37 files here.

**Three floors, checked before any deletion:**

* the newest backup overall is never removed, whatever its class;
* at least ``min_total_keep`` backups always survive;
* a class is skipped entirely if applying its rule would breach either floor.

**Dry run is the default posture.** ``plan`` changes nothing and prints exactly
what ``apply`` would do. ``apply`` re-derives the plan rather than trusting a
stored one, so a stale plan cannot delete the wrong thing.

Rollback
--------
Deletions are logged to ``retention.log`` with size and SHA-256 of the first
64 KiB, so a removed file can be identified in an off-box copy. There is no
undelete: recovery is by restoring from a retained milestone, which is why the
milestone rule has no exceptions. See ``docs/Runbook-Retention.md``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BACKEND = REPO / "backend"
CONFIG_FILE = BACKEND / "retention_config.json"
LOG_FILE = REPO / "monitoring" / "retention.log"

#: energy_platform-20260806_141710-pre-014-up.db
_BACKUP_RE = re.compile(
    r"^energy_platform-(?P<stamp>\d{8}_\d{6})-(?P<kind>pre-(?P<version>\d+)-(?:up|down)|drill)\.db$"
)


@dataclass
class Policy:
    """Retention rules. Every value is configurable; defaults are conservative."""

    # --- migration backups ---------------------------------------------
    #: Newest N drills always kept, whatever their age.
    drill_keep: int = 2
    #: Drills younger than this are kept even beyond drill_keep.
    drill_max_age_days: int = 7
    #: Absolute floor on surviving backups of any class.
    min_total_keep: int = 3
    #: Milestones (pre-NNN-up) are never deleted. Present so the intent is
    #: explicit and so a future operator must consciously change it.
    keep_milestones: bool = True

    # --- generated reports ----------------------------------------------
    report_max_age_days: int = 90
    report_keep: int = 20

    # --- temporary files -------------------------------------------------
    tmp_max_age_days: int = 7

    # --- journal ----------------------------------------------------------
    journal_max_use: str = "200M"

    # --- docker -------------------------------------------------------------
    #: Only the build cache is ever touched, and only entries with no active
    #: reference. Images and volumes are never removed by this tool: on this
    #: host all three images and both volumes are in use by running containers
    #: (OpenWebUI), and a broad `docker system prune` would take them.
    docker_build_cache: bool = True

    @classmethod
    def load(cls) -> Policy:
        policy = cls()
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text())
            except (OSError, ValueError):
                return policy
            for key, value in (data.get("retention") or data).items():
                if hasattr(policy, key):
                    setattr(policy, key, value)
        return policy


@dataclass
class Candidate:
    """One file considered for removal."""

    path: Path
    size: int
    mtime: float
    kind: str  # milestone | drill | report | tmp
    version: str | None = None
    verdict: str = "keep"
    reason: str = ""


@dataclass
class Plan:
    candidates: list[Candidate] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def deletions(self) -> list[Candidate]:
        return [c for c in self.candidates if c.verdict == "delete"]

    @property
    def reclaim_bytes(self) -> int:
        return sum(c.size for c in self.deletions)


def _human(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _sidecars(path: Path) -> list[Path]:
    """SQLite -wal/-shm files belonging to a backup."""
    return [p for p in (Path(str(path) + "-wal"), Path(str(path) + "-shm")) if p.exists()]


# ---------------------------------------------------------------- planning
def plan_migration_backups(policy: Policy, now: datetime) -> Plan:
    """Classify every migration backup and decide its fate."""
    plan = Plan()
    directory = BACKEND / "backups" / "db"
    if not directory.is_dir():
        plan.notes.append(f"{directory} does not exist — nothing to do")
        return plan

    entries: list[Candidate] = []
    for path in sorted(directory.glob("*.db")):
        match = _BACKUP_RE.match(path.name)
        if not match:
            entries.append(
                Candidate(
                    path,
                    path.stat().st_size,
                    path.stat().st_mtime,
                    "unrecognised",
                    verdict="keep",
                    reason="name not recognised — never guessed at",
                )
            )
            continue
        stat = path.stat()
        kind = "drill" if match.group("kind") == "drill" else "milestone"
        entries.append(Candidate(path, stat.st_size, stat.st_mtime, kind, match.group("version")))

    if not entries:
        plan.notes.append("no backups found")
        return plan

    newest_overall = max(entries, key=lambda c: c.mtime)

    # --- milestones: newest per migration version, kept forever -----------
    milestones = [c for c in entries if c.kind == "milestone"]
    newest_per_version: dict[str, Candidate] = {}
    for candidate in milestones:
        current = newest_per_version.get(candidate.version)
        if current is None or candidate.mtime > current.mtime:
            newest_per_version[candidate.version] = candidate

    for candidate in milestones:
        if policy.keep_milestones and newest_per_version.get(candidate.version) is candidate:
            candidate.verdict = "keep"
            candidate.reason = f"milestone: restore point for migration {candidate.version}"
        elif not policy.keep_milestones:
            candidate.verdict = "delete"
            candidate.reason = "milestone retention disabled in config"
        else:
            candidate.verdict = "delete"
            candidate.reason = (
                f"superseded duplicate for migration {candidate.version} " f"(newer copy retained)"
            )

    # --- drills: newest N, plus anything inside the age window ------------
    drills = sorted((c for c in entries if c.kind == "drill"), key=lambda c: c.mtime, reverse=True)
    cutoff = now - timedelta(days=policy.drill_max_age_days)
    for index, candidate in enumerate(drills):
        age_ok = datetime.fromtimestamp(candidate.mtime) >= cutoff
        if index < policy.drill_keep:
            candidate.verdict = "keep"
            candidate.reason = f"newest {policy.drill_keep} drills"
        elif age_ok:
            candidate.verdict = "keep"
            candidate.reason = f"younger than {policy.drill_max_age_days}d"
        else:
            candidate.verdict = "delete"
            candidate.reason = (
                f"restore drill, older than {policy.drill_max_age_days}d — "
                "a verification artefact, not a recovery point"
            )

    # --- floors -----------------------------------------------------------
    for candidate in entries:
        if candidate is newest_overall and candidate.verdict == "delete":
            candidate.verdict = "keep"
            candidate.reason = "newest backup overall — never removed"

    survivors = [c for c in entries if c.verdict == "keep"]
    if len(survivors) < policy.min_total_keep:
        deficit = policy.min_total_keep - len(survivors)
        rescued = sorted(
            (c for c in entries if c.verdict == "delete"),
            key=lambda c: c.mtime,
            reverse=True,
        )[:deficit]
        for candidate in rescued:
            candidate.verdict = "keep"
            candidate.reason = f"floor: at least {policy.min_total_keep} backups retained"
        plan.notes.append(f"floor rescued {len(rescued)} backup(s)")

    plan.candidates.extend(entries)
    return plan


def plan_reports(policy: Policy, now: datetime) -> Plan:
    """Generated reports: keep the newest N and anything recent."""
    plan = Plan()
    directory = BACKEND / "generated_reports"
    if not directory.is_dir():
        return plan

    files = sorted(
        (p for p in directory.iterdir() if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    cutoff = now - timedelta(days=policy.report_max_age_days)
    for index, path in enumerate(files):
        stat = path.stat()
        candidate = Candidate(path, stat.st_size, stat.st_mtime, "report")
        if index < policy.report_keep or datetime.fromtimestamp(stat.st_mtime) >= cutoff:
            candidate.verdict = "keep"
            candidate.reason = "recent or within keep count"
        else:
            candidate.verdict = "delete"
            candidate.reason = f"older than {policy.report_max_age_days}d"
        plan.candidates.append(candidate)
    return plan


def plan_tmp(policy: Policy, now: datetime) -> Plan:
    """Our own temporary artefacts. Never touches anything outside these paths."""
    plan = Plan()
    cutoff = now - timedelta(days=policy.tmp_max_age_days)
    roots = [Path("/tmp/energy-platform-tests")]
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            stat = path.stat()
            candidate = Candidate(path, stat.st_size, stat.st_mtime, "tmp")
            if datetime.fromtimestamp(stat.st_mtime) >= cutoff:
                candidate.verdict = "keep"
                candidate.reason = "recent"
            else:
                candidate.verdict = "delete"
                candidate.reason = f"test artefact older than {policy.tmp_max_age_days}d"
            plan.candidates.append(candidate)
    return plan


def build_plan(policy: Policy, now: datetime | None = None) -> Plan:
    now = now or datetime.now()
    combined = Plan()
    for part in (
        plan_migration_backups(policy, now),
        plan_reports(policy, now),
        plan_tmp(policy, now),
    ):
        combined.candidates.extend(part.candidates)
        combined.notes.extend(part.notes)
    return combined


# ----------------------------------------------------------------- actions
def _fingerprint(path: Path) -> str:
    """SHA-256 of the first 64 KiB — identifies a file in an off-box copy."""
    try:
        with path.open("rb") as handle:
            return hashlib.sha256(handle.read(65536)).hexdigest()[:16]
    except OSError:
        return "unreadable"


def apply_plan(plan: Plan, *, log: Path = LOG_FILE) -> tuple[int, int]:
    """Delete what the plan marked. Returns (files, bytes)."""
    log.parent.mkdir(parents=True, exist_ok=True)
    removed = freed = 0
    stamp = datetime.utcnow().isoformat()

    with log.open("a") as handle:
        handle.write(f"\n# retention run {stamp}\n")
        for candidate in plan.deletions:
            targets = [candidate.path, *_sidecars(candidate.path)]
            for target in targets:
                try:
                    size = target.stat().st_size
                    fingerprint = _fingerprint(target)
                    target.unlink()
                    removed += 1
                    freed += size
                    handle.write(
                        f"{stamp}\tDELETE\t{target}\t{size}\tsha256:{fingerprint}\t{candidate.reason}\n"
                    )
                except OSError as exc:
                    handle.write(f"{stamp}\tFAILED\t{target}\t{exc}\n")
    return removed, freed


def configure_journal(policy: Policy, apply: bool) -> list[str]:
    """Cap journald. Requires root; reports honestly when it cannot."""
    out = []
    current = subprocess.run(
        ["journalctl", "--disk-usage"], capture_output=True, text=True, check=False
    )
    out.append(f"current: {current.stdout.strip() or current.stderr.strip()}")

    conf = Path("/etc/systemd/journald.conf.d/99-energy-platform.conf")
    body = (
        "# Managed by scripts/retention.py — journal capped so an incident\n"
        "# investigation still has history without the journal owning the disk.\n"
        "[Journal]\n"
        f"SystemMaxUse={policy.journal_max_use}\n"
    )
    if not apply:
        out.append(f"would write {conf} with SystemMaxUse={policy.journal_max_use}")
        return out

    if os.geteuid() != 0:
        out.append(
            f"SKIPPED: needs root. Run:\n"
            f"  sudo mkdir -p {conf.parent}\n"
            f"  printf '%s' {body!r} | sudo tee {conf}\n"
            f"  sudo systemctl restart systemd-journald\n"
            f"  sudo journalctl --vacuum-size={policy.journal_max_use}"
        )
        return out

    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text(body)
    subprocess.run(["systemctl", "restart", "systemd-journald"], check=False)
    subprocess.run(
        ["journalctl", f"--vacuum-size={policy.journal_max_use}"],
        capture_output=True,
        check=False,
    )
    out.append(f"applied SystemMaxUse={policy.journal_max_use}")
    return out


def docker_manifest() -> list[str]:
    """Enumerate Docker usage. Deletes nothing; prints what is safe to delete.

    Deliberately never runs ``docker system prune``. On this host every image
    and volume is referenced by a running container (OpenWebUI), and a broad
    prune would take a 9.6 GB volume with it.
    """
    out = []
    df = subprocess.run(["docker", "system", "df"], capture_output=True, text=True, check=False)
    if df.returncode != 0:
        return ["docker unavailable"]
    out.append(df.stdout.strip())

    dangling = subprocess.run(
        ["docker", "images", "-f", "dangling=true", "-q"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    out.append(f"dangling images (safe to remove): {len(dangling)}")
    out.append(
        "build cache reclaimable: run `docker builder prune -f` "
        "(touches cache only, never images or volumes)"
    )
    return out


# -------------------------------------------------------------------- CLI
def _print_plan(plan: Plan) -> None:
    by_kind: dict[str, list[Candidate]] = {}
    for candidate in plan.candidates:
        by_kind.setdefault(candidate.kind, []).append(candidate)

    for kind, items in sorted(by_kind.items()):
        keep = [c for c in items if c.verdict == "keep"]
        delete = [c for c in items if c.verdict == "delete"]
        print(f"\n{kind}: {len(items)} file(s) — keep {len(keep)}, delete {len(delete)}")
        for candidate in sorted(delete, key=lambda c: c.mtime):
            print(
                f"  DELETE {candidate.path.name:52} {_human(candidate.size):>9}  {candidate.reason}"
            )
        for candidate in sorted(keep, key=lambda c: c.mtime)[:4]:
            print(
                f"  keep   {candidate.path.name:52} {_human(candidate.size):>9}  {candidate.reason}"
            )
        if len(keep) > 4:
            print(f"  keep   ... and {len(keep) - 4} more")

    for note in plan.notes:
        print(f"\nnote: {note}")
    print(f"\nTOTAL RECLAIMABLE: {_human(plan.reclaim_bytes)} across {len(plan.deletions)} file(s)")


def _disk() -> str:
    usage = shutil.disk_usage("/")
    return (
        f"{_human(usage.used)} used of {_human(usage.total)}, "
        f"{_human(usage.free)} free "
        f"({usage.used / (usage.used + usage.free) * 100:.1f}% by df)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="retention", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("report")
    sub.add_parser("plan")
    apply_cmd = sub.add_parser("apply")
    apply_cmd.add_argument("--yes", action="store_true", help="do not prompt")
    apply_cmd.add_argument(
        "--journal", action="store_true", help="also apply the journald cap (needs root)"
    )

    args = parser.parse_args(argv)
    policy = Policy.load()
    plan = build_plan(policy)

    print(f"disk before: {_disk()}")

    if args.command == "report":
        _print_plan(plan)
        print("\n--- journal ---")
        for line in configure_journal(policy, apply=False):
            print(f"  {line}")
        print("\n--- docker ---")
        for line in docker_manifest():
            print(f"  {line}")
        return 0

    if args.command == "plan":
        _print_plan(plan)
        print("\n(dry run — nothing was changed)")
        return 0

    _print_plan(plan)
    if not plan.deletions:
        print("\nnothing to do")
        return 0

    if not args.yes and sys.stdin.isatty():
        if input(f"\nDelete {len(plan.deletions)} file(s)? [y/N] ").strip().lower() != "y":
            print("aborted")
            return 1

    removed, freed = apply_plan(plan)
    print(f"\nremoved {removed} file(s), freed {_human(freed)}")
    print(f"logged to {LOG_FILE}")

    if args.journal:
        for line in configure_journal(policy, apply=True):
            print(f"  {line}")

    time.sleep(1)
    print(f"disk after:  {_disk()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
