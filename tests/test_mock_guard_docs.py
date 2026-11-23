"""docs/mock-guard.md: its synthetic run is the example script's real output, it cites the markers by file and line,
and the README names it. A digit walk over every word the guard adds to a label or a doctor reason. Synthetic only.
"""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import doctor, mock_guard as mg, noop_export as nx  # noqa: E402

DOC = ROOT / "docs" / "mock-guard.md"


class Docs(unittest.TestCase):
    def test_the_doc_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "mock_guard_example.py")],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(r.stdout, re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S))

    def test_the_doc_cites_each_marker(self):
        text = DOC.read_text()
        for cite in ("DemoSeeder.kt:70", "AppleDemoSeeder.swift:55", "DemoSeeder.kt:93", "AppleDemoSeeder.swift:67",
                     "seed_data/service.py:155", "user_management/user.py:117", "mock_device_patterns"):
            self.assertIn(cite, text)

    def test_the_readme_names_the_doc_and_the_config(self):
        text = (ROOT / "README.md").read_text()
        for word in ("docs/mock-guard.md", "mock_device_patterns", "limitless/mock_guard.py"):
            self.assertIn(word, text)


class DigitWalk(unittest.TestCase):
    def test_no_digit_in_any_word_the_guard_adds(self):
        said = [mg.LEFT_OUT, mg.ONLY_DEMO, doctor.INPUT_WORDS["demo"][1]]
        said += [nx.demo_words(n) for n in range(0, 12001, 7)]
        said += [doctor.words(s) for s in said]
        for s in said:
            self.assertNotRegex(s, r"\d", s)


if __name__ == "__main__":
    unittest.main()
