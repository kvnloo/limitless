"""The measured scorecard lines are documented where the audits say where they show, and in the README."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Docs(unittest.TestCase):
    def test_uptime_doc_says_the_scorecard_cites_it(self):
        text = (ROOT / "docs" / "uptime-audit.md").read_text()
        for words in ("Measured: loop uptime:", "says green but the measurement says not met", "never marks",
                      "scorecard.measured"):
            self.assertIn(words, text)

    def test_delivery_doc_says_the_scorecard_cites_it_and_its_goal(self):
        text = (ROOT / "docs" / "delivery-audit.md").read_text()
        for words in ("Measured: delivery:", "says green but the measurement says not met", "delivery_audit.goal",
                      "unknown is never met"):
            self.assertIn(words, text)

    def test_readme_names_the_measured_field_and_lines(self):
        text = (ROOT / "README.md").read_text()
        self.assertIn("`measured`", text)
        self.assertIn("Measured: loop uptime", text)
        for words in ("Measured: habit loop", "Measured: evidence loop", "Measured: privacy",
                      "docs/scorecard-measured.md"):
            self.assertIn(words, text)

    def test_scorecard_doc_defines_rows_three_four_and_seven(self):
        text = " ".join((ROOT / "docs" / "scorecard-measured.md").read_text().split())
        for words in ("Habit loop: 4 weekly cycles", "confirmed start", "Keep or Drop", "last four habit weeks",
                      "finished week", "no habit week was ever started", "Skipped and unanswered days never count",
                      "Evidence loop: >=2 locked N-of-1 experiments with outcome receipts", "judged receipt",
                      "supports, contradicts or inconclusive", "not pending", "unknown: no experiment locked",
                      "unknown is never met", "Privacy: no raw health data above T1, 0 leaks", "tier_audit.check",
                      "last seven days", "blocked rows are fine", "without the opt-in", "no audit log is set",
                      "More measured rows in limitless_scorecard.", "says green but the measurement says not met",
                      "never marks a row green"):
            self.assertIn(words, text)


if __name__ == "__main__":
    unittest.main()
