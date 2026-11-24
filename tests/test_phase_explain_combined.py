"""The light line (phase) and the explain-back offer share one card without pushing each other out.
Synthetic fixtures only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import card, explain_back, phase  # noqa: E402
from limitless.state_reader import StateReader, parse_ts  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "state"
WAKE = parse_ts("2030-01-15T06:58:00Z")
TODAY = date(2030, 1, 15)


class CombinedCard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.st = root / "state"
        shutil.copytree(FIX, self.st)
        cfg = root / "config.json"
        cfg.write_text("{}")
        self.env = {"LIMITLESS_CONFIG": str(cfg), "LIMITLESS_STATE": str(self.st)}

    def test_build_keeps_light_line_and_explain_offer_last(self):
        out = card.build(StateReader(self.st), WAKE + 600, TODAY, env=self.env,
                         light=phase.CARD_LINE, explain_offer=explain_back.OFFER)
        self.assertIn(phase.CARD_LINE, out["text"])
        self.assertEqual(out["lines"][-1], explain_back.OFFER)

    def test_cache_passes_both_through(self):
        r = StateReader(self.st)
        built = []
        orig = card.build

        def spy(*a, **k):
            built.append(k)
            return orig(*a, **k)

        card.build = spy
        self.addCleanup(setattr, card, "build", orig)
        orig_lit, orig_exp = card.light_line, card.explain_offer
        card.light_line = lambda *a, **k: phase.CARD_LINE
        card.explain_offer = lambda *a, **k: (explain_back.OFFER, WAKE)
        self.addCleanup(setattr, card, "light_line", orig_lit)
        self.addCleanup(setattr, card, "explain_offer", orig_exp)
        text = card.CardCache().get(r, WAKE + 600, TODAY, env=self.env)
        self.assertEqual(built[-1].get("light"), phase.CARD_LINE)
        self.assertEqual(built[-1].get("explain_offer"), explain_back.OFFER)
        self.assertIn(phase.CARD_LINE, text)
        self.assertEqual(text.splitlines()[-1], explain_back.OFFER)


if __name__ == "__main__":
    unittest.main()
