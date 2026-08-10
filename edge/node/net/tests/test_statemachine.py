"""State machine tests.

These exercise the transitions named in the design directly, with a fake
clock, so the behaviour that matters -- a node always finds its way back to a
reachable state -- is verified without touching a radio.
"""

from __future__ import annotations

import unittest

from netd.config import TimingConfig
from netd.models import Action, ConnectivityVerdict, LinkKind, NetState
from netd.statemachine import ConnectivityStateMachine, MachineInput


def verdict(
    usable: bool = True,
    link: LinkKind = LinkKind.WIFI,
    backend: bool = True,
) -> ConnectivityVerdict:
    """Build a verdict whose ``usable`` property is the requested value."""
    return ConnectivityVerdict(
        link=link if usable else LinkKind.NONE,
        interface="wlan0" if usable else None,
        ipv4="192.168.1.50" if usable else None,
        ssid="Lab" if usable else None,
        gateway_ok=usable,
        dns_ok=usable,
        internet_ok=usable,
        backend_ok=backend and usable,
    )


TIMING = TimingConfig(
    boot_grace=45,
    connect_grace=60,
    offline_before_ap=180,
    stable_before_ap_down=60,
    monitor_interval=10,
    retry_backoff_initial=15,
    retry_backoff_max=300,
    ap_min_uptime=120,
)


class BootTests(unittest.TestCase):
    def test_boot_goes_online_when_uplink_present(self) -> None:
        machine = ConnectivityStateMachine(TIMING)
        transition = machine.step(MachineInput(verdict=verdict(True), now=0.0))
        self.assertIs(transition.state, NetState.ONLINE)

    def test_boot_waits_before_declaring_failure(self) -> None:
        """A node must not give up on NetworkManager immediately."""
        machine = ConnectivityStateMachine(TIMING)
        transition = machine.step(MachineInput(verdict=verdict(False), now=0.0))
        self.assertIs(transition.state, NetState.BOOT)

        transition = machine.step(MachineInput(verdict=verdict(False), now=44.0))
        self.assertIs(transition.state, NetState.BOOT, "gave up before boot_grace elapsed")

        transition = machine.step(MachineInput(verdict=verdict(False), now=46.0))
        self.assertIs(transition.state, NetState.CONNECTING)


class FirstBootTests(unittest.TestCase):
    def test_first_boot_without_wifi_reaches_maintenance_ap(self) -> None:
        """BOOT -> CONNECTING -> OFFLINE_BUFFERING -> MAINTENANCE_AP, no reboot."""
        machine = ConnectivityStateMachine(TIMING)
        down = verdict(False)

        machine.step(MachineInput(verdict=down, now=0.0))
        machine.step(MachineInput(verdict=down, now=50.0))
        self.assertIs(machine.state, NetState.CONNECTING)

        machine.step(MachineInput(verdict=down, now=115.0))
        self.assertIs(machine.state, NetState.OFFLINE_BUFFERING)

        # Offline timer started at t=0 (first unusable observation).
        transition = machine.step(MachineInput(verdict=down, now=200.0))
        self.assertIs(transition.state, NetState.MAINTENANCE_AP)
        self.assertIs(transition.action, Action.START_AP)


class RecoveryTests(unittest.TestCase):
    def test_ap_shuts_down_only_after_connection_is_stable(self) -> None:
        machine = ConnectivityStateMachine(TIMING, initial=NetState.MAINTENANCE_AP)
        machine.note_ap_raised(0.0)

        up = verdict(True, link=LinkKind.ETHERNET)
        transition = machine.step(MachineInput(verdict=up, now=10.0, ap_active=True))
        self.assertIs(transition.state, NetState.RECOVERING)
        self.assertIs(transition.action, Action.NONE, "AP dropped before proving stability")

        transition = machine.step(MachineInput(verdict=up, now=50.0, ap_active=True))
        self.assertIs(transition.state, NetState.RECOVERING)

        transition = machine.step(MachineInput(verdict=up, now=75.0, ap_active=True))
        self.assertIs(transition.state, NetState.ONLINE)
        self.assertIs(transition.action, Action.STOP_AP)

    def test_flapping_link_returns_to_buffering_not_online(self) -> None:
        machine = ConnectivityStateMachine(TIMING, initial=NetState.MAINTENANCE_AP)
        machine.note_ap_raised(0.0)
        machine.step(MachineInput(verdict=verdict(True), now=10.0, ap_active=True))
        self.assertIs(machine.state, NetState.RECOVERING)

        transition = machine.step(MachineInput(verdict=verdict(False), now=20.0, ap_active=True))
        self.assertIs(transition.state, NetState.OFFLINE_BUFFERING)

    def test_online_to_offline_triggers_retry(self) -> None:
        machine = ConnectivityStateMachine(TIMING, initial=NetState.ONLINE)
        machine.step(MachineInput(verdict=verdict(True), now=0.0))
        transition = machine.step(MachineInput(verdict=verdict(False), now=10.0))
        self.assertIs(transition.state, NetState.OFFLINE_BUFFERING)
        self.assertIs(transition.action, Action.RETRY_WIFI)

    def test_offline_returns_online_when_link_restored(self) -> None:
        machine = ConnectivityStateMachine(TIMING, initial=NetState.OFFLINE_BUFFERING)
        machine.step(MachineInput(verdict=verdict(False), now=0.0))
        transition = machine.step(MachineInput(verdict=verdict(True), now=30.0))
        self.assertIs(transition.state, NetState.ONLINE)


