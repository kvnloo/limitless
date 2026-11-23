"""limitless_loop (read-only): the last few weekly loop rows as T1 words. The decision is an envelope with
modality self_report; the outcome carries the receipt's own modality, or is missing with a reason. No
digit, clock time, streak, missed, failed, must or should in any word. Synthetic data only."""
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import plugin, prediction, stop_rule, tools  # noqa: E402

UTC = timezone.utc
NOW = 2_000_000_000.0
TODAY = datetime.fromtimestamp(NOW, UTC).date()
FIELDS = {"value", "modality", "age_h", "evidence_tier"}
BANNED = re.compile(r"(?i)\d|streak|missed|failed|\bmust\b|\bshould\b|\b(am|pm)\b|o'clock")


def strings(v):
    if isinstance(v, str):
        yield v
    elif isinstance(v, dict):
        for k, x in v.items():
            if k not in ("age_h", "tier"):   # the tier name T1 is not a word shown
                yield from strings(x)
    elif isinstance(v, list):
        for x in v:
            yield from strings(x)


class LoopTool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def week(self, weeks_back, decision, rule=None, answers=("Done", "Done", "No"), habit="Synthetic habit"):
        start = TODAY - timedelta(days=6 + 7 * weeks_back)
        h = {"habit": habit, "week_of": start.isoformat(),
             "checkins": {(start + timedelta(days=i)).isoformat(): a for i, a in enumerate(answers)}}
        if rule:
            h["stop_rule"] = rule
        decided = datetime.combine(start + timedelta(days=6), datetime.min.time(), UTC).isoformat()
        return stop_rule.record_loop(self.st, h, decision, decided, now=NOW)

    def call(self, args=None, now=NOW):
        env = {"LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(self.st / "none.json")}
        with mock.patch.dict(os.environ, env), mock.patch("time.time", return_value=now):
            return json.loads(plugin._handler(plugin.TOOLS["limitless_loop"][1])(args or {}))

    def test_registered_with_no_parameters(self):
        schema = plugin.TOOLS["limitless_loop"][0]
        self.assertEqual(schema["parameters"]["properties"], {})
        self.assertIn("read-only", schema["description"].lower())

    def test_no_rows_is_missing_with_a_reason(self):
        res = self.call()
        self.assertIsNone(res["value"])
        self.assertIn("no week decided yet", res["reason"])

    def test_the_last_few_weeks_newest_first_in_words(self):
        for back, d, rule in ((5, "Drop", None), (3, "Keep", "any_done"), (2, "Drop", "most_done"),
                              (1, "Keep", "no_rule"), (0, "Keep", "most_done")):
            self.week(back, d, rule)
        res = self.call()
        self.assertTrue(FIELDS <= set(res), res)
        self.assertEqual(res["modality"], "self_report")
        self.assertEqual(res["label"], {"label": "latest week: kept", "tier": "T1", "modality": "self_report"})
        weeks = res["value"]["weeks"]
        self.assertEqual(len(weeks), tools.LOOP_WEEKS)
        self.assertEqual([w["week"] for w in weeks], ["this week", "last week", "two weeks ago", "three weeks ago"])
        self.assertEqual([w["rule"] for w in weeks],
                         ["your rule said keep it", "your rule said your call", "your rule said keep it",
                          "your rule said keep it"])
        self.assertEqual([w["decision"]["value"] for w in weeks], ["kept", "kept", "dropped", "kept"])
        for w in weeks:
            self.assertEqual(w["decision"]["modality"], "self_report")
            self.assertEqual(w["decision"]["label"]["tier"], "T1")
            self.assertEqual(w["prediction"], "no prediction")
            self.assertIsNone(w["outcome"]["value"])
            self.assertIn("reason", w["outcome"])

    def test_the_outcome_carries_the_receipt_modality(self):
        start = TODAY - timedelta(days=6)
        h = {"habit": "Synthetic habit", "week_of": start.isoformat(), "checkins": {}}
        (self.st / "habit.json").write_text(json.dumps(h))
        prediction.lock(self.st, start.isoformat(), "Synthetic prediction", "logged", "at_least 2 of 7", write=True,
                        today=start, now=NOW - 7 * 86400)
        h["checkins"] = {(start + timedelta(days=i)).isoformat(): a for i, a in enumerate(("Done", "Done", "No"))}
        (self.st / "habit.json").write_text(json.dumps(h))
        prediction.receipt(self.st, start.isoformat(), write=True, today=TODAY + timedelta(days=1), now=NOW - 60)
        stop_rule.record_loop(self.st, h, "Keep", "2033-05-18T00:00:00+00:00", now=NOW)
        (w,) = self.call()["value"]["weeks"]
        self.assertEqual(w["prediction"], "prediction locked")
        self.assertEqual(w["outcome"]["value"], "supports")
        self.assertEqual(w["outcome"]["modality"], "self_report")
        self.assertEqual(w["outcome"]["label"], {"label": "supports", "tier": "T1", "modality": "self_report"})

    def test_unknown_and_no_rule_words(self):
        self.week(1, "Drop", "most_done", answers=("Skipped",))
        self.week(0, "Keep", None)
        weeks = self.call()["value"]["weeks"]
        self.assertEqual([w["rule"] for w in weeks], ["no rule set", "your rule could not tell"])
        self.assertEqual(weeks[1]["decision"]["value"], "dropped")

    def test_no_word_has_a_digit_or_a_hard_word(self):
        for back, d, rule in ((2, "Drop", "most_done"), (1, "Keep", None), (0, "Drop", "not_a_chore")):
            self.week(back, d, rule)
        res = self.call()
        for s in strings(res):
            self.assertIsNone(BANNED.search(s), s)

    def test_read_only(self):
        self.week(0, "Keep", "most_done")
        before = sorted((p.name, p.read_bytes()) for p in self.st.iterdir())
        self.call()
        self.assertEqual(sorted((p.name, p.read_bytes()) for p in self.st.iterdir()), before)


if __name__ == "__main__":
    unittest.main()
