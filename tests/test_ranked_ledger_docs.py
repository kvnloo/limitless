"""docs/ranked-ledger.md: the two writers, a synthetic example that is the script's real output, and the links."""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "ranked-ledger.md"
ROW10_ANCHOR = "scorecard-measured.md#row-10-top-25-ranked-items-done-verified-or-dropped"


class Docs(unittest.TestCase):
    def text(self):
        return " ".join(DOC.read_text().split())

    def test_the_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "ranked_ledger_example.py")],
                           capture_output=True, text=True, timeout=60, env=child_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        blocks = re.findall(r"```text\n(.*?)```", DOC.read_text(), re.S)
        self.assertIn(r.stdout, blocks)

    def test_the_example_ids_are_synthetic(self):
        blocks = "\n".join(re.findall(r"^```text\n(.*?)^```", DOC.read_text(), re.S | re.M))
        # "<job>: drop: <reason>" is a limitless-jobs verdict line (the action drop), not an owner message
        ids = re.findall(r'"id": "([^"]+)"', blocks) + re.findall(r"(?<!: )drop: ([^\n`]+)", blocks)
        ids += re.findall(r"limitless-ranked add (\S+)", blocks)
        self.assertTrue(ids)
        for chunk in ids:
            for i in chunk.split(","):
                self.assertTrue(i.strip().startswith("synthetic-item-"), i)

    def test_the_doc_says_the_rules(self):
        want = ("bin/limitless-ranked add", "bin/limitless-ranked list", "bin/limitless-ranked ingest", "--write",
                "--evidence", "--raw", '"by": "agent"', '"by": "owner"', '"evidence": "owner reply"', "exit 2",
                "only the owner drops", "append-only", "0600", "flock", "ranked-drops.json", "dry run",
                "unknown ids are ignored and counted", "all, most, some, few or none", "never sends",
                "ranked ledger", "LIMITLESS_RANKED_LEDGER", "`ranked_ledger`", ROW10_ANCHOR, "doctor.md")
        text = self.text()
        self.assertEqual([w for w in want if w not in text], [])

    def test_the_scorecard_doc_readme_and_doctor_doc_link_it(self):
        self.assertIn("ranked-ledger.md", (ROOT / "docs" / "scorecard-measured.md").read_text())
        self.assertIn("ranked-ledger.md", (ROOT / "docs" / "doctor.md").read_text())
        readme = (ROOT / "README.md").read_text()
        for w in ("bin/limitless-ranked", "docs/ranked-ledger.md", "ranked-drops.json"):
            self.assertIn(w, readme)

    def test_the_row_ten_anchor_is_the_heading(self):
        heading = '### Row 10, "Top-25 ranked items done-verified or dropped"'
        self.assertIn(heading, (ROOT / "docs" / "scorecard-measured.md").read_text())
        slug = re.sub(r"[^\w\- ]", "", heading.lstrip("# ").lower()).replace(" ", "-")
        self.assertEqual("scorecard-measured.md#" + slug, ROW10_ANCHOR)


if __name__ == "__main__":
    unittest.main()
