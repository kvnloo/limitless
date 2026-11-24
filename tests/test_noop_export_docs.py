"""docs/noop-export.md shows the real output of scripts/noop_export_example.py, and the README points at it."""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "noop-export.md"


class Docs(unittest.TestCase):
    def test_the_doc_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "noop_export_example.py")],
                           capture_output=True, text=True, timeout=120, env=child_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        blocks = re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S)
        self.assertIn(r.stdout, blocks)

    def test_the_readme_names_the_tool_the_config_and_the_doc(self):
        text = (ROOT / "README.md").read_text()
        for word in ("bin/limitless-noop-export", "noop_db", "docs/noop-export.md"):
            self.assertIn(word, text)

    def test_the_doc_cites_the_noop_sources_and_says_what_it_never_does(self):
        text = DOC.read_text()
        for word in ("android/app/src/main/java/com/noop/data/Entities.kt",
                     "android/app/src/main/java/com/noop/data/PairedDevice.kt", "sleepSession", "hrSample",
                     "pairedDevice", "mode=ro&immutable=1", "0600", "--write", "unchanged"):
            self.assertIn(word, text)
        low = text.lower()
        for word in ("never a clock time", "no device name", "never a guess", "no advice"):
            self.assertIn(word, low)


if __name__ == "__main__":
    unittest.main()
