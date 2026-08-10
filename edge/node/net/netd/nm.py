"""NetworkManager adapter.

This is the **only** module in the subsystem that invokes ``nmcli``.  Every
other component works with the typed values defined in :mod:`netd.models`.
Keeping the boundary here means the rest of the system can be exercised
without a real NetworkManager, and that a future move to the D-Bus API is a
single-file change.

NetworkManager is integrated with, never replaced: profiles are ordinary
connection profiles, autoconnect and priorities are NetworkManager's own, and
nothing here writes to ``/etc/NetworkManager`` directly.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .models import InterfaceInfo, SavedNetwork, ScanResult, Security

log = logging.getLogger("netd.nm")

# Marker written into profiles this subsystem creates, so a factory network
# reset can distinguish our profiles from ones an operator added by hand.
NETD_MARKER = "netd"

CommandRunner = Callable[[Sequence[str], int], "CommandResult"]


@dataclass(frozen=True)
class CommandResult:
    """Result of an external command invocation."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def message(self) -> str:
        text = (self.stderr or self.stdout or "").strip()
        return text.splitlines()[-1] if text else f"exit {self.returncode}"


def _run(argv: Sequence[str], timeout: int = 30) -> CommandResult:
    """Execute ``argv``, never raising for non-zero exit."""
    try:
        proc = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return CommandResult(proc.returncode, proc.stdout, proc.stderr)
    except subprocess.TimeoutExpired:
        return CommandResult(124, "", f"timeout after {timeout}s")
    except FileNotFoundError as exc:
        return CommandResult(127, "", str(exc))
    except OSError as exc:  # pragma: no cover - defensive
        return CommandResult(1, "", str(exc))


def split_terse(line: str) -> List[str]:
    """Split one line of ``nmcli --terse`` output.

    ``nmcli`` escapes literal ``:`` and ``\\`` inside fields with a backslash,
    so a naive ``str.split(':')`` corrupts SSIDs that contain a colon.
    """
    fields: List[str] = []
    current: List[str] = []
    escaped = False
    for ch in line:
        if escaped:
            current.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(ch)
    fields.append("".join(current))
    return fields


def parse_security(flags: str) -> Security:
    """Normalise an ``nmcli`` security flag string into a :class:`Security`."""
    value = (flags or "").strip().upper()
    if not value or value == "--":
        return Security.OPEN
    if "802.1X" in value or "EAP" in value:
        return Security.WPA_EAP
    if "WPA" in value or "RSN" in value:
        return Security.WPA_PSK
    if "WEP" in value:
        return Security.WEP
    return Security.UNKNOWN


class NetworkManagerError(RuntimeError):
    """Raised when a NetworkManager mutation fails."""


