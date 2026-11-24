"""docs/ui-card.md and its committed synthetic examples match ui_card's real output; the README points at it."""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "ui-card.md"
EXAMPLES = ROOT / "docs" / "examples"


class Docs(unittest.TestCase):
    def test_the_committed_examples_are_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "ui_card_example.py"), "--check"],
                           capture_output=True, text=True, timeout=60, env=child_env())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_the_examples_are_self_contained_and_digit_free_to_read(self):
        for name in ("ui-card-state.html", "ui-card-week.html"):
            html = (EXAMPLES / name).read_text(encoding="utf-8")
            self.assertNotRegex(html.lower(), r"<script|<link|@import|url\(|https?:|src=")
            words = re.sub(r"<[^>]*>", "", re.search(r"(?s)<body>(.*)</body>", html).group(1))
            self.assertNotRegex(words, r"\d", name)

    def test_the_doc_links_the_examples_and_shows_the_lines(self):
        text = DOC.read_text()
        for name in ("examples/ui-card-state.html", "examples/ui-card-week.html"):
            self.assertIn(name, text)
        self.assertIn("window: peak (proxy)", text)

    def test_the_doc_says_what_it_never_does(self):
        text = DOC.read_text().lower()
        for word in ("limitless_card_view", "card_dir", "limitless_card_dir", "tier_audit.gate", "no score",
                     "no javascript", "prefers-reduced-motion", "no push", "clock time", "raw opt-in"):
            self.assertIn(word, text)

    def test_the_readme_names_the_tool_and_the_doc(self):
        text = (ROOT / "README.md").read_text()
        self.assertIn("limitless_card_view", text)
        self.assertIn("docs/ui-card.md", text)


if __name__ == "__main__":
    unittest.main()
