"""The card builds its lines from labeler (T1) output; the digit mask stays as a second guard only.
Synthetic fixtures only."""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import card  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "state"
NOW = 1894708800.0
TODAY = date(2030, 1, 15)
FAKE = "import sys\nsys.stdin.read()\nprint(sys.argv[1])\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Path(self.tmp.name) / "st"
        shutil.copytree(FIX, self.st)

    def tearDown(self):
        self.tmp.cleanup()

    def digest(self, **metrics):
        row = {"date": "2030-01-15", "at": "2030-01-15T07:12:00Z",
               "metrics": {k: {"value": v, "modality": m} for k, (v, m) in metrics.items()}}
        with open(self.st / "digests.jsonl", "a") as f:
            f.write(json.dumps(row) + "\n")

    def build(self, **kw):
        return card.build(StateReader(self.st), NOW, TODAY, **kw)


class NoDigitsWithoutTheMask(Base):
    def test_raw_values_full_of_digits_leave_no_digit_with_the_mask_off(self):
        self.digest(sleep_h=(4.75, "proxy"), readiness=(38, "imported"), hrv_ms=(41.2, "measured"))
        (self.st / "asks-latest.json").write_text(json.dumps({"at": NOW - 600, "count": 7, "lines": ["a 1"]}))
        with mock.patch.object(card, "MASK_DIGITS", False):
            c = self.build()
        self.assertIn("sleep short (proxy)", c["text"])
        self.assertIn("readiness moderate (imported)", c["text"])
        self.assertEqual(re.findall(r"\d", c["text"]), [])

    def test_the_mask_is_still_on_by_default(self):
        self.assertTrue(card.MASK_DIGITS)

    def test_raw_opt_in_still_shows_raw_values(self):
        self.digest(sleep_h=(4.75, "proxy"), readiness=(38, "imported"))
        hook = card.make_pre_llm_call(env={"LIMITLESS_STATE": str(self.st), "LIMITLESS_RAW_IN_PROMPT": "1"},
                                      clock=lambda: NOW, today=lambda: TODAY)
        ctx = hook()["context"]
        self.assertIn("sleep short (proxy, 4.75 h)", ctx)
        self.assertIn("readiness moderate (imported, 38)", ctx)


class FromTheLabeler(Base):
    def test_lines_use_the_labeler_passed_in(self):
        calls = []

        def fake(kind, value, modality):
            calls.append((kind, value, modality))
            return {"label": {"sleep_h": "long", "readiness": "high"}[kind], "tier": "T1", "modality": modality}

        text = self.build(labeler=fake)["text"]
        self.assertIn("sleep long (proxy)", text)        # the rules would say short
        self.assertIn("readiness high (imported)", text)  # the rules would say low
        self.assertIn(("sleep_h", 5.3, "proxy"), calls)

    def test_a_labeler_answer_outside_the_kinds_set_is_unknown(self):
        def fake(kind, value, modality):
            return {"label": "zz" + str(value), "tier": "T1", "modality": modality}

        with mock.patch.object(card, "MASK_DIGITS", False):
            text = self.build(labeler=fake)["text"]
        self.assertIn("sleep unknown", text)
        self.assertNotIn("zz", text)
        self.assertEqual(re.findall(r"\d", text), [])

    def test_an_unknown_label_is_unknown_not_a_guess(self):
        self.digest(sleep_h=(30, "proxy"), readiness=(-4, "imported"))
        text = self.build()["text"]
        self.assertIn("sleep unknown", text)
        self.assertIn("readiness unknown", text)
        self.assertNotIn("long", text)

    def test_items_carry_the_t1_label_next_to_the_value(self):
        items = self.build()["items"]
        self.assertEqual(items["sleep"]["value"], "short")
        self.assertEqual(items["sleep"]["label"], {"label": "short", "tier": "T1", "modality": "proxy"})
        self.assertNotIn("raw", items["sleep"])

    def test_the_hook_uses_the_configured_local_model(self):
        script = Path(self.tmp.name) / "fake_model.py"
        script.write_text(FAKE)
        env = {"LIMITLESS_STATE": str(self.st), "LIMITLESS_T1_CMD": f'"{sys.executable}" -I "{script}" ok'}
        ctx = card.make_pre_llm_call(env=env, clock=lambda: NOW, today=lambda: TODAY)()["context"]
        self.assertIn("sleep ok (proxy)", ctx)       # the rule would say short
        self.assertIn("readiness low (imported)", ctx)  # "ok" is not in readiness's set: rule fallback


if __name__ == "__main__":
    unittest.main()
