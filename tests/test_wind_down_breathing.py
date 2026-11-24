"""Config wind_down_breathing_link: one extra choice, "slow breathing in your app", in the same wind-down line.

Off by default. A link is one token with no digit and no space (it rides in a line that tier_audit.gate would
drop for a digit); anything else is ignored, never sent. Synthetic links only (example://breathe).
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import wind_down  # noqa: E402

LINK = "example://breathe"
NIGHT = "2030-01-15"
WITHOUT = "Screens down and lights low when you're ready, or slow breathing in your app (without heart data): " + LINK
ALONE = "Slow breathing in your app when you're ready (without heart data): " + LINK
NEVER = ("breath", "per minute", "bpm", "hrv", "heart rate", "dose", "dosing", "mg", "supplement", "melatonin",
         "medic", "drug", "pill", "therapy", "treat", "cure", "must", "should", "pm", "am ")


class Link(unittest.TestCase):
    def test_absent_is_off_by_default(self):
        for cfg in (None, {}, {"wind_down_line": "Lights low when you're ready."}):
            self.assertIsNone(wind_down.breathing_link(cfg))
        self.assertEqual(wind_down.line({}), wind_down.DEFAULT)
        self.assertNotIn("breathing", wind_down.line({"wind_down_line": "Screens down when you're ready."}))

    def test_a_url_or_app_deep_link_is_kept(self):
        for link in (LINK, "https://example.org/breathe", "shortcuts://run-shortcut?name=Breathe", "  example://x  "):
            self.assertEqual(wind_down.breathing_link({wind_down.BREATHING_KEY: link}), link.strip())

    def test_anything_else_is_ignored(self):
        for bad in ("", "   ", "off", "breathe", "example://breathe two", "example://box4", "a\nb", "example://\tx",
                    "x" * 300 + "://y", 7, True, None, ["example://breathe"], "javascript:alert", "://nothing"):
            self.assertIsNone(wind_down.breathing_link({wind_down.BREATHING_KEY: bad}), repr(bad))


class Line(unittest.TestCase):
    def test_link_adds_one_choice_to_the_default_line(self):
        got = wind_down.line({wind_down.BREATHING_KEY: LINK})
        self.assertEqual(got, WITHOUT)
        self.assertEqual(len(got.splitlines()), 1)
        self.assertEqual(got.count("slow breathing in your app"), 1)

    def test_link_with_a_chosen_line(self):
        got = wind_down.line({"wind_down_line": "lights low when you're ready.", wind_down.BREATHING_KEY: LINK})
        self.assertEqual(got, "Lights low when you're ready, or slow breathing in your app (without heart data): "
                         + LINK)

    def test_link_alone_when_the_line_is_off(self):
        self.assertEqual(wind_down.line({"wind_down_line": "off", wind_down.BREATHING_KEY: LINK}), ALONE)

    def test_glide_nudge_still_silences_everything(self):
        cfg = {wind_down.BREATHING_KEY: LINK}
        self.assertEqual(wind_down.line(cfg, {"nudged": NIGHT}, NIGHT), "")
        self.assertEqual(wind_down.line(cfg, {"nudged": "2030-01-14"}, NIGHT), WITHOUT)

    def test_no_digit_no_clock_no_medical_word(self):
        for cfg in ({wind_down.BREATHING_KEY: LINK}, {"wind_down_line": "off", wind_down.BREATHING_KEY: LINK}):
            got = wind_down.line(cfg)
            self.assertEqual(re.findall(r"\d", got), [], got)
            words = got.replace(LINK, "").lower().replace("slow breathing", "")
            for w in NEVER:
                self.assertNotIn(w, words, (w, got))


if __name__ == "__main__":
    unittest.main()
