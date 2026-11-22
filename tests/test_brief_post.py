"""Brief post-processing: the folded asks digest becomes ONE brief line; no card ids reach Kevin.
Synthetic fixtures only."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from limitless import brief_post as bp  # noqa: E402

NOW = 1_800_000_000
ASKS = {"at": NOW - 3600, "count": 5, "lines": [
    "A0001: Pick a color for the test widget? (cards t_0123abcd/t_89abcdef)",
    "A0002: Approve the synthetic fixture rename?",
    "A0003: Decide between plan X and plan Y for the demo?",
    "3 waiting on you. Reply in any bot chat with the id.",
]}


class AsksLine(unittest.TestCase):
    def test_counts_only_ask_lines_and_names_the_first(self):
        line = bp.asks_line(ASKS, NOW)
        self.assertTrue(line.startswith("Asks waiting on you: 3"), line)
        self.assertIn("Pick a color for the test widget", line)

    def test_has_no_card_ids_and_is_one_line(self):
        line = bp.asks_line(ASKS, NOW)
        self.assertNotRegex(line, r"t_[0-9a-f]{6,}")
        self.assertNotIn("\n", line)
        self.assertLessEqual(len(line), 140)

    def test_missing_or_empty_digest_gives_no_line(self):
        self.assertIsNone(bp.asks_line(None, NOW))
        self.assertIsNone(bp.asks_line({"at": NOW, "count": 0, "lines": []}, NOW))

    def test_stale_digest_gives_no_line(self):
        old = dict(ASKS, at=NOW - 40 * 3600)
        self.assertIsNone(bp.asks_line(old, NOW))


class Finalize(unittest.TestCase):
    def test_appends_asks_line_and_scrubs_card_ids(self):
        text = "State: fine\nDecision: ship t_deadbeef first → default yes"
        out = bp.finalize(text, ASKS, NOW)
        self.assertNotRegex(out, r"t_[0-9a-f]{6,}")
        self.assertEqual(out.splitlines()[-1], bp.asks_line(ASKS, NOW))
        self.assertTrue(out.startswith("State: fine\n"))

    def test_without_asks_text_is_only_scrubbed(self):
        self.assertEqual(bp.finalize("Peak: 10-12 t_deadbeef", None, NOW), "Peak: 10-12")

    def test_load_asks_reads_file_and_tolerates_missing_or_bad(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "asks-latest.json"
            self.assertIsNone(bp.load_asks(p))
            p.write_text("{not json")
            self.assertIsNone(bp.load_asks(p))
            p.write_text(json.dumps(ASKS))
            self.assertEqual(bp.load_asks(p)["count"], 5)


if __name__ == "__main__":
    unittest.main()
