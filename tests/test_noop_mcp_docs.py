"""docs/noop-mcp.md: the config key, a placeholder-only host mcp_servers snippet, why the result filter comes first,
and every doctor row's words; the README points at it."""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import doctor, noop_mcp  # noqa: E402

DOC = ROOT / "docs" / "noop-mcp.md"


class Docs(unittest.TestCase):
    def setUp(self):
        self.text = DOC.read_text()

    def test_names_the_key_the_glob_and_the_filter(self):
        for word in ("`noop_mcp`", "`t0_tools`", "mcp__noop__*", "result-tier.md", "never starts", "Off by default",
                     "raw_numbers_opt_in"):
            self.assertIn(word, self.text)

    def test_the_json_example_is_a_config_the_module_reads(self):
        block = re.findall(r"```json\n(.*?)```", self.text, re.S)[0]
        cfg = json.loads(block)
        self.assertEqual(noop_mcp.state(cfg), noop_mcp.BY_HAND)
        self.assertEqual(noop_mcp.server_spec(cfg)["name"], noop_mcp.DEFAULT_NAME)

    def test_the_yaml_snippet_is_placeholders_only(self):
        block = re.findall(r"```yaml\n(.*?)```", self.text, re.S)[0]
        self.assertTrue(block.startswith("mcp_servers:\n  noop:\n"), block)
        for key in ("command:", "args:", "env:"):
            self.assertIn(key, block)
        self.assertNotIn("/", block)
        for value in re.findall(r'"([^"]*)"', block):
            self.assertRegex(value, r"^<[^<>]+>$")

    def test_every_doctor_row_is_written_down(self):
        for status, reason in doctor.NOOP_MCP_WORDS.values():
            self.assertIn(f"`{doctor.NOOP_MCP_ROW}: {status}: {reason}`", self.text)

    def test_says_why_the_plugin_registers_nothing(self):
        for word in ("hermes_cli/plugins_context.py", "hermes_cli/data/plugin_api.json", "mcp.json",
                     "registers nothing"):
            self.assertIn(word, self.text)

    def test_the_readme_points_at_it(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("docs/noop-mcp.md", readme)
        self.assertIn("`noop_mcp`", readme)


if __name__ == "__main__":
    unittest.main()
