"""The effective Wi-Fi whitelist, its credentials, and its health. I/O layer.

THREE STORES, THREE OWNERS

    network.yaml                     git-managed baseline. SSIDs, priorities
                                     and metadata only. NEVER a passphrase -
                                     this file is in a public repository.

    operator-networks.json           networks a technician added at the node,
                                     through the maintenance portal. Git has
                                     no opinion about this file and a
                                     deployment never rewrites it.

    secrets.json  (0600 root:root)   passphrases, for both sources. Written
                                     only by netd, which runs as root.

WHY A DEPLOYMENT CANNOT DELETE AN OPERATOR NETWORK
    The two lists are merged, not synchronised. A deployment replaces the
    baseline; the operator list is a separate file it never touches. Someone
    standing at a dead node in another building knows something git does not,
    and losing that on the next deploy would strand the node exactly where it
    is hardest to reach. `reset_operator_networks()` is the explicit,
    deliberate way back to the baseline.

WHY THE PORTAL DOES NOT WRITE THE SECRETS FILE
    The portal runs as an unprivileged user with CAP_NET_BIND_SERVICE and
    nothing else; every privileged action is delegated to netd over the
    control socket. Giving it write access to a credential store would
    undo that. It asks; netd writes.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .netselect import (BASELINE, OPERATOR, KnownNetwork, NetHealth,
                        merge_whitelist)

log = logging.getLogger("netd.knownnets")

OPERATOR_FILE = "operator-networks.json"
SECRETS_FILE = "secrets.json"
HEALTH_FILE = "network-health.json"

SECRETS_MODE = 0o600
DATA_MODE = 0o640


def _atomic_write(path: Path, payload: dict, mode: int) -> None:
    """Write or leave the previous file intact. Never a half-written store."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read(path: Path) -> Optional[dict]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        # Loud, and degrade to empty rather than refusing to run: a corrupt
        # operator list must not stop the node reaching a known network.
        log.error("%s is unreadable (%s) - treating as empty", path, exc)
        return None