class NetworkManager:
    """Typed facade over ``nmcli``."""

    def __init__(self, runner: Optional[CommandRunner] = None, default_timeout: int = 30) -> None:
        self._run: CommandRunner = runner or _run
        self._timeout = default_timeout

    # ------------------------------------------------------------------
    # low level
    # ------------------------------------------------------------------
    def nmcli(self, *args: str, timeout: Optional[int] = None) -> CommandResult:
        """Invoke ``nmcli`` with the given arguments."""
        return self._run(["nmcli", *args], timeout or self._timeout)

    @staticmethod
    def available() -> bool:
        """Whether ``nmcli`` exists on this system."""
        return shutil.which("nmcli") is not None

    def running(self) -> bool:
        """Whether the NetworkManager daemon is answering."""
        return self.nmcli("-t", "-f", "RUNNING", "general", timeout=10).ok

    # ------------------------------------------------------------------
    # inspection
    # ------------------------------------------------------------------
    def devices(self) -> List[InterfaceInfo]:
        """All devices NetworkManager knows about."""
        res = self.nmcli("-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status", timeout=15)
        if not res.ok:
            log.warning("device status failed: %s", res.message)
            return []
        out: List[InterfaceInfo] = []
        for line in res.stdout.splitlines():
            if not line.strip():
                continue
            parts = split_terse(line)
            if len(parts) < 4:
                continue
            device, kind, state, conn = parts[0], parts[1], parts[2], parts[3]
            ipv4, gateway = self.device_ipv4(device)
            out.append(
                InterfaceInfo(
                    device=device,
                    kind=kind,
                    state=state,
                    connection=conn or None,
                    ipv4=ipv4,
                    gateway=gateway,
                    carrier=state not in ("unavailable", "unmanaged"),
                )
            )
        return out

    def device_ipv4(self, device: str) -> Tuple[Optional[str], Optional[str]]:
        """Return ``(address/prefix, gateway)`` for ``device``."""
        res = self.nmcli(
            "-t", "-f", "IP4.ADDRESS,IP4.GATEWAY", "device", "show", device, timeout=15
        )
        if not res.ok:
            return None, None
        address: Optional[str] = None
        gateway: Optional[str] = None
        for line in res.stdout.splitlines():
            parts = split_terse(line)
            if len(parts) < 2:
                continue
            key, value = parts[0], parts[1]
            value = value.strip()
            if not value or value == "--":
                continue
            if key.startswith("IP4.ADDRESS") and address is None:
                address = value
            elif key.startswith("IP4.GATEWAY") and gateway is None:
                gateway = value
        return address, gateway

    def connections(self) -> List[SavedNetwork]:
        """All saved connection profiles."""
        res = self.nmcli(
            "-t",
            "-f",
            "NAME,UUID,TYPE,DEVICE,AUTOCONNECT,AUTOCONNECT-PRIORITY",
            "connection",
            "show",
            timeout=15,
        )
        if not res.ok:
            log.warning("connection show failed: %s", res.message)
            return []
        out: List[SavedNetwork] = []
        for line in res.stdout.splitlines():
            if not line.strip():
                continue
            parts = split_terse(line)
            if len(parts) < 6:
                continue
            name, uuid, kind, device, autoconnect, priority = parts[:6]
            if kind not in ("802-11-wireless", "wifi"):
                continue
            try:
                prio = int(priority)
            except ValueError:
                prio = 0
            out.append(
                SavedNetwork(
                    name=name,
                    uuid=uuid,
                    ssid=self.connection_ssid(uuid) or name,
                    autoconnect=autoconnect.lower() in ("yes", "true"),
                    priority=prio,
                    device=device or None,
                    active=bool(device and device != "--"),
                    managed_by_netd=self.connection_field(uuid, "connection.zone") == NETD_MARKER,
                )
            )
        return out

    def all_connection_names(self) -> List[Tuple[str, str, str]]:
        """Return ``(name, uuid, type)`` for every profile, any type."""
        res = self.nmcli("-t", "-f", "NAME,UUID,TYPE", "connection", "show", timeout=15)
        if not res.ok:
            return []
        out = []
        for line in res.stdout.splitlines():
            if not line.strip():
                continue
            parts = split_terse(line)
            if len(parts) >= 3:
                out.append((parts[0], parts[1], parts[2]))
        return out

    def connection_field(self, ident: str, field: str) -> Optional[str]:
        """Read one property from a saved profile."""
        res = self.nmcli("-t", "-f", field, "connection", "show", ident, timeout=15)
        if not res.ok:
            return None
        for line in res.stdout.splitlines():
            parts = split_terse(line)
            if len(parts) >= 2 and parts[0] == field:
                value = parts[1].strip()
                return value if value and value != "--" else None
        return None

    def connection_ssid(self, ident: str) -> Optional[str]:
        return self.connection_field(ident, "802-11-wireless.ssid")

    def active_wifi_ssid(self, device: str) -> Optional[str]:
        """SSID currently associated on ``device``, if any."""
        res = self.nmcli(
            "-t", "-f", "GENERAL.CONNECTION", "device", "show", device, timeout=15
        )
        if not res.ok:
            return None
        for line in res.stdout.splitlines():
            parts = split_terse(line)
            if len(parts) >= 2:
                value = parts[1].strip()
                return value if value and value != "--" else None
        return None

    def scan(self, device: str, rescan: bool = True) -> List[ScanResult]:
        """Scan for Wi-Fi networks, strongest first, deduplicated by SSID."""
        if rescan:
            # A failed rescan is not fatal: cached results are still useful.
            self.nmcli("device", "wifi", "rescan", "ifname", device, timeout=30)
        res = self.nmcli(
            "-t",
            "-f",
            "IN-USE,SSID,SIGNAL,SECURITY,CHAN",
            "device",
            "wifi",
            "list",
            "ifname",
            device,
            timeout=30,
        )
        if not res.ok:
            log.warning("wifi list failed: %s", res.message)
            return []

        saved_ssids = {n.ssid for n in self.connections()}
        best: Dict[str, ScanResult] = {}
        for line in res.stdout.splitlines():
            if not line.strip():
                continue
            parts = split_terse(line)
            if len(parts) < 5:
                continue
            in_use, ssid, signal, security, chan = parts[:5]
            ssid = ssid.strip()
            if not ssid or ssid == "--":
                continue  # hidden network; nothing actionable to show
            try:
                sig = int(signal)
            except ValueError:
                sig = 0
            try:
                channel: Optional[int] = int(chan)
            except ValueError:
                channel = None
            entry = ScanResult(
                ssid=ssid,
                signal=sig,
                security=parse_security(security),
                channel=channel,
                band="5GHz" if channel and channel > 14 else "2.4GHz",
                in_use=in_use.strip() == "*",
                saved=ssid in saved_ssids,
            )
            existing = best.get(ssid)
            if existing is None or entry.signal > existing.signal:
                best[ssid] = entry
        return sorted(best.values(), key=lambda r: r.signal, reverse=True)

    # ------------------------------------------------------------------
    # mutation
    # ------------------------------------------------------------------
    def up(self, ident: str, timeout: int = 60) -> CommandResult:
        """Activate a profile."""
        log.info("activating profile %s", ident)
        return self.nmcli("connection", "up", ident, timeout=timeout)

    def down(self, ident: str, timeout: int = 30) -> CommandResult:
        """Deactivate a profile."""
        log.info("deactivating profile %s", ident)
        return self.nmcli("connection", "down", ident, timeout=timeout)

    def delete(self, ident: str) -> CommandResult:
        log.info("deleting profile %s", ident)
        return self.nmcli("connection", "delete", ident, timeout=30)

    def modify(self, ident: str, settings: Dict[str, str]) -> CommandResult:
        args: List[str] = ["connection", "modify", ident]
        for key, value in settings.items():
            args += [key, value]
        return self.nmcli(*args, timeout=30)

    def device_connect(self, device: str, timeout: int = 60) -> CommandResult:
        """Ask NetworkManager to bring ``device`` back to normal autoconnect."""
        return self.nmcli("device", "connect", device, timeout=timeout)

    def device_disconnect(self, device: str, timeout: int = 30) -> CommandResult:
        return self.nmcli("device", "disconnect", device, timeout=timeout)

    def radio_wifi_on(self) -> CommandResult:
        return self.nmcli("radio", "wifi", "on", timeout=15)

    def add_wifi(
        self,
        ssid: str,
        password: Optional[str],
        *,
        device: str,
        priority: int = 0,
        name: Optional[str] = None,
        hidden: bool = False,
    ) -> Tuple[bool, str]:
        """Create (or replace) a Wi-Fi client profile.

        Returns ``(ok, message)``.  An existing profile for the same SSID is
        removed first so repeated 'connect' actions from the portal are
        idempotent rather than accumulating duplicates.
        """
        if not ssid:
            return False, "SSID must not be empty"
        if password is not None and password != "" and len(password) < 8:
            return False, "WPA passphrase must be at least 8 characters"

        profile = name or f"en-{ssid}"
        for existing in self.connections():
            if existing.ssid == ssid or existing.name == profile:
                self.delete(existing.uuid)

        args: List[str] = [
            "connection", "add",
            "type", "wifi",
            "ifname", device,
            "con-name", profile,
            "ssid", ssid,
            "connection.autoconnect", "yes",
            "connection.autoconnect-priority", str(priority),
            "connection.zone", NETD_MARKER,
        ]
        if hidden:
            args += ["802-11-wireless.hidden", "yes"]
        if password:
            args += [
                "wifi-sec.key-mgmt", "wpa-psk",
                "wifi-sec.psk", password,
            ]
        res = self.nmcli(*args, timeout=30)
        if not res.ok:
            return False, res.message
        return True, profile

    def set_priority(self, ident: str, priority: int) -> Tuple[bool, str]:
        """Set autoconnect priority; higher values are preferred."""
        res = self.modify(ident, {"connection.autoconnect-priority": str(priority)})
        return res.ok, res.message

    def set_autoconnect(self, ident: str, enabled: bool) -> Tuple[bool, str]:
        res = self.modify(ident, {"connection.autoconnect": "yes" if enabled else "no"})
        return res.ok, res.message

    def ensure_ap_profile(
        self,
        *,
        name: str,
        ssid: str,
        password: str,
        device: str,
        address: str,
        prefix: int,
        band: str = "bg",
        channel: int = 6,
        hidden: bool = False,
    ) -> Tuple[bool, str]:
        """Create or update the maintenance AP profile, idempotently.

        The profile is deliberately ``autoconnect=no`` with a strongly negative
        priority: the AP must only ever come up because the supervisor decided
        it should, never because NetworkManager picked it during normal
        autoconnect.
        """
        if len(password) < 8:
            return False, "AP password must be at least 8 characters"

        settings: Dict[str, str] = {
            "802-11-wireless.ssid": ssid,
            "802-11-wireless.mode": "ap",
            "802-11-wireless.band": band,
            "802-11-wireless.channel": str(channel),
            "802-11-wireless.hidden": "yes" if hidden else "no",
            "wifi-sec.key-mgmt": "wpa-psk",
            "wifi-sec.proto": "rsn",
            "wifi-sec.group": "ccmp",
            "wifi-sec.pairwise": "ccmp",
            "wifi-sec.psk": password,
            "ipv4.method": "shared",
            "ipv4.addresses": f"{address}/{prefix}",
            "ipv6.method": "ignore",
            "connection.autoconnect": "no",
            "connection.autoconnect-priority": "-999",
            "connection.interface-name": device,
            "connection.zone": NETD_MARKER,
        }

        exists = any(n == name or u == name for n, u, _ in self.all_connection_names())
        if not exists:
            res = self.nmcli(
                "connection", "add",
                "type", "wifi",
                "ifname", device,
                "con-name", name,
                "autoconnect", "no",
                "ssid", ssid,
                timeout=30,
            )
            if not res.ok:
                return False, f"could not create AP profile: {res.message}"

        res = self.modify(name, settings)
        if not res.ok:
            return False, f"could not configure AP profile: {res.message}"
        return True, "ap profile ready"

    def is_active(self, ident: str) -> bool:
        """Whether a profile is currently activated."""
        res = self.nmcli("-t", "-f", "NAME,UUID", "connection", "show", "--active", timeout=15)
        if not res.ok:
            return False
        for line in res.stdout.splitlines():
            parts = split_terse(line)
            if ident in parts:
                return True
        return False

    def reload(self) -> CommandResult:
        return self.nmcli("connection", "reload", timeout=30)
