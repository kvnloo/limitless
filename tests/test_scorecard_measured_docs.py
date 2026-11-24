"""The measured scorecard lines are documented where the audits say where they show, and in the README."""
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


if __name__ == "__main__":
    unittest.main()