class KnownNetworkStore:
    """Owns the operator list, the secrets and the health file."""

    def __init__(self, var_dir: Path, baseline: Sequence[KnownNetwork] = ()) -> None:
        self._dir = Path(var_dir)
        self._baseline = list(baseline)

    # ------------------------------------------------------------------ paths
    @property
    def operator_path(self) -> Path:
        return self._dir / OPERATOR_FILE

    @property
    def secrets_path(self) -> Path:
        return self._dir / SECRETS_FILE

    @property
    def health_path(self) -> Path:
        return self._dir / HEALTH_FILE

    # --------------------------------------------------------------- baseline
    @property
    def baseline(self) -> List[KnownNetwork]:
        return list(self._baseline)

    # --------------------------------------------------------------- operator
    def _operator_doc(self) -> dict:
        return _read(self.operator_path) or {"networks": [], "suppressed": []}

    def operator_networks(self) -> List[KnownNetwork]:
        doc = self._operator_doc()
        out = []
        for entry in doc.get("networks", []):
            if not isinstance(entry, dict) or not entry.get("ssid"):
                continue
            out.append(KnownNetwork(
                ssid=str(entry["ssid"]),
                priority=int(entry.get("priority") or 0),
                source=OPERATOR,
                hidden=bool(entry.get("hidden")),
                open=bool(entry.get("open")),
                notes=str(entry.get("notes") or ""),
            ))
        return out

    def suppressed(self) -> List[str]:
        return [str(s) for s in self._operator_doc().get("suppressed", [])]

    def effective(self) -> List[KnownNetwork]:
        """Baseline + operator, operator winning, minus suppressed."""
        return merge_whitelist(self._baseline, self.operator_networks(),
                               self.suppressed())

    def add_operator_network(self, ssid: str, priority: int = 0,
                             hidden: bool = False, open_network: bool = False,
                             notes: str = "") -> Tuple[bool, str]:
        ssid = (ssid or "").strip()
        if not ssid:
            return False, "SSID must not be empty"
        doc = self._operator_doc()
        nets = [n for n in doc.get("networks", [])
                if isinstance(n, dict) and n.get("ssid") != ssid]
        nets.append({"ssid": ssid, "priority": int(priority),
                     "hidden": bool(hidden), "open": bool(open_network),
                     "notes": str(notes)})
        doc["networks"] = nets
        # Adding a network un-suppresses it: the operator has changed their mind.
        doc["suppressed"] = [s for s in doc.get("suppressed", []) if s != ssid]
        _atomic_write(self.operator_path, doc, DATA_MODE)
        log.info("operator network saved: %s (priority %d)", ssid, priority)
        return True, f"saved {ssid}"

    def remove_operator_network(self, ssid: str) -> Tuple[bool, str]:
        """Remove an operator entry; suppress it if it came from the baseline.

        Without the suppression a forgotten baseline network would silently
        reappear on the next deployment, which is indistinguishable from the
        forget having failed.
        """
        doc = self._operator_doc()
        before = len(doc.get("networks", []))
        doc["networks"] = [n for n in doc.get("networks", [])
                           if isinstance(n, dict) and n.get("ssid") != ssid]
        removed = len(doc["networks"]) != before

        if any(n.ssid == ssid for n in self._baseline):
            sup = set(doc.get("suppressed", []))
            sup.add(ssid)
            doc["suppressed"] = sorted(sup)
            removed = True

        if not removed:
            return False, f"{ssid} is not a known network"
        _atomic_write(self.operator_path, doc, DATA_MODE)
        self.forget_secret(ssid)
        log.info("operator network removed: %s", ssid)
        return True, f"removed {ssid}"

    def reset_operator_networks(self) -> Tuple[bool, str]:
        """Explicitly return to the git baseline. Deliberate, never automatic."""
        doc = self._operator_doc()
        count = len(doc.get("networks", []))
        removed_ssids = [n.get("ssid") for n in doc.get("networks", [])
                         if isinstance(n, dict)]
        _atomic_write(self.operator_path, {"networks": [], "suppressed": []},
                      DATA_MODE)
        for ssid in removed_ssids:
            if ssid:
                self.forget_secret(str(ssid))
        log.warning("operator networks reset to baseline (%d removed)", count)
        return True, (f"reset to baseline; removed {count} operator network(s) "
                      f"and their credentials")

    # ---------------------------------------------------------------- secrets
    def _secrets(self) -> dict:
        return _read(self.secrets_path) or {}

    def set_secret(self, ssid: str, password: Optional[str]) -> None:
        """Store or clear a passphrase. netd only - never the portal directly."""
        doc = self._secrets()
        if password:
            doc[ssid] = password
        else:
            doc.pop(ssid, None)
        _atomic_write(self.secrets_path, doc, SECRETS_MODE)

    def secret_for(self, ssid: str) -> Optional[str]:
        return self._secrets().get(ssid)

    def forget_secret(self, ssid: str) -> None:
        doc = self._secrets()
        if ssid in doc:
            doc.pop(ssid, None)
            _atomic_write(self.secrets_path, doc, SECRETS_MODE)

    def secrets_audit(self) -> dict:
        """Which SSIDs have a stored credential. Never the credentials."""
        try:
            mode = oct(self.secrets_path.stat().st_mode & 0o777)
        except OSError:
            mode = "absent"
        return {"path": str(self.secrets_path), "mode": mode,
                "ssids_with_credentials": sorted(self._secrets().keys())}

    # ----------------------------------------------------------------- health
    def health(self) -> Dict[str, NetHealth]:
        doc = _read(self.health_path) or {}
        out: Dict[str, NetHealth] = {}
        for ssid, entry in doc.items():
            if isinstance(entry, dict):
                entry.setdefault("ssid", ssid)
                out[ssid] = NetHealth.from_dict(entry)
        return out

    def save_health(self, health: Dict[str, NetHealth]) -> None:
        _atomic_write(self.health_path,
                      {k: v.as_dict() for k, v in health.items()}, DATA_MODE)

    # ------------------------------------------------------------------ audit
    def describe(self) -> dict:
        """Everything an operator or the portal may see. No credentials."""
        secrets = set(self._secrets().keys())
        return {
            "baseline": [n.redacted() for n in self._baseline],
            "operator": [n.redacted() for n in self.operator_networks()],
            "suppressed": self.suppressed(),
            "effective": [
                dict(n.redacted(), has_credential=(n.ssid in secrets))
                for n in self.effective()
            ],
        }
