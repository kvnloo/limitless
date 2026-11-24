"""docs/voice-miq.md shows the real output of scripts/voice_miq_example.py and cites z0live's documented shape;
the README and docs/call-brief.md name the voice MIQ."""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "voice-miq.md"


class Docs(unittest.TestCase):
    def test_the_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "voice_miq_example.py")],
                           capture_output=True, text=True, timeout=120, env=child_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        blocks = re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S)
        self.assertIn(r.stdout, blocks)

    def test_the_doc_cites_the_z0live_shape_and_says_what_it_never_does(self):
        text = DOC.read_text()
        for word in ("sessions/SESSION_ID.jsonl", "docs/API.md", "export_events", "cf52d56", "user_transcript",
                     "assistant_transcript", "data.final", '"voice_miq"', "off", "dry_run", "write",
                     '"voice_miq_sessions"', "voice-miq.json", "0600", "epoch seconds only", "miq_answer",
                     "never sends", "no clock-time rule", "job voice MIQ"):
            self.assertIn(word, text)

    def test_readme_and_call_brief_doc_name_it(self):
        readme = (ROOT / "README.md").read_text()
        for word in ("docs/voice-miq.md", '"voice_miq"', "miq_answer"):
            self.assertIn(word, readme)
        self.assertIn("voice-miq.md", (ROOT / "docs" / "call-brief.md").read_text())


if __name__ == "__main__":
    unittest.main()
