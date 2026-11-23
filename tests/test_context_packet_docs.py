"""docs/context-packet.md shows the real output of scripts/context_packet_example.py, names the schema and its
rules, and the README points at it."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "context-packet.md"


class Docs(unittest.TestCase):
    def test_the_doc_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "context_packet_example.py")],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        blocks = re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S)
        self.assertIn(r.stdout, blocks)

    def test_the_doc_names_the_schema_and_its_rules(self):
        text = DOC.read_text()
        for word in ("limitless.context/1", "generated_at", "evidence_tier", "age_words", "context_packet_path",
                     "LIMITLESS_RAW_IN_PROMPT", "0600", "card.build", "dry run", "--write", "--json",
                     "z0", "no digit"):
            self.assertIn(word, text)

    def test_the_readme_names_the_command_and_the_doc(self):
        text = (ROOT / "README.md").read_text()
        for word in ("bin/limitless-context-packet", "docs/context-packet.md", "context_packet_path"):
            self.assertIn(word, text)


if __name__ == "__main__":
    unittest.main()
