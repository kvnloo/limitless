"""docs/app-candidates.md shows the real output of scripts/app_candidates_example.py; README and coach point at it."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "app-candidates.md"
sys.path.insert(0, str(ROOT))

from limitless import app_candidates  # noqa: E402


class Docs(unittest.TestCase):
    def test_the_doc_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "app_candidates_example.py")],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        blocks = re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S)
        self.assertIn(r.stdout, blocks)
        self.assertIn("work apps: ", r.stdout)
        self.assertIn("feed apps: ", r.stdout)

    def test_the_readme_names_the_module_tool_cli_and_doc(self):
        text = (ROOT / "README.md").read_text()
        for word in ("limitless/app_candidates.py", "limitless_app_candidates", "bin/limitless-app-candidates",
                     "docs/app-candidates.md", "app_candidates_max"):
            self.assertIn(word, text)

    def test_the_coach_skill_routes_the_question(self):
        self.assertIn("| limitless_app_candidates |", (ROOT / "skills" / "coach" / "SKILL.md").read_text())

    def test_the_doc_names_the_rule_and_its_constants(self):
        text = DOC.read_text()
        for word in ("KNOWN", "MAX_N", "MIN_TOTAL_S", "LOOKBACK_DAYS", "app_candidates_max", "flow_work_apps",
                     "feed_apps", "blocks.read_rows", "aw_desktop", "reply_line", "LIMITLESS_RAW_IN_PROMPT",
                     "--json", "kept"):
            self.assertIn(word, text)
        for word in app_candidates.WORDS + (app_candidates.NO_SOURCE, app_candidates.NO_ROWS,
                                            app_candidates.TOO_LITTLE, app_candidates.NO_KNOWN):
            self.assertIn(word, text)

    def test_the_doc_says_what_it_never_does(self):
        text = DOC.read_text().lower()
        for word in ("never writes config or any file", "never sends", "never empty lists",
                     "browsers are never work by default", "never a clock time", "no score"):
            self.assertIn(word, text)
        self.assertNotRegex(text, r"\b(supplement|dose|dosing|melatonin|caffeine)\b")

    def test_the_example_output_is_synthetic(self):
        text = DOC.read_text()
        self.assertNotRegex(text, r"/(Users|home)/")
        for block in re.findall(r"```text\n(.*?)```", text, re.S):
            self.assertNotIn("tmp", block)


if __name__ == "__main__":
    unittest.main()
