"""The doctor's feed reflex row: off, live or unknown, words only, never a value. Synthetic DBs only."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from limitless import doctor, feed_reflex  # noqa: E402
from test_aw_reader import make_db  # noqa: E402

NOW = 1894708800.0
H = 3600.0


class Row(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.st = Path(tmp.name)
        p = mock.patch.dict(os.environ, {}, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def db(self, n=6):
        unlocks = [NOW - (i + 2) * H for i in range(n)]
        make_db(self.st / f"aw-{n}.db", unlocks=unlocks, spans=[(u + 2, u + 300, "feedapp") for u in unlocks])
        return f"aw-{n}.db"

    def row(self, **cfg):
        cfg.setdefault("state", str(self.st))
        return doctor.feed_reflex_row(cfg, NOW)

    def check(self, r, status):
        self.assertEqual((r["name"], r["kind"], r["status"]), (doctor.FEED_REFLEX_ROW, "source", status), r)
        self.assertNotRegex(r["reason"], r"\d")
        self.assertNotIn("feedapp", r["reason"])
        for w in feed_reflex.WORDS:
            self.assertNotIn(w, r["reason"])   # never the value
        return r

    def test_off_without_feed_apps(self):
        r = self.check(self.row(aw_db=self.db()), doctor.OFF)
        self.assertEqual(r["reason"], feed_reflex.NO_FEEDS)
        self.assertEqual(doctor.text([r]), f"feed reflex: off: {feed_reflex.NO_FEEDS}")

    def test_the_env_feed_list_counts(self):
        with mock.patch.dict(os.environ, {"LIMITLESS_FEED_APPS": "feedapp"}):
            self.check(self.row(aw_db=self.db()), doctor.LIVE)

    def test_unknown_without_a_db_or_unlocks(self):
        r = self.check(self.row(feed_apps=["feedapp"]), doctor.MISSING)
        self.assertEqual(r["reason"], "unknown: no readable ActivityWatch DB (aw_db)")
        r = self.check(self.row(feed_apps=["feedapp"], aw_db=self.db(n=2)), doctor.MISSING)
        self.assertEqual(r["reason"], "unknown: " + feed_reflex.TOO_FEW)

    def test_live_with_enough_unlocks(self):
        r = self.check(self.row(feed_apps=["feedapp"], aw_db=self.db()), doctor.LIVE)
        self.assertEqual(r["reason"], doctor.FEED_REFLEX_LIVE)

    def test_the_report_has_it_after_the_desktop_row(self):
        names = [r["name"] for r in doctor.report({"state": str(self.st)}, NOW)]
        self.assertEqual(names.index(doctor.FEED_REFLEX_ROW), names.index(doctor.DESKTOP_AW_ROW) + 1)

    def test_nothing_written(self):
        name = self.db()
        before = sorted((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in self.st.iterdir())
        self.row(feed_apps=["feedapp"], aw_db=name)
        after = sorted((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in self.st.iterdir())
        self.assertEqual(before, after)

    def test_every_reason_is_digit_free(self):
        for why in feed_reflex.REASONS + (doctor.FEED_REFLEX_LIVE,):
            self.assertNotRegex(why, r"\d")


if __name__ == "__main__":
    unittest.main()
