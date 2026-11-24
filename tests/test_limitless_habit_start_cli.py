"""bin/limitless-habit-start end to end in a temp HOME. Synthetic data only; nothing sends."""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "limitless-habit-start"


class HabitStartCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.st = self.home / "state"
        self.st.mkdir()
        self.hj = self.st / "habit.json"
        self.env = {"HOME": str(self.home), "PATH": os.environ.get("PATH", ""), "LIMITLESS_STATE": str(self.st),
                    "LIMITLESS_CONFIG": str(self.home / "no-config.json")}

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args, env=None):
        return subprocess.run([sys.executable, "-I", str(CLI), *args], env=child_env(env or self.env),
                              capture_output=True, text=True, timeout=60)

    def test_dry_run_prints_would_start_and_writes_nothing(self):
        r = self.run_cli("Synthetic habit")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(),
                         [f"would start: Synthetic habit for the week of {date.today().isoformat()}"])
        self.assertEqual(list(self.st.iterdir()), [])

    def test_write_starts_the_week(self):
        r = self.run_cli("Synthetic habit", "--write")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(),
                         [f"started: Synthetic habit for the week of {date.today().isoformat()}"])
        got = json.loads(self.hj.read_text())
        self.assertEqual((got["habit"], got["week_of"], got["checkins"]),
                         ("Synthetic habit", date.today().isoformat(), {}))

    def test_first_step_is_written(self):
        r = self.run_cli("Synthetic habit", "--first-step", "Synthetic two-minute step", "--write")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(self.hj.read_text())["start"], "Synthetic two-minute step")

    def test_refused_exits_three_with_one_line(self):
        self.hj.write_text(json.dumps({"habit": "Older synthetic habit", "week_of": date.today().isoformat()}))
        before = self.hj.read_bytes()
        for args in (("Synthetic habit",), ("Synthetic habit", "--write")):
            r = self.run_cli(*args)
            self.assertEqual(r.returncode, 3, r.stderr)
            self.assertEqual(r.stdout.splitlines(), ["refused: a habit week is already running: one habit a week"])
        self.assertEqual(self.hj.read_bytes(), before)

    def test_empty_habit_exits_three(self):
        r = self.run_cli("  ", "--write")
        self.assertEqual(r.returncode, 3)
        self.assertEqual(r.stdout.splitlines(), ["refused: the habit text is empty"])
        self.assertEqual(list(self.st.iterdir()), [])

    def test_finished_week_is_kept(self):
        old = (date.today() - timedelta(days=8)).isoformat()
        self.hj.write_text(json.dumps({"habit": "Older synthetic habit", "week_of": old}))
        r = self.run_cli("Synthetic habit", "--write")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"kept as habit-{old}.json", r.stdout)
        self.assertTrue((self.st / f"habit-{old}.json").exists())

    def test_state_dir_from_config(self):
        cfg = self.home / "config.json"
        cfg.write_text(json.dumps({"state": str(self.st)}))
        env = dict(self.env, LIMITLESS_CONFIG=str(cfg))
        del env["LIMITLESS_STATE"]
        r = self.run_cli("Synthetic habit", "--write", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.hj.exists())


if __name__ == "__main__":
    unittest.main()
