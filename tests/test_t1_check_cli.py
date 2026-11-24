"""bin/limitless-t1-check: runs the check only when called, prints words only (counts only with --json), saves
the verdict words to config t1_check_file under the state dir (mode 0600) and exits 0 only when the verdict
meets t1_min_agreement. Fake model executables in temp dirs; synthetic config only."""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import t1_agreement as ta  # noqa: E402

BIN = ROOT / "bin" / "limitless-t1-check"
FAKE = """#!{python} -I
import re, sys
sys.path.insert(0, {root!r})
from limitless import labeler
prompt = sys.stdin.read()
kind = re.search(r"Label one (\\S+) value", prompt).group(1)
allowed = re.search(r"from this set: ([^\\n]*?)\\.\\n", prompt).group(1).split(", ")
rule = labeler.rule_label(kind, float(re.search(r"Value: (\\S+)", prompt).group(1)))
print(rule if sys.argv[1] == "agree" else [w for w in allowed if w != rule][0])
"""


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.state = self.dir / "state"
        self.state.mkdir()
        self.fake = self.dir / "fake-model"
        self.fake.write_text(FAKE.format(python=sys.executable, root=str(ROOT)))
        self.fake.chmod(0o755)

    def run_cli(self, mode="agree", *args, **cfg):
        base = {"state": str(self.state)}
        if mode:
            base["t1_model_cmd"] = f'"{self.fake}" {mode}'
        base.update(cfg)
        path = self.dir / "config.json"
        path.write_text(json.dumps(base))
        return subprocess.run([sys.executable, "-I", str(BIN), *args], capture_output=True, text=True, timeout=120,
                              env=child_env(LIMITLESS_CONFIG=str(path)))


class Cli(Base):
    def test_an_agreeing_model_passes_and_the_words_are_saved_mode_0600(self):
        r = self.run_cli("agree", t1_check_file="t1-check.txt")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotRegex(r.stdout, r"\d")
        self.assertIn("local model check: agrees on all checks", r.stdout)
        self.assertIn("sleep_h: agrees", r.stdout)
        f = self.state / "t1-check.txt"
        self.assertEqual(f.read_text(), "agrees on all checks\n")
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)

    def test_a_wrong_word_model_fails_and_its_verdict_replaces_the_old_one(self):
        f = self.state / "t1-check.txt"
        f.write_text("agrees on all checks\n")
        f.chmod(0o644)
        r = self.run_cli("wrong", t1_check_file="t1-check.txt")
        self.assertEqual(r.returncode, 1)
        self.assertIn("agrees on few checks", r.stdout)
        self.assertNotRegex(r.stdout, r"\d")
        self.assertEqual(f.read_text(), "agrees on few checks\n")
        self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)

    def test_json_gives_the_counts(self):
        r = self.run_cli("agree", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual((got["verdict"], got["agrees"], got["checks"]), ("all", len(ta.CASES), len(ta.CASES)))
        self.assertEqual((got["allowed"], got["saved"], got["min_agreement"]), (True, False, "most"))

    def test_no_check_file_writes_nothing(self):
        r = self.run_cli("agree")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("not saved", r.stdout)
        self.assertEqual(list(self.state.iterdir()), [])

    def test_no_command_is_unknown_and_exits_one(self):
        r = self.run_cli(None, t1_check_file="t1-check.txt")
        self.assertEqual(r.returncode, 1)
        self.assertIn("local model check: unknown: no local model command set", r.stdout)
        self.assertEqual((self.state / "t1-check.txt").read_text(), "unknown: no local model command set\n")

    def test_min_agreement_all_is_stricter(self):
        self.assertEqual(self.run_cli("agree", t1_min_agreement="all").returncode, 0)


class CheckPath(unittest.TestCase):
    def test_a_file_under_the_state_dir_only(self):
        cfg = {"state": "/tmp/zq-state"}
        self.assertEqual(ta.check_path(dict(cfg, t1_check_file="t1-check.txt"), env={}),
                         Path("/tmp/zq-state/t1-check.txt"))
        for bad in ("/etc/t1-check.txt", "../t1-check.txt", "a/../../b", "", "  ", ["x"], None):
            self.assertIsNone(ta.check_path(dict(cfg, t1_check_file=bad), env={}), bad)
        self.assertIsNone(ta.check_path(cfg, env={}))


if __name__ == "__main__":
    unittest.main()
