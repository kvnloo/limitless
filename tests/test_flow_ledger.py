"""flow_ledger: one local day's focus blocks, each with a feed leak flag, and the work items that landed.

Pure core (flow_ledger.ledger) on synthetic rows; no score, no ranking, no target. UTC as the local zone.
"""
import os
import re
import sys
import unittest
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import flow_ledger  # noqa: E402

UTC = timezone.utc
DAY = date(2033, 5, 17)
DS = datetime(2033, 5, 17, tzinfo=UTC).timestamp()
DE = DS + 86400.0
NOW = DE + 8 * 3600.0
M = 60.0
WORK, FEEDS = ("editor",), ("feed",)


def row(s, e, app):
    return {"start": s, "end": e, "names": [app, "org.example." + app], "title": ""}


def long_block(at, minutes=100, feed=False):
    """A work block from ``at``: editor, a two-minute look at ``feed`` (or ``chat``), editor again."""
    mid = at + 40 * M
    other = "feed" if feed else "chat"
    return [row(at, mid, "editor"), row(mid, mid + 2 * M, other), row(mid + 2 * M, at + minutes * M, "editor")]


def items(*specs):
    return [{"name": f"synthetic-{i}", "status": st, "mtime": mt} for i, (st, mt) in enumerate(specs)]


def ledger(rows, work=WORK, feeds=FEEDS, its=None, now=NOW, day=DAY):
    return flow_ledger.ledger(rows, work, feeds, its, day, now, tz=UTC)


class Ledger(unittest.TestCase):
    def test_blocks_with_their_leak(self):
        rows = long_block(DS + 9 * 3600) + long_block(DS + 13 * 3600, feed=True)
        got = ledger(rows)
        self.assertEqual(got["why"], "")
        self.assertEqual(got["day"], DAY.isoformat())
        self.assertEqual([(b["long"], b["leak"]) for b in got["blocks"]], [(True, False), (True, True)])
        self.assertEqual((got["long_blocks"], got["leaks"]), (2, 1))
        self.assertEqual(got["blocks"][0]["start"], DS + 9 * 3600)

    def test_a_short_block_is_kept_but_not_long(self):
        got = ledger(long_block(DS + 9 * 3600, minutes=30))
        self.assertEqual([b["long"] for b in got["blocks"]], [False])
        self.assertEqual(got["long_blocks"], 0)

    def test_a_feed_outside_any_block_is_no_leak(self):
        rows = long_block(DS + 9 * 3600) + [row(DS + 20 * 3600, DS + 20 * 3600 + 30 * M, "feed")]
        self.assertEqual([b["leak"] for b in ledger(rows)["blocks"]], [False])

    def test_no_feed_apps_set_is_leak_unknown(self):
        got = ledger(long_block(DS + 9 * 3600, feed=True), feeds=())
        self.assertEqual([b["leak"] for b in got["blocks"]], [None])
        self.assertIsNone(got["leaks"])

    def test_rows_outside_the_day_do_not_count(self):
        rows = long_block(DS - 5 * 3600) + long_block(DE + 3600)
        got = ledger(rows + [row(DS + 3600, DS + 3600 + M, "chat")])
        self.assertEqual(got["blocks"], [])
        self.assertEqual(got["why"], "")

    def test_landed_counts_done_items_whose_mtime_is_in_the_day(self):
        its = items(("done", DS + 100), ("done", DE - 1), ("failed", DS + 200), ("done", DS - 1),
                    ("done", DE), ("running", DS + 300), ("queued", DS + 400))
        got = ledger(long_block(DS + 9 * 3600), its=its)
        self.assertEqual(got["landed"], 2)
        self.assertNotIn("synthetic", repr(got))       # item names never leave the ledger

    def test_no_queue_is_landed_unknown(self):
        self.assertIsNone(ledger(long_block(DS + 9 * 3600), its=None)["landed"])
        self.assertEqual(ledger(long_block(DS + 9 * 3600), its=[])["landed"], 0)


class Unknown(unittest.TestCase):
    def test_no_work_apps_is_unknown(self):
        got = ledger(long_block(DS + 9 * 3600), work=())
        self.assertIsNone(got["blocks"])
        self.assertEqual(got["why"], "no work apps set (flow_work_apps)")

    def test_no_activity_for_the_day_is_unknown(self):
        self.assertEqual(ledger(None)["why"], "no app activity that day")
        self.assertIsNone(ledger(None)["blocks"])
        self.assertEqual(ledger(long_block(DS - 5 * 3600))["why"], "no app activity that day")

    def test_a_day_not_over_is_unknown(self):
        got = ledger(long_block(DS + 9 * 3600), now=DE - 1)
        self.assertIsNone(got["blocks"])
        self.assertEqual(got["why"], "the day is not over")

    def test_reasons_are_plain_and_digit_free(self):
        for why in (ledger(None)["why"], ledger([], work=())["why"], ledger([], now=DS)["why"]):
            self.assertTrue(why)
            self.assertEqual(re.findall(r"\d", why), [])


class NoScore(unittest.TestCase):
    def test_no_score_rank_or_target_key(self):
        got = ledger(long_block(DS + 9 * 3600), its=items(("done", DS + 1)))
        keys = set(got) | {k for b in got["blocks"] for k in b}
        for bad in ("score", "rank", "target", "grade", "productivity"):
            self.assertFalse(any(bad in k for k in keys), keys)


if __name__ == "__main__":
    unittest.main()
