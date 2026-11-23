"""docs/apps-ask.md shows the real output of scripts/apps_ask_example.py, and the README points at it."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "apps-ask.md"


class Docs(unittest.TestCase):
    def test_the_doc_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "apps_ask_example.py")],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        blocks = re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S)
        self.assertIn(r.stdout, blocks)
        self.assertIn("Reply with this to set your app lists (edit freely):\nwork apps: ", r.stdout)
        self.assertIn("apps ask: live: told recently", r.stdout)

    def test_the_readme_names_the_module_and_the_doc(self):
        text = (ROOT / "README.md").read_text()
        for word in ("limitless/apps_ask.py", "docs/apps-ask.md", "apps-ask.json", "apps_ask"):
            self.assertIn(word, text)

    def test_the_doc_names_the_rules(self):
        text = DOC.read_text()
        for word in ("apps_ask", "apps-ask.json", "0600", "seven days", "delivery", "brief:apps_ask",
                     "app_candidates.reply_line", "apps_reply.lists_for", "apps ask", "not needed", "told recently",
                     "waiting", "state card", "never sends", "bin/limitless-brief"):
            self.assertIn(word, text)
        self.assertNotRegex(text, r"/(Users|home)/")
        self.assertNotIn("tmp", "".join(re.findall(r"```text\n(.*?)```", text, re.S)))


if __name__ == "__main__":
    unittest.main()
