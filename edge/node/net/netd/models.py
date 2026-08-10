"""Domain model for the networking subsystem.

Every type in this module is a plain data container or enumeration.  Nothing
here performs I/O, which keeps the decision logic in :mod:`netd.evaluator` and
:mod:`netd.statemachine` trivially testable.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


class NetState(str, enum.Enum):
    """States of the connectivity state machine.

    The values are stable strings: they are written to the published state
    file, shown in the portal and TUI, and logged.  Do not rename them without
    treating it as a compatibility break.
    """

    BOOT = "BOOT"
    """Initial state. NetworkManager is settling; no judgement made yet."""

    CONNECTING = "CONNECTING"
    """An uplink is being attempted. Grace period before declaring failure."""

    ONLINE = "ONLINE"
    """A usable uplink exists (at minimum: gateway reachable)."""

    OFFLINE_BUFFERING = "OFFLINE_BUFFERING"
    """No usable uplink. The collector keeps buffering; retries continue."""

    MAINTENANCE_AP = "MAINTENANCE_AP"
    """The maintenance access point is active so an operator can intervene."""

    RECOVERING = "RECOVERING"
    """Uplink regained but not yet proven stable; AP teardown is pending."""


class LinkKind(str, enum.Enum):
    """Kind of uplink currently carrying traffic."""

    NONE = "none"
    ETHERNET = "ethernet"
    WIFI = "wifi"
    AP = "ap"


class Security(str, enum.Enum):
    """Wi-Fi security type, normalised from NetworkManager's flag strings."""

    OPEN = "open"
    WEP = "wep"
    WPA_PSK = "wpa-psk"
    WPA_EAP = "wpa-eap"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ScanResult:
    """A single Wi-Fi network observed during a scan."""

    ssid: str
    signal: int
    """Signal quality, 0-100 as reported by NetworkManager."""
    security: Security
    channel: Optional[int] = None
    band: Optional[str] = None
    in_use: bool = False
    saved: bool = False

    @property
    def bars(self) -> str:
        """A coarse 4-step signal indicator suitable for text UIs.

        ASCII only: the Linux virtual console's default font lacks block
        glyphs, and this string is rendered on an attached HDMI display as
        well as in the browser.
        """
        if self.signal >= 75:
            return "[####]"
        if self.signal >= 50:
            return "[###.]"
        if self.signal >= 25:
            return "[##..]"
        return "[#...]"

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["security"] = self.security.value
        d["bars"] = self.bars
        return d


@dataclass(frozen=True)
class SavedNetwork:
    """A Wi-Fi profile persisted in NetworkManager."""

    name: str
    uuid: str
    ssid: str
    autoconnect: bool
    priority: int
    """NetworkManager ``connection.autoconnect-priority``; higher wins."""
    device: Optional[str] = None
    active: bool = False
    managed_by_netd: bool = False
    """True when the profile carries the netd ownership marker."""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InterfaceInfo:
    """Snapshot of one network interface as NetworkManager sees it."""

    device: str
    kind: str
    state: str
    connection: Optional[str]
    ipv4: Optional[str] = None
    gateway: Optional[str] = None
    carrier: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of a single connectivity probe."""

    name: str
    ok: bool
    detail: str = ""
    latency_ms: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ConnectivityVerdict:
    """Aggregated judgement produced by :mod:`netd.evaluator`.

    The layers are deliberately independent: a node can have a gateway but no
    DNS, or internet but no backend.  Each is reported separately so the
    portal and TUI can point an operator at the actual fault.
    """

    link: LinkKind
    interface: Optional[str]
    ipv4: Optional[str]
    ssid: Optional[str]
    gateway_ok: bool
    dns_ok: bool
    internet_ok: bool
    backend_ok: bool
    probes: List[ProbeResult] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
    deep_age: Optional[float] = None
    """Seconds since the DNS/internet/backend probes last actually ran.

    Those probes are expensive and do not run on every monitor cycle.  Their
    results are carried forward between full sweeps, and this field says how
    old they are.  ``None`` means they have never run -- which is *not* the
    same as having failed, and the UIs must not present it as one.
    """

    @property
    def usable(self) -> bool:
        """Whether the node has a network worth staying on.

        Reaching the default gateway is the minimum bar.  A node on an
        isolated LAN with a working backend is still 'usable' even without
        internet, which is the common case on a campus network behind a
        filtering proxy.
        """
        return self.link in (LinkKind.ETHERNET, LinkKind.WIFI) and (
            self.gateway_ok or self.backend_ok
        )

    @property
    def summary(self) -> str:
        if self.link is LinkKind.AP:
            return "maintenance access point active"
        if not self.usable:
            return "no usable uplink"
        parts = [f"link={self.link.value}"]
        parts.append("gw" if self.gateway_ok else "!gw")
        parts.append("dns" if self.dns_ok else "!dns")
        parts.append("net" if self.internet_ok else "!net")
        parts.append("backend" if self.backend_ok else "!backend")
        return " ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "link": self.link.value,
            "interface": self.interface,
            "ipv4": self.ipv4,
            "ssid": self.ssid,
            "gateway_ok": self.gateway_ok,
            "dns_ok": self.dns_ok,
            "internet_ok": self.internet_ok,
            "backend_ok": self.backend_ok,
            "usable": self.usable,
            "summary": self.summary,
            "probes": [p.to_dict() for p in self.probes],
            "timestamp": self.timestamp,
            "deep_age": self.deep_age,
            "deep_measured": self.deep_age is not None,
        }


class Action(str, enum.Enum):
    """Side effects the state machine may request.

    The state machine never performs these itself; the supervisor executes
    them.  This keeps the machine pure and testable.
    """

    NONE = "none"
    START_AP = "start_ap"
    STOP_AP = "stop_ap"
    RETRY_WIFI = "retry_wifi"
    RESCAN = "rescan"


@dataclass(frozen=True)
class Transition:
    """Result of feeding a verdict to the state machine."""

    state: NetState
    previous: NetState
    action: Action = Action.NONE
    reason: str = ""

    @property
    def changed(self) -> bool:
        return self.state is not self.previous
