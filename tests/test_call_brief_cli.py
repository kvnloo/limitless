"""bin/limitless-call-brief write [--out PATH]: the digit-free state card as a voice-call brief file, written
atomically with mode 0600 and only when its content changed. Synthetic fixtures only; nothing sends.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "limitless-call-brief"
FIX = Path(__file__).resolve().parent / "fixtures" / "state"


class CLITest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.st = self.dir / "state"
        shutil.copytree(FIX, self.st)
        self.out = self.dir / "briefs" / "latest.md"
        self.out.parent.mkdir()
        self.env = {"PATH": os.environ.get("PATH", ""), "HOME": str(self.dir),
                    "LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(self.dir / "none.json")}

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-I", str(CLI), *args], capture_output=True, text=True,
                              env=child_env(self.env), timeout=30)

    def assert_one_line(self, r):
        self.assertEqual(len(r.stdout.strip().splitlines()), 1, r.stdout)
        self.assertNotIn("Traceback", r.stdout + r.stderr)

    def test_write_out(self):
        r = self.run_cli("write", "--out", str(self.out))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_one_line(r)
        self.assertIn("call brief written", r.stdout)
        lines = self.out.read_text().splitlines()
        self.assertRegex(lines[0], r"^<!-- limitless call brief; generated: \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ -->$")
        self.assertTrue(lines[1].startswith("TLDR: "))
        self.assertLessEqual(len(lines), 5)
        self.assertFalse(re.search(r"\d", "\n".join(lines[1:])))
        self.assertEqual(stat.S_IMODE(self.out.stat().st_mode), 0o600)
        self.assertEqual([p.name for p in self.out.parent.iterdir()], ["latest.md"])

    def test_second_run_leaves_the_file_untouched(self):
        self.run_cli("write", "--out", str(self.out))
        os.utime(self.out, ns=(1_000_000_000, 1_000_000_000))
        r = self.run_cli("write", "--out", str(self.out))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("call brief unchanged", r.stdout)
        self.assertEqual(self.out.stat().st_mtime_ns, 1_000_000_000)

    def test_not_configured(self):
        r = self.run_cli("write")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_one_line(r)
        self.assertIn("not configured", r.stdout)
        self.assertEqual(list(self.out.parent.iterdir()), [])

    def test_config_default_relative_to_the_state_dir(self):
        cfg = self.dir / "config.json"
        cfg.write_text(json.dumps({"call_brief_file": "call-brief.md"}))
        self.env["LIMITLESS_CONFIG"] = str(cfg)
        r = self.run_cli("write")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.st / "call-brief.md").is_file())

    def test_unwritable_is_exit_1_one_line(self):
        r = self.run_cli("write", "--out", str(self.dir / "nope" / "latest.md"))
        self.assertEqual(r.returncode, 1)
        self.assert_one_line(r)
        self.assertNotIn(str(self.dir), r.stdout)

    def test_bad_arguments_are_usage_exit_2(self):
        for args in ([], ["send"], ["write", "--out"], ["write", "--out", "a", "--out", "b"], ["write", "--x", "a"]):
            r = self.run_cli(*args)
            self.assertEqual(r.returncode, 2, args)
            self.assertIn("usage: limitless-call-brief", r.stderr)
            self.assertEqual(r.stdout, "")

    def test_help(self):
        r = self.run_cli("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("usage: limitless-call-brief", r.stdout)


if __name__ == "__main__":
    unittest.main()
