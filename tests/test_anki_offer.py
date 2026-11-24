"""anki.offer: one digit-free line, "trough: a short Anki review fits now", only in a trough window with a
collection set; never in a peak, asleep, an unknown window or a focus block. And its place on the
pre_llm_call card: added like the card's other optional lines, through tier_audit.gate, within MAX_LINES.

Synthetic state and collections only. No clock time decides anything here.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import anki, card  # noqa: E402
from limitless.decision_window import WindowState  # noqa: E402
from limitless.envelope import envelope  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from test_anki_reviews import collection  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "state"
NOW = 1894708800.0     # the fixture clock: the fixture's window is peak
TODAY = date(2030, 1, 15)
SET, UNSET = {"set": True}, {"set": False}
TROUGH_BANDS = {"peak": [6, 8], "trough": [1, 6]}   # moves the fixture's wake into a trough


def win(cls):
    return envelope(cls, "proxy", 0.1)


class Offer(unittest.TestCase):
    def test_trough_with_a_collection_offers_one_line(self):
        for state in (WindowState("trough", since="wake"), win("trough"), {"cls": "trough"}):
            self.assertEqual(anki.offer(state, SET), "trough: a short Anki review fits now")
        self.assertEqual(anki.OFFER, "trough: a short Anki review fits now")
        self.assertFalse(any(c.isdigit() for c in anki.OFFER))

    def test_never_outside_a_trough(self):
        for state in (WindowState("peak"), win("peak"), win("asleep"), {"cls": "asleep"}, win("unknown"),
                      WindowState("unknown"), WindowState("anytime"), WindowState("wind_down"), None,
                      WindowState("trough", confidence=0.2), "trough", 42):
            self.assertEqual(anki.offer(state, SET), "", state)

    def test_never_in_a_focus_block(self):
        self.assertEqual(anki.offer(WindowState("trough", hold_asks=True), SET), "")

    def test_never_without_a_collection(self):
        for week in (UNSET, None, {}, {"set": "yes"}):
            self.assertEqual(anki.offer(WindowState("trough"), week), "", week)

    def test_a_week_dict_from_week_counts_as_set(self):
        self.assertEqual(anki.offer(WindowState("trough"), anki.week("x.anki2", TODAY, TODAY)), anki.OFFER)
        self.assertEqual(anki.offer(WindowState("trough"), anki.week(None, TODAY, TODAY)), "")


class OnTheCard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.st = self.dir / "st"
        shutil.copytree(FIX, self.st)
        self.db = collection(self.dir / "collection.anki2", [NOW - 3600])
        self.audit = self.dir / "audit.jsonl"
        self.env = {"LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(self.dir / "none.json"),
                    "LIMITLESS_ANKI": str(self.db), "LIMITLESS_AUDIT": str(self.audit)}

    def tearDown(self):
        self.tmp.cleanup()

    def hook(self, env=None, bands=TROUGH_BANDS):
        h = card.make_pre_llm_call(env=env or self.env, clock=lambda: NOW, today=lambda: TODAY, bands=bands)
        return h(session_id="s", user_message="hi")

    def test_the_line_is_on_the_card_in_a_trough(self):
        out = self.hook()
        lines = out["context"].splitlines()
        self.assertLessEqual(len(lines), card.MAX_LINES)        # the fixture card is full: after the last words
        self.assertTrue(lines[-1].endswith(f"; {anki.OFFER}"), lines)
        row = json.loads(self.audit.read_text().splitlines()[-1])
        self.assertEqual((row["tier"], row["blocked"]), ("T1", False))   # passed tier_audit.gate

    def test_not_in_the_fixture_peak(self):
        self.assertNotIn("Anki", self.hook(bands=None)["context"])

    def test_not_without_a_collection_or_with_a_missing_file(self):
        env = dict(self.env)
        del env["LIMITLESS_ANKI"]
        self.assertNotIn("Anki", self.hook(env)["context"])
        self.assertNotIn("Anki", self.hook(dict(self.env, LIMITLESS_ANKI=str(self.dir / "gone.anki2")))["context"])

    def test_not_in_a_glide_focus_block(self):
        glide = self.dir / "attention.json"
        glide.write_text(json.dumps({"block": {"start": NOW - 600, "end": NOW + 600, "minutes": 20}}))
        self.assertNotIn("Anki", self.hook(dict(self.env, LIMITLESS_GLIDE_ATTENTION=str(glide)))["context"])

    def test_not_in_focused_mode(self):
        (self.st / "mode.json").write_text(json.dumps({"mode": "focused"}))
        self.assertNotIn("Anki", self.hook()["context"])

    def test_the_cache_sees_the_window_change(self):
        cache = card.CardCache()
        reader = StateReader(self.st)
        peak = cache.get(reader, NOW, TODAY, env=self.env)
        trough = cache.get(reader, NOW, TODAY, bands=TROUGH_BANDS, env=self.env)
        self.assertNotIn("Anki", peak)
        self.assertIn(anki.OFFER, trough)

    def test_a_full_card_keeps_max_lines(self):
        reader = StateReader(self.st)
        c = card.build(reader, NOW, TODAY, bands=TROUGH_BANDS, env=self.env, anki_offer=anki.OFFER)
        self.assertLessEqual(len(c["lines"]), card.MAX_LINES)
        self.assertIn(anki.OFFER, c["text"])
        full = card.build(reader, NOW, TODAY, bands=TROUGH_BANDS, env=self.env, anki_offer=anki.OFFER,
                          peak="post-wake peak: open")
        self.assertLessEqual(len(full["lines"]), card.MAX_LINES)
        self.assertIn(anki.OFFER, full["text"])

    def test_a_card_with_room_gets_a_line_of_its_own(self):
        lean = self.dir / "lean"
        lean.mkdir()
        for name in ("sleepmode.jsonl", "sleepmode-poll.json", "unlocks.jsonl"):
            shutil.copy(self.st / name, lean / name)
        out = self.hook(dict(self.env, LIMITLESS_STATE=str(lean)))
        self.assertEqual(out["context"].splitlines()[-1], anki.OFFER)

    def test_build_adds_nothing_by_default(self):
        c = card.build(StateReader(self.st), NOW, TODAY, bands=TROUGH_BANDS, env=self.env)
        self.assertNotIn("Anki", c["text"])   # the call brief and limitless_state stay as they were


if __name__ == "__main__":
    unittest.main()
