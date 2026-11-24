"""state_reader reads the private state dir read-only. Synthetic fixtures only (tests/fixtures/state)."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import state_reader as sr  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "state"


def snapshot(d):
    return {p.name: (p.stat().st_mtime_ns, p.read_bytes()) for p in Path(d).iterdir()}


class StateDir(unittest.TestCase):
    def test_env_wins(self):
        self.assertEqual(sr.state_dir({"LIMITLESS_STATE": "/x/st"}, home=Path("/h")), Path("/x/st"))

    def test_config_json_state_key(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "config.json"
            cfg.write_text(json.dumps({"state": "/from/config"}))
            self.assertEqual(sr.state_dir({"LIMITLESS_CONFIG": str(cfg)}, home=Path("/h")), Path("/from/config"))

    def test_default_config_under_home(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            (home / ".config/limitless").mkdir(parents=True)
            (home / ".config/limitless/config.json").write_text(json.dumps({"state": "/cfg/home"}))
            self.assertEqual(sr.state_dir({}, home=home), Path("/cfg/home"))

    def test_config_dict(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "config.json"
            cfg.write_text(json.dumps({"state": "/s", "window_bands": {"peak": [1, 2]}}))
            self.assertEqual(sr.config({"LIMITLESS_CONFIG": str(cfg)}, home=Path("/h"))["window_bands"],
                             {"peak": [1, 2]})
            cfg.write_text("[1, 2]")
            self.assertEqual(sr.config({"LIMITLESS_CONFIG": str(cfg)}, home=Path("/h")), {})
        self.assertEqual(sr.config({}, home=Path("/nohome")), {})

    def test_fallback(self):
        self.assertEqual(sr.state_dir({}, home=Path("/nohome")), Path("/nohome/.local/state/limitless"))


class Reader(unittest.TestCase):
    def setUp(self):
        self.r = sr.StateReader(FIX)

    def test_inputs(self):
        inp = self.r.inputs()
        self.assertEqual(inp["at"], "2030-01-15T11:30:00Z")
        self.assertEqual(inp["ageHours"]["bike"], "down")
        self.assertEqual(inp["ageHours"]["wearable"], 3.7)

    def test_last_run_is_the_last_valid_row(self):
        self.assertEqual(self.r.last_run()["at"], "2030-01-15T10:47:00Z")

    def test_digests_and_latest(self):
        self.assertEqual(len(self.r.digests()), 2)
        self.assertEqual(self.r.latest_digest()["date"], "2030-01-15")

    def test_asks_habit_and_events(self):
        self.assertEqual(self.r.asks()["count"], 2)
        self.assertEqual(self.r.habit()["week_of"], "2030-01-11")
        self.assertEqual([row["on"] for row in self.r.sleepmode()], [False, True, False])
        self.assertTrue(self.r.sleepmode_poll()["ok"])
        self.assertEqual(self.r.last_unlock()["at"], "2030-01-15T11:52:00Z")

    def test_mtime(self):
        self.assertIsInstance(self.r.mtime("inputs.json"), int)
        self.assertIsNone(self.r.mtime("nope.json"))

    def test_missing_dir_gives_none_not_errors(self):
        r = sr.StateReader(Path("/definitely/not/here"))
        self.assertFalse(r.exists())
        self.assertIsNone(r.inputs())
        self.assertIsNone(r.last_run())
        self.assertEqual(r.digests(), [])
        self.assertIsNone(r.latest_digest())
        self.assertIsNone(r.asks())
        self.assertIsNone(r.last_unlock())

    def test_malformed_json_file_is_none(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "inputs.json").write_text("{not json")
            self.assertIsNone(sr.StateReader(Path(d)).inputs())

    def test_reading_never_writes(self):
        with tempfile.TemporaryDirectory() as d:
            st = Path(d) / "st"
            shutil.copytree(FIX, st)
            before = snapshot(st)
            r = sr.StateReader(st)
            r.inputs(), r.last_run(), r.digests(), r.latest_digest(), r.asks(), r.habit()
            r.sleepmode(), r.sleepmode_poll(), r.last_unlock()
            self.assertEqual(snapshot(st), before)

    def test_last_row_of_a_large_file(self):
        with tempfile.TemporaryDirectory() as d:
            with open(Path(d) / "runs.jsonl", "w") as f:
                for i in range(20000):
                    f.write(json.dumps({"at": i, "job": "sync", "ok": True}) + "\n")
            self.assertEqual(sr.StateReader(Path(d)).last_run()["at"], 19999)


class ParseTs(unittest.TestCase):
    def test_iso_z_and_epoch(self):
        self.assertEqual(sr.parse_ts("2030-01-15T12:00:00Z"), 1894708800.0)
        self.assertEqual(sr.parse_ts("2030-01-15T12:00:00+00:00"), 1894708800.0)
        self.assertEqual(sr.parse_ts(1894708800), 1894708800.0)
        self.assertIsNone(sr.parse_ts("yesterday"))
        self.assertIsNone(sr.parse_ts(None))
        self.assertIsNone(sr.parse_ts(True))


if __name__ == "__main__":
    unittest.main()
