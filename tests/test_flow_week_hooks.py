"""The flow line in the week review (digits, Telegram only) and the card's digit-free flow label.

Synthetic data only: a tiny ActivityWatch DB built in setUp, made-up app names, a fake push.
"""
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import card, jobs, jobs_runner  # noqa: E402

KD = "\nReply: Keep / Drop"   # the week review's choices line (one_tap), always its last line
from limitless.state_reader import StateReader  # noqa: E402

UTC = timezone.utc
NS = 1_000_000_000
H = 3600.0
FIX = Path(__file__).resolve().parent / "fixtures" / "state"


def write_db(path, spans):
    """``spans``: (start_s, end_s, app) app-in-foreground spans in the ActivityWatch schema."""
    con = sqlite3.connect(str(path))
    con.executescript("""
        CREATE TABLE buckets(id INTEGER PRIMARY KEY, name TEXT UNIQUE, type TEXT, client TEXT,
                             hostname TEXT, created TEXT, data TEXT);
        CREATE TABLE events(id INTEGER PRIMARY KEY, bucketrow INTEGER, starttime INTEGER, endtime INTEGER,
                            data TEXT);
        INSERT INTO buckets VALUES (1, 'w', 'currentwindow', 'test', 'test-host', '', '{}');""")
    for s, e, app in spans:
        con.execute("INSERT INTO events(bucketrow, starttime, endtime, data) VALUES (1, ?, ?, ?)",
                    (int(s * NS), int(e * NS), json.dumps({"app": app, "package": "org.example." + app})))
    con.commit()
    con.close()


class FakePush:
    def __init__(self):
        self.calls = []

    def __call__(self, title, body, once=None):
        self.calls.append((title, body, once))
        return "telegram"


NOW = 2_000_000_000.0
TODAY = datetime.fromtimestamp(NOW, UTC).date()


def noon(d: date, tz=UTC) -> float:
    return datetime.combine(d, time(12), tzinfo=tz).timestamp()


class WeekReview(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.cfg = self.root / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg)}
        self.week_of = TODAY - timedelta(days=6)
        self.habit = {"week_of": self.week_of.isoformat(), "habit": "Synthetic habit",
                      "checkins": {self.week_of.isoformat(): "Done"}}
        (self.st / "habit.json").write_text(json.dumps(self.habit))
        (self.st / "events.jsonl").write_text(json.dumps({"event": "habit_cue", "at": NOW - 60}) + "\n")

    def tearDown(self):
        self.tmp.cleanup()

    def review(self):
        push = FakePush()
        rows = jobs_runner.run_once(self.st, NOW, push=push, dry_run=False, env=self.env, home=self.root, tz=UTC)
        row = {r["job"]: r for r in rows}["Week review"]
        self.assertEqual(row["action"], jobs.DELIVER, row)
        bodies = [c[1] for c in push.calls if c[0] == "Week review"]
        self.assertTrue(all(b.endswith(KD) for b in bodies), bodies)
        return [b[:-len(KD)] for b in bodies]

    def test_body_adds_the_flow_line_after_the_review_text(self):
        text = jobs.week_review_text(self.habit)
        self.assertEqual(jobs_runner.body(jobs.WEEK_REVIEW, self.habit, flow="Flow: x."), text + "\nFlow: x." + KD)
        self.assertEqual(jobs_runner.body(jobs.WEEK_REVIEW, self.habit, flow=""), text + KD)
        check = jobs_runner.body(jobs.HABIT_CHECKIN, self.habit, flow="Flow: x.")
        self.assertNotIn("Flow", check)

    def test_the_review_carries_this_week_and_last_week(self):
        write_db(self.st / "aw.db", [
            (noon(self.week_of), noon(self.week_of) + 2 * H, "editor"),
            (noon(self.week_of + timedelta(days=2)), noon(self.week_of + timedelta(days=2)) + H, "editor"),
            (noon(self.week_of - timedelta(days=3)), noon(self.week_of - timedelta(days=3)) + H, "editor")])
        self.cfg.write_text(json.dumps({"aw_db": "aw.db", "flow_work_apps": ["editor"]}))
        bodies = self.review()
        self.assertEqual(len(bodies), 1)
        first, flow = bodies[0].split("\n")
        self.assertEqual(first, jobs.week_review_text(self.habit))
        self.assertEqual(flow, "Flow (measured, 2 of 7 days): deep work 180 min (last week 60); "
                               "feed leak unknown (no focus blocks).")

    def test_a_configured_db_with_no_week_data_says_not_recording(self):
        write_db(self.st / "aw.db", [])
        self.cfg.write_text(json.dumps({"aw_db": "aw.db"}))
        self.assertEqual(self.review()[0].split("\n")[1],
                         "Flow: not recording this week (no ActivityWatch data).")

    def test_no_db_configured_leaves_the_review_unchanged(self):
        self.assertEqual(self.review(), [jobs.week_review_text(self.habit)])

    def test_the_db_is_never_written(self):
        db = self.st / "aw.db"
        write_db(db, [(noon(self.week_of), noon(self.week_of) + H, "editor")])
        self.cfg.write_text(json.dumps({"aw_db": "aw.db", "flow_work_apps": ["editor"]}))
        before = (db.read_bytes(), db.stat().st_mtime_ns)
        self.review()
        self.assertEqual((db.read_bytes(), db.stat().st_mtime_ns), before)


