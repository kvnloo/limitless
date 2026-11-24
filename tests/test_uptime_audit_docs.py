"""docs/uptime-audit.md shows the real output of scripts/uptime_audit_example.py, and the README points at it."""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "uptime-audit.md"


class Docs(unittest.TestCase):
    def test_the_doc_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "uptime_audit_example.py")],
                           capture_output=True, text=True, timeout=60, env=child_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        blocks = re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S)
        self.assertIn(r.stdout, blocks)

    def test_the_readme_names_the_tool_the_cli_the_config_and_the_doc(self):
        text = (ROOT / "README.md").read_text()
        for word in ("limitless_uptime", "limitless/uptime_audit.py", "bin/limitless-uptime-audit",
                     "docs/uptime-audit.md", "uptime_days", "uptime_target"):
            self.assertIn(word, text)

    def test_the_doc_names_the_rules_it_relies_on(self):
        text = DOC.read_text()
        for word in ('"at"', '"inputs"', '"stale a,b,c"', "no `inputs` key", "never fresh", "unknown, not zero",
                     "uptime_days", "uptime_target", "outage_ignore", "RAW_IN_PROMPT", "limitless-doctor",
                     "--json", "scorecard", "never marks", "never changes how it is written", "no clock time"):
            self.assertIn(word, text)


if __name__ == "__main__":
    unittest.main()
