"""limitless_experiment: one read-only view over the prediction ledger. {current: words, past: [{week_of, verdict,
falsifier_stated}]}, modality derived, a digit-free T1 label; prediction and falsifier text only under the raw
opt-in. No score, no streak. Synthetic state only."""
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import plugin, prediction, tools  # noqa: E402

NOW = 1894708800.0           # 2030-01-15T12:00:00Z
H = 3600.0
WEEK = date(2030, 1, 15)
TEXT = "Synthetic prediction: the habit week brings more sleep"
FALSIFIER = "Synthetic falsifier: no more sleep than the week before"
FIELDS = {"value", "modality", "age_h", "evidence_tier"}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.st = Path(self.tmp.name) / "st"
        self.st.mkdir()

    def lock(self, week=WEEK, lag=0, falsifier=FALSIFIER, metric="sleep_h", direction="up"):
        r = prediction.lock(self.st, week.isoformat(), TEXT, metric, direction, write=True, today=week,
                            now=NOW, falsifier=falsifier, lag_days=lag)
        self.assertEqual(r["action"], prediction.LOCKED, r)

    def judge(self, week=WEEK, day=7, at=NOW):
        r = prediction.receipt(self.st, week.isoformat(), write=True, today=week + timedelta(days=day), now=at)
        self.assertEqual(r["action"], prediction.WROTE, r)

    def tool(self, day=0, raw=False, now=None):
        return tools.experiment(self.st, NOW + day * 86400 if now is None else now, WEEK + timedelta(days=day),
                                raw=raw)

    def assertDigitFree(self, out):
        self.assertEqual(re.findall(r"\d", out["label"]["label"]), [], out["label"])
        self.assertEqual(re.findall(r"\d", out["value"]["current"]), [], out["value"]["current"])


class Current(Base):
    def test_nothing_locked(self):
        out = self.tool()
        self.assertEqual(out["value"], {"current": "no experiment locked", "past": []})
        self.assertEqual((out["modality"], out["age_h"], out["evidence_tier"]), ("derived", None, "none"))
        self.assertEqual(out["label"], {"label": "no experiment locked", "tier": "T1", "modality": "derived"})

    def test_running_outcome_pending(self):
        self.lock()
        out = self.tool(day=2)
        self.assertEqual(out["label"]["label"], "one experiment running, outcome pending")
        self.assertIn("falsifier stated", out["value"]["current"])
        self.assertEqual(out["value"]["past"], [])
        self.assertEqual(out["age_h"], 48.0)
        self.assertEqual(out["evidence_tier"], "stale")    # self-reported, over a day old
        self.assertEqual(self.tool(day=0)["evidence_tier"], "direct")
        self.assertDigitFree(out)

    def test_no_falsifier_is_said(self):
        self.lock(falsifier=None)
        self.assertIn("no falsifier stated", self.tool(day=1)["value"]["current"])

    def test_a_lag_waits_in_words(self):
        self.lock(lag=7)
        out = self.tool(day=9)
        self.assertEqual(out["label"]["label"], "one experiment waiting, outcome pending (judged later)")
        self.assertIn("the week after the habit week", out["value"]["current"])
        self.assertDigitFree(out)
        self.assertEqual(self.tool(day=14)["label"]["label"], "one experiment ready to judge")

    def test_ready_to_judge_once_the_week_is_over(self):
        self.lock()
        self.assertEqual(self.tool(day=7)["label"]["label"], "one experiment ready to judge")


