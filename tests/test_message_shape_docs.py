"""docs/message-shape.md shows the real output of scripts/message_shape_example.py, and the README points at it."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "message-shape.md"


class Docs(unittest.TestCase):
    def run_example(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "message_shape_example.py")],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_the_doc_example_is_the_scripts_real_output(self):
        blocks = re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S)
        self.assertIn(self.run_example(), blocks)

    def test_the_example_shows_a_before_and_an_after(self):
        out = self.run_example()
        before, after = out.split("after:")
        self.assertIn("before:", before)
        self.assertIn("more lines in the plugin", after)
        self.assertIn("Reply: Keep / Drop\n  Why now:", after)

    def test_the_readme_names_the_module_the_config_and_the_doc(self):
        text = (ROOT / "README.md").read_text()
        for word in ("limitless/message_shape.py", "message_max_lines", "message_max_line_chars",
                     "docs/message-shape.md"):
            self.assertIn(word, text)

    def test_the_doc_says_the_rules(self):
        text = DOC.read_text().lower()
        for word in ("tldr", "reply line", "why now", "message_max_lines", "message_max_line_chars", "default",
                     "bin/kevin-push", "tier_audit", "counts only", "no new push", "never adds a digit",
                     "no clock time", "link", "reworded"):
            self.assertIn(word, text)


if __name__ == "__main__":
    unittest.main()
