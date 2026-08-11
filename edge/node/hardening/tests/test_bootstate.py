"""Hermetic tests for the persistent boot state machine.

Covers the seventeen scenarios required for Phase 2. Every test runs against a
temporary SQLite database in a temporary directory: no node, no meter, no
radio, no reboot, no clock.

The scenarios are expressed as stage sweeps, so each one asserts on the two
questions the record exists to answer:

    how far did this boot get?          last_successful_stage
    what stopped it, and whose fault?   first_failed_stage + failure_owner
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_LIB = os.path.join(_HERE, "..", "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from recovery import pipeline as P  # noqa: E402


def sweep(**overrides):
    """A full stage sweep, everything OK unless overridden."""
    return [P.StageResult(s, overrides.get(s, P.OK)) for s in P.STAGE_ORDER]


class BootStateCase(unittest.TestCase):
    """Each test gets a private database and a fixed, fake boot id."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.db = os.path.join(self.dir, "blackbox.db")

        # NOTE: enconfig only lets a real environment variable override a key
        # that already exists in hardening.conf -- it cannot introduce one. On
        # a machine with no /opt/energy-node that means no override works at
        # all, so the test writes the cache directly.
        import enconfig
        enconfig.load(reload=True).update({
            "EN_BLACKBOX_DB": self.db,
            "EN_STATE_DIR": self.dir,
            "NODE_ID": "NTEST",
        })

        from recovery import bootstate
        self.bs = bootstate
        self._boot = "boot-aaaa-0001"
        bootstate.boot_id = lambda: self._boot          # deterministic
        self.conn = bootstate.connect()
        self.policy = P.Policy()

    def tearDown(self):
        try:
            self.conn.close()
        except Exception:
            pass
        import enconfig
        enconfig._cache = None

    def tick(self, results, now=1000.0, state=None, action=P.NONE, stage=None):
        failure = P.first_failure(results)
        if state is None:
            state = P.HEALTHY if failure is None else P.RECOVERING
        d = P.Decision(state, action, stage or (failure.stage if failure else None))
        self.bs.update(self.conn, results, d, self.policy, now)
        return self.bs.status(self.conn)


class CanonicalStages(BootStateCase):
    def test_stage_names_derive_from_the_pipeline(self):
        names = self.bs.stage_names()
        self.assertEqual(names[0], "BOOT_STARTED")
        self.assertEqual(names[-1], "HEALTHY")
        # One name per pipeline stage - no second definition anywhere.
        self.assertEqual(len(names), len(P.STAGE_ORDER) + 2)
        for s in P.STAGE_ORDER:
            self.assertIn(f"{s.upper()}_READY", names)


class Scenario01SuccessfulBoot(BootStateCase):
    def test_healthy_boot_is_complete_and_timed(self):
        r = self.tick(sweep(), now=1500.0)
        self.assertEqual(r["current_stage"], "HEALTHY")
        self.assertEqual(r["last_successful_stage"], "HEARTBEAT_READY")
        self.assertIsNone(r["first_failed_stage"])
        self.assertEqual(r["boot_complete"], 1)
        self.assertIsNotNone(r["time_to_healthy_s"])

    def test_linux_being_up_is_not_a_complete_boot(self):
        r = self.tick(sweep(collector=P.FAILED))
        self.assertEqual(r["boot_complete"], 0)


class Scenario02to11StageFailures(BootStateCase):
    """One case per failing subsystem: where did boot stop, and whose fault."""

    def _assert(self, stage_key, expect_reached, expect_owner):
        r = self.tick(sweep(**{stage_key: P.FAILED}))
        self.assertEqual(r["first_failed_stage"], f"{stage_key.upper()}_READY")
        self.assertEqual(r["last_successful_stage"], expect_reached)
        self.assertEqual(r["failure_owner"], expect_owner)
        self.assertEqual(r["boot_complete"], 0)

    def test_02_filesystem_failure(self):
        self._assert("filesystem", "BOOT_STARTED", "LOCAL")

    def test_03_clock_not_synchronised(self):
        self._assert("clock", "FILESYSTEM_READY", "LOCAL")

    def test_04_wifi_unavailable(self):
        self._assert("network", "CLOCK_READY", "LOCAL")

    def test_05_tailscale_unavailable(self):
        self._assert("tailscale", "NETWORK_READY", "EXTERNAL")

    def test_06_sensor_unavailable(self):
        self._assert("sensor", "TAILSCALE_READY", "EXTERNAL")

    def test_07_collector_stopped(self):
        self._assert("collector", "SENSOR_READY", "LOCAL")

    def test_08_collector_wedged_shows_as_stale_measurements(self):
        # The wedge case: the unit is 'active', so only measurements fail.
        r = self.tick(sweep(measurements=P.FAILED))
        self.assertEqual(r["first_failed_stage"], "MEASUREMENTS_READY")
        self.assertEqual(r["last_successful_stage"], "COLLECTOR_READY")
        self.assertEqual(r["failure_owner"], "LOCAL")

    def test_09_backend_unavailable(self):
        self._assert("backend", "MEASUREMENTS_READY", "EXTERNAL")

    def test_10_heartbeat_stale(self):
        self._assert("heartbeat", "BACKEND_READY", "LOCAL")

    def test_11_unknown_stage_does_not_block_progress(self):
        # No Tailscale on this hardware: unavailable is not a failed boot.
        r = self.tick(sweep(tailscale=P.UNKNOWN))
        self.assertEqual(r["boot_complete"], 1)
        self.assertIsNone(r["first_failed_stage"])

    def test_owner_is_unknown_when_the_stage_cannot_be_judged(self):
        results = sweep()
        results[P.STAGE_ORDER.index(P.SENSOR)] = P.StageResult(
            P.SENSOR, P.UNKNOWN, "no probe")
        owner = self.bs.failure_owner(P.SENSOR, results, self.policy)
        self.assertEqual(owner, "UNKNOWN")


