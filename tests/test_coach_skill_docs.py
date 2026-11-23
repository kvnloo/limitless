"""docs/coach-skill.md and the README line: the doc names the host method and the exact log lines, links the
skill, and its registration-test output names every test in test_coach_register.py."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import coach_skill  # noqa: E402

DOC = ROOT / "docs" / "coach-skill.md"


class CoachSkillDoc(unittest.TestCase):
    def setUp(self):
        self.text = DOC.read_text()

    def test_names_the_host_method_and_the_log_lines(self):
        self.assertIn(f"`{coach_skill.HOST_METHOD}`", self.text)
        self.assertIn(coach_skill.NO_HOST, self.text)
        self.assertIn(coach_skill.HOST_FAILED, self.text)
        self.assertIn("limitless:coach", self.text)

    def test_links_the_skill(self):
        self.assertIn("(../skills/coach/SKILL.md)", self.text)

    def test_the_registration_output_lists_every_registration_test(self):
        src = (ROOT / "tests" / "test_coach_register.py").read_text()
        for name in re.findall(r"(?m)^    def (test_\w+)\(", src):
            self.assertIn(name, self.text, name)
        self.assertRegex(self.text, r"\nOK\n")


class Readme(unittest.TestCase):
    def test_readme_names_the_skill_and_links_the_doc(self):
        text = (ROOT / "README.md").read_text()
        self.assertTrue("limitless:coach" in text, "README names limitless:coach")
        self.assertTrue("(docs/coach-skill.md)" in text, "README links docs/coach-skill.md")


if __name__ == "__main__":
    unittest.main()
