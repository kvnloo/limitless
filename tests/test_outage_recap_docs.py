"""docs/outage-recap.md shows the real output of scripts/outage_recap_example.py, names its rules, and the README,
doctor and schedule-card docs point at it."""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "outage-recap.md"


class Docs(unittest.TestCase):
    def test_the_doc_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "outage_recap_example.py")],
                           capture_output=True, text=True, timeout=60, env=child_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        for said in ("Outage recap: not_triggered: pushes are still failing", "Phone pushes are reaching you again.",
                     "Reply: OK / More", "Outage recap: drop: already told about this outage",
                     "job outage recap: live: outage recap: told"):
            self.assertIn(said, r.stdout)
        blocks = re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S)
        self.assertIn(r.stdout, blocks)

    def test_the_doc_names_its_rules(self):
        text = DOC.read_text()
        for word in ("SEND_FAIL_RUN", "--once", "outage_recap:<first failed push time>", "push_back", "outage-recap.json",
                     "0600", "`off`", "`dry_run`", "`write`", "no digit", "placeholder", "Show more", "never a clock",
                     "still open", "push_log", "limitless-doctor"):
            self.assertIn(word, text)

    def test_the_readme_and_sibling_docs_point_at_it(self):
        readme = (ROOT / "README.md").read_text()
        for word in ("limitless/outage_recap.py", "docs/outage-recap.md", "outage_recap"):
            self.assertIn(word, readme)
        self.assertIn("outage-recap.md", (ROOT / "docs" / "doctor.md").read_text())
        self.assertIn("outage-recap.md", (ROOT / "docs" / "schedule-cards.md").read_text())


if __name__ == "__main__":
    unittest.main()
