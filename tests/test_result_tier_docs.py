"""docs/result-tier.md shows the real output of scripts/result_tier_example.py, names the Hermes contract and
the MCP tool name spelling it relies on, and the README points at it."""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "result-tier.md"


class Docs(unittest.TestCase):
    def test_the_doc_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "result_tier_example.py")],
                           capture_output=True, text=True, timeout=60, env=child_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        blocks = re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S)
        self.assertIn(r.stdout, blocks)
        self.assertNotRegex(r.stdout, r"/tmp|/home|/Users")

    def test_the_example_shows_no_reading_after_the_filter(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "result_tier_example.py")],
                           capture_output=True, text=True, timeout=60, env=child_env())
        after = [ln for ln in r.stdout.splitlines() if ln.startswith("after:")]
        self.assertTrue(after)
        for ln in after:
            self.assertNotRegex(re.sub(r'"[A-Za-z_]*\d[A-Za-z_\d]*":', "", ln), r"(?<![A-Za-z_])\d", ln)

    def test_the_doc_cites_the_host_contract(self):
        text = DOC.read_text()
        for word in ("transform_tool_result", "model_tools.py", "_apply_transform_tool_result_hook",
                     "tools/mcp_tool_schema.py", "mcp_prefixed_tool_name", "mcp__<server>__<tool>",
                     "t0_tools", "raw_numbers_opt_in", "fail-open", "a number", "limitless_result_tier",
                     "off by default", "VALID_HOOKS", "never a value"):
            self.assertIn(word, text)

    def test_the_readme_names_the_module_tool_and_doc(self):
        text = (ROOT / "README.md").read_text()
        for word in ("limitless/result_tier.py", "limitless_result_tier", "docs/result-tier.md", "t0_tools"):
            self.assertIn(word, text)


if __name__ == "__main__":
    unittest.main()
