"""docs/noop-export.md shows the real output of scripts/noop_export_job_example.py (the NOOP export as an event job),
and the README names the job and its config."""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "noop-export.md"


class Docs(unittest.TestCase):
    def test_the_job_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "noop_export_job_example.py")],
                           capture_output=True, text=True, timeout=120, env=child_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        blocks = re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S)
        self.assertIn(r.stdout, blocks)

    def test_the_readme_names_the_job_its_config_and_its_event(self):
        text = (ROOT / "README.md").read_text()
        for word in ('"noop_export"', "dry_run", "noop-export.json", "limitless-jobs --send",
                     "a sync that copied the NOOP database"):
            self.assertIn(word, text)

    def test_the_doc_section_says_what_the_job_never_does(self):
        text = DOC.read_text()
        self.assertIn("## As an event job", text)
        section = text.split("## As an event job", 1)[1].lower()
        for word in ("noop-export.json", "0600", "runs.jsonl", "\"noop\"", "off", "dry_run", "write",
                     "never sends", "never restarts, kills or starts a process", "no clock time", "--strict"):
            self.assertIn(word, section)


if __name__ == "__main__":
    unittest.main()
