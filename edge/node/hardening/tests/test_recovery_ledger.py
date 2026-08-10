"""Unit tests for recovery ledger persistence.

The ledger is the boot-loop guard. If it does not survive a reboot, the node
reboots forever - which is exactly the bug this replaces. These tests use a
temporary directory and never touch a real node.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_LIB = os.path.join(_HERE, "..", "lib")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from recovery import ledger as L  # noqa: E402
from recovery.pipeline import Ledger  # noqa: E402


class Roundtrip(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "recovery-ledger.json")

    def test_save_then_load_preserves_every_field(self):
        led = Ledger(
            reboots=[100.0, 200.0],
            attempts={"collector": 2},
            last_attempt={"collector": 250.0},
            safe_mode_since=300.0,
            safe_mode_last_retry=400.0,
            safe_mode_last_reboot=500.0,
        )
        L.save(led, self.path)
        back = L.load(self.path)
        self.assertEqual(back.reboots, [100.0, 200.0])
        self.assertEqual(back.attempts, {"collector": 2})
        self.assertEqual(back.last_attempt, {"collector": 250.0})
        self.assertEqual(back.safe_mode_since, 300.0)
        self.assertEqual(back.safe_mode_last_retry, 400.0)
        self.assertEqual(back.safe_mode_last_reboot, 500.0)

    def test_reboot_history_survives_a_reload(self):
        """The property the whole guard rests on."""
        led = Ledger(reboots=[10.0, 20.0, 30.0])
        L.save(led, self.path)
        # Simulate the reboot: brand new process, nothing in memory.
        reloaded = L.load(self.path)
        self.assertEqual(reloaded.reboots_in_window(35.0, 1800), 3)

    def test_missing_file_gives_an_empty_ledger(self):
        led = L.load(os.path.join(self.dir, "nope.json"))
        self.assertEqual(led.reboots, [])
        self.assertIsNone(led.safe_mode_since)

    def test_corrupt_file_degrades_instead_of_crashing(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{not json at all")
        led = L.load(self.path)
        self.assertEqual(led.reboots, [])

    def test_non_dict_json_degrades(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump([1, 2, 3], fh)
        self.assertEqual(L.load(self.path).reboots, [])

    def test_save_leaves_no_temp_file_behind(self):
        L.save(Ledger(reboots=[1.0]), self.path)
        leftovers = [f for f in os.listdir(self.dir) if f.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_save_is_atomic_replace_not_truncate(self):
        L.save(Ledger(reboots=[1.0]), self.path)
        first = os.stat(self.path).st_ino
        L.save(Ledger(reboots=[2.0]), self.path)
        # os.replace swaps in a new inode; a truncating write would reuse it,
        # which is what leaves a half-written ledger after a power cut.
        self.assertNotEqual(first, os.stat(self.path).st_ino)

    def test_prune_drops_old_reboots_only(self):
        now = 1_000_000.0
        week = 604800.0
        led = Ledger(reboots=[100_000.0, 600_000.0, now])  # ages: 900k, 400k, 0
        L.prune(led, now=now, keep_s=week)
        self.assertEqual(led.reboots, [600_000.0, now])

    def test_garbage_entries_are_ignored(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"reboots": [1.0, "x", None, 2.0]}, fh)
        self.assertEqual(L.load(self.path).reboots, [1.0, 2.0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
