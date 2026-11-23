"""The habit check-in speaks only inside a started habit week. Synthetic data only; fake push only.

A week is started when habit.json names a habit and its ``week_of`` date is today or up to six days
back (days one to seven). No started week, or a week past its seventh day: the check-in drops.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import jobs, jobs_runner  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "limitless-jobs"
NOW = 2_000_000_000.0
H = 3600.0
TODAY = date.fromtimestamp(NOW)


def week(days_back, habit="Synthetic habit"):
    return {"week_of": (TODAY - timedelta(days=days_back)).isoformat(), "habit": habit, "checkins": {}}


def write_rows(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


class HabitWeekGate(unittest.TestCase):
    def test_started_week_days_one_to_seven(self):
        for back in range(7):
            self.assertIsNone(jobs.habit_week_gate(week(back), TODAY), back)

    def test_no_started_week_drops(self):
        cases = [None, {}, "junk", {"habit": "Synthetic habit"}, {"week_of": TODAY.isoformat()},
                 {"week_of": TODAY.isoformat(), "habit": "  "}, {"week_of": TODAY.isoformat(), "habit": 7},
                 {"week_of": "not a date", "habit": "Synthetic habit"}, {"week_of": None, "habit": "x"},
                 week(-1)]                                     # a week that starts tomorrow is not started
        for h in cases:
            v = jobs.habit_week_gate(h, TODAY)
            self.assertEqual(v, jobs.Verdict(jobs.DROP, "no habit week started"), repr(h))

    def test_week_over_after_day_seven(self):
        for back in (7, 8, 30):
            self.assertEqual(jobs.habit_week_gate(week(back), TODAY),
                             jobs.Verdict(jobs.DROP, "habit week over"), back)

    def test_reasons_are_plain_words(self):
        for h in (None, week(9)):
            reason = jobs.habit_week_gate(h, TODAY).reason
            self.assertRegex(reason, r"^[a-z ]+$")


class FakePush:
    def __init__(self):
        self.calls = []

    def __call__(self, title, body):
        self.calls.append((title, body))
        return "telegram"


class RunnerGate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.env = {"LIMITLESS_CONFIG": str(self.root / "no-config.json")}
        write_rows(self.st / "sleepmode.jsonl", [{"at": NOW - 8.5 * H, "on": True}, {"at": NOW - 0.2 * H, "on": False}])
        (self.st / "sleepmode-poll.json").write_text(json.dumps({"at": NOW - 60, "ok": True}))
        write_rows(self.st / "unlocks.jsonl", [{"at": NOW - 120}])
        write_rows(self.st / "events.jsonl", [{"event": "habit_cue", "at": NOW - 60}])

    def tearDown(self):
        self.tmp.cleanup()

    def run_pass(self, habit, push):
        if habit is not None:
            (self.st / "habit.json").write_text(json.dumps(habit))
        rows = jobs_runner.run_once(self.st, NOW, push=push, dry_run=False, env=self.env, home=self.root)
        return {r["job"]: r for r in rows}

    def habit_calls(self, push):
        return [c for c in push.calls if c[0] == "Habit check-in"]

    def sent_jobs(self):
        p = self.st / "jobs-sent.jsonl"
        return [json.loads(ln).get("job") for ln in p.read_text().splitlines()] if p.exists() else []

    def test_no_habit_json_drops_and_sends_nothing(self):
        push = FakePush()
        row = self.run_pass(None, push)["Habit check-in"]
        self.assertEqual((row["action"], row["reason"]), (jobs.DROP, "no habit week started"))
        self.assertEqual(self.habit_calls(push), [])
        self.assertNotIn("habit_checkin", self.sent_jobs())

    def test_habit_without_week_drops_and_sends_nothing(self):
        push = FakePush()
        row = self.run_pass({"habit": "Synthetic habit", "checkins": {}}, push)["Habit check-in"]
        self.assertEqual((row["action"], row["reason"]), (jobs.DROP, "no habit week started"))
        self.assertEqual(self.habit_calls(push), [])

    def test_no_week_and_no_other_job_due_means_zero_push_calls(self):
        (self.st / "sleepmode.jsonl").unlink()      # no wake: only the habit cue could speak
        push = FakePush()
        rows = self.run_pass(None, push)
        self.assertEqual(rows["Habit check-in"]["action"], jobs.DROP)
        self.assertEqual(push.calls, [])
        self.assertEqual(self.sent_jobs(), [])

    def test_week_over_drops_and_sends_nothing(self):
        push = FakePush()
        row = self.run_pass(week(7), push)["Habit check-in"]
        self.assertEqual((row["action"], row["reason"]), (jobs.DROP, "habit week over"))
        self.assertEqual(self.habit_calls(push), [])

    def test_started_week_delivers_as_before(self):
        push = FakePush()
        row = self.run_pass(week(6), push)["Habit check-in"]
        self.assertEqual(row["action"], jobs.DELIVER)
        self.assertIn("Did you do it today: Synthetic habit?", dict(push.calls)["Habit check-in"])
        self.assertIn("habit_checkin", self.sent_jobs())

    def test_gate_leaves_the_other_jobs_alone(self):
        push = FakePush()
        self.assertEqual(self.run_pass(None, push)["Wake-up brief"]["action"], jobs.DELIVER)


class CliDryRun(unittest.TestCase):
    def test_dry_run_shows_no_habit_week_started(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            st = home / "state"
            st.mkdir()
            at = datetime.fromtimestamp(time.time() - 60, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            write_rows(st / "events.jsonl", [{"event": "habit_cue", "at": at}])
            env = {"HOME": str(home), "PATH": os.environ.get("PATH", ""), "LIMITLESS_STATE": str(st),
                   "LIMITLESS_CONFIG": str(home / "no-config.json")}
            r = subprocess.run([sys.executable, "-I", str(CLI)], env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("Habit check-in: drop: no habit week started", r.stdout.splitlines(), r.stdout)
            self.assertFalse((st / "jobs-sent.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
