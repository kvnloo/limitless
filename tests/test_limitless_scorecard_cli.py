"""bin/limitless-scorecard end to end: prints the weekly-review block, never writes. Synthetic fixtures only."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "limitless-scorecard"
FIX = ROOT / "tests" / "fixtures" / "scorecard"
BLOCK = ("North star (self-reported)\n"
         "- 1 green, 2 amber, 2 red of 5\n"
         "- not all green yet\n"
         "- Loop uptime: red\n"
         "- Review held: red\n"
         "- Delivery: amber\n")


def tree(d):
    return sorted((str(p.relative_to(d)), p.stat().st_mtime_ns, p.stat().st_size) for p in Path(d).rglob("*"))


class LimitlessScorecardCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("LIMITLESS_")}
        self.env["HOME"] = str(self.home)

    def run_cli(self, *args, **env):
        return subprocess.run([sys.executable, "-I", str(CLI), *args], env=dict(self.env, **env), cwd=self.home,
                              capture_output=True, text=True, timeout=30)

    def test_path_argument_prints_the_block(self):
        r = self.run_cli(str(FIX / "thresholds.md"))
        self.assertEqual((r.returncode, r.stdout), (0, BLOCK), r.stderr)

    def test_env_path(self):
        r = self.run_cli(LIMITLESS_SCORECARD=str(FIX / "thresholds.md"))
        self.assertEqual((r.returncode, r.stdout), (0, BLOCK), r.stderr)

    def test_config_path(self):
        cfg = self.home / ".config/limitless/config.json"
        cfg.parent.mkdir(parents=True)
        cfg.write_text(json.dumps({"scorecard": str(FIX / "thresholds.md")}))
        r = self.run_cli()
        self.assertEqual((r.returncode, r.stdout), (0, BLOCK), r.stderr)

    def test_original_fixture(self):
        r = self.run_cli(str(FIX / "scorecard.md"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), ["North star (self-reported)", "- 6 green, 2 amber, 2 red of 10",
                                                 "- not all green yet", "- Habit logging: red",
                                                 "- Experiment readout: red", "- Delivery: amber"])
        self.assertNotIn("sentinel", r.stdout)

    def test_no_table_exits_zero_with_no_output(self):
        p = self.home / "empty.md"
        p.write_text("# Scorecard\n\nnot started\n")
        r = self.run_cli(str(p))
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_no_path_configured_exits_zero_with_no_output(self):
        r = self.run_cli()
        self.assertEqual((r.returncode, r.stdout), (0, ""))

    def test_missing_file_fails_without_echoing_the_path(self):
        missing = self.home / "private-dir" / "nope.md"
        r = self.run_cli(str(missing))
        self.assertEqual((r.returncode, r.stdout), (1, ""))
        self.assertTrue(r.stderr)
        self.assertNotIn("private-dir", r.stderr)

    def test_never_writes(self):
        card = self.home / "card.md"
        card.write_text((FIX / "thresholds.md").read_text())
        before, fix_before = tree(self.home), tree(FIX)
        for args in ((str(card),), (), (str(self.home / "nope.md"),)):
            self.run_cli(*args)
        self.run_cli(LIMITLESS_SCORECARD=str(card))
        self.assertEqual(tree(self.home), before)
        self.assertEqual(tree(FIX), fix_before)


    def test_an_existing_state_dir_adds_the_measured_lines(self):
        st = self.home / "state"
        st.mkdir()
        r = self.run_cli(str(FIX / "scorecard.md"), LIMITLESS_STATE=str(st))
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(len(lines), 6)
        self.assertEqual(lines[1:4], ["- 6 green, 2 amber, 2 red of 10", "- not all green yet", "- Habit logging: red"])
        self.assertEqual(lines[4], "- Measured: loop uptime: unknown: no sync run log in the state dir (runs.jsonl)")
        self.assertEqual(lines[5], "- Measured: delivery: unknown: no push log set")
        self.assertEqual(tree(st), [])

    def test_no_state_dir_keeps_the_plain_block(self):
        r = self.run_cli(str(FIX / "thresholds.md"), LIMITLESS_STATE=str(self.home / "absent"))
        self.assertEqual((r.returncode, r.stdout), (0, BLOCK), r.stderr)

if __name__ == "__main__":
    unittest.main()
