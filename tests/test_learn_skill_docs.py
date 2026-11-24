"""docs/learn-skill.md and the README line: the doc names limitless:learn, the host method and the exact log lines,
links the skill, and its registration-test output names every test in test_learn_register.py."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import coach_skill  # noqa: E402

DOC = ROOT / "docs" / "learn-skill.md"


class LearnSkillDoc(unittest.TestCase):
    def setUp(self):
        self.text = DOC.read_text()

    def test_names_the_skill_the_host_method_and_the_log_lines(self):
        self.assertIn("limitless:learn", self.text)
        self.assertIn(f"`{coach_skill.HOST_METHOD}`", self.text)
        self.assertIn(coach_skill.NO_HOST, self.text)
        self.assertIn(coach_skill.HOST_FAILED, self.text)

    def test_links_the_skill(self):
        self.assertIn("(../skills/learn/SKILL.md)", self.text)

    def test_the_registration_output_lists_every_registration_test(self):
        src = (ROOT / "tests" / "test_learn_register.py").read_text()
        names = re.findall(r"(?m)^    def (test_\w+)\(", src)
        self.assertTrue(names)
        for name in names:
            self.assertIn(name, self.text, name)
        self.assertRegex(self.text, r"\nOK\n")


class Readme(unittest.TestCase):
    def test_readme_names_the_skill_and_links_the_doc(self):
        text = (ROOT / "README.md").read_text()
        self.assertTrue("limitless:learn" in text, "README names limitless:learn")
        self.assertTrue("(docs/learn-skill.md)" in text, "README links docs/learn-skill.md")


if __name__ == "__main__":
    unittest.main()
