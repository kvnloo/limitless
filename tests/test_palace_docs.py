"""docs/palace.md shows the real output of scripts/palace_example.py, says what the offer never does, and the README
points at it."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "palace.md"


class Docs(unittest.TestCase):
    def test_the_doc_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "palace_example.py")],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        blocks = re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S)
        self.assertIn(r.stdout, blocks)

    def test_the_readme_names_the_tool_the_config_and_the_doc(self):
        text = (ROOT / "README.md").read_text()
        for word in ("limitless_palace", "docs/palace.md", "palace_link", "limitless/palace.py"):
            self.assertIn(word, text)

    def test_the_doc_says_what_it_never_does(self):
        text = " ".join(DOC.read_text().lower().split())
        for word in ("palace_link", "palace_label", "no clock time", "no score, streak or count of walks",
                     "no push of its own", "no job", "one learning offer per trough", "palace.json", "0600",
                     "suggest only"):
            self.assertIn(word, text)

    def test_example_links_only(self):
        links = set(re.findall(r"\b[a-z][a-z+.-]*://[^\s`\"')]+", DOC.read_text()))
        self.assertEqual(links - {"palace://example"}, set())


if __name__ == "__main__":
    unittest.main()
