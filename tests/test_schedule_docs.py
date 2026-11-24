"""docs/schedule-cards.md: the field mapping covers every card field, and its example is real output."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import jobs, schedule_cards  # noqa: E402

DOC = ROOT / "docs" / "schedule-cards.md"


def _blocks(text, lang):
    return re.findall(rf"```{lang}\n(.*?)```", text, re.S)


class ScheduleCardsDoc(unittest.TestCase):
    def setUp(self):
        self.text = DOC.read_text()

    def test_mapping_table_has_every_card_field(self):
        for f in schedule_cards.card_for(jobs.WAKE_BRIEF):
            self.assertRegex(self.text, rf"(?m)^\| `{f}` \|", f)

    def test_cites_the_upstream_heads_it_read(self):
        self.assertIn("dd4e675b", self.text)
        self.assertIn("158289", self.text)
        self.assertIn("158538", self.text)
        self.assertIn(f"`{schedule_cards.HOST_METHOD}`", self.text)

    def test_example_card_is_real_output(self):
        card = json.loads(_blocks(self.text, "json")[0])
        self.assertEqual(card, schedule_cards.card_for(jobs.WAKE_BRIEF))

    def test_example_lines_are_real_output(self):
        lines = _blocks(self.text, "text")[0].strip().splitlines()
        self.assertEqual(lines, [schedule_cards.label(len(jobs.SPECS))]
                         + [c["description"] for c in schedule_cards.cards()])

    def test_readme_names_the_tool_and_the_doc(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("`limitless_schedule`", readme)
        self.assertIn("docs/schedule-cards.md", readme)


if __name__ == "__main__":
    unittest.main()
