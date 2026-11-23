"""docs/open-wearables.md shows the real output of scripts/ow_export_example.py, cites the Open Wearables API it
reads, and the README points at it."""
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "open-wearables.md"


class Docs(unittest.TestCase):
    def test_the_doc_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "ow_export_example.py")],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        blocks = re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S)
        self.assertIn(r.stdout, blocks)

    def test_the_readme_names_the_tool_the_config_the_key_and_the_doc(self):
        text = (ROOT / "README.md").read_text()
        for word in ("bin/limitless-ow-export", "open_wearables_export", "open_wearables_url", "LIMITLESS_OW_KEY",
                     "docs/open-wearables.md"):
            self.assertIn(word, text)

    def test_the_doc_cites_the_api_and_says_what_it_never_does(self):
        text = DOC.read_text()
        for word in ("github.com/the-momentum/open-wearables", "/api/v1/users/{user_id}/events/sleep",
                     "X-Open-Wearables-API-Key", "docs/api-reference/introduction.mdx", "docs/openapi.json",
                     "backend/app/api/routes/v1/events.py", "sleep_duration_seconds", "next_cursor",
                     "LIMITLESS_OW_KEY", "open_wearables_user", "0600", "--write", "unchanged", "noop"):
            self.assertIn(word, text)
        self.assertRegex(text, r"\b[0-9a-f]{40}\b")   # the upstream commit read
        low = text.lower()
        for word in ("never from config.json", "never a guess", "never a clock time", "which wins"):
            self.assertIn(word, low)


if __name__ == "__main__":
    unittest.main()
