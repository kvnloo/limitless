"""docs/apps-ingest.md shows the real output of scripts/apps_ingest_job_example.py (the apps ingest as an event job),
and the README names the job and its config."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "apps-ingest.md"


class Docs(unittest.TestCase):
    def test_the_job_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "apps_ingest_job_example.py")],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        blocks = re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S)
        self.assertIn(r.stdout, blocks)
        for w in ("Apps ingest: run: a sync ran; wrote the app lists", "already ran after this sync",
                  "skipped: no Hermes DB set (config hermes_db)", "job apps ingest: live",
                  "app lists set from your reply"):
            self.assertIn(w, r.stdout)

    def test_the_readme_names_the_job_its_config_and_its_event(self):
        text = (ROOT / "README.md").read_text()
        for word in ('"apps_ingest"', "apps-ingest.json", "after each sync run", "limitless-jobs --send",
                     "docs/apps-ingest.md#as-an-event-job"):
            self.assertIn(word, text)

    def test_the_doc_section_says_what_the_job_never_does(self):
        text = DOC.read_text()
        self.assertIn("## As an event job", text)
        section = text.split("## As an event job", 1)[1].lower()
        for word in ("apps-ingest.json", "0600", "runs.jsonl", "off", "dry_run", "write", "hermes_db",
                     "already ran after this sync", "app lists set from your reply", "never sends",
                     "never restarts, kills or starts a process", "no clock time", "--strict",
                     "never an app name", "job apps ingest"):
            self.assertIn(word, section)
        self.assertNotRegex(text, r"/(Users|home)/")


if __name__ == "__main__":
    unittest.main()
