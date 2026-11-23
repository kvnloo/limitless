"""docs/delivery-audit.md shows the real output of scripts/delivery_audit_example.py, and the README points at it."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "delivery-audit.md"


class Docs(unittest.TestCase):
    def test_the_doc_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "delivery_audit_example.py")],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        blocks = re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S)
        self.assertIn(r.stdout, blocks)

    def test_the_readme_names_the_tool_the_config_and_the_doc(self):
        text = (ROOT / "README.md").read_text()
        for word in ("limitless_delivery", "limitless/delivery_audit.py", "docs/delivery-audit.md", "push_log"):
            self.assertIn(word, text)

    def test_the_doc_names_the_fields_it_relies_on_and_what_is_not_written(self):
        text = DOC.read_text()
        for word in ('"how"', '"telegram"', '"at"', '"title"', '"body"', "Wake-up brief", "DAILY_CAP", "push_cap",
                     "push_log", "--once", "not in the row", "unknown, not zero", "RAW_IN_PROMPT",
                     "week_review:delivery", "no clock time", "never changes how it is written"):
            self.assertIn(word, text)


if __name__ == "__main__":
    unittest.main()
