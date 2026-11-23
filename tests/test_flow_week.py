"""Weekly deep-work minutes and feed leak per block-hour from an ActivityWatch DB copy (no score).

Synthetic DBs only, built in setUp with the ActivityWatch schema; app names are made up. The zone is a
fixed synthetic offset; only the local day boundaries it gives matter.
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import flow_week  # noqa: E402

NS = 1_000_000_000
TZ = timezone(timedelta(hours=-5))
WEEK_OF = date(2033, 5, 16)
WORK = ("editor",)
FEEDS = ("scroller",)

SCHEMA = """
CREATE TABLE buckets(id INTEGER PRIMARY KEY, name TEXT UNIQUE, type TEXT, client TEXT, hostname TEXT,
                     created TEXT, data TEXT);
CREATE TABLE events(id INTEGER PRIMARY KEY, bucketrow INTEGER REFERENCES buckets(id), starttime INTEGER,
                    endtime INTEGER, data TEXT);
"""


def at(day: int, hour: float) -> float:
    """Epoch seconds for local hour ``hour`` on day ``day`` (0 = WEEK_OF) of the synthetic zone."""
    d = datetime(WEEK_OF.year, WEEK_OF.month, WEEK_OF.day, tzinfo=TZ) + timedelta(days=day, hours=hour)
    return d.timestamp()


def make_db(path, spans=(), afk=()):
    """``spans``: (start_s, end_s, app[, title]) app-in-foreground spans; ``afk``: (start_s, end_s, status)."""
    con = sqlite3.connect(str(path))
    con.executescript(SCHEMA)
    con.execute("INSERT INTO buckets VALUES (1, 'w', 'currentwindow', 'test', 'test-host', '', '{}')")
    con.execute("INSERT INTO buckets VALUES (2, 'u', 'os.lockscreen.unlocks', 'test', 'test-host', '', '{}')")
    if afk:
        con.execute("INSERT INTO buckets VALUES (3, 'a', 'afkstatus', 'test', 'test-host', '', '{}')")
    for s in spans:
        start, end, app = s[:3]
        data = {"app": app, "package": "org.example." + app}
        if len(s) > 3:
            data["title"] = s[3]
        con.execute("INSERT INTO events(bucketrow, starttime, endtime, data) VALUES (1, ?, ?, ?)",
                    (int(start * NS), int(end * NS), json.dumps(data)))
    for start, end, status in afk:
        con.execute("INSERT INTO events(bucketrow, starttime, endtime, data) VALUES (3, ?, ?, ?)",
                    (int(start * NS), int(end * NS), json.dumps({"status": status})))
    con.commit()
    con.close()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "aw.db"

    def tearDown(self):
        self.tmp.cleanup()

    def week(self, blocks=None, work=WORK, feeds=FEEDS, week_of=WEEK_OF):
        return flow_week.week(self.db, week_of, TZ, blocks=blocks, work_apps=work, feed_apps=feeds)


class DeepWork(Base):
    def test_deep_minutes_are_active_time_in_work_apps(self):
        make_db(self.db, spans=[(at(0, 9), at(0, 10), "editor"), (at(0, 10), at(0, 10.5), "scroller"),
                                (at(2, 14), at(2, 14.25), "editor")])
        w = self.week()
        self.assertEqual(w["deep_min"], 75.0)
        self.assertEqual(w["days_with_data"], 2)
        self.assertEqual(w["modality"], "measured")

    def test_work_apps_match_app_or_package_case_folded(self):
        make_db(self.db, spans=[(at(0, 9), at(0, 9.5), "editor"), (at(1, 9), at(1, 9.5), "other")])
        self.assertEqual(self.week(work=("ORG.EXAMPLE.OTHER",))["deep_min"], 30.0)

    def test_title_entries_match_inside_the_window_title(self):
        make_db(self.db, spans=[(at(0, 9), at(0, 10), "browser", "Project notes - Browser"),
                                (at(0, 10), at(0, 11), "browser", "Videos - Browser")])
        self.assertEqual(self.week(work=("title:project notes",))["deep_min"], 60.0)

    def test_overlapping_spans_count_once(self):
        make_db(self.db, spans=[(at(0, 9), at(0, 10), "editor"), (at(0, 9.5), at(0, 10.5), "editor")])
        self.assertEqual(self.week()["deep_min"], 90.0)

    def test_only_the_seven_local_days_count(self):
        make_db(self.db, spans=[(at(-1, 23), at(0, 1), "editor"), (at(6, 23.5), at(7, 2), "editor"),
                                (at(8, 9), at(8, 10), "editor")])
        w = self.week()
        self.assertEqual(w["deep_min"], 90.0)      # one hour after the start, half an hour before the end
        self.assertEqual(w["days_with_data"], 2)

    def test_afk_time_is_not_active(self):
        make_db(self.db, spans=[(at(0, 9), at(0, 11), "editor")],
                afk=[(at(0, 9), at(0, 10), "not-afk"), (at(0, 10), at(0, 11), "afk")])
        self.assertEqual(self.week()["deep_min"], 60.0)

    def test_no_work_apps_is_unknown_never_guessed(self):
        make_db(self.db, spans=[(at(0, 9), at(0, 10), "editor")])
        w = self.week(work=())
        self.assertIsNone(w["deep_min"])
        self.assertEqual(w["days_with_data"], 1)
        self.assertIn("no work apps", w["evidence"]["deep"])

    def test_week_of_may_be_an_iso_string(self):
        make_db(self.db, spans=[(at(0, 9), at(0, 10), "editor")])
        self.assertEqual(self.week(week_of=WEEK_OF.isoformat())["deep_min"], 60.0)


class FeedLeak(Base):
    def test_leak_is_feed_time_inside_focus_blocks(self):
        make_db(self.db, spans=[(at(0, 9), at(0, 9.75), "editor"), (at(0, 9.75), at(0, 10.25), "scroller"),
                                (at(0, 12), at(0, 13), "scroller")])
        w = self.week(blocks=[(at(0, 9), at(0, 10))])
        self.assertEqual(w["block_hours"], 1.0)
        self.assertEqual(w["feed_leak_min"], 15.0)
        self.assertEqual(w["leak_per_block_hour"], 15.0)

    def test_block_dicts_like_glides_are_accepted(self):
        make_db(self.db, spans=[(at(1, 9), at(1, 9.5), "scroller"), (at(1, 9.5), at(1, 11), "editor")])
        w = self.week(blocks=[{"start": at(1, 9), "end": at(1, 11), "minutes": 120}])
        self.assertEqual(w["block_hours"], 2.0)
        self.assertEqual(w["leak_per_block_hour"], 15.0)

    def test_no_blocks_is_unknown_leak(self):
        make_db(self.db, spans=[(at(0, 9), at(0, 10), "scroller")])
        for blocks in (None, []):
            w = self.week(blocks=blocks)
            self.assertIsNone(w["block_hours"], blocks)
            self.assertIsNone(w["feed_leak_min"], blocks)
            self.assertIsNone(w["leak_per_block_hour"], blocks)
            self.assertIn("no focus blocks", w["evidence"]["leak"])

    def test_a_clean_block_is_zero_leak_not_unknown(self):
        make_db(self.db, spans=[(at(0, 9), at(0, 10), "editor")])
        w = self.week(blocks=[(at(0, 9), at(0, 10))])
        self.assertEqual(w["feed_leak_min"], 0.0)
        self.assertEqual(w["leak_per_block_hour"], 0.0)

    def test_no_feed_list_is_unknown_leak(self):
        make_db(self.db, spans=[(at(0, 9), at(0, 10), "scroller")])
        w = self.week(blocks=[(at(0, 9), at(0, 10))], feeds=())
        self.assertEqual(w["block_hours"], 1.0)
        self.assertIsNone(w["feed_leak_min"])
        self.assertIsNone(w["leak_per_block_hour"])

    def test_block_time_after_the_newest_event_is_not_covered(self):
        make_db(self.db, spans=[(at(0, 9), at(0, 9.5), "scroller")])
        w = self.week(blocks=[(at(0, 9), at(0, 11))])       # the phone data stops half an hour in
        self.assertEqual(w["block_hours"], 0.5)
        self.assertEqual(w["leak_per_block_hour"], 60.0)

    def test_blocks_outside_the_week_do_not_count(self):
        make_db(self.db, spans=[(at(0, 9), at(0, 10), "scroller"), (at(9, 9), at(9, 10), "scroller")])
        w = self.week(blocks=[(at(9, 9), at(9, 10))])
        self.assertIsNone(w["block_hours"])
        self.assertIsNone(w["leak_per_block_hour"])


UNKNOWN_FIELDS = ("deep_min", "block_hours", "feed_leak_min", "leak_per_block_hour", "days_with_data")


class MissingIsUnknown(Base):
    def assert_all_unknown(self, w, why):
        for k in UNKNOWN_FIELDS:
            self.assertIsNone(w[k], k)
        self.assertEqual(w["modality"], "measured")
        self.assertIn(why, w["evidence"]["reason"])

    def test_no_db_path_is_all_unknown(self):
        for path in (None, ""):
            self.assert_all_unknown(flow_week.week(path, WEEK_OF, TZ, work_apps=WORK), "no ActivityWatch DB")

    def test_missing_file_is_all_unknown_and_not_created(self):
        self.assert_all_unknown(self.week(blocks=[(at(0, 9), at(0, 10))]), "no ActivityWatch DB")
        self.assertFalse(self.db.exists())

    def test_broken_db_is_all_unknown(self):
        self.db.write_bytes(b"not a database at all")
        self.assert_all_unknown(self.week(), "could not be read")
        sqlite3.connect(str(Path(self.tmp.name) / "empty.db")).close()
        w = flow_week.week(Path(self.tmp.name) / "empty.db", WEEK_OF, TZ, work_apps=WORK)
        self.assert_all_unknown(w, "could not be read")      # no AW tables

    def test_bad_week_of_is_all_unknown(self):
        make_db(self.db, spans=[(at(0, 9), at(0, 10), "editor")])
        for bad in ("next week", None, 7):
            self.assert_all_unknown(self.week(week_of=bad), "no valid week")

    def test_a_week_with_no_events_is_unknown_not_zero(self):
        make_db(self.db, spans=[(at(-9, 9), at(-9, 10), "editor")])
        w = self.week(blocks=[(at(0, 9), at(0, 10))])
        self.assertEqual(w["days_with_data"], 0)
        for k in UNKNOWN_FIELDS[:-1]:
            self.assertIsNone(w[k], k)
        self.assertIn("no ActivityWatch events", w["evidence"]["reason"])

    def test_a_day_with_no_events_is_not_counted(self):
        make_db(self.db, spans=[(at(0, 9), at(0, 10), "editor"), (at(3, 9), at(3, 9.5), "scroller"),
                                (at(3, 9.5), at(3, 10), "editor")])
        w = self.week(blocks=[(at(1, 9), at(1, 11)), (at(3, 9), at(3, 10))])   # day one has no data
        self.assertEqual(w["days_with_data"], 2)
        self.assertEqual(w["evidence"]["days"], ["2033-05-16", "2033-05-19"])
        self.assertEqual(w["block_hours"], 1.0)
        self.assertEqual(w["leak_per_block_hour"], 30.0)

    def test_bad_rows_are_skipped_never_raise(self):
        make_db(self.db, spans=[(at(0, 9), at(0, 10), "editor")])
        con = sqlite3.connect(str(self.db))
        con.execute("INSERT INTO events(bucketrow, starttime, endtime, data) VALUES (1, ?, ?, 'not json')",
                    (int(at(1, 9) * NS), int(at(1, 10) * NS)))
        con.execute("INSERT INTO events(bucketrow, starttime, endtime, data) VALUES (1, 'x', 'y', '{}')")
        con.commit()
        con.close()
        w = self.week(blocks=["junk", (None, 1), {"start": "a"}])
        self.assertEqual((w["deep_min"], w["days_with_data"], w["block_hours"]), (60.0, 1, None))


class ReadOnly(Base):
    def test_db_bytes_and_mtime_are_unchanged(self):
        make_db(self.db, spans=[(at(0, 9), at(0, 10), "editor")])
        before = (self.db.read_bytes(), self.db.stat().st_mtime_ns)
        self.week(blocks=[(at(0, 9), at(0, 10))])
        self.assertEqual((self.db.read_bytes(), self.db.stat().st_mtime_ns), before)
        self.assertEqual(sorted(p.name for p in Path(self.tmp.name).iterdir()), ["aw.db"])


if __name__ == "__main__":
    unittest.main()