class BackoffTests(unittest.TestCase):
    def test_retries_back_off_instead_of_looping_tightly(self) -> None:
        """Reconnects must not become a tight loop."""
        machine = ConnectivityStateMachine(TIMING, initial=NetState.OFFLINE_BUFFERING)
        down = verdict(False)

        first = machine.step(MachineInput(verdict=down, now=0.0))
        self.assertIs(first.action, Action.RETRY_WIFI)
        self.assertEqual(machine.retry_delay, 30)

        # Too soon: no retry.
        quiet = machine.step(MachineInput(verdict=down, now=10.0))
        self.assertIs(quiet.action, Action.NONE)

        second = machine.step(MachineInput(verdict=down, now=35.0))
        self.assertIs(second.action, Action.RETRY_WIFI)
        self.assertEqual(machine.retry_delay, 60)

    def test_backoff_is_capped(self) -> None:
        machine = ConnectivityStateMachine(TIMING, initial=NetState.OFFLINE_BUFFERING)
        down = verdict(False)
        now = 0.0
        for _ in range(20):
            machine.step(MachineInput(verdict=down, now=now, suppress_ap=True))
            now += 600.0
        self.assertLessEqual(machine.retry_delay, TIMING.retry_backoff_max)

    def test_backoff_resets_once_online(self) -> None:
        machine = ConnectivityStateMachine(TIMING, initial=NetState.OFFLINE_BUFFERING)
        machine.step(MachineInput(verdict=verdict(False), now=0.0))
        machine.step(MachineInput(verdict=verdict(False), now=40.0))
        self.assertGreater(machine.retry_delay, TIMING.retry_backoff_initial)

        machine.step(MachineInput(verdict=verdict(True), now=60.0))
        self.assertEqual(machine.retry_delay, TIMING.retry_backoff_initial)


class OperatorOverrideTests(unittest.TestCase):
    def test_force_ap_wins_from_any_state(self) -> None:
        machine = ConnectivityStateMachine(TIMING, initial=NetState.ONLINE)
        transition = machine.step(
            MachineInput(verdict=verdict(True), now=0.0, force_ap=True)
        )
        self.assertIs(transition.state, NetState.MAINTENANCE_AP)
        self.assertIs(transition.action, Action.START_AP)

    def test_suppress_ap_defers_automatic_activation(self) -> None:
        machine = ConnectivityStateMachine(TIMING, initial=NetState.OFFLINE_BUFFERING)
        down = verdict(False)
        machine.step(MachineInput(verdict=down, now=0.0, suppress_ap=True))
        transition = machine.step(MachineInput(verdict=down, now=500.0, suppress_ap=True))
        self.assertIs(transition.state, NetState.OFFLINE_BUFFERING)
        self.assertIsNot(transition.action, Action.START_AP)

    def test_pinned_ap_is_not_torn_down_for_recovery_probe(self) -> None:
        machine = ConnectivityStateMachine(TIMING, initial=NetState.MAINTENANCE_AP)
        machine.note_ap_raised(0.0)
        transition = machine.step(
            MachineInput(verdict=verdict(False), now=900.0, ap_active=True, force_ap=True)
        )
        self.assertIs(transition.action, Action.NONE)


class SelfHealingTests(unittest.TestCase):
    def test_ap_probes_for_known_networks_when_idle(self) -> None:
        """A node in AP mode must recover on its own when Wi-Fi returns."""
        machine = ConnectivityStateMachine(TIMING, initial=NetState.MAINTENANCE_AP)
        machine.note_ap_raised(0.0)
        transition = machine.step(
            MachineInput(verdict=verdict(False), now=300.0, ap_active=True, ap_clients=0)
        )
        self.assertIs(transition.action, Action.RETRY_WIFI)

    def test_ap_is_not_disturbed_while_operator_connected(self) -> None:
        machine = ConnectivityStateMachine(TIMING, initial=NetState.MAINTENANCE_AP)
        machine.note_ap_raised(0.0)
        transition = machine.step(
            MachineInput(verdict=verdict(False), now=300.0, ap_active=True, ap_clients=1)
        )
        self.assertIs(transition.action, Action.NONE)

    def test_ap_holds_for_minimum_uptime(self) -> None:
        """An AP that vanishes before anyone can associate is useless."""
        machine = ConnectivityStateMachine(TIMING, initial=NetState.MAINTENANCE_AP)
        machine.note_ap_raised(0.0)
        transition = machine.step(
            MachineInput(verdict=verdict(False), now=60.0, ap_active=True, ap_clients=0)
        )
        self.assertIs(transition.action, Action.NONE)


class UsabilityTests(unittest.TestCase):
    def test_gateway_alone_counts_as_usable(self) -> None:
        """A campus LAN with no internet is still a usable network."""
        value = ConnectivityVerdict(
            link=LinkKind.WIFI, interface="wlan0", ipv4="10.0.0.5", ssid="Campus",
            gateway_ok=True, dns_ok=False, internet_ok=False, backend_ok=False,
        )
        self.assertTrue(value.usable)

    def test_backend_alone_counts_as_usable(self) -> None:
        value = ConnectivityVerdict(
            link=LinkKind.ETHERNET, interface="eth0", ipv4="192.168.50.2", ssid=None,
            gateway_ok=False, dns_ok=False, internet_ok=False, backend_ok=True,
        )
        self.assertTrue(value.usable)

    def test_ap_mode_is_never_usable_uplink(self) -> None:
        value = ConnectivityVerdict(
            link=LinkKind.AP, interface="wlan0", ipv4="192.168.66.1", ssid="EnergyNode-N001",
            gateway_ok=False, dns_ok=False, internet_ok=False, backend_ok=False,
        )
        self.assertFalse(value.usable)

    def test_no_link_is_not_usable(self) -> None:
        self.assertFalse(verdict(False).usable)


if __name__ == "__main__":
    unittest.main()
