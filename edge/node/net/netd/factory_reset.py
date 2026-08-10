"""Factory network reset.

Deliberately narrow: this removes saved **Wi-Fi client** profiles and nothing
else.  It is the last-resort recovery path for a node whose Wi-Fi
configuration has become unusable -- wrong credentials everywhere, a renamed
campus SSID, a replaced router -- and it must be safe to invoke by someone who
is not sure what else it might touch.

Explicitly preserved:

* the SQLite buffer and every measurement in it
* all logs and journal history
* node identity and the subsystem's own configuration
* Ethernet profiles (on these nodes that is the Shelly sensor segment; wiping
  it would disconnect the meter, which has nothing to do with Wi-Fi)
* the maintenance AP profile, which is recreated rather than removed

Deleted profiles are exported to a timestamped backup directory first, so even
this operation is reversible.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from .ap_manager import AccessPointManager
from .config import Config
from .nm import NetworkManager

log = logging.getLogger("netd.factory_reset")

# NetworkManager keeps profiles here; copies are taken for the backup.
NM_PROFILE_DIR = Path("/etc/NetworkManager/system-connections")


@dataclass
class ResetReport:
    """Outcome of a factory network reset."""

    started_at: float = field(default_factory=time.time)
    backup_path: Optional[Path] = None
    removed: List[str] = field(default_factory=list)
    preserved: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    ap_started: bool = False

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "backup_path": str(self.backup_path) if self.backup_path else None,
            "removed": self.removed,
            "preserved": self.preserved,
            "errors": self.errors,
            "ap_started": self.ap_started,
            "ok": self.ok,
        }


class FactoryNetworkReset:
    """Performs the network-only reset."""

    def __init__(
        self,
        config: Config,
        nm: NetworkManager,
        ap: AccessPointManager,
    ) -> None:
        self._config = config
        self._nm = nm
        self._ap = ap

    # ------------------------------------------------------------------
    def _backup_profiles(self) -> Tuple[Optional[Path], Optional[str]]:
        """Copy NetworkManager profiles aside before deleting anything."""
        stamp = time.strftime("%Y%m%d_%H%M%S")
        target = self._config.paths.var_dir / "network-reset-backups" / stamp
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return None, f"could not create backup directory: {exc}"

        if not NM_PROFILE_DIR.is_dir():
            return target, None
        try:
            for profile in NM_PROFILE_DIR.glob("*.nmconnection"):
                shutil.copy2(profile, target / profile.name)
            # Profiles contain PSKs; keep the backup root-only.
            target.chmod(0o700)
        except OSError as exc:
            return target, f"could not back up all profiles: {exc}"
        return target, None

    # ------------------------------------------------------------------
    def run(self, start_ap: bool = True) -> ResetReport:
        """Execute the reset.

        Ordering matters: back up, then delete, then restart NetworkManager so
        it reloads a clean profile set, then raise the AP.  The AP is raised
        last and unconditionally, because after this operation the node has no
        Wi-Fi credentials at all and the AP is the only way back in.
        """
        report = ResetReport()
        log.warning("FACTORY NETWORK RESET requested - Wi-Fi profiles will be removed")

        backup_path, backup_error = self._backup_profiles()
        report.backup_path = backup_path
        if backup_error:
            report.errors.append(backup_error)
            log.error("%s", backup_error)

        ap_profile = self._config.access_point.profile_name

        # Delete Wi-Fi client profiles only.
        for name, uuid, kind in self._nm.all_connection_names():
            if kind not in ("802-11-wireless", "wifi"):
                report.preserved.append(f"{name} ({kind})")
                continue
            if name == ap_profile:
                report.preserved.append(f"{name} (maintenance AP)")
                continue
            result = self._nm.delete(uuid)
            if result.ok:
                report.removed.append(name)
                log.info("removed Wi-Fi profile %s", name)
            else:
                message = f"could not remove {name}: {result.message}"
                report.errors.append(message)
                log.error("%s", message)

        # Restart NetworkManager so it re-reads a clean profile set.
        try:
            proc = subprocess.run(
                ["systemctl", "restart", "NetworkManager.service"],
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            if proc.returncode != 0:
                message = f"NetworkManager restart failed: {proc.stderr.strip()}"
                report.errors.append(message)
                log.error("%s", message)
            else:
                log.info("NetworkManager restarted")
                # Give it a moment to claim devices before touching the AP.
                time.sleep(5)
        except (subprocess.TimeoutExpired, OSError) as exc:
            message = f"NetworkManager restart failed: {exc}"
            report.errors.append(message)
            log.error("%s", message)

        if start_ap:
            self._ap.ensure_profile(force=True)
            ok, message = self._ap.start()
            report.ap_started = ok
            if not ok:
                report.errors.append(f"could not start maintenance AP: {message}")
                log.error("could not start maintenance AP after reset: %s", message)

        log.warning(
            "factory network reset finished: %d profile(s) removed, AP=%s",
            len(report.removed),
            "up" if report.ap_started else "down",
        )
        return report
