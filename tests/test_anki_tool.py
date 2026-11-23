"""limitless_anki: this week's Anki reviews as an evidence envelope with a digit-free T1 label.

Synthetic collections only. value is the week's reviews in words; the raw count (and the day counts) appear
only under LIMITLESS_RAW_IN_PROMPT=1. Modality measured, age_h from the newest review. No collection set or an
unreadable one is value None with a path-free reason: unknown, not zero. tier_audit logs the label.
"""
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import plugin, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from test_anki_reviews import collection  # noqa: E402

TODAY = date(2030, 1, 27)


def local(d: date, h: float) -> float:
    return datetime.combine(d, time()).timestamp() + h * 3600


NOW = local(TODAY, 15)


class AnkiTool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.st = self.dir / "state"
        self.st.mkdir()
        self.db = collection(self.dir / "collection.anki2",
                             [local(TODAY - timedelta(days=d), 9) for d in (0, 1, 3, 5)] + [local(TODAY, 10)])
        self.env = {"LIMITLESS_CONFIG": str(self.dir / "none.json"), "LIMITLESS_ANKI": str(self.db)}

    def tearDown(self):
        self.tmp.cleanup()

    def tool(self, raw=False, env=None):
        return tools.anki(StateReader(self.st), NOW, TODAY, raw=raw, env=env or self.env)

    def test_envelope_label_and_age(self):
        res = self.tool()
        self.assertEqual(res["modality"], "measured")
        self.assertEqual(res["age_h"], 5.0)                  # the newest review was at ten, now is three
        self.assertEqual(res["evidence_tier"], "direct")
        self.assertEqual(res["value"], {"label": "reviewed most days this week"})
        self.assertEqual(res["label"], {"label": "reviewed most days this week", "tier": "T1",
                                        "modality": "measured"})

    def test_raw_count_only_under_the_opt_in(self):
        self.assertNotIn("count", json.dumps(self.tool()))
        self.assertEqual(re.findall(r"\d", json.dumps(self.tool()["value"])), [])
        raw = self.tool(raw=True)["value"]
        self.assertEqual((raw["count"], raw["days_with_review"], raw["days_so_far"]), (5, 4, 7))

    def test_this_week_is_the_running_habit_week(self):
        (self.st / "habit.json").write_text(json.dumps({"habit": "synthetic habit",
                                                        "week_of": (TODAY - timedelta(days=1)).isoformat()}))
        raw = self.tool(raw=True)["value"]
        self.assertEqual((raw["count"], raw["days_so_far"]), (3, 2))   # day two of the week

    def test_an_old_newest_review_is_stale(self):
        db = collection(self.dir / "old.anki2", [local(TODAY - timedelta(days=20), 9)])
        res = self.tool(env=dict(self.env, LIMITLESS_ANKI=str(db)))
        self.assertEqual(res["value"], {"label": "no reviews this week"})
        self.assertEqual(res["evidence_tier"], "stale")

    def test_unknown_is_a_reason_never_zero(self):
        res = self.tool(env={"LIMITLESS_CONFIG": str(self.dir / "none.json")})
        self.assertIsNone(res["value"])
        self.assertEqual(res["reason"], "no Anki collection set")
        res = self.tool(env=dict(self.env, LIMITLESS_ANKI=str(self.dir / "gone.anki2")))
        self.assertIsNone(res["value"])
        self.assertNotIn(str(self.dir), res["reason"])

    def test_through_the_plugin_handler_and_the_audit(self):
        audit = self.dir / "audit.jsonl"
        env = dict(self.env, LIMITLESS_STATE=str(self.st), LIMITLESS_AUDIT=str(audit))
        with mock.patch.dict(os.environ, env, clear=True), mock.patch("time.time", return_value=NOW):
            res = json.loads(plugin._handler(plugin.TOOLS["limitless_anki"][1], "limitless_anki")({}))
        self.assertEqual(res["label"]["label"], "reviewed most days this week")
        row = json.loads(audit.read_text().splitlines()[-1])
        self.assertEqual((row["hook"], row["tier"], row["blocked"]), ("tool:limitless_anki", "T1", False))

    def test_the_schema_says_read_only_and_no_clock_rule(self):
        desc = plugin.TOOLS["limitless_anki"][0]["description"]
        self.assertIn("read-only", desc.lower())
        self.assertIn("never written", desc)
        self.assertNotRegex(desc, r"\d\s*(am|pm)\b")


if __name__ == "__main__":
    unittest.main()
