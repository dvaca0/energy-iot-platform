"""Portal tests: lifecycle and the trust boundary on mutating actions."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from netd.config import Config, PortalConfig
from netd.portal.app import PortalApplication

REPO_ROOT = Path(__file__).resolve().parent.parent


class TrustBoundaryTests(unittest.TestCase):
    """Mutating actions must be restricted by source address.

    The portal is unauthenticated by design -- a technician at a dead node
    must not need a password -- so 'where you connect from' is the boundary.
    """

    def setUp(self) -> None:
        config = Config(
            portal=PortalConfig(
                trusted_networks=["127.0.0.0/8", "192.168.66.0/24", "100.64.0.0/10"]
            )
        )
        self.app = PortalApplication(config, client=mock.Mock())

    def test_maintenance_ap_clients_are_trusted(self) -> None:
        self.assertTrue(self.app.is_trusted("192.168.66.42"))

    def test_loopback_is_trusted(self) -> None:
        self.assertTrue(self.app.is_trusted("127.0.0.1"))

    def test_tailscale_is_trusted(self) -> None:
        self.assertTrue(self.app.is_trusted("100.98.67.31"))

    def test_campus_network_is_not_trusted(self) -> None:
        """A public campus address must not be able to reboot the node."""
        self.assertFalse(self.app.is_trusted("148.213.2.245"))

    def test_arbitrary_internet_address_is_not_trusted(self) -> None:
        self.assertFalse(self.app.is_trusted("8.8.8.8"))

    def test_ipv4_mapped_ipv6_is_judged_on_its_real_address(self) -> None:
        """::ffff:192.168.66.5 must be treated as 192.168.66.5, not rejected."""
        self.assertTrue(self.app.is_trusted("::ffff:192.168.66.5"))
        self.assertFalse(self.app.is_trusted("::ffff:8.8.8.8"))

    def test_malformed_address_is_not_trusted(self) -> None:
        self.assertFalse(self.app.is_trusted("not-an-address"))
        self.assertFalse(self.app.is_trusted(""))

    def test_malformed_trusted_network_is_ignored_not_fatal(self) -> None:
        config = Config(portal=PortalConfig(trusted_networks=["nonsense", "127.0.0.0/8"]))
        app = PortalApplication(config, client=mock.Mock())
        self.assertTrue(app.is_trusted("127.0.0.1"))
        self.assertFalse(app.is_trusted("10.0.0.1"))


class ShutdownTests(unittest.TestCase):
    """Regression: the portal used to deadlock on SIGTERM.

    ``shutdown()`` blocks until ``serve_forever()`` returns, and the signal
    handler runs *in* that thread. Calling it directly hung until systemd
    SIGKILLed the process, leaving the unit in 'failed' after every restart.
    """

    def test_portal_exits_cleanly_on_sigterm(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as handle:
            handle.write("portal:\n  port: 18099\n  bind: 127.0.0.1\n")
            config_path = handle.name

        env = dict(os.environ, PYTHONPATH=str(REPO_ROOT), NETD_CONFIG=config_path)
        process = subprocess.Popen(
            [sys.executable, "-m", "netd.portal"],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                try:
                    with urllib.request.urlopen(
                        "http://127.0.0.1:18099/healthz", timeout=2
                    ) as response:
                        self.assertEqual(response.status, 200)
                        break
                except OSError:
                    if process.poll() is not None:
                        self.fail(f"portal exited early: {process.stdout.read()}")
                    time.sleep(0.3)
            else:
                self.fail("portal never became ready")

            process.send_signal(signal.SIGTERM)
            try:
                returncode = process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                self.fail("portal did not exit on SIGTERM (deadlock regression)")
            self.assertEqual(returncode, 0, "portal exited uncleanly on SIGTERM")
        finally:
            if process.poll() is None:
                process.kill()
            os.unlink(config_path)


if __name__ == "__main__":
    unittest.main()
