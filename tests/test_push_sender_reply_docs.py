"""docs/push-sender-reply.md shows the real output of scripts/sender_ingest_example.py, and the README, the doctor
doc and the schedule-cards doc point at it."""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "push-sender-reply.md"


class Docs(unittest.TestCase):
    def test_the_doc_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "sender_ingest_example.py")],
                           capture_output=True, text=True, timeout=60, env=child_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(r.stdout, re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S))

    def test_the_example_line_and_doctor_row_never_name_a_profile(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "sender_ingest_example.py")],
                           capture_output=True, text=True, timeout=60, env=child_env())
        tool_lines = [ln for ln in r.stdout.splitlines()
                      if ln.startswith(("Sender ingest:", "job sender ingest:", "Schedule "))]
        self.assertGreaterEqual(len(tool_lines), 6)
        for ln in tool_lines:
            self.assertNotRegex(ln, r"sender-(old|new|gone)", ln)
            self.assertNotRegex(ln, r"\d", ln)

    def test_the_doc_states_the_order_and_the_rules(self):
        text = DOC.read_text()
        for words in ("push via <name>", "sender_ingest", "push-sender.json", "push-sender-ingest.json",
                      "KEVIN_PUSH_PROFILE", "push_profile", "that sender profile does not exist",
                      "never a fallback", "never picks a sender", "never runs hermes", "job sender ingest"):
            self.assertIn(words, text)

    def test_the_other_docs_point_at_it(self):
        for name in ("README.md", "docs/doctor.md", "docs/schedule-cards.md"):
            self.assertIn("push-sender-reply.md", (ROOT / name).read_text(), name)


if __name__ == "__main__":
    unittest.main()
