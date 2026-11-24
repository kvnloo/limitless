"""docs/chief-skill.md and the README line: the doc names limitless:chief, the host method and the exact log lines,
links the skill and the asks design note, and its registration-test output names every test in
test_chief_register.py."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import coach_skill  # noqa: E402

DOC = ROOT / "docs" / "chief-skill.md"


class ChiefSkillDoc(unittest.TestCase):
    def setUp(self):
        self.text = DOC.read_text()

    def test_names_the_skill_the_host_method_and_the_log_lines(self):
        self.assertIn("limitless:chief", self.text)
        self.assertIn(f"`{coach_skill.HOST_METHOD}`", self.text)
        self.assertIn(coach_skill.NO_HOST, self.text)
        self.assertIn(coach_skill.HOST_FAILED, self.text)

    def test_links_the_skill_and_the_asks_note(self):
        self.assertIn("(../skills/chief/SKILL.md)", self.text)
        self.assertIn("(decision-window.md#asks)", self.text)

    def test_the_registration_output_lists_every_registration_test(self):
        src = (ROOT / "tests" / "test_chief_register.py").read_text()
        names = re.findall(r"(?m)^    def (test_\w+)\(", src)
        self.assertTrue(names)
        for name in names:
            self.assertIn(name, self.text, name)
        self.assertRegex(self.text, r"\nOK\n")


class OtherDocs(unittest.TestCase):
    def test_readme_names_the_skill_and_links_the_doc(self):
        text = (ROOT / "README.md").read_text()
        self.assertTrue("limitless:chief" in text, "README names limitless:chief")
        self.assertTrue("(docs/chief-skill.md)" in text, "README links docs/chief-skill.md")

    def test_the_asks_note_points_at_the_skill(self):
        text = (ROOT / "docs" / "decision-window.md").read_text()
        self.assertIn("limitless:chief", text)
        self.assertIn("(chief-skill.md)", text)


if __name__ == "__main__":
    unittest.main()
