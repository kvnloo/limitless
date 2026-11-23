"""docs/habit-catalogue.md lists every catalogue habit as the code has it, and the README points to it."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from limitless import habit_catalogue  # noqa: E402


class Docs(unittest.TestCase):
    def test_every_habit_is_in_the_doc_in_order(self):
        doc = (ROOT / "docs" / "habit-catalogue.md").read_text()
        at = [doc.index(f"| `{h['id']}` | {h['layer']} | {h['name']} | `{h['cue']}` | {h['start']} |")
              for h in habit_catalogue.CATALOGUE]
        self.assertEqual(at, sorted(at))

    def test_readme_names_the_tool_and_the_doc(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("docs/habit-catalogue.md", readme)
        self.assertIn("| `limitless_habit_next` |", readme)


if __name__ == "__main__":
    unittest.main()
