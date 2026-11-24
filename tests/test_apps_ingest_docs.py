"""docs/apps-ingest.md shows the real output of scripts/apps_ingest_example.py, and the README points at it."""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "apps-ingest.md"


class Docs(unittest.TestCase):
    def test_the_doc_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "apps_ingest_example.py")],
                           capture_output=True, text=True, timeout=60, env=child_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        blocks = re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S)
        self.assertIn(r.stdout, blocks)
        self.assertIn("apps lists: live: work apps set from a reply", r.stdout)

    def test_the_readme_names_the_cli_and_the_doc(self):
        text = (ROOT / "README.md").read_text()
        for word in ("limitless/apps_reply.py", "bin/limitless-apps-ingest", "docs/apps-ingest.md", "apps.json"):
            self.assertIn(word, text)

    def test_the_doc_names_the_rules(self):
        text = DOC.read_text()
        for word in ("work apps:", "feed apps:", "none", "apps.json", "0600", "--write", "dry run",
                     "LIMITLESS_FLOW_WORK_APPS", "LIMITLESS_FEED_APPS", "flow_work_apps", "feed_apps",
                     "config wins", "apps_reply.list_for", "apps lists", "never edits the config",
                     "twenty", "sixty", "hermes_db", "LIMITLESS_HERMES_DB"):
            self.assertIn(word, text)
        self.assertNotRegex(text, r"/(Users|home)/")
        self.assertNotIn("tmp", "".join(re.findall(r"```text\n(.*?)```", text, re.S)))


if __name__ == "__main__":
    unittest.main()
