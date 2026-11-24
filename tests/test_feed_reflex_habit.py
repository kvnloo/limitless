"""The circuit-breaker hint: when the feed reflex is "often" and the feeds-free habit is not running, the existing
"Next up" suggestion may name the circuit-breaker habit. Suggest only: nothing starts, nothing is written."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from limitless import habit_catalogue as hc  # noqa: E402
from limitless import jobs_runner, tools  # noqa: E402
from test_aw_reader import make_db  # noqa: E402

CB = hc.CIRCUIT_BREAKER
FEEDS = hc.CATALOGUE[0]
UTC = timezone.utc
NOW = 2_000_000_000.0
TODAY = datetime.fromtimestamp(NOW, UTC).date()


def loop(*pairs):
    return [{"kind": "loop", "week_of": f"2030-01-0{i + 1}", "habit": h, "decision": d}
            for i, (h, d) in enumerate(pairs)]


class Entry(unittest.TestCase):
    def test_the_entry_keeps_the_catalogue_rules(self):
        self.assertEqual(hc.problems([CB]), [])
        self.assertEqual(CB["layer"], "foundation")

    def test_it_is_findable_but_not_on_the_ordered_list(self):
        self.assertIs(hc.find(CB["id"]), CB)
        self.assertIs(hc.find(CB["name"].upper()), CB)
        self.assertNotIn(CB, hc.CATALOGUE)
        self.assertLessEqual(len(hc.CATALOGUE), hc.MAX_HABITS)
        self.assertEqual(FEEDS["id"], "feeds_free_first_hour")

    def test_decisions_know_it(self):
        self.assertEqual(hc.decisions(loop((CB["name"], "Drop"))), {CB["id"]: "Drop"})


class NextHabit(unittest.TestCase):
    def test_without_the_reflex_nothing_changes(self):
        for rows, cur in (([], None), (loop((FEEDS["name"], "Drop")), None), ([], FEEDS["name"])):
            self.assertEqual(hc.next_habit(rows, current=cur), hc.next_habit(rows, current=cur, reflex_often=False))
            self.assertIsNot(hc.next_habit(rows, current=cur).habit, CB)

    def test_often_names_the_circuit_breaker(self):
        n = hc.next_habit([], reflex_often=True)
        self.assertIs(n.habit, CB)
        self.assertEqual(n.reason, hc.CIRCUIT_REASON)
        self.assertNotRegex(n.reason, r"\d")

    def test_not_while_the_feeds_free_habit_runs(self):
        n = hc.next_habit([], current={"habit": FEEDS["name"]}, reflex_often=True)
        self.assertIsNot(n.habit, CB)
        self.assertEqual(n, hc.next_habit([], current={"habit": FEEDS["name"]}))

    def test_not_while_it_runs_or_once_the_person_decided_it(self):
        self.assertIsNot(hc.next_habit([], current=CB["name"], reflex_often=True).habit, CB)
        for d in ("Keep", "Drop"):
            self.assertIsNot(hc.next_habit(loop((CB["name"], d)), reflex_often=True).habit, CB)

    def test_review_line_after_dropping_the_feeds_free_week(self):
        week = {"week_of": "2030-01-08", "habit": FEEDS["name"]}
        self.assertEqual(hc.review_line("Drop", [], week, reflex_often=True), f"{hc.NEXT_PREFIX}{CB['name']}.")
        self.assertEqual(hc.review_line("Drop", [], week), hc.review_line("Drop", [], week, reflex_often=False))
        self.assertEqual(hc.review_line("Keep", [], week, reflex_often=True), "")

    def test_review_line_never_offers_it_straight_back(self):
        week = {"week_of": "2030-01-08", "habit": CB["name"]}
        self.assertNotIn(CB["name"], hc.review_line("Drop", [], week, reflex_often=True))


class Wired(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.cfg = self.root / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg)}
        self.week = {"week_of": (TODAY - timedelta(days=6)).isoformat(), "habit": "Synthetic habit"}
        unlocks = [NOW - (i + 2) * 3600.0 for i in range(6)]
        make_db(self.st / "aw.db", unlocks=unlocks, spans=[(u + 2, u + 300, "feedapp") for u in unlocks])

    def files(self):
        return sorted((str(p), p.stat().st_mtime_ns) for p in self.root.rglob("*"))

    def test_week_next_names_it_when_often(self):
        self.cfg.write_text(json.dumps({"aw_db": "aw.db", "feed_apps": ["feedapp"]}))
        before = self.files()
        line = jobs_runner.week_next(self.st, self.week, "Drop", self.env, self.root, tz=UTC)
        self.assertEqual(line, f"{hc.NEXT_PREFIX}{CB['name']}.")
        self.assertEqual(self.files(), before)   # nothing written, nothing started

    def test_week_next_unchanged_without_feed_apps(self):
        self.cfg.write_text(json.dumps({"aw_db": "aw.db"}))
        line = jobs_runner.week_next(self.st, self.week, "Drop", self.env, self.root, tz=UTC)
        self.assertEqual(line, f"{hc.NEXT_PREFIX}{FEEDS['name']}.")

    def test_habit_next_tool_names_it_and_starts_nothing(self):
        self.cfg.write_text(json.dumps({"aw_db": "aw.db", "feed_apps": ["feedapp"]}))
        before = self.files()
        out = tools.habit_next(self.st, NOW, TODAY, env=self.env, home=self.root, tz=UTC)
        self.assertEqual(out["value"]["id"], CB["id"])
        self.assertEqual(out["because"], hc.CIRCUIT_REASON)
        self.assertIn("nothing was started", out["note"])
        self.assertEqual(self.files(), before)
        self.cfg.write_text(json.dumps({"aw_db": "aw.db"}))
        self.assertEqual(tools.habit_next(self.st, NOW, TODAY, env=self.env, home=self.root, tz=UTC)
                         ["value"]["id"], FEEDS["id"])


if __name__ == "__main__":
    unittest.main()
