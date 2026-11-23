"""docs/desktop-aw.md shows the real output of scripts/desktop_aw_example.py, and the README points at it."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "desktop-aw.md"


class Docs(unittest.TestCase):
    def test_the_doc_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "desktop_aw_example.py")],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("planted title anywhere in the result: False", r.stdout)
        self.assertNotIn("PLANTED-WINDOW-TITLE", r.stdout)
        blocks = re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S)
        self.assertIn(r.stdout, blocks)

    def test_the_readme_names_the_config_and_the_doc(self):
        text = (ROOT / "README.md").read_text()
        for word in ("docs/desktop-aw.md", "desktop_aw_url", "desktop_aw_export"):
            self.assertIn(word, text)

    def test_the_doc_says_what_it_never_keeps(self):
        text = DOC.read_text().lower()
        for word in ("title is t0", "dropped at read time", "unknown is never zero", "afkstatus", "currentwindow",
                     "no second store", "off", "live", "stale", "unreachable"):
            self.assertIn(word, text)


if __name__ == "__main__":
    unittest.main()