class Past(Base):
    def test_a_judged_week_moves_to_past(self):
        self.lock()
        self.judge(at=NOW + 7 * 86400)
        out = self.tool(day=8)
        self.assertEqual(out["value"]["current"], "no experiment running")
        self.assertEqual(out["value"]["past"], [{"week_of": WEEK.isoformat(), "verdict": "inconclusive",
                                                 "falsifier_stated": True}])
        self.assertEqual(out["age_h"], 24.0)            # the newest row: the receipt

    def test_newest_first_with_open_older_weeks_named(self):
        old = WEEK - timedelta(days=14)
        self.lock(week=old, falsifier=None, metric="logged", direction="at_least 4 of 7")
        self.lock(week=WEEK - timedelta(days=7), lag=14)
        self.lock(week=WEEK)
        out = self.tool(day=2)
        self.assertEqual(out["label"]["label"], "one experiment running, outcome pending")
        self.assertEqual(out["value"]["past"], [
            {"week_of": (WEEK - timedelta(days=7)).isoformat(), "verdict": "pending", "falsifier_stated": True},
            {"week_of": old.isoformat(), "verdict": "not judged", "falsifier_stated": False}])

    def test_an_old_row_without_the_new_fields_reads(self):
        old = {"kind": "prediction", "week_of": WEEK.isoformat(), "text": TEXT, "metric": "logged",
               "direction": "at_least 4 of 7", "locked_at": "2030-01-15T00:00:00+00:00"}
        (self.st / prediction.PREDICTIONS_FILE).write_text(json.dumps(old) + "\n")
        out = self.tool(day=1)
        self.assertEqual(out["label"]["label"], "one experiment running, outcome pending")
        self.assertIn("no falsifier stated", out["value"]["current"])


class Privacy(Base):
    def test_text_only_under_the_raw_opt_in(self):
        self.lock(week=WEEK - timedelta(days=7))
        self.judge(week=WEEK - timedelta(days=7), day=7)
        self.lock()
        plain = json.dumps(self.tool(day=1))
        for t in (TEXT, FALSIFIER):
            self.assertNotIn(t, plain)
        raw = self.tool(day=1, raw=True)["value"]
        self.assertEqual(raw["prediction"], {"text": TEXT, "falsifier": FALSIFIER})
        self.assertEqual((raw["past"][0]["text"], raw["past"][0]["falsifier"]), (TEXT, FALSIFIER))

    def test_no_score_no_streak(self):
        self.lock()
        words = json.dumps(self.tool(day=2)).lower()
        for bad in ("score", "streak", "points"):
            self.assertNotIn(bad, words)

    def test_read_only(self):
        self.lock()
        before = sorted((p.name, p.read_bytes()) for p in self.st.iterdir())
        self.tool(day=3)
        self.tool(day=9, raw=True)
        self.assertEqual(sorted((p.name, p.read_bytes()) for p in self.st.iterdir()), before)

    def test_no_state_dir(self):
        out = tools.experiment(Path(self.tmp.name) / "nowhere", NOW, WEEK)
        self.assertIsNone(out["value"])
        self.assertTrue(out["reason"])


class ThroughThePlugin(Base):
    def call(self, raw=False):
        env = {"LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(Path(self.tmp.name) / "none.json"),
               "LIMITLESS_RAW_IN_PROMPT": "1" if raw else "0"}
        with mock.patch.dict(os.environ, env), mock.patch("time.time", return_value=NOW + H):
            return json.loads(plugin._handler(plugin.TOOLS["limitless_experiment"][1], "limitless_experiment")({}))

    def test_registered_with_the_envelope(self):
        self.lock()
        out = self.call()
        self.assertTrue(FIELDS <= set(out))
        self.assertEqual(out["label"]["label"], "one experiment running, outcome pending")
        self.assertNotIn(TEXT, json.dumps(out))
        self.assertEqual(self.call(raw=True)["value"]["prediction"]["text"], TEXT)

    def test_in_the_manifest(self):
        self.assertIn("  - limitless_experiment", (ROOT / "plugin.yaml").read_text().splitlines())
        desc = plugin.TOOLS["limitless_experiment"][0]["description"].lower()
        for word in ("read-only", "falsifier", "pending", "raw opt-in"):
            self.assertIn(word, desc)


if __name__ == "__main__":
    unittest.main()
