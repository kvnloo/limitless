"""docs/push-reach.md shows the real output of scripts/push_reach_example.py, the card and status docs name the
line, and the README points at it."""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "push-reach.md"
LINE = "Phone pushes are not reaching you"


class Docs(unittest.TestCase):
    def test_the_doc_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "push_reach_example.py")],
                           capture_output=True, text=True, timeout=60, env=child_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(LINE + ": the sender profile is missing", r.stdout)
        self.assertIn(LINE + ": the last pushes failed to send", r.stdout)
        blocks = re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S)
        self.assertIn(r.stdout, blocks)

    def test_the_doc_names_its_sources_and_rules(self):
        text = DOC.read_text()
        for word in ("push_sender.check", "send_failures", "push_log", "tier_audit.gate", "limitless_status",
                     "`delivery`", "context packet", "unknown is silent", "no digit", "MAX_LINES"):
            self.assertIn(word, text)

    def test_the_readme_and_the_packet_doc_name_it(self):
        readme = (ROOT / "README.md").read_text()
        for word in ("limitless/push_reach.py", "docs/push-reach.md", LINE):
            self.assertIn(word, readme)
        self.assertIn("`delivery`", (ROOT / "docs" / "context-packet.md").read_text())


if __name__ == "__main__":
    unittest.main()
