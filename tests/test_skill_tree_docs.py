"""docs/skill-tree.md shows the example script's real output, its committed card is the script's real card, and
the README points at both the tool and the doc."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "skill-tree.md"
SCRIPT = ROOT / "scripts" / "skill_tree_example.py"
CARD = ROOT / "docs" / "examples" / "skill-tree.html"


def run(*args):
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], capture_output=True, text=True, timeout=60)


class Docs(unittest.TestCase):
    def test_the_doc_shows_the_scripts_real_output(self):
        r = run("--print")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("limitless_skill_tree", r.stdout)
        self.assertIn(r.stdout.strip(), DOC.read_text())

    def test_the_committed_card_is_the_scripts_real_card(self):
        r = run("--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_the_card_is_self_contained_and_digit_free_to_read(self):
        html = CARD.read_text(encoding="utf-8")
        self.assertNotRegex(html.lower(), r"<script|<link|@import|url\(|https?:|src=")
        words = re.sub(r"<[^>]*>", "", re.search(r"(?s)<body>(.*)</body>", html).group(1))
        self.assertNotRegex(words, r"\d")
        self.assertIn("Foundation open", words)

    def test_the_doc_says_what_it_never_does(self):
        text = DOC.read_text().lower()
        for word in ("foundation", "learning", "flow", "enhancement", "kept", "dropped", "trying", "not tried",
                     "no score", "streak", "never starts a habit", "unlogged", "predictions.jsonl",
                     "examples/skill-tree.html", "card_dir"):
            self.assertIn(word, text)

    def test_the_readme_names_the_tool_and_the_doc(self):
        text = (ROOT / "README.md").read_text()
        self.assertIn("| `limitless_skill_tree` |", text)
        self.assertIn("docs/skill-tree.md", text)


if __name__ == "__main__":
    unittest.main()
