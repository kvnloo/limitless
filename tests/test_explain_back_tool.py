"""limitless_explain_back: read-only. {offered, answered_this_week} in words, self_report, a digit-free T1 label.
The answers' text appears only under the raw opt-in. No score, no streak. Synthetic state only.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import explain_back, plugin, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "state"
NOW = 1894708800.0
H = 3600.0
WAKE = 1894690680.0      # the fixture's latest wake (Sleep mode off)
ANSWER = "The synthetic parser reads the new field. I could not explain the retry path."
FIELDS = {"value", "modality", "age_h", "evidence_tier"}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.st = Path(self.tmp.name) / "st"
        shutil.copytree(FIX, self.st)
        self.env = {"LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(Path(self.tmp.name) / "none.json")}

    def answer(self, at, text=ANSWER):
        explain_back.reply(self.st, text, at)

    def tool(self, raw=False):
        return tools.explain_back(StateReader(self.st), NOW, raw=raw, env=self.env)


class Value(Base):
    def test_nothing_yet(self):
        out = self.tool()
        self.assertEqual(out["value"], {"offered": False, "answered_this_week": "none this week"})
        self.assertEqual(out["modality"], "self_report")
        self.assertEqual(out["label"]["label"], "explain-back not offered today; none answered this week")

    def test_offered_for_this_wake_and_answers_in_words(self):
        explain_back.mark(self.st, WAKE, NOW - H)
        self.answer(NOW - 2 * H)
        self.answer(NOW - 3 * 24 * H, "another synthetic answer")
        self.answer(NOW - 9 * 24 * H, "an old synthetic answer")       # outside the seven days
        out = self.tool()
        self.assertEqual(out["value"], {"offered": True, "answered_this_week": "two this week"})
        self.assertEqual(out["age_h"], 1.0)                              # the newest of the offer and answers
        self.assertEqual(out["evidence_tier"], "direct")
        self.assertEqual(out["label"]["label"], "explain-back offered today; two answered this week")

    def test_an_offer_for_an_earlier_wake_is_not_today(self):
        explain_back.mark(self.st, WAKE - 24 * H, NOW - 26 * H)
        self.assertFalse(self.tool()["value"]["offered"])

    def test_other_captures_do_not_count(self):
        from limitless import capture
        capture.capture(self.st, "a synthetic idea", NOW - H)
        self.assertEqual(self.tool()["value"]["answered_this_week"], "none this week")

    def test_digit_free_and_no_text_without_the_opt_in(self):
        self.answer(NOW - H)
        out = self.tool()
        self.assertNotIn(ANSWER, json.dumps(out))
        self.assertNotIn("retry", json.dumps(out))
        self.assertEqual(re.findall(r"\d", out["label"]["label"]), [])
        self.assertEqual(re.findall(r"\d", json.dumps(out["value"])), [])
        for word in ("score", "streak", "xp", "grade"):
            self.assertIsNone(re.search(rf"\b{word}\b", json.dumps(out).lower()), word)

    def test_raw_opt_in_shows_the_answers(self):
        self.answer(NOW - H)
        answers = self.tool(raw=True)["value"]["answers"]
        self.assertEqual([a["text"] for a in answers], [ANSWER])
        self.assertEqual(answers[0]["unknowns"], ["I could not explain the retry path."])

    def test_no_state_dir(self):
        out = tools.explain_back(StateReader(Path(self.tmp.name) / "gone"), NOW, env=self.env)
        self.assertIsNone(out["value"])
        self.assertTrue(out["reason"])

    def test_read_only(self):
        before = sorted(p.name for p in self.st.iterdir())
        self.tool()
        self.assertEqual(sorted(p.name for p in self.st.iterdir()), before)


class ThroughThePlugin(Base):
    def call(self, raw=False):
        env = dict(self.env, LIMITLESS_RAW_IN_PROMPT="1" if raw else "0")
        with mock.patch.dict(os.environ, env), mock.patch("time.time", return_value=NOW):
            return json.loads(plugin._handler(plugin.TOOLS["limitless_explain_back"][1], "limitless_explain_back")({}))

    def test_registered_with_the_envelope(self):
        self.answer(NOW - H)
        out = self.call()
        self.assertTrue(FIELDS <= set(out))
        self.assertEqual(out["label"]["tier"], "T1")
        self.assertNotIn(ANSWER, json.dumps(out))
        self.assertEqual(self.call(raw=True)["value"]["answers"][0]["text"], ANSWER)

    def test_in_the_manifest(self):
        self.assertIn("  - limitless_explain_back", (ROOT / "plugin.yaml").read_text().splitlines())


if __name__ == "__main__":
    unittest.main()
