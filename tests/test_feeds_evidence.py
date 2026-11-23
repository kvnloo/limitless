"""feeds_evidence: did the phone see a feed app in the first hour after a wake? A hint, never an answer.

Synthetic app starts and synthetic app names only. NOW is an arbitrary epoch; only differences between
times matter. Nothing here reads the clock or sends.
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from limitless import aw_reader, feeds_evidence, jobs  # noqa: E402
from test_aw_reader import make_db  # noqa: E402

NOW = 2_000_000_000.0
H = 3600.0
WAKE = NOW - 2 * H
FEEDS = ("feedapp", "otherfeed")


def start(t, app):
    return {"ts": t, "app": app}


class FirstHour(unittest.TestCase):
    def test_feed_app_in_the_hour_is_seen(self):
        rows = [start(WAKE, "reader"), start(WAKE + 600, "feedapp"), start(WAKE + 1.5 * H, "reader")]
        self.assertEqual(feeds_evidence.feeds_in_first_hour(rows, WAKE, FEEDS), {"seen": True, "count": 1})

    def test_counts_every_feed_start_in_the_hour(self):
        rows = [start(WAKE + 60, "feedapp"), start(WAKE + 120, "otherfeed"), start(WAKE + 180, "feedapp"),
                start(WAKE + H, "reader")]
        self.assertEqual(feeds_evidence.feeds_in_first_hour(rows, WAKE, FEEDS), {"seen": True, "count": 3})

    def test_no_feed_app_in_a_covered_hour_is_not_seen(self):
        rows = [start(WAKE, "reader"), start(WAKE + 900, "maps"), start(WAKE + 1.2 * H, "reader")]
        self.assertEqual(feeds_evidence.feeds_in_first_hour(rows, WAKE, FEEDS), {"seen": False, "count": 0})

    def test_the_hour_is_half_open(self):
        rows = [start(WAKE - 1, "feedapp"), start(WAKE + jobs.HABIT_CUE_AFTER_S, "feedapp")]
        self.assertEqual(feeds_evidence.feeds_in_first_hour(rows, WAKE, FEEDS), {"seen": False, "count": 0})
        rows = [start(WAKE, "feedapp"), start(WAKE + jobs.HABIT_CUE_AFTER_S - 1, "reader"),
                start(WAKE + 2 * H, "reader")]
        self.assertEqual(feeds_evidence.feeds_in_first_hour(rows, WAKE, FEEDS), {"seen": True, "count": 1})

    def test_no_rows_is_unknown_not_clean(self):
        self.assertEqual(feeds_evidence.feeds_in_first_hour([], WAKE, FEEDS), {"seen": None, "count": 0})
        self.assertEqual(feeds_evidence.feeds_in_first_hour(None, WAKE, FEEDS), {"seen": None, "count": 0})

    def test_data_that_stops_inside_the_hour_is_unknown(self):
        rows = [start(WAKE, "reader"), start(WAKE + 0.5 * H, "maps")]
        self.assertEqual(feeds_evidence.feeds_in_first_hour(rows, WAKE, FEEDS), {"seen": None, "count": 0})

    def test_data_that_stops_inside_the_hour_is_unknown_even_with_a_feed_seen(self):
        # The hour is not covered, so the answer is unknown; the count says what was seen so far.
        rows = [start(WAKE + 60, "feedapp")]
        self.assertEqual(feeds_evidence.feeds_in_first_hour(rows, WAKE, FEEDS), {"seen": None, "count": 1})

    def test_newest_row_at_the_hour_end_covers_it(self):
        rows = [start(WAKE + 60, "reader"), start(WAKE + jobs.HABIT_CUE_AFTER_S, "reader")]
        self.assertEqual(feeds_evidence.feeds_in_first_hour(rows, WAKE, FEEDS), {"seen": False, "count": 0})

    def test_no_feed_list_is_unknown(self):
        rows = [start(WAKE + 60, "feedapp"), start(WAKE + 2 * H, "reader")]
        for feeds in (None, (), [], ["", "  "]):
            self.assertEqual(feeds_evidence.feeds_in_first_hour(rows, WAKE, feeds), {"seen": None, "count": 0})

    def test_no_wake_is_unknown(self):
        rows = [start(WAKE + 60, "feedapp"), start(WAKE + 2 * H, "reader")]
        self.assertEqual(feeds_evidence.feeds_in_first_hour(rows, None, FEEDS), {"seen": None, "count": 0})

    def test_names_match_case_and_space_insensitively_and_by_package(self):
        rows = [start(WAKE + 60, " FeedApp "), {"ts": WAKE + 120, "app": "x", "package": "org.example.otherfeed"},
                start(WAKE + 2 * H, "reader")]
        self.assertEqual(feeds_evidence.feeds_in_first_hour(rows, WAKE, ["feedapp", "org.example.otherfeed"]),
                         {"seen": True, "count": 2})

    def test_bad_rows_are_skipped(self):
        rows = [None, "x", {"ts": "soon", "app": "feedapp"}, {"ts": True, "app": "feedapp"},
                {"ts": WAKE + 60}, start(WAKE + 2 * H, "reader")]
        self.assertEqual(feeds_evidence.feeds_in_first_hour(rows, WAKE, FEEDS), {"seen": False, "count": 0})

    def test_millisecond_rows_count_too(self):
        rows = [{"ts": (WAKE + 60) * 1000, "app": "feedapp"}, {"ts": (WAKE + 2 * H) * 1000, "app": "reader"}]
        self.assertEqual(feeds_evidence.feeds_in_first_hour(rows, WAKE, FEEDS), {"seen": True, "count": 1})

    def test_inputs_are_not_changed(self):
        rows = [start(WAKE + 60, "feedapp"), start(WAKE + 2 * H, "reader")]
        before = json.dumps(rows)
        feeds_evidence.feeds_in_first_hour(rows, WAKE, FEEDS)
        self.assertEqual(json.dumps(rows), before)


class FeedList(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cfg = self.root / "config.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_env_comma_list(self):
        env = {"LIMITLESS_FEED_APPS": " feedapp, otherfeed ,,", "LIMITLESS_CONFIG": str(self.cfg)}
        self.assertEqual(feeds_evidence.feed_apps(env, self.root), ("feedapp", "otherfeed"))

    def test_config_list_or_comma_string(self):
        env = {"LIMITLESS_CONFIG": str(self.cfg)}
        self.cfg.write_text(json.dumps({"feed_apps": ["feedapp", 3, " otherfeed "]}))
        self.assertEqual(feeds_evidence.feed_apps(env, self.root), ("feedapp", "otherfeed"))
        self.cfg.write_text(json.dumps({"feed_apps": "feedapp,otherfeed"}))
        self.assertEqual(feeds_evidence.feed_apps(env, self.root), ("feedapp", "otherfeed"))

    def test_env_wins_over_config(self):
        self.cfg.write_text(json.dumps({"feed_apps": ["otherfeed"]}))
        env = {"LIMITLESS_FEED_APPS": "feedapp", "LIMITLESS_CONFIG": str(self.cfg)}
        self.assertEqual(feeds_evidence.feed_apps(env, self.root), ("feedapp",))

    def test_none_set_is_empty_and_the_repo_ships_no_default(self):
        env = {"LIMITLESS_CONFIG": str(self.root / "absent.json")}
        self.assertEqual(feeds_evidence.feed_apps(env, self.root), ())
        self.assertFalse([n for n in dir(feeds_evidence) if "DEFAULT" in n.upper()])


class AppStarts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "aw.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_app_span_starts_with_names_unlocks_left_out(self):
        make_db(self.db, unlocks=[WAKE], spans=[(WAKE + 10, WAKE + 60, "feedapp"), (WAKE + 70, WAKE + 90, "maps")])
        self.assertEqual(aw_reader.app_starts(self.db), [
            {"ts": WAKE + 10, "app": "feedapp", "package": "org.example.feedapp"},
            {"ts": WAKE + 70, "app": "maps", "package": "org.example.maps"},
        ])

    def test_since_s_limits_rows(self):
        make_db(self.db, spans=[(WAKE - 60, WAKE - 30, "a"), (WAKE + 10, WAKE + 20, "b")])
        self.assertEqual([r["app"] for r in aw_reader.app_starts(self.db, since_s=WAKE)], ["b"])

    def test_missing_or_broken_db_is_empty(self):
        self.assertEqual(aw_reader.app_starts(None), [])
        self.assertEqual(aw_reader.app_starts(self.db), [])
        self.db.write_text("not a database")
        self.assertEqual(aw_reader.app_starts(self.db), [])

    def test_bad_json_rows_are_skipped(self):
        make_db(self.db, spans=[(WAKE + 10, WAKE + 20, "a")])
        con = sqlite3.connect(str(self.db))
        con.execute("INSERT INTO events(bucketrow, starttime, endtime, data) VALUES (2, ?, ?, 'nope')",
                    (int((WAKE + 30) * 1e9), int((WAKE + 40) * 1e9)))
        con.commit()
        con.close()
        self.assertEqual([r["app"] for r in aw_reader.app_starts(self.db)], ["a"])


if __name__ == "__main__":
    unittest.main()
