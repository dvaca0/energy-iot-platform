"""Hardening package version management.

A field node must be able to answer "what exactly is installed on you?"
without anyone reading source. Tracks:

    hardening version · install date · last upgrade date · package checksum
    configuration version · driver versions · verification (doctor) version

The checksum covers every executable artefact (lib/, bin/, systemd/), so
drift — a hand-edited file on one node — is detectable across the fleet.

STATE FILE
    /opt/energy-node/state/hardening.json
    Written by the installer, read by `energy-node hardening status` and by
    the doctor. Never written by the running services.

COMPATIBILITY
    The installer calls check_upgrade() BEFORE replacing anything. A downgrade
    or a cross-major upgrade is refused unless explicitly forced, because a
    config written for a newer schema can silently mean something different
    to older code.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from typing import Optional

_LIB = os.path.dirname(os.path.abspath(__file__))
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

import enconfig  # noqa: E402

__version__ = "1.0.0"

#: Bump MAJOR when the config schema changes incompatibly.
PACKAGE_VERSION = "1.1.0"
#: Bump when hardening.conf gains/renames keys that older code cannot honour.
CONFIG_SCHEMA_VERSION = "2"

PKG_ROOT = os.path.dirname(_LIB)
STATE_PATH_DEFAULT = "/opt/energy-node/state/hardening.json"

#: Directories whose contents define the package identity.
CHECKSUM_DIRS = ("lib", "bin", "systemd")
CHECKSUM_SKIP = ("__pycache__", ".pyc", ".swp", "~")


def state_path() -> str:
    return os.path.join(enconfig.get("EN_STATE_DIR",
                                     "/opt/energy-node/state"),
                        "hardening.json")


# ------------------------------------------------------------- checksum
def _iter_files(root: str):
    for d in CHECKSUM_DIRS:
        base = os.path.join(root, d)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [x for x in dirnames if x not in CHECKSUM_SKIP]
            for fn in sorted(filenames):
                if any(fn.endswith(s) for s in CHECKSUM_SKIP):
                    continue
                yield os.path.join(dirpath, fn)


def package_checksum(root: Optional[str] = None) -> str:
    """Deterministic SHA-256 over every executable artefact.

    Path-relative and sorted, so it is stable across nodes — two nodes running
    identical code produce an identical checksum, which is what makes fleet
    drift visible.
    """
    root = root or PKG_ROOT
    h = hashlib.sha256()
    for path in sorted(_iter_files(root)):
        rel = os.path.relpath(path, root)
        h.update(rel.encode())
        try:
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    h.update(chunk)
        except OSError:
            h.update(b"<unreadable>")
    return h.hexdigest()


def driver_versions() -> dict:
    """Versions of the pluggable pieces, so a driver fix is traceable."""
    out = {}
    try:
        import ups as ups_pkg
        out["ups_drivers"] = sorted(ups_pkg.REGISTRY)
    except Exception:
        out["ups_drivers"] = []
    for mod in ("tristate", "sensors", "doctor", "telemetry", "heartbeat",
                "powerlog", "i2cbus", "sysinfo"):
        try:
            m = __import__(mod)
            out[mod] = getattr(m, "__version__", "unversioned")
        except Exception:
            out[mod] = "unavailable"
    return out


# ------------------------------------------------------------- state I/O
def read_state() -> dict:
    try:
        with open(state_path()) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def write_state(**overrides) -> dict:
    st = read_state()
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    first = st.get("installed_at") or now
    new = {
        "package_version": PACKAGE_VERSION,
        "config_schema_version": CONFIG_SCHEMA_VERSION,
        "installed_at": first,
        "upgraded_at": now if st.get("package_version") not in (None, PACKAGE_VERSION)
                       else st.get("upgraded_at"),
        "last_install_run_at": now,
        "package_checksum": package_checksum(),
        "doctor_version": _safe_version("doctor"),
        "drivers": driver_versions(),
        "node_id": enconfig.node_id(),
        "previous_version": st.get("package_version"),
    }
    new.update(overrides)
    path = state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(new, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)
    return new


def _safe_version(mod: str) -> str:
    try:
        return getattr(__import__(mod), "__version__", "unversioned")
    except Exception:
        return "unavailable"


def installed_version() -> Optional[str]:
    return read_state().get("package_version")


# ------------------------------------------------------- compatibility
def _parse(v: str) -> tuple:
    try:
        return tuple(int(x) for x in str(v).split(".")[:3])
    except (TypeError, ValueError):
        return (0, 0, 0)


def check_upgrade(force: bool = False) -> tuple:
    """Decide whether installing PACKAGE_VERSION over the installed one is safe.

    Returns (ok: bool, message: str). Called by install.sh BEFORE it replaces
    anything.
    """
    st = read_state()
    current = st.get("package_version")
    if not current:
        return True, f"fresh install of {PACKAGE_VERSION}"

    cur, new = _parse(current), _parse(PACKAGE_VERSION)
    if new == cur:
        return True, f"reinstall of {PACKAGE_VERSION} (idempotent)"
    if new < cur:
        if force:
            return True, (f"DOWNGRADE {current} -> {PACKAGE_VERSION} forced")
        return False, (
            f"refusing to downgrade {current} -> {PACKAGE_VERSION}. A config "
            f"written for the newer schema can mean something different to "
            f"older code. Re-run with --force if you accept that.")
    if new[0] != cur[0]:
        if force:
            return True, f"MAJOR upgrade {current} -> {PACKAGE_VERSION} forced"
        return False, (
            f"major version change {current} -> {PACKAGE_VERSION}: the config "
            f"schema is not guaranteed compatible. Review "
            f"config/hardening.conf.new against your config, then re-run with "
            f"--force.")

    old_schema = st.get("config_schema_version")
    if old_schema and old_schema != CONFIG_SCHEMA_VERSION and not force:
        return True, (
            f"upgrade {current} -> {PACKAGE_VERSION}; NOTE config schema "
            f"{old_schema} -> {CONFIG_SCHEMA_VERSION}, new keys will use "
            f"defaults until you merge hardening.conf.new")
    return True, f"upgrade {current} -> {PACKAGE_VERSION}"


def verify_integrity() -> tuple:
    """Compare the on-disk checksum against what the installer recorded."""
    st = read_state()
    recorded = st.get("package_checksum")
    if not recorded:
        return None, "no checksum recorded (package never installed via install.sh)"
    actual = package_checksum()
    if actual == recorded:
        return True, f"checksum matches ({actual[:12]})"
    return False, (f"CHECKSUM MISMATCH — files changed since install. "
                   f"recorded {recorded[:12]}, actual {actual[:12]}")


# ------------------------------------------------------------- reporting
def status_dict() -> dict:
    st = read_state()
    ok, msg = verify_integrity()
    return {
        "installed": bool(st),
        "package_version": st.get("package_version"),
        "running_version": PACKAGE_VERSION,
        "config_schema_version": st.get("config_schema_version"),
        "installed_at": st.get("installed_at"),
        "upgraded_at": st.get("upgraded_at"),
        "last_install_run_at": st.get("last_install_run_at"),
        "package_checksum": st.get("package_checksum"),
        "checksum_ok": ok,
        "checksum_detail": msg,
        "doctor_version": st.get("doctor_version"),
        "drivers": st.get("drivers", {}),
        "node_id": st.get("node_id"),
        "previous_version": st.get("previous_version"),
    }


def doctor_result():
    """Result for the doctor's hardening_version check."""
    from tristate import Outcome, Result, Tri
    d = status_dict()
    if not d["installed"]:
        return Result("hardening_version", Outcome.WARN,
                      "no install state recorded — package present but never "
                      "installed via install.sh", Tri.UNKNOWN, None)
    if d["checksum_ok"] is False:
        return Result("hardening_version", Outcome.WARN,
                      f"v{d['package_version']} — {d['checksum_detail']}",
                      Tri.TRUE, d["package_version"])
    drift = ""
    if d["package_version"] != PACKAGE_VERSION:
        drift = (f" (running code is {PACKAGE_VERSION}, state says "
                 f"{d['package_version']} — re-run install.sh)")
        return Result("hardening_version", Outcome.WARN,
                      f"version drift{drift}", Tri.TRUE, d["package_version"])
    return Result("hardening_version", Outcome.PASS,
                  f"v{d['package_version']} schema {d['config_schema_version']} "
                  f"installed {d['installed_at']} checksum "
                  f"{(d['package_checksum'] or '')[:12]}",
                  Tri.FALSE, d["package_version"])


