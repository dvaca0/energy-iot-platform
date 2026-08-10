"""Maintenance access point lifecycle.

The AP is a normal NetworkManager profile in ``ap`` mode with
``ipv4.method=shared``, which gives us NetworkManager's own DHCP server and
DNS forwarder for free -- no hostapd or dnsmasq to install, configure or keep
in sync.

Two invariants matter:

* The AP profile is ``autoconnect=no`` with priority ``-999``.  It comes up
  because this module decided so, never because NetworkManager chose it.
* The AP is never left running once a real uplink has proven stable, unless
  an operator explicitly pinned it.

Because these nodes have a single radio, raising the AP necessarily drops the
Wi-Fi client association.  That is why the supervisor only raises it after the
configured offline threshold, and why it is torn down again automatically.
"""

from __future__ import annotations

import logging
import re
import subprocess
import time
from typing import List, Optional, Tuple

from .config import Config
from .nm import NetworkManager

log = logging.getLogger("netd.ap")

_STATION_RE = re.compile(r"^Station\s+([0-9a-f:]{17})", re.IGNORECASE | re.MULTILINE)


class AccessPointManager:
    """Owns the maintenance access point."""

    def __init__(self, config: Config, nm: NetworkManager) -> None:
        self._config = config
        self._nm = nm
        self._raised_at: Optional[float] = None
        self._ensured = False

    # ------------------------------------------------------------------
    @property
    def profile(self) -> str:
        return self._config.access_point.profile_name

    @property
    def ssid(self) -> str:
        return self._config.ap_ssid

    @property
    def address(self) -> str:
        return self._config.access_point.address

    @property
    def raised_at(self) -> Optional[float]:
        return self._raised_at

    # ------------------------------------------------------------------
    def ensure_profile(self, force: bool = False) -> Tuple[bool, str]:
        """Create or update the AP profile to match configuration.

        Called at supervisor startup so that the profile is always present and
        correct *before* it is ever needed -- an AP that has to be created at
        the moment connectivity is lost is an AP that will not come up.
        """
        if self._ensured and not force:
            return True, "already ensured"
        ap = self._config.access_point
        ok, message = self._nm.ensure_ap_profile(
            name=ap.profile_name,
            ssid=self.ssid,
            password=ap.password,
            device=self._config.interfaces.wifi,
            address=ap.address,
            prefix=ap.prefix,
            band=ap.band,
            channel=ap.channel,
            hidden=ap.hidden,
        )
        if ok:
            self._ensured = True
            log.info("maintenance AP profile ready: SSID=%s at %s", self.ssid, ap.cidr)
        else:
            log.error("could not prepare maintenance AP profile: %s", message)
        return ok, message

    # ------------------------------------------------------------------
    def is_active(self) -> bool:
        """Whether the AP profile is currently activated."""
        return self._nm.is_active(self.profile)

    def start(self) -> Tuple[bool, str]:
        """Raise the maintenance AP."""
        if not self._config.access_point.enabled:
            return False, "maintenance AP is disabled in configuration"

        ok, message = self.ensure_profile()
        if not ok:
            return False, message

        if self.is_active():
            self._raised_at = self._raised_at or time.monotonic()
            return True, "maintenance AP already active"

        device = self._config.interfaces.wifi
        # Release the radio from any client association first; with a single
        # radio the AP cannot come up while the client side holds the device.
        self._nm.device_disconnect(device)

        result = self._nm.up(self.profile, timeout=75)
        if result.ok:
            self._raised_at = time.monotonic()
            log.warning(
                "MAINTENANCE AP ENABLED - SSID=%s address=http://%s",
                self.ssid,
                self.address,
            )
            return True, f"Maintenance AP '{self.ssid}' enabled at http://{self.address}"

        log.error("could not raise maintenance AP: %s", result.message)
        # Do not strand the radio: hand it back to the client side.
        self._nm.device_connect(device)
        return False, result.message

    def stop(self, reconnect: bool = True) -> Tuple[bool, str]:
        """Lower the maintenance AP and return the radio to client mode."""
        if not self.is_active():
            self._raised_at = None
            if reconnect:
                self._nm.device_connect(self._config.interfaces.wifi)
            return True, "maintenance AP was not active"

        result = self._nm.down(self.profile)
        self._raised_at = None
        if reconnect:
            self._nm.radio_wifi_on()
            self._nm.device_connect(self._config.interfaces.wifi, timeout=45)
        if result.ok:
            log.warning("maintenance AP disabled")
            return True, "Maintenance AP disabled"
        return False, result.message

    # ------------------------------------------------------------------
    def clients(self) -> List[str]:
        """MAC addresses currently associated with the AP.

        Used so the supervisor does not tear the AP down while a technician is
        mid-configuration.  Failure to determine this is reported as 'no
        clients' only after the AP's minimum uptime has elapsed, so a probe
        can still eventually run on a node where ``iw`` is unavailable.
        """
        if not self.is_active():
            return []
        device = self._config.interfaces.wifi
        try:
            proc = subprocess.run(
                ["iw", "dev", device, "station", "dump"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            return []
        if proc.returncode != 0:
            return []
        return [m.group(1).lower() for m in _STATION_RE.finditer(proc.stdout)]

    def client_count(self) -> int:
        return len(self.clients())

    def uptime(self) -> float:
        if self._raised_at is None:
            return 0.0
        return max(0.0, time.monotonic() - self._raised_at)

    def status(self) -> dict:
        """Serialisable AP status for the UIs."""
        active = self.is_active()
        return {
            "enabled_in_config": self._config.access_point.enabled,
            "active": active,
            "ssid": self.ssid,
            "address": self.address,
            "url": f"http://{self.address}",
            "clients": self.client_count() if active else 0,
            "uptime_seconds": round(self.uptime(), 1),
        }
