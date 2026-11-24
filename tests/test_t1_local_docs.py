"""docs/privacy-tiers.md's local model labeler section: the config keys, CPU only, the rule label wins on any
doubt, and a synthetic example that is scripts/t1_local_example.py's real output."""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "privacy-tiers.md"


def section():
    text = DOC.read_text()
    m = re.search(r"^## Local model labeler\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return m.group(1) if m else ""


class Docs(unittest.TestCase):
    def test_the_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "t1_local_example.py")],
                           capture_output=True, text=True, timeout=120, env=child_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("local label: ok", r.stdout)
        self.assertIn("(the rule label)", r.stdout)
        self.assertIn(r.stdout, re.findall(r"```text\n(.*?)```", section(), re.S))

    def test_the_section_names_the_keys_and_the_rules(self):
        text = " ".join(section().split())
        want = ("bin/limitless-t1-local", "LIMITLESS_T1_CMD", "`t1_model_cmd`", "LIMITLESS_T1_BIN", "`t1_bin`",
                "LIMITLESS_T1_MODEL", "`t1_model`", "`t1_threads`", "`t1_timeout_s`", "-ngl 0",
                "must run on the CPU", "rule label wins on any doubt", "CUDA_VISIBLE_DEVICES",
                "HIP_VISIBLE_DEVICES", "tiny-model.gguf", "never writes a file", "local labeler", "doctor.md",
                "never downloads")
        self.assertEqual([w for w in want if w not in text], [])

    def test_the_example_config_is_synthetic(self):
        text = section()
        for name in re.findall(r"[\w.-]+\.gguf", text):
            self.assertEqual(name, "tiny-model.gguf")

    def test_the_readme_names_the_runner_and_the_doctor_doc_links_it(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("bin/limitless-t1-local", readme)
        self.assertIn("privacy-tiers.md#local-model-labeler", readme)
        self.assertIn("privacy-tiers.md#local-model-labeler", (ROOT / "docs" / "doctor.md").read_text())


if __name__ == "__main__":
    unittest.main()
