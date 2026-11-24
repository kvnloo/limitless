"""docs/phase.md shows the real output of scripts/phase_example.py, and the README points at it."""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "phase.md"
sys.path.insert(0, str(ROOT))

from limitless import phase  # noqa: E402


class Docs(unittest.TestCase):
    def test_the_doc_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "phase_example.py")],
                           capture_output=True, text=True, timeout=60, env=child_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        blocks = re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S)
        self.assertIn(r.stdout, blocks)

    def test_the_readme_names_the_tool_and_the_doc(self):
        text = (ROOT / "README.md").read_text()
        for word in ("limitless_phase", "docs/phase.md", "phase_light_h", "posture_file"):
            self.assertIn(word, text)

    def test_the_doc_says_what_it_never_does(self):
        text = DOC.read_text().lower()
        for word in ("never a clock", "no clock time", "no target bedtime", "no light dose", "supplement",
                     "no push", "no new job", "limitless_posture", "posture_ignored"):
            self.assertIn(word, text)

    def test_no_clock_time_anywhere_in_the_words(self):
        words = list(phase.LABELS.values()) + list(phase.UNKNOWN_LABELS.values()) + [phase.CARD_LINE]
        for w in words:
            self.assertIsNone(re.search(r"\d|\b(am|pm|o'clock|morning|noon|night)\b", w.lower()), w)


if __name__ == "__main__":
    unittest.main()
