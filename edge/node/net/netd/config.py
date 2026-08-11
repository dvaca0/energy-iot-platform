"""Typed configuration loading.

Configuration lives in a single readable YAML file (by default
``/opt/energy-node/net/config/network.yaml``).  Every value has a documented
default, so a truncated or partially hand-edited file degrades to sane
behaviour rather than refusing to start -- an appliance that will not boot its
networking stack because of a typo is exactly the failure this subsystem
exists to prevent.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import yaml

log = logging.getLogger("netd.config")

DEFAULT_CONFIG_PATH = Path("/opt/energy-node/net/config/network.yaml")

# Where the subsystem publishes the collector-facing contract.
DEFAULT_STATE_DIR = Path("/run/energy-node")


def _get(mapping: Mapping[str, Any], key: str, default: Any) -> Any:
    """Fetch ``key`` from ``mapping``, falling back to ``default`` on None."""
    value = mapping.get(key, default)
    return default if value is None else value


@dataclass(frozen=True)
class NodeConfig:
    """Identity of this physical node."""

    id: str = "N000"
    hostname: str = "energy-node"
    model: str = "unknown"
    site: str = ""

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "NodeConfig":
        return cls(
            id=str(_get(d, "id", "N000")),
            hostname=str(_get(d, "hostname", "energy-node")),
            model=str(_get(d, "model", "unknown")),
            site=str(_get(d, "site", "")),
        )


@dataclass(frozen=True)
class InterfaceConfig:
    """Which kernel interfaces play which role.

    ``ethernet_is_uplink`` is the important one.  On these nodes ``eth0`` is
    normally a private sensor segment carrying the Shelly meter and offering no
    default route.  Treating it as an uplink unconditionally would declare the
    node online while it has no path to anything.  When this is ``auto`` the
    subsystem promotes Ethernet to uplink only if it actually carries a
    default route.
    """

    wifi: str = "wlan0"
    ethernet: str = "eth0"
    ethernet_is_uplink: str = "auto"  # auto | always | never
    sensor_subnet: str = "192.168.50.0/24"

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "InterfaceConfig":
        mode = str(_get(d, "ethernet_is_uplink", "auto")).lower()
        if mode not in ("auto", "always", "never"):
            mode = "auto"
        return cls(
            wifi=str(_get(d, "wifi", "wlan0")),
            ethernet=str(_get(d, "ethernet", "eth0")),
            ethernet_is_uplink=mode,
            sensor_subnet=str(_get(d, "sensor_subnet", "192.168.50.0/24")),
        )


@dataclass(frozen=True)
class AccessPointConfig:
    """Maintenance access point parameters."""

    enabled: bool = True
    ssid_format: str = "EnergyNode-{node_id}"
    password: str = "maintenance"
    profile_name: str = "energy-node-maintenance-ap"
    address: str = "192.168.66.1"
    prefix: int = 24
    channel: int = 6
    band: str = "bg"
    hidden: bool = False
    portal_port: int = 80

    @property
    def cidr(self) -> str:
        return f"{self.address}/{self.prefix}"

    def ssid_for(self, node_id: str) -> str:
        """Render the per-node SSID, tolerating a malformed format string."""
        try:
            return self.ssid_format.format(node_id=node_id)
        except (KeyError, IndexError, ValueError):
            return f"EnergyNode-{node_id}"

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "AccessPointConfig":
        return cls(
            enabled=bool(_get(d, "enabled", True)),
            ssid_format=str(_get(d, "ssid_format", "EnergyNode-{node_id}")),
            password=str(_get(d, "password", "maintenance")),
            profile_name=str(_get(d, "profile_name", "energy-node-maintenance-ap")),
            address=str(_get(d, "address", "192.168.66.1")),
            prefix=int(_get(d, "prefix", 24)),
            channel=int(_get(d, "channel", 6)),
            band=str(_get(d, "band", "bg")),
            hidden=bool(_get(d, "hidden", False)),
            portal_port=int(_get(d, "portal_port", 80)),
        )


@dataclass(frozen=True)
class TimingConfig:
    """Every timeout and interval the subsystem observes, in seconds.

    Defaults are tuned for a headless appliance on a campus network: patient
    enough not to flap the AP during a transient outage, fast enough that a
    technician standing next to a dead node is not waiting more than a couple
    of minutes.
    """

    boot_grace: int = 45
    """How long to let NetworkManager settle at boot before judging."""

    connect_grace: int = 60
    """How long CONNECTING may last before falling back to offline."""

    offline_before_ap: int = 180
    """Continuous offline time before the maintenance AP is raised."""

    stable_before_ap_down: int = 60
    """Uplink must be continuously usable this long before the AP is dropped."""

    monitor_interval: int = 10
    """Base evaluation period of the supervisor loop."""

    probe_timeout: int = 4
    """Per-probe network timeout."""

    retry_backoff_initial: int = 15
    retry_backoff_max: int = 300
    """Reconnect backoff bounds; prevents endless tight reconnect loops."""

    scan_min_interval: int = 30
    """Floor between Wi-Fi scans; scanning is disruptive on a single radio."""

    ap_min_uptime: int = 120
    """Once raised, the AP stays up at least this long so an operator can
    actually associate and finish a configuration change."""

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "TimingConfig":
        defaults = cls()
        values: Dict[str, Any] = {}
        for f in defaults.__dataclass_fields__:  # noqa: SLF001 - dataclass API
            raw = _get(d, f, getattr(defaults, f))
            try:
                values[f] = max(1, int(raw))
            except (TypeError, ValueError):
                values[f] = getattr(defaults, f)
        return cls(**values)


@dataclass(frozen=True)
class ProbeConfig:
    """Targets used to establish what kind of connectivity exists."""

    dns_names: List[str] = field(default_factory=lambda: ["deb.debian.org", "one.one.one.one"])
    internet_hosts: List[str] = field(default_factory=lambda: ["1.1.1.1", "8.8.8.8"])
    backend_url: str = ""
    backend_timeout: int = 6
    shelly_host: str = ""

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "ProbeConfig":
        defaults = cls()

        def _strlist(key: str, fallback: List[str]) -> List[str]:
            raw = _get(d, key, fallback)
            if isinstance(raw, str):
                raw = [raw]
            if not isinstance(raw, (list, tuple)):
                return fallback
            out = [str(x).strip() for x in raw if str(x).strip()]
            return out or fallback

        return cls(
            dns_names=_strlist("dns_names", defaults.dns_names),
            internet_hosts=_strlist("internet_hosts", defaults.internet_hosts),
            backend_url=str(_get(d, "backend_url", "")).strip(),
            backend_timeout=int(_get(d, "backend_timeout", 6)),
            shelly_host=str(_get(d, "shelly_host", "")).strip(),
        )


@dataclass(frozen=True)
class PortalConfig:
    """Maintenance portal behaviour."""

    enabled: bool = True
    bind: str = "0.0.0.0"
    port: int = 80
    always_on: bool = True
    """When True the portal also listens on the normal LAN address, so a node
    that is merely offline (not in AP mode) is still serviceable over Ethernet
    or a working Wi-Fi link."""
    allow_power_actions: bool = True
    log_tail_lines: int = 200
    trusted_networks: List[str] = field(
        default_factory=lambda: [
            "127.0.0.0/8",
            "::1/128",
            "192.168.66.0/24",  # the maintenance AP segment
            "192.168.50.0/24",  # the private sensor segment
            "100.64.0.0/10",    # Tailscale (already authenticated at the network layer)
        ]
    )
    """Source networks permitted to perform *mutating* actions.

    Status pages are readable from anywhere the portal is reachable, but
    reboot, shutdown, factory reset and Wi-Fi changes are restricted to these
    ranges.  The portal is unauthenticated by design -- a technician standing
    at a dead node must not need a password -- so the trust boundary is
    *where you are connected from*, not who you claim to be.
    """

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "PortalConfig":
        defaults = cls()
        raw = _get(d, "trusted_networks", defaults.trusted_networks)
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, (list, tuple)):
            raw = defaults.trusted_networks
        return cls(
            enabled=bool(_get(d, "enabled", True)),
            bind=str(_get(d, "bind", "0.0.0.0")),
            port=int(_get(d, "port", 80)),
            always_on=bool(_get(d, "always_on", True)),
            allow_power_actions=bool(_get(d, "allow_power_actions", True)),
            log_tail_lines=int(_get(d, "log_tail_lines", 200)),
            trusted_networks=[str(x).strip() for x in raw if str(x).strip()],
        )


@dataclass(frozen=True)
class ServicesConfig:
    """Names of neighbouring units the subsystem reports on and can restart.

    The networking subsystem does not depend on these existing; a node without
    a collector simply reports it as absent.
    """

    collector: str = "energy-node-collector.service"
    backend_probe_name: str = "central backend"
    manageable: List[str] = field(
        default_factory=lambda: [
            "energy-node-collector.service",
            "energy-node-netd.service",
            "energy-node-portal.service",
            "NetworkManager.service",
        ]
    )

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "ServicesConfig":
        defaults = cls()
        raw = _get(d, "manageable", defaults.manageable)
        if not isinstance(raw, (list, tuple)):
            raw = defaults.manageable
        return cls(
            collector=str(_get(d, "collector", defaults.collector)),
            backend_probe_name=str(_get(d, "backend_probe_name", defaults.backend_probe_name)),
            manageable=[str(x) for x in raw if str(x).strip()],
        )


@dataclass(frozen=True)
class PathsConfig:
    """Filesystem locations owned or observed by the subsystem."""

    state_dir: Path = DEFAULT_STATE_DIR
    var_dir: Path = Path("/var/lib/energy-node-net")
    collector_db: Path = Path("/opt/energy-node/database/edge_buffer.db")

    @property
    def state_file(self) -> Path:
        return self.state_dir / "network-state.json"

    @property
    def control_socket(self) -> Path:
        return self.state_dir / "netd.sock"

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "PathsConfig":
        defaults = cls()
        return cls(
            state_dir=Path(str(_get(d, "state_dir", defaults.state_dir))),
            var_dir=Path(str(_get(d, "var_dir", defaults.var_dir))),
            collector_db=Path(str(_get(d, "collector_db", defaults.collector_db))),
        )


@dataclass(frozen=True)
class WifiPolicyConfig:
    """How the node chooses between known Wi-Fi networks.

    The declared networks live here as SSIDs, priorities and metadata ONLY.
    Passphrases are never part of this file: it is git-managed and the
    repository is public. Credentials live in the 0600 secrets store that
    netd owns (see netd/knownnets.py).
    """

    #: Refuse open networks unless an operator deliberately turns this on.
    #: A node that joins any open SSID it sees is a node that can be moved
    #: onto an attacker's network by standing next to it.
    allow_open_networks: bool = False
    #: Exponential backoff bounds for a network that keeps failing.
    backoff_initial: int = 15
    backoff_max: int = 300
    #: A success older than this stops earning the "try me first" slot.
    recent_success_window: int = 86400
    #: Declared baseline networks. Never contains a passphrase.
    networks: List["BaselineNetwork"] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "WifiPolicyConfig":
        defaults = cls()
        raw = _get(d, "networks", []) or []
        nets: List[BaselineNetwork] = []
        for entry in raw:
            if not isinstance(entry, Mapping):
                log.warning("ignoring malformed network entry %r", entry)
                continue
            ssid = str(_get(entry, "ssid", "")).strip()
            if not ssid:
                log.warning("ignoring network entry with no ssid")
                continue
            for banned in ("password", "psk", "passphrase"):
                if banned in entry:
                    log.error(
                        "network %s declares '%s' in network.yaml - IGNORED. "
                        "Credentials belong in the secrets store, never in "
                        "git.", ssid, banned)
            nets.append(BaselineNetwork(
                ssid=ssid,
                priority=int(_get(entry, "priority", 0) or 0),
                hidden=bool(_get(entry, "hidden", False)),
                open=bool(_get(entry, "open", False)),
                notes=str(_get(entry, "notes", "") or ""),
            ))
        return cls(
            allow_open_networks=bool(_get(d, "allow_open_networks",
                                          defaults.allow_open_networks)),
            backoff_initial=int(_get(d, "backoff_initial",
                                     defaults.backoff_initial)),
            backoff_max=int(_get(d, "backoff_max", defaults.backoff_max)),
            recent_success_window=int(_get(d, "recent_success_window",
                                           defaults.recent_success_window)),
            networks=nets,
        )


@dataclass(frozen=True)
class BaselineNetwork:
    """A declared network. SSID, priority and metadata - never a passphrase."""

    ssid: str
    priority: int = 0
    hidden: bool = False
    open: bool = False
    notes: str = ""


@dataclass(frozen=True)
class Config:
    """Root configuration object."""

    node: NodeConfig = field(default_factory=NodeConfig)
    interfaces: InterfaceConfig = field(default_factory=InterfaceConfig)
    access_point: AccessPointConfig = field(default_factory=AccessPointConfig)
    timing: TimingConfig = field(default_factory=TimingConfig)
    probes: ProbeConfig = field(default_factory=ProbeConfig)
    portal: PortalConfig = field(default_factory=PortalConfig)
    services: ServicesConfig = field(default_factory=ServicesConfig)
    paths: PathsConfig = field(default_factory=PathsConfig)
    wifi: WifiPolicyConfig = field(default_factory=WifiPolicyConfig)
    source_path: Optional[Path] = None

    @property
    def ap_ssid(self) -> str:
        return self.access_point.ssid_for(self.node.id)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any], source: Optional[Path] = None) -> "Config":
        d = d or {}
        return cls(
            node=NodeConfig.from_dict(_get(d, "node", {}) or {}),
            interfaces=InterfaceConfig.from_dict(_get(d, "interfaces", {}) or {}),
            access_point=AccessPointConfig.from_dict(_get(d, "access_point", {}) or {}),
            timing=TimingConfig.from_dict(_get(d, "timing", {}) or {}),
            probes=ProbeConfig.from_dict(_get(d, "probes", {}) or {}),
            portal=PortalConfig.from_dict(_get(d, "portal", {}) or {}),
            services=ServicesConfig.from_dict(_get(d, "services", {}) or {}),
            paths=PathsConfig.from_dict(_get(d, "paths", {}) or {}),
            wifi=WifiPolicyConfig.from_dict(_get(d, "wifi", {}) or {}),
            source_path=source,
        )

    def redacted(self) -> Dict[str, Any]:
        """Configuration as a dict with secrets masked, for UI display."""
        data = {
            "node": asdict(self.node),
            "interfaces": asdict(self.interfaces),
            "access_point": asdict(self.access_point),
            "timing": asdict(self.timing),
            "probes": asdict(self.probes),
            "portal": asdict(self.portal),
            "services": asdict(self.services),
            "paths": {k: str(v) for k, v in asdict(self.paths).items()},
        }
        data["access_point"]["password"] = "********"
        return data


class ConfigError(RuntimeError):
    """Raised only when configuration is unreadable *and* unusable."""


def load_config(path: Optional[os.PathLike[str] | str] = None) -> Config:
    """Load configuration from ``path``.

    A missing or malformed file yields a fully defaulted :class:`Config` rather
    than an exception: the subsystem must still come up and raise the
    maintenance AP so an operator can fix whatever is wrong.
    """
    cfg_path = Path(path) if path else Path(
        os.environ.get("NETD_CONFIG", str(DEFAULT_CONFIG_PATH))
    )
    if not cfg_path.is_file():
        return Config(source_path=None)
    try:
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return Config(source_path=None)
    if not isinstance(raw, dict):
        return Config(source_path=None)
    return Config.from_dict(raw, source=cfg_path)