class Scenario12RecoveryAfterRestart(BootStateCase):
    def test_failure_is_kept_after_recovery_succeeds(self):
        self.tick(sweep(collector=P.FAILED), now=1000.0)
        self.bs.event(self.conn, self.bs.E_REMEDY, P.COLLECTOR,
                      "systemctl restart", 1010.0)
        r = self.tick(sweep(), now=1100.0)

        self.assertEqual(r["boot_complete"], 1)
        self.assertEqual(r["service_restarts"], 1)
        kinds = [e["kind"] for e in self.bs.events(self._boot, conn=self.conn)]
        # The failure must still be visible; recovery appends, never erases.
        self.assertIn(self.bs.E_STAGE_FAIL, kinds)
        self.assertIn(self.bs.E_REMEDY, kinds)
        self.assertIn(self.bs.E_HEALTHY, kinds)


class Scenario13RecoveryAfterReboot(BootStateCase):
    def test_reboot_is_counted_and_a_new_boot_starts_a_new_record(self):
        self.tick(sweep(measurements=P.FAILED), now=1000.0)
        self.bs.event(self.conn, self.bs.E_REBOOT, P.MEASUREMENTS,
                      "3 remedies exhausted", 1200.0)
        old = self.bs.status(self.conn)
        self.assertEqual(old["reboot_attempts"], 1)
        self.assertEqual(old["boot_complete"], 0)

        # New boot: new kernel boot_id, new record, old one preserved intact.
        self._boot = "boot-aaaa-0002"
        self.bs.boot_id = lambda: self._boot
        r = self.tick(sweep(), now=2000.0)
        self.assertEqual(r["boot_id"], "boot-aaaa-0002")
        self.assertEqual(r["boot_complete"], 1)

        rows = self.bs.history(limit=10, conn=self.conn)
        self.assertEqual(len(rows), 2)
        prior = [x for x in rows if x["boot_id"] == "boot-aaaa-0001"][0]
        self.assertEqual(prior["reboot_attempts"], 1)
        self.assertEqual(prior["first_failed_stage"], "MEASUREMENTS_READY")


class Scenario14SafeMode(BootStateCase):
    def test_safe_mode_entry_is_recorded(self):
        self.tick(sweep(collector=P.FAILED), now=1000.0)
        self.bs.event(self.conn, self.bs.E_SAFE_MODE, P.COLLECTOR,
                      "budget exhausted", 1500.0)
        r = self.bs.status(self.conn)
        self.assertEqual(r["safe_mode_entered"], 1)
        self.assertEqual(r["safe_mode_at"], 1500.0)


class Scenario15RebootBudgetSurvives(BootStateCase):
    def test_budget_is_held_in_the_ledger_and_survives(self):
        from recovery import ledger as L
        path = os.path.join(self.dir, "recovery-ledger.json")
        L.save(P.Ledger(reboots=[100.0, 200.0, 300.0]), path)
        reloaded = L.load(path)
        self.assertEqual(reloaded.reboots_in_window(400.0, 1800), 3)
        # And the guard actually refuses a fourth.
        led = reloaded
        led.attempts[P.COLLECTOR] = 99
        led.last_attempt[P.COLLECTOR] = 0.0
        d = P.decide(sweep(collector=P.FAILED), led, 400.0, P.Policy())
        self.assertEqual(d.action, P.ENTER_SAFE_MODE)