CARD_NOW = 1894708800.0
CARD_TODAY = date(2030, 1, 15)


def local_noon(d: date) -> float:
    return datetime.combine(d, time(12)).timestamp()      # the card reads days in this machine's zone


class Card(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Path(self.tmp.name) / "state"
        shutil.copytree(FIX, self.st)
        self.db = Path(self.tmp.name) / "aw.db"
        self.env = {"LIMITLESS_CONFIG": str(Path(self.tmp.name) / "none.json"), "LIMITLESS_AW_DB": str(self.db),
                    "LIMITLESS_FLOW_WORK_APPS": "editor"}

    def tearDown(self):
        self.tmp.cleanup()

    def spans(self, this_h, last_h):
        """``this_h`` hours of editor today and ``last_h`` hours a week earlier."""
        t, l = local_noon(CARD_TODAY), local_noon(CARD_TODAY - timedelta(days=7))
        return [(t, t + this_h * H, "editor"), (l, l + last_h * H, "editor")]

    def habit_line(self, env):
        lines = card.build(StateReader(self.st), CARD_NOW, CARD_TODAY, env=env)["lines"]
        self.assertLessEqual(len(lines), card.MAX_LINES)
        return [ln for ln in lines if ln.startswith("habit")][0]

    def test_the_habit_line_carries_a_digit_free_flow_label(self):
        write_db(self.db, self.spans(3, 1))
        line = self.habit_line(self.env)
        self.assertTrue(line.endswith("; flow: deep work up on last week (measured)"), line)
        self.assertFalse(any(c.isdigit() for c in line))

    def test_no_data_this_week_says_not_recording(self):
        write_db(self.db, [])
        self.assertTrue(self.habit_line(self.env).endswith("; flow: not recording"))

    def test_raw_opt_in_still_gets_no_numbers_from_flow(self):
        write_db(self.db, self.spans(3, 1))
        lines = card.build(StateReader(self.st), CARD_NOW, CARD_TODAY, env=self.env, raw=True)["lines"]
        self.assertIn("; flow: deep work up on last week (measured)", "\n".join(lines))

    def test_no_db_configured_no_flow_label(self):
        env = {"LIMITLESS_CONFIG": self.env["LIMITLESS_CONFIG"]}
        self.assertNotIn("flow", self.habit_line(env))

    def test_cache_rebuilds_when_the_db_changes(self):
        write_db(self.db, self.spans(3, 1))
        cache = card.CardCache()
        reader = StateReader(self.st)
        first = cache.get(reader, CARD_NOW, CARD_TODAY, env=self.env)
        self.assertIn("deep work up", first)
        self.assertEqual(cache.get(reader, CARD_NOW, CARD_TODAY, env=self.env), first)
        self.assertEqual(cache.builds, 1)
        self.db.unlink()
        write_db(self.db, self.spans(1, 3))
        os.utime(self.db, ns=(self.db.stat().st_mtime_ns + 10 ** 9,) * 2)
        self.assertIn("deep work down", cache.get(reader, CARD_NOW, CARD_TODAY, env=self.env))
        self.assertEqual(cache.builds, 2)


if __name__ == "__main__":
    unittest.main()
