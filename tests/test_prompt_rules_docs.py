"""docs/prompt-rules.md and the README line: the doc names the section id, the host method, the config key and
the exact log lines, quotes the section verbatim, and its test output names every test in test_prompt_rules.py."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import prompt_rules  # noqa: E402

DOC = ROOT / "docs" / "prompt-rules.md"


class PromptRulesDoc(unittest.TestCase):
    def setUp(self):
        self.text = DOC.read_text()

    def test_names_the_id_the_host_method_the_config_key_and_the_log_lines(self):
        for s in (f"`{prompt_rules.SECTION_ID}`", f"`{prompt_rules.HOST_METHOD}`", f"`{prompt_rules.CONFIG_KEY}`",
                  f"`{prompt_rules.POSITION}`", prompt_rules.NO_HOST, prompt_rules.HOST_FAILED,
                  prompt_rules.DISABLED):
            self.assertIn(s, self.text)

    def test_quotes_the_section_verbatim(self):
        self.assertIn("```text\n" + prompt_rules.CONTENT + "\n```", self.text)

    def test_links_the_coach_skill(self):
        self.assertIn("(../skills/coach/SKILL.md)", self.text)

    def test_the_test_output_lists_every_test(self):
        src = (ROOT / "tests" / "test_prompt_rules.py").read_text()
        for name in re.findall(r"(?m)^    def (test_\w+)\(", src):
            self.assertIn(name, self.text, name)
        self.assertRegex(self.text, r"\nOK\n")


class Readme(unittest.TestCase):
    def test_readme_names_the_section_and_links_the_doc(self):
        text = (ROOT / "README.md").read_text()
        self.assertIn("`limitless.rules`", text)
        self.assertIn("(docs/prompt-rules.md)", text)


if __name__ == "__main__":
    unittest.main()