class Scenario16SurvivesProcessCrash(BootStateCase):
    def test_record_is_readable_from_a_new_connection(self):
        self.tick(sweep(network=P.FAILED), now=1000.0)
        self.conn.close()           # simulate the process dying outright
        conn2 = self.bs.connect()
        try:
            r = self.bs.status(conn2)
            self.assertEqual(r["first_failed_stage"], "NETWORK_READY")
            self.assertEqual(r["last_successful_stage"], "CLOCK_READY")
        finally:
            conn2.close()

    def test_each_update_is_committed_not_buffered(self):
        self.tick(sweep(clock=P.FAILED), now=1000.0)
        raw = sqlite3.connect(self.db)
        try:
            row = raw.execute(
                "SELECT first_failed_stage FROM boot_state WHERE boot_id=?",
                (self._boot,)).fetchone()
            self.assertEqual(row[0], "CLOCK_READY")
        finally:
            raw.close()


class Scenario17CorruptStateDegrades(BootStateCase):
    def test_corrupt_database_raises_rather_than_returning_a_lie(self):
        self.conn.close()
        with open(self.db, "wb") as fh:
            fh.write(b"this is not a sqlite database" * 50)
        with self.assertRaises(sqlite3.DatabaseError):
            c = self.bs.connect()
            self.bs.status(c)

    def test_corrupt_ledger_degrades_loudly_to_empty(self):
        from recovery import ledger as L
        path = os.path.join(self.dir, "recovery-ledger.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{ broken")
        led = L.load(path)          # must not raise
        self.assertEqual(led.reboots, [])

    def test_daemon_keeps_recovering_when_the_boot_record_is_broken(self):
        """The boot record is observability, not a dependency of recovery."""
        import importlib.util
        import types
        broken = types.ModuleType("bootstate_broken")

        def explode(*_a, **_k):
            raise sqlite3.DatabaseError("database disk image is malformed")

        broken.connect = explode
        broken.update = explode
        broken.status = explode

        path = os.path.join(_LIB, "recovery", "daemon.py")
        spec = importlib.util.spec_from_file_location("daemon_under_test", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["daemon_under_test"] = mod
        spec.loader.exec_module(mod)
        mod.bootstate = broken

        # bs() must swallow it and return None rather than propagating.
        self.assertIsNone(mod.bs(broken.update))
        self.assertIsNone(mod.bs(broken.status))


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TimeToHealthyIsHonest(BootStateCase):
    """A record created mid-boot must not claim to have timed the boot."""

    def test_measured_when_the_record_started_with_the_boot(self):
        import blackbox
        blackbox.sysinfo.boot_time = lambda: 1000.0
        self.tick(sweep(collector=P.FAILED), now=1010.0)   # observed_from=1010
        r = self.tick(sweep(), now=1100.0)
        self.assertEqual(r["boot_complete"], 1)
        self.assertAlmostEqual(r["time_to_healthy_s"], 100.0, places=0)

    def test_not_claimed_when_the_record_started_hours_into_the_boot(self):
        import blackbox
        blackbox.sysinfo.boot_time = lambda: 1000.0
        # Daemon installed 22h in: observed_from is far past boot_started_at.
        r = self.tick(sweep(), now=1000.0 + 81000)
        self.assertEqual(r["boot_complete"], 1)
        self.assertIsNone(r["time_to_healthy_s"])

    def test_migration_adds_the_column_to_a_legacy_database(self):
        """A database written before observed_from existed must still open."""
        self.conn.close()
        os.unlink(self.db)
        legacy = sqlite3.connect(self.db)
        legacy.execute(
            "CREATE TABLE boot_state (boot_id TEXT PRIMARY KEY, node_id TEXT, "
            "boot_started_at REAL, boot_started_iso TEXT, prev_boot_reason TEXT, "
            "current_stage TEXT, last_successful_stage TEXT, "
            "first_failed_stage TEXT, failure_reason TEXT, failure_owner TEXT, "
            "service_restarts INTEGER NOT NULL DEFAULT 0, "
            "reboot_attempts INTEGER NOT NULL DEFAULT 0, "
            "safe_mode_entered INTEGER NOT NULL DEFAULT 0, safe_mode_at REAL, "
            "network_used TEXT, tailscale_state TEXT, backend_state TEXT, "
            "sensor_state TEXT, collector_state TEXT, heartbeat_state TEXT, "
            "measurements_state TEXT, time_sync_state TEXT, "
            "boot_complete INTEGER NOT NULL DEFAULT 0, healthy_at REAL, "
            "time_to_healthy_s REAL, final_outcome TEXT, updated_at REAL)")
        legacy.execute(
            "INSERT INTO boot_state (boot_id, last_successful_stage) "
            "VALUES ('legacy-boot', 'NETWORK_READY')")
        legacy.commit()
        legacy.close()

        conn2 = self.bs.connect()          # must migrate, not crash
        try:
            cols = {r[1] for r in conn2.execute("PRAGMA table_info(boot_state)")}
            self.assertIn("observed_from", cols)
            # and the pre-existing row is preserved
            row = conn2.execute(
                "SELECT last_successful_stage FROM boot_state WHERE boot_id=?",
                ("legacy-boot",)).fetchone()
            self.assertEqual(row[0], "NETWORK_READY")
        finally:
            conn2.close()
