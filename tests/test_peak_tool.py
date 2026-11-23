"""limitless_window gains post_wake_peak (T1 words); the envelope is unchanged. Synthetic fixtures only."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import plugin, tools  # noqa: E402
from limitless.state_reader import StateReader, parse_ts  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "state"
WAKE = parse_ts("2030-01-15T06:58:00Z")
NOW = 1894708800.0   # the fixture clock: five hours after the wake event
H = 3600.0
WORDS = ("post-wake peak: open", "post-wake peak: in use", "post-wake peak: closed", "unknown")
ENVELOPE = {"value", "modality", "age_h", "evidence_tier"}


class WindowPeak(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.st = self.dir / "state"
        shutil.copytree(FIX, self.st)
        self.env = {"LIMITLESS_CONFIG": str(self.dir / "no-config.json"), "LIMITLESS_STATE": str(self.st)}

    def window(self, now):
        return tools.window(StateReader(self.st), now, env=self.env, home=self.dir)

    def test_open_inside_the_peak(self):
        p = self.window(WAKE + H)["post_wake_peak"]
        self.assertEqual((p["open"], p["in_use"]), (True, False))
        self.assertEqual(p["label"], {"label": "post-wake peak: open", "tier": "T1", "modality": "proxy"})

    def test_closed_after_the_peak(self):
        p = self.window(NOW)["post_wake_peak"]
        self.assertFalse(p["open"])
        self.assertEqual(p["label"]["label"], "post-wake peak: closed")

    def test_unknown_without_a_wake(self):
        (self.st / "sleepmode.jsonl").write_text("")
        p = self.window(NOW)["post_wake_peak"]
        self.assertEqual((p["open"], p["why"], p["label"]["label"]), (False, "unknown: no wake seen", "unknown"))

    def test_envelope_and_window_value_are_unchanged(self):
        res = self.window(NOW)
        self.assertEqual(res["value"], "peak")
        self.assertTrue(ENVELOPE <= set(res))
        self.assertEqual(set(res) - ENVELOPE - {"reason"}, {"asks", "post_wake_peak"})

    def test_words_are_digit_free_and_known(self):
        for now in (WAKE + H, NOW, WAKE + 30 * H):
            p = self.window(now)["post_wake_peak"]
            self.assertIn(p["label"]["label"], WORDS)
            self.assertFalse(any(c.isdigit() for c in p["label"]["label"] + p["why"]))

    def test_handler_result_keeps_the_peak_label(self):
        with mock.patch.dict(os.environ, self.env, clear=False), mock.patch("time.time", return_value=WAKE + H):
            res = json.loads(plugin._handler(plugin._window, "limitless_window")({}))
        self.assertEqual(res["post_wake_peak"]["label"]["label"], "post-wake peak: open")
        self.assertIn("post_wake_peak", plugin.TOOLS["limitless_window"][0]["description"])


if __name__ == "__main__":
    unittest.main()
