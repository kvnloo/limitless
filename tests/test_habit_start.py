"""Starting a habit week: one habit a week, written only on --write / confirm. Synthetic data; fake push only.

start_week(state_dir, habit, today, write) writes habit.json {"habit", "week_of", "start", "at",
"checkins": {}} with the same atomic 0600 write habit_replies uses. It refuses, writing nothing, when
the habit text is empty or a week is already running (habit_week_gate is None for the existing file).
A finished week is kept as habit-<week_of>.json next to the new one, never deleted.
"""
import json
import os
import stat
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import habit_start, jobs, jobs_runner  # noqa: E402

NOW = 2_000_000_000.0
H = 3600.0
TODAY = date.fromtimestamp(NOW)
HABIT = "Synthetic habit"


def week(days_back, habit="Older synthetic habit"):
    return {"week_of": (TODAY - timedelta(days=days_back)).isoformat(), "habit": habit,
            "start": "Synthetic first step", "checkins": {(TODAY - timedelta(days=days_back)).isoformat(): "Done"}}


def write_rows(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.hj = self.st / "habit.json"

    def tearDown(self):
        self.tmp.cleanup()

    def start(self, habit=HABIT, write=True, **kw):
        return habit_start.start_week(self.st, habit, TODAY, write, now=NOW, **kw)

    def files(self):
        return sorted(p.name for p in self.st.iterdir())


class StartWeek(Base):
    def test_dry_run_writes_nothing(self):
        r = self.start(write=False)
        self.assertEqual(r["action"], habit_start.WOULD_START)
        self.assertEqual((r["habit"], r["week_of"]), (HABIT, TODAY.isoformat()))
        self.assertEqual(self.files(), [])

    def test_write_starts_the_week(self):
        r = self.start()
        self.assertEqual(r["action"], habit_start.STARTED)
        got = json.loads(self.hj.read_text())
        self.assertEqual(got["habit"], HABIT)
        self.assertEqual(got["week_of"], TODAY.isoformat())
        self.assertEqual(got["checkins"], {})
        self.assertIn("start", got)
        self.assertEqual(got["at"], "2033-05-18T03:33:20+00:00")
        self.assertIsNone(jobs.habit_week_gate(got, TODAY))

    def test_habit_text_is_trimmed(self):
        self.start("  Synthetic habit \n")
        self.assertEqual(json.loads(self.hj.read_text())["habit"], HABIT)

    def test_first_step_is_kept_when_given(self):
        self.start(first_step="Synthetic two-minute step")
        self.assertEqual(json.loads(self.hj.read_text())["start"], "Synthetic two-minute step")

    def test_file_is_private_and_no_temp_file_is_left(self):
        self.start()
        self.assertEqual(stat.S_IMODE(self.hj.stat().st_mode), 0o600)
        self.assertEqual(self.files(), ["habit.json"])

    def test_empty_habit_is_refused(self):
        for text in ("", "   ", None, 7):
            r = self.start(text)
            self.assertEqual(r["action"], habit_start.REFUSED, repr(text))
            self.assertEqual(r["reason"], "the habit text is empty")
            self.assertEqual(self.files(), [])

    def test_a_running_week_is_refused_and_kept(self):
        for back in range(7):
            old = week(back)
            self.hj.write_text(json.dumps(old))
            before = self.hj.read_bytes()
            for write in (True, False):
                r = self.start(write=write)
                self.assertEqual(r["action"], habit_start.REFUSED, back)
                self.assertEqual(r["reason"], "a habit week is already running: one habit a week")
            self.assertEqual(self.hj.read_bytes(), before)
            self.assertEqual(self.files(), ["habit.json"])

    def test_a_week_set_for_later_is_refused(self):
        self.hj.write_text(json.dumps(week(-2)))
        r = self.start()
        self.assertEqual(r["action"], habit_start.REFUSED)
        self.assertEqual(r["reason"], "a habit week is already set to start later: one habit a week")
        self.assertEqual(self.files(), ["habit.json"])

    def test_a_finished_week_is_replaced_and_kept(self):
        for back in (7, 8, 30):
            old = week(back)
            self.hj.write_text(json.dumps(old))
            before = self.hj.read_bytes()
            r = self.start()
            self.assertEqual(r["action"], habit_start.STARTED, back)
            kept = self.st / f"habit-{old['week_of']}.json"
            self.assertEqual(r["kept"], kept.name)
            self.assertEqual(kept.read_bytes(), before)
            self.assertEqual(stat.S_IMODE(kept.stat().st_mode), 0o600)
            self.assertEqual(json.loads(self.hj.read_text())["habit"], HABIT)
            for p in self.st.iterdir():
                p.unlink()

    def test_dry_run_on_a_finished_week_says_what_it_would_keep(self):
        old = week(9)
        self.hj.write_text(json.dumps(old))
        r = self.start(write=False)
        self.assertEqual(r["action"], habit_start.WOULD_START)
        self.assertEqual(r["kept"], f"habit-{old['week_of']}.json")
        self.assertEqual(self.files(), ["habit.json"])

    def test_an_already_kept_week_is_never_overwritten(self):
        old = week(9)
        self.hj.write_text(json.dumps(old))
        kept = self.st / f"habit-{old['week_of']}.json"
        kept.write_text("an earlier copy")
        r = self.start()
        self.assertEqual(r["action"], habit_start.REFUSED)
        self.assertEqual(r["reason"], "an older habit file for that week is already kept: left as it is")
        self.assertEqual(kept.read_text(), "an earlier copy")
        self.assertEqual(json.loads(self.hj.read_text()), old)

    def test_an_undated_or_unreadable_file_is_kept_as_undated(self):
        for text in ('{"habit": "Older synthetic habit", "checkins": {}}', "not json"):
            self.hj.write_text(text)
            r = self.start()
            self.assertEqual(r["action"], habit_start.STARTED, text)
            self.assertEqual((self.st / "habit-undated.json").read_text(), text)
            (self.st / "habit-undated.json").unlink()

    def test_reasons_and_actions_are_digit_free_plain_words(self):
        self.hj.write_text(json.dumps(week(1)))
        rows = [self.start(""), self.start()]
        self.hj.unlink()
        rows += [self.start(write=False), self.start()]
        for r in rows:
            self.assertRegex(r["action"], r"^[a-z ]+$")
            self.assertRegex(r["reason"], r"^[a-z :]+$")
            self.assertRegex(habit_start.label(r), r"^[a-z :]+$")

    def test_line_says_would_start_started_or_refused(self):
        self.assertTrue(habit_start.line(self.start(write=False)).startswith("would start: Synthetic habit"))
        self.assertTrue(habit_start.line(self.start()).startswith("started: Synthetic habit"))
        self.assertEqual(habit_start.line(self.start()),
                         "refused: a habit week is already running: one habit a week")


class StartThenCheckIn(Base):
    def test_after_a_start_the_check_in_delivers(self):
        env = {"LIMITLESS_CONFIG": str(self.root / "no-config.json")}
        write_rows(self.st / "sleepmode.jsonl", [{"at": NOW - 8.5 * H, "on": True}, {"at": NOW - 0.2 * H, "on": False}])
        (self.st / "sleepmode-poll.json").write_text(json.dumps({"at": NOW - 60, "ok": True}))
        write_rows(self.st / "unlocks.jsonl", [{"at": NOW - 120}])
        write_rows(self.st / "events.jsonl", [{"event": "habit_cue", "at": NOW - 60}])
        calls = []

        def push(title, text):
            calls.append((title, text))
            return "telegram"

        rows = {r["job"]: r for r in jobs_runner.run_once(self.st, NOW, push=push, dry_run=False,
                                                          env=env, home=self.root)}
        self.assertEqual(rows["Habit check-in"]["reason"], "no habit week started")
        self.assertEqual(self.start()["action"], habit_start.STARTED)
        self.assertIsNone(jobs.habit_week_gate(json.loads(self.hj.read_text()), TODAY))
        rows = {r["job"]: r for r in jobs_runner.run_once(self.st, NOW, push=push, dry_run=False,
                                                          env=env, home=self.root)}
        self.assertEqual(rows["Habit check-in"]["action"], jobs.DELIVER)
        self.assertIn("Did you do it today: Synthetic habit?", dict(calls)["Habit check-in"])


if __name__ == "__main__":
    unittest.main()
