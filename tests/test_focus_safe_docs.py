"""docs/focus-safe.md shows the real output of scripts/focus_safe_example.py and every rule, and the README
points at it."""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "focus-safe.md"
sys.path.insert(0, str(ROOT))

from limitless import focus_safe  # noqa: E402


class Docs(unittest.TestCase):
    def test_the_doc_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "focus_safe_example.py")],
                           capture_output=True, text=True, timeout=60, env=child_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        blocks = re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S)
        self.assertIn(r.stdout, blocks)
        self.assertNotRegex(r.stdout, r"/tmp|/home|/Users")

    def test_the_doc_has_every_rule_in_its_table(self):
        rows = [ln for ln in DOC.read_text().splitlines() if ln.startswith("| `")]
        for rule in focus_safe.RULES:
            row = next((ln for ln in rows if ln.startswith(f"| `{rule['id']}` |")), None)
            self.assertIsNotNone(row, rule["id"])
            for k in ("drives", "ok_when", "why"):
                self.assertIn(rule[k], row, (rule["id"], k))

    def test_the_doc_says_what_it_never_does(self):
        text = DOC.read_text().lower()
        for word in ("never blocks", "never rewrites", "off by default", "fail open", "no device commands",
                     "focus_safe_serials", "focus_safe_agent_displays", "pre_tool_call"):
            self.assertIn(word, text)

    def test_the_readme_names_the_tool_hook_and_doc(self):
        text = (ROOT / "README.md").read_text()
        for word in ("limitless_focus_safe", "docs/focus-safe.md", "focus_safe_serials", "pre_tool_call"):
            self.assertIn(word, text)


if __name__ == "__main__":
    unittest.main()
