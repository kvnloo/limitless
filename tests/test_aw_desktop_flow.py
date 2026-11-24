"""The desktop ActivityWatch source feeds the same flow features as the phone DB: one store, two sources.

Synthetic only: a phone DB built with the AW schema (test_flow_week.make_db), a desktop served by a fake
fetch or a synthetic export file. App names and window titles are made up; nothing reads the clock.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import aw_desktop, blocks, card, flow_ledger, flow_metrics, flow_week, jobs_runner  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from test_aw_desktop import PLANTED, FakeFetch, afk, server, win  # noqa: E402
from test_flow_week import TZ, WEEK_OF, at, make_db  # noqa: E402

H, M = 3600.0, 60.0
URL = "http://desk.example.invalid:5600"
DAY = WEEK_OF + timedelta(days=1)           # the ledger's day
LO, HI = at(1, 0), at(2, 0)
AFTER = at(3, 12)                           # "now": after the ledger's day is over


def dev(start_h, end_h, app="editor", status=None):
    """A desktop event on DAY at local hours (minutes from the AW test epoch are not used here)."""
    from datetime import datetime, timezone
    s, e = at(1, start_h), at(1, end_h)
    data = {"status": status} if status else {"app": app, "title": f"{PLANTED} {app}"}
    return {"timestamp": datetime.fromtimestamp(s, timezone.utc).isoformat(), "duration": e - s, "data": data}


def desk(windows, afks):
    return server(windows, afks)


def never(url, timeout):
    raise AssertionError("fetch must not be called")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.st = self.dir / "state"
        self.st.mkdir()
        self.cfg_path = self.dir / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg_path)}
        self.reader = StateReader(self.st)
        aw_desktop._HOLD.clear()

    def tearDown(self):
        aw_desktop._HOLD.clear()
        self.tmp.cleanup()

    def config(self, **kv):
        cfg = {"state": str(self.st), "flow_work_apps": ["editor", f"title:{PLANTED.lower()}"],
               "feed_apps": ["scroller"], "break_after_min": 90}
        cfg.update(kv)
        self.cfg_path.write_text(json.dumps(cfg))

    def phone(self, spans=(), afk_rows=()):
        make_db(self.st / "aw.db", spans, afk_rows)

    def all_outputs(self, fetch, now=AFTER):
        with mock.patch.object(aw_desktop, "urllib_fetch", fetch):
            return {
                "blocks": blocks.read_for(self.reader, at(1, 23), self.env, self.dir),
                "metrics": flow_metrics.read_for(self.reader, LO, HI, self.env, self.dir, TZ),
                "ledger": flow_ledger.read_for(self.reader, DAY, now, self.env, self.dir, TZ),
                "week": flow_week.for_week(self.reader, WEEK_OF, TZ, self.env, self.dir),
            }


class OffIsTheSameAsBefore(Base):
    """Regression pin: with no desktop source the flow features answer exactly what the phone DB gives."""

    def phone_day(self):
        self.phone([(at(1, 9), at(1, 11), "editor"), (at(1, 11), at(1, 11.1), "scroller"),
                    (at(1, 11.1), at(1, 12), "editor"), (at(1, 14), at(1, 15), "scroller")])

    def test_off_answers_equal_the_phone_only_functions(self):
        self.phone_day()
        self.config(aw_db="aw.db")
        got = self.all_outputs(never)
        rows = blocks.read_rows(self.st / "aw.db", LO, HI)
        work = ("editor", f"title:{PLANTED.lower()}")
        self.assertEqual(got["metrics"]["days"], flow_metrics.metrics(rows, work, blocks.GAP_S,
                                                                      break_after_s=90 * M, tz=TZ))
        self.assertEqual(got["ledger"]["blocks"], flow_ledger.ledger(rows, work, ("scroller",), None, DAY, AFTER,
                                                                     TZ)["blocks"])
        self.assertEqual(got["week"], flow_week.week(self.st / "aw.db", WEEK_OF, TZ, blocks=None, work_apps=work,
                                                     feed_apps=("scroller",)))
        brows = blocks.read_rows(self.st / "aw.db", at(1, 23) - blocks.LOOKBACK_S, at(1, 23))
        self.assertEqual(got["blocks"]["blocks"], blocks.focus_blocks(brows, work, blocks.GAP_S))
        self.assertNotIn("sources", got["week"]["evidence"])

    def test_off_with_no_phone_db_is_the_same_unknown_as_before(self):
        self.config()
        got = self.all_outputs(never)
        self.assertEqual(got["blocks"]["why"], blocks.NO_DB)
        self.assertEqual(got["metrics"]["why"], blocks.NO_DB)
        self.assertEqual(got["ledger"]["why"], blocks.NO_DB)
        self.assertEqual(got["week"], flow_week.unknown("no ActivityWatch DB at the configured path"))

    def test_empty_desktop_setting_is_off(self):
        self.phone_day()
        self.config(aw_db="aw.db")
        before = self.all_outputs(never)
        self.config(aw_db="aw.db", desktop_aw_url="  ", desktop_aw_export="")
        self.assertEqual(self.all_outputs(never), before)


class DesktopFeedsTheSameFeatures(Base):
    def test_desktop_only_gives_blocks_metrics_ledger_and_week(self):
        self.config(desktop_aw_url=URL)
        f = FakeFetch(desk([dev(9, 11), dev(11, 11.1, "scroller"), dev(11.1, 12)], [dev(8, 13, status="not-afk")]))
        got = self.all_outputs(f)
        self.assertEqual(got["blocks"]["blocks"], [(at(1, 9), at(1, 12))])
        day = got["metrics"]["days"][0]
        self.assertAlmostEqual(day["work_h"], 2.9)
        self.assertEqual(day["switches"], 1)
        self.assertEqual(got["ledger"]["long_blocks"], 1)
        self.assertEqual(got["ledger"]["blocks"][0]["leak"], True)
        self.assertEqual(got["week"]["deep_min"], 174.0)
        self.assertEqual(got["week"]["evidence"]["sources"], ["desktop"])

    def test_both_sources_merge_and_overlap_counts_once(self):
        self.phone([(at(1, 9), at(1, 10), "editor"), (at(1, 13), at(1, 14), "editor")])
        self.config(aw_db="aw.db", desktop_aw_url=URL)
        f = FakeFetch(desk([dev(9.5, 11)], [dev(8, 13, status="not-afk")]))
        got = self.all_outputs(f)
        self.assertEqual(got["week"]["deep_min"], 180.0)     # 9-11 once, plus 13-14
        self.assertEqual(got["week"]["evidence"]["sources"], ["phone", "desktop"])
        self.assertAlmostEqual(got["metrics"]["days"][0]["work_h"], 3.0)
        self.assertEqual(got["blocks"]["blocks"], [(at(1, 9), at(1, 11)), (at(1, 13), at(1, 14))])

    def test_desktop_afk_time_is_not_work(self):
        self.config(desktop_aw_url=URL)
        f = FakeFetch(desk([dev(9, 12)], [dev(9, 10, status="not-afk"), dev(10, 12, status="afk")]))
        got = self.all_outputs(f)
        self.assertEqual(got["week"]["deep_min"], 60.0)
        self.assertAlmostEqual(got["metrics"]["days"][0]["work_h"], 1.0)

    def test_the_work_app_list_applies_to_the_desktop_and_titles_never_match(self):
        self.config(desktop_aw_url=URL, flow_work_apps=["terminal", f"title:{PLANTED.lower()}"])
        f = FakeFetch(desk([dev(9, 10, "editor"), dev(10, 11, "Terminal")], [dev(8, 13, status="not-afk")]))
        got = self.all_outputs(f)
        self.assertEqual(got["week"]["deep_min"], 60.0)      # editor's title holds the planted text: no match
        self.assertEqual(got["blocks"]["blocks"], [(at(1, 10), at(1, 11))])

    def test_an_export_file_feeds_the_same_features(self):
        b = desk([dev(9, 11)], [dev(8, 13, status="not-afk")])
        (self.st / "desk-export.json").write_text(json.dumps({"buckets": b}))
        self.config(desktop_aw_export="desk-export.json")
        from_file = self.all_outputs(never)
        aw_desktop._HOLD.clear()
        self.config(desktop_aw_url=URL)
        self.assertEqual(self.all_outputs(FakeFetch(b)), from_file)

    def test_titles_are_absent_from_every_output(self):
        self.phone([(at(1, 9), at(1, 10), "editor")])
        self.config(aw_db="aw.db", desktop_aw_url=URL)
        f = FakeFetch(desk([dev(9, 11), dev(11, 12, "scroller")], [dev(8, 13, status="not-afk")]))
        got = self.all_outputs(f)
        text = json.dumps(got, default=str) + repr(got)
        self.assertNotIn(PLANTED, text)
        self.assertNotIn(PLANTED.lower(), text.replace(f"title:{PLANTED.lower()}", ""))
        with mock.patch.object(aw_desktop, "urllib_fetch", f):
            rows, why = blocks.source_rows(self.reader, LO, HI, self.env, self.dir)
        self.assertEqual({r["source"] for r in rows}, {"phone", "desktop"})
        self.assertNotIn(PLANTED, repr(rows))


class MissingDesktopIsUnknownNeverZero(Base):
    def test_an_unreachable_desktop_makes_every_feature_unknown(self):
        self.phone([(at(1, 9), at(1, 10), "editor")])
        self.config(aw_db="aw.db", desktop_aw_url=URL)
        got = self.all_outputs(FakeFetch({}, fail=OSError("refused")))
        self.assertIsNone(got["blocks"]["blocks"])
        self.assertEqual(got["blocks"]["why"], aw_desktop.NO_ANSWER)
        self.assertIsNone(got["metrics"]["days"])
        self.assertEqual(got["metrics"]["why"], aw_desktop.NO_ANSWER)
        self.assertIsNone(got["ledger"]["blocks"])
        self.assertEqual(got["ledger"]["why"], aw_desktop.NO_ANSWER)
        self.assertIsNone(got["week"]["deep_min"])
        self.assertIsNone(got["week"]["days_with_data"])
        self.assertIn(aw_desktop.NO_ANSWER, got["week"]["evidence"]["reason"])

    def test_a_desktop_with_no_afk_bucket_is_unknown(self):
        self.config(desktop_aw_url=URL)
        got = self.all_outputs(FakeFetch(desk([dev(9, 11)], None)))
        self.assertEqual(got["metrics"]["why"], aw_desktop.NO_AFK)
        self.assertIsNone(got["week"]["deep_min"])

    def test_a_desktop_answer_with_no_events_is_known_not_unknown(self):
        self.config(desktop_aw_url=URL)
        got = self.all_outputs(FakeFetch(desk([], [])))
        self.assertEqual(got["blocks"]["blocks"], [])
        self.assertEqual(got["metrics"]["why"], "no activity rows in that time")
        self.assertEqual(got["week"]["evidence"]["reason"], "no ActivityWatch events this week: unknown, not zero")

    def test_an_unreachable_desktop_is_not_asked_again_at_once(self):
        self.config(desktop_aw_url=URL)
        f = FakeFetch({}, fail=OSError("refused"))
        self.all_outputs(f)
        self.assertEqual(len(f.calls), 1)


class Words(Base):
    """Digit walk: every label and reason a desktop source can reach is digit-free and title-free."""

    def words(self, got):
        th = got["metrics"]["thresholds"]
        return [got["blocks"]["why"], got["metrics"]["why"], flow_metrics.label(got["metrics"]["pool"],
                got["metrics"]["why"] or flow_metrics.NO_DATA, th), flow_ledger.label(got["ledger"]),
                flow_week.t1_label(got["week"], got["week"])]

    def test_labels_have_no_digit_or_title(self):
        cases = [FakeFetch(desk([dev(9, 11), dev(11, 11.1, "scroller"), dev(11.1, 12)],
                                [dev(8, 13, status="not-afk")])),
                 FakeFetch({}, fail=OSError("refused")), FakeFetch(desk([dev(9, 11)], None)),
                 FakeFetch(desk(None, [])), FakeFetch({}, body=b"<html>"), FakeFetch(desk([], []))]
        for f in cases:
            aw_desktop._HOLD.clear()
            self.config(desktop_aw_url=URL)
            for w in self.words(self.all_outputs(f)):
                self.assertIsInstance(w, str)
                self.assertFalse(any(c.isdigit() for c in w), w)
                self.assertNotIn(PLANTED.lower(), w.lower())
                self.assertNotIn("example", w)


class CardAndReview(Base):
    def test_the_card_and_week_review_read_a_desktop_only_setup(self):
        self.config(desktop_aw_url=URL)
        f = FakeFetch(desk([dev(9, 11)], [dev(8, 13, status="not-afk")]))
        with mock.patch.object(aw_desktop, "urllib_fetch", f):
            word = card.flow_label(self.reader, WEEK_OF + timedelta(days=6), self.env)
            line = jobs_runner.week_flow(self.st, {"habit": "made-up habit", "week_of": WEEK_OF.isoformat()}, self.env, self.dir, TZ)
        self.assertIsNotNone(word)
        self.assertFalse(any(c.isdigit() for c in word))
        self.assertTrue(line.startswith("Flow (measured"), line)

    def test_the_card_cache_key_moves_with_a_desktop_source_only(self):
        self.config()
        self.assertIsNone(card._desktop_tick(AFTER, self.env))
        self.config(desktop_aw_url=URL)
        a = card._desktop_tick(AFTER, self.env)
        self.assertEqual(card._desktop_tick(AFTER + 1, self.env), a)
        self.assertNotEqual(card._desktop_tick(AFTER + card.DESKTOP_REFRESH_S, self.env), a)

    def test_neither_source_set_keeps_the_card_and_review_silent(self):
        self.config()
        self.assertIsNone(card.flow_label(self.reader, date(2033, 5, 22), self.env))
        self.assertEqual(jobs_runner.week_flow(self.st, {"habit": "made-up habit", "week_of": WEEK_OF.isoformat()}, self.env, self.dir,
                                               TZ), "")


if __name__ == "__main__":
    unittest.main()
