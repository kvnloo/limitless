"""docs/privacy-tiers.md's local model check section: the CLI, the config keys, the verdict words, and a synthetic
run that is scripts/t1_check_example.py's real output (bin/limitless-t1-check against fake model scripts)."""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "privacy-tiers.md"


def section():
    m = re.search(r"^## Local model check\n(.*?)(?=^## |\Z)", DOC.read_text(), re.S | re.M)
    return m.group(1) if m else ""


class Docs(unittest.TestCase):
    def test_the_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "t1_check_example.py")],
                           capture_output=True, text=True, timeout=120, env=child_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        for want in ("local model check: agrees on most checks", "local model check: agrees on few checks",
                     "local model check: unknown: no local model command set", "set: checked, agrees on most checks",
                     "set: not checked yet"):
            self.assertIn(want, r.stdout)
        self.assertIn(r.stdout, re.findall(r"```text\n(.*?)```", section(), re.S))

    def test_the_section_names_the_cli_the_keys_and_the_words(self):
        text = " ".join(section().split())
        want = ("bin/limitless-t1-check", "`t1_min_agreement`", "`t1_check_file`", "agrees on all checks",
                "agrees on most checks", "agrees on few checks", "unknown:", "no answer", "disagrees", "--json",
                "0600", "synthetic", "never runs the model", "not a capability score", "doctor")
        self.assertEqual([w for w in want if w not in text], [])

    def test_the_readme_names_the_check(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("bin/limitless-t1-check", readme)
        self.assertIn("privacy-tiers.md#local-model-check", readme)


if __name__ == "__main__":
    unittest.main()
