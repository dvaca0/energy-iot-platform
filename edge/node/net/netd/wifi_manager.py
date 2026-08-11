"""Wi-Fi client management: saved networks, priorities, scanning, roaming.

Saved networks are ordinary NetworkManager profiles.  This module never keeps
its own parallel database of credentials -- NetworkManager already is that
database, and duplicating it is how appliances end up with two sources of
truth that disagree after a manual ``nmcli`` edit.

Roaming between known networks is NetworkManager's own autoconnect, driven by
``connection.autoconnect-priority``.  This module's job is to keep those
priorities coherent and to nudge NetworkManager when it has given up.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple

from .config import Config
from .models import SavedNetwork, ScanResult
from .nm import NetworkManager

if TYPE_CHECKING:  # pragma: no cover
    from .knownnets import KnownNetworkStore
    from .netselect import Candidate, KnownNetwork, SelectionPolicy

log = logging.getLogger("netd.wifi")


class WifiManager:
    """Owns the Wi-Fi client side of the radio."""

    def __init__(self, config: Config, nm: NetworkManager,
                 store: Optional["KnownNetworkStore"] = None) -> None:
        self._config = config
        self._nm = nm
        self._last_scan_at: float = 0.0
        self._last_scan: List[ScanResult] = []
        self._store = store if store is not None else self._build_store(config)

    @staticmethod
    def _build_store(config: Config) -> "KnownNetworkStore":
        from .knownnets import KnownNetworkStore
        from .netselect import BASELINE, KnownNetwork
        baseline = [
            KnownNetwork(ssid=n.ssid, priority=n.priority, source=BASELINE,
                         hidden=n.hidden, open=n.open, notes=n.notes)
            for n in config.wifi.networks
        ]
        return KnownNetworkStore(config.paths.var_dir, baseline)

    @property
    def store(self) -> "KnownNetworkStore":
        return self._store

    def _policy(self) -> "SelectionPolicy":
        from .netselect import SelectionPolicy
        w = self._config.wifi
        return SelectionPolicy(
            backoff_initial=w.backoff_initial,
            backoff_max=w.backoff_max,
            recent_success_window=w.recent_success_window,
            allow_open=w.allow_open_networks,
        )

    # ------------------------------------------------------------------
    # the whitelist and its health
    # ------------------------------------------------------------------
    def known_networks(self) -> List["KnownNetwork"]:
        """The effective whitelist: git baseline plus operator additions."""
        return self._store.effective()

    def visible_signals(self, use_cache: bool = True) -> Dict[str, int]:
        scans = self.cached_scan() if use_cache else self.scan()
        out: Dict[str, int] = {}
        for r in scans:
            sig = getattr(r, "signal", None)
            if r.ssid and (r.ssid not in out or (sig or -999) > out[r.ssid]):
                out[r.ssid] = sig if sig is not None else 0
        return out

    def ranked(self, now: Optional[float] = None,
               use_cache: bool = True) -> List["Candidate"]:
        """Try-order for the whitelist, with a reason for every entry."""
        from . import netselect
        return netselect.rank(
            self.known_networks(), self._store.health(),
            self.visible_signals(use_cache) or None,
            now if now is not None else time.time(), self._policy())

    def should_raise_ap(self, now: Optional[float] = None) -> bool:
        """True only when NO known network is worth trying right now.

        FAIL-SAFE: a node with an empty whitelist - nothing declared in
        network.yaml and nothing added by an operator - falls back to the
        previous behaviour of asking whether any SAVED profile is in range.
        Without that, an un-migrated node would decide that nothing is worth
        trying and raise the maintenance AP, which on a single radio drops the
        client connection. Being unconfigured must not strand a node that is
        working perfectly well.
        """
        from . import netselect
        known = self.known_networks()
        if not known:
            log.debug("no declared whitelist; falling back to saved profiles")
            return not bool(self.known_networks_in_range())
        return netselect.should_raise_ap(
            known, self._store.health(), self.visible_signals() or None,
            now if now is not None else time.time(), self._policy())

    def note_result(self, ssid: str, ok: bool, error: str = "",
                    now: Optional[float] = None) -> None:
        """Record what happened, so the next choice is better informed."""
        from . import netselect
        now = now if now is not None else time.time()
        health = self._store.health()
        signal = self.visible_signals().get(ssid)
        if ok:
            netselect.record_success(health, ssid, now, signal)
        else:
            netselect.record_failure(health, ssid, now, error, signal)
        try:
            self._store.save_health(health)
        except OSError as exc:
            log.warning("could not persist network health: %s", exc)

    def reconcile(self, now: Optional[float] = None) -> Dict[str, str]:
        """Push the computed try-order onto NetworkManager.

        NetworkManager stays the roaming engine - a second one would fight it.
        What changes is that its autoconnect priorities now reflect measured
        health rather than a static list, and a network in backoff has
        autoconnect switched off so it stops soaking up every attempt.

        Returns ssid -> what was done, for logging and the portal.
        """
        actions: Dict[str, str] = {}
        saved = {n.ssid: n for n in self.saved_networks()}
        rank_order = self.ranked(now)
        top = 100

        for position, cand in enumerate(rank_order):
            ssid = cand.network.ssid
            profile = saved.get(ssid)
            if profile is None:
                # A declared network we have never saved. We can only create a
                # profile if we hold a credential (or it is deliberately open).
                secret = self._store.secret_for(ssid)
                if secret or cand.network.open:
                    ok, msg = self._nm.add_wifi(
                        ssid, secret, device=self.device,
                        priority=max(0, top - position * 5),
                        hidden=cand.network.hidden)
                    actions[ssid] = ("created profile" if ok
                                     else f"could not create profile: {msg}")
                else:
                    actions[ssid] = "declared but no credential stored"
                continue

            want_priority = max(0, top - position * 5)
            if profile.priority != want_priority:
                self._nm.set_priority(profile.uuid, want_priority)
            # Backing off, or refused by policy: stop NetworkManager retrying.
            want_auto = cand.eligible or cand.reason == "not in range"
            self._nm.set_autoconnect(profile.uuid, want_auto)
            actions[ssid] = (f"priority {want_priority}, "
                             f"autoconnect {'on' if want_auto else 'off'} "
                             f"({cand.reason})")
        return actions

    @property
    def device(self) -> str:
        return self._config.interfaces.wifi

    # ------------------------------------------------------------------
    # inspection
    # ------------------------------------------------------------------
    def saved_networks(self) -> List[SavedNetwork]:
        """Saved Wi-Fi profiles, highest priority first.

        The maintenance AP profile is excluded: it is infrastructure, not a
        network the operator saved, and showing it in the roaming list invites
        someone to 'connect' to it.
        """
        ap_profile = self._config.access_point.profile_name
        networks = [n for n in self._nm.connections() if n.name != ap_profile]
        return sorted(networks, key=lambda n: (-n.priority, n.ssid.lower()))

    def scan(self, force: bool = False) -> List[ScanResult]:
        """Scan for networks, rate-limited to protect the single radio."""
        now = time.monotonic()
        min_interval = self._config.timing.scan_min_interval
        if not force and self._last_scan and (now - self._last_scan_at) < min_interval:
            return self._last_scan
        results = self._nm.scan(self.device, rescan=True)
        if results:
            self._last_scan = results
            self._last_scan_at = now
        return results or self._last_scan

    def cached_scan(self) -> List[ScanResult]:
        return list(self._last_scan)

    def known_networks_in_range(self, use_cache: bool = True) -> List[str]:
        """SSIDs that are both saved and currently visible."""
        saved = {n.ssid for n in self.saved_networks()}
        visible = self.cached_scan() if use_cache else self.scan()
        return [r.ssid for r in visible if r.ssid in saved]

    def current_ssid(self) -> Optional[str]:
        """Broadcast SSID currently associated, excluding the maintenance AP.

        NetworkManager reports the *profile* name on the device, which is
        frequently not the SSID (netplan generates names such as
        ``netplan-wlan0-wirelesslan``).  Operators recognise the SSID, so
        resolve the profile to it and fall back to the profile name only if
        the lookup fails.
        """
        profile = self._nm.active_wifi_ssid(self.device)
        if not profile or profile == self._config.access_point.profile_name:
            return None
        return self._nm.connection_ssid(profile) or profile

    # ------------------------------------------------------------------
    # mutation
    # ------------------------------------------------------------------
    def connect(
        self,
        ssid: str,
        password: Optional[str] = None,
        priority: Optional[int] = None,
        hidden: bool = False,
    ) -> Tuple[bool, str]:
        """Save and activate a Wi-Fi network.

        The profile is created before activation so that a wrong password
        leaves a saved (and therefore correctable) profile behind rather than
        vanishing -- the operator can fix the passphrase from the portal
        instead of retyping the whole entry.
        """
        ssid = (ssid or "").strip()
        if not ssid:
            return False, "SSID must not be empty"

        if priority is None:
            priority = self._next_priority()

        ok, message = self._nm.add_wifi(
            ssid,
            password,
            device=self.device,
            priority=priority,
            hidden=hidden,
        )
        if not ok:
            log.warning("could not save profile for %s: %s", ssid, message)
            return False, message

        profile = message
        log.info("saved profile %s for SSID %s (priority %d)", profile, ssid, priority)

        # Remember it as an operator network, and keep the passphrase in the
        # 0600 secrets store rather than only inside NetworkManager, so a
        # profile rebuild or factory-network-reset does not lose it.
        try:
            self._store.add_operator_network(ssid, priority=priority,
                                             hidden=hidden,
                                             open_network=not password)
            self._store.set_secret(ssid, password)
        except OSError as exc:
            log.warning("could not persist operator network %s: %s", ssid, exc)

        result = self._nm.up(profile, timeout=75)
        if result.ok:
            log.info("connected to %s", ssid)
            self.note_result(ssid, True)
            return True, f"Connected to {ssid}"

        log.warning("activation of %s failed: %s", ssid, result.message)
        self.note_result(ssid, False, result.message)
        return False, f"Saved {ssid} but could not connect: {result.message}"

    def disconnect(self) -> Tuple[bool, str]:
        """Drop the current Wi-Fi association without forgetting it."""
        result = self._nm.device_disconnect(self.device)
        if result.ok:
            log.info("disconnected %s", self.device)
            return True, f"Disconnected {self.device}"
        return False, result.message

    def forget(self, identifier: str) -> Tuple[bool, str]:
        """Delete a saved profile by UUID, profile name or SSID."""
        ap_profile = self._config.access_point.profile_name
        if identifier in (ap_profile,):
            return False, "the maintenance AP profile cannot be deleted here"

        target = self._resolve(identifier)
        if target is None:
            return False, f"no saved network matching '{identifier}'"
        result = self._nm.delete(target.uuid)
        if result.ok:
            log.info("forgot network %s (%s)", target.ssid, target.uuid)
            try:
                # Also suppresses it if it came from the git baseline, so a
                # deployment does not quietly reinstate what was forgotten.
                self._store.remove_operator_network(target.ssid)
            except OSError as exc:
                log.warning("could not update operator networks: %s", exc)
            return True, f"Forgot {target.ssid}"
        return False, result.message

    def set_priority(self, identifier: str, priority: int) -> Tuple[bool, str]:
        """Set roaming priority; higher wins."""
        target = self._resolve(identifier)
        if target is None:
            return False, f"no saved network matching '{identifier}'"
        ok, message = self._nm.set_priority(target.uuid, priority)
        if ok:
            log.info("priority of %s set to %d", target.ssid, priority)
            return True, f"{target.ssid} priority set to {priority}"
        return False, message

    def reconnect(self) -> Tuple[bool, str]:
        """Ask NetworkManager to retry saved networks on the Wi-Fi device.

        This is the recovery nudge used by the supervisor.  It is intentionally
        gentle: it re-enables the radio and asks the device to autoconnect,
        rather than forcing a specific profile, so NetworkManager's own
        priority and signal logic picks the best available network.
        """
        self._nm.radio_wifi_on()
        result = self._nm.device_connect(self.device, timeout=45)
        if result.ok:
            return True, "reconnect requested"
        # 'device connect' fails when already connecting; that is not an error
        # worth escalating, so report it as a soft outcome.
        return False, result.message

    def prefer(self, ssid: str) -> Tuple[bool, str]:
        """Raise one network above all others in the roaming order."""
        networks = self.saved_networks()
        if not networks:
            return False, "no saved networks"
        highest = max((n.priority for n in networks), default=0)
        return self.set_priority(ssid, highest + 10)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    def _resolve(self, identifier: str) -> Optional[SavedNetwork]:
        """Find a saved network by UUID, profile name or SSID."""
        identifier = (identifier or "").strip()
        if not identifier:
            return None
        networks = self.saved_networks()
        for network in networks:
            if identifier == network.uuid:
                return network
        for network in networks:
            if identifier == network.name:
                return network
        for network in networks:
            if identifier == network.ssid:
                return network
        return None

    def _next_priority(self) -> int:
        """Default priority for a newly added network: most recent wins.

        An operator adding a network from the portal is standing in front of
        the node and wants *that* network used, so it goes to the top.
        """
        networks = self.saved_networks()
        if not networks:
            return 10
        return max(n.priority for n in networks) + 10
