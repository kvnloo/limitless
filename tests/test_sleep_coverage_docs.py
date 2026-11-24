"""docs/sleep-coverage.md shows the real output of scripts/sleep_coverage_example.py, and the README points at it."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "sleep-coverage.md"


class Docs(unittest.TestCase):
    def test_the_doc_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "sleep_coverage_example.py")],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        blocks = re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S)
        self.assertIn(r.stdout, blocks)

    def test_the_readme_names_the_tool_the_cli_the_config_and_the_doc(self):
        text = (ROOT / "README.md").read_text()
        for word in ("limitless_sleep_coverage", "limitless/sleep_coverage.py", "bin/limitless-sleep-coverage",
                     "docs/sleep-coverage.md", "sleep_coverage_days", "sleep_coverage_target"):
            self.assertIn(word, text)

    def test_the_doc_names_the_rules_it_relies_on(self):
        text = DOC.read_text()
        for word in ("sleep_file", "sleep_coverage_days", "sleep_coverage_target", "mock_device_patterns",
                     "mock_guard", "never counts as wearable", "unknown, not zero", "fewer than a week",
                     "RAW_IN_PROMPT", "limitless-doctor", "--json", "scorecard", "no clock time", "read-only"):
            self.assertIn(word, text)


if __name__ == "__main__":
    unittest.main()
