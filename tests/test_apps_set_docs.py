"""docs/apps-ingest.md says how the apps-set line is told once in the wake brief and shows the real output of
scripts/apps_set_example.py; docs/apps-ask.md says the line and the ask never share a brief; the README names it."""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INGEST = ROOT / "docs" / "apps-ingest.md"
ASK = ROOT / "docs" / "apps-ask.md"
SECTION = "## Told once in the wake brief"


class Docs(unittest.TestCase):
    def section(self, path, head):
        text = path.read_text()
        self.assertIn(head, text)
        return text.split(head, 1)[1].split("\n## ", 1)[0]

    def test_the_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "apps_set_example.py")],
                           capture_output=True, text=True, timeout=120, env=child_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(r.stdout, re.findall(r"```text\n(.*?)```", self.section(INGEST, SECTION), re.S))
        for w in ("Work and feed app lists set from your reply.", "Feed app list set from your reply.",
                  "not told yet", "told in a brief", "(no apps-set line)"):
            self.assertIn(w, r.stdout)
        for name in ("editorapp", "termapp", "scrollapp", "otherfeedapp"):
            for ln in r.stdout.splitlines():
                if ln.startswith(("brief line:", "job apps ingest:")):
                    self.assertNotIn(name, ln)

    def test_the_ingest_section_says_the_rule(self):
        s = self.section(INGEST, SECTION).lower()
        for w in ("jobs_runner.brief_apps_set", "brief_apps_set_told", "brief:apps_set", "apps-set.json", "0600",
                  "wrote_at", "only after a real delivery", "build", "dry_run", "never an app name", "no digit",
                  "told in a brief", "not told yet", "a later reply", "never twice", "message-shape",
                  "no push of its own"):
            self.assertIn(w, s)
        self.assertNotRegex(INGEST.read_text(), r"/(Users|home)/")

    def test_the_ask_doc_says_they_never_share_a_brief(self):
        s = self.section(ASK, "## After the reply").lower()
        for w in ("brief_apps_set", "never in the same brief", "a list is set", "apps-ingest.md#told-once-in-the-wake-brief"):
            self.assertIn(w, s)

    def test_the_readme_names_it(self):
        text = (ROOT / "README.md").read_text()
        for w in ("apps-set.json", "set from your reply.", "docs/apps-ingest.md#told-once-in-the-wake-brief"):
            self.assertIn(w, text)


if __name__ == "__main__":
    unittest.main()