def print_status() -> int:
    d = status_dict()
    if not d["installed"]:
        print("hardening: NOT INSTALLED via install.sh")
        print(f"  running code version: {PACKAGE_VERSION}")
        print(f"  on-disk checksum    : {package_checksum()[:16]}")
        return 1
    print(f"=== energy-node hardening — {d['node_id']} ===")
    print(f"  package version      : {d['package_version']}")
    if d["package_version"] != PACKAGE_VERSION:
        print(f"  RUNNING CODE VERSION : {PACKAGE_VERSION}  <-- DRIFT")
    print(f"  config schema        : {d['config_schema_version']}")
    print(f"  installed at         : {d['installed_at']}")
    print(f"  last upgrade         : {d['upgraded_at'] or '(never upgraded)'}")
    print(f"  last install run     : {d['last_install_run_at']}")
    print(f"  previous version     : {d['previous_version'] or '(none)'}")
    print(f"  package checksum     : {d['package_checksum']}")
    print(f"  checksum status      : {d['checksum_detail']}")
    print(f"  doctor version       : {d['doctor_version']}")
    print("  driver / module versions:")
    for k, v in sorted((d.get("drivers") or {}).items()):
        print(f"     {k:16} {v}")
    return 0 if d["checksum_ok"] is not False else 1


if __name__ == "__main__":
    sys.exit(print_status())
