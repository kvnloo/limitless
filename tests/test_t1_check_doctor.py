"""limitless-doctor's local labeler row says whether a passing local model check is on file: "set: checked,
agrees on most checks" or "set: not checked yet". Words only. It reads the small saved file and never runs the
model or the check. Synthetic config and a fake model binary only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import doctor  # noqa: E402

WRAPPER = ROOT / "bin" / "limitless-t1-local"
FAKE = "#!{python} -I\nopen({mark!r}, 'w').write('ran')\nprint('ok')\n"


class Row(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "box-42"   # a digit in every path: it must never reach a row
        self.state = self.dir / "state-9"
        self.state.mkdir(parents=True)
        self.mark = self.dir / "ran.txt"
        self.bin = self.dir / "llama-cli-7"
        self.bin.write_text(FAKE.format(python=sys.executable, mark=str(self.mark)))
        self.bin.chmod(0o755)
        self.model = self.dir / "tiny-model-3.gguf"
        self.model.write_bytes(b"")
        self.cfg = {"t1_model_cmd": f'"{sys.executable}" -I "{WRAPPER}"', "t1_bin": str(self.bin),
                    "t1_model": str(self.model), "state": str(self.state)}

    def row(self, saved=None, **extra):
        if saved is not None:
            (self.state / "t1-check.txt").write_text(saved)
        boom = mock.Mock(side_effect=AssertionError("the doctor started a process"))
        with mock.patch("subprocess.Popen", boom), mock.patch("subprocess.run", boom):
            r = doctor.local_labeler_row(dict(self.cfg, **extra), {})
        self.assertNotRegex(doctor.text([r]) + doctor.as_json([r]), r"\d", r)
        self.assertFalse(self.mark.exists(), "the doctor ran the model")
        self.assertIn("not run", r["reason"])
        return r

    def test_a_passing_check_on_file(self):
        r = self.row("agrees on most checks\n", t1_check_file="t1-check.txt")
        self.assertEqual(r["status"], doctor.LIVE)
        self.assertTrue(r["reason"].startswith("set: checked, agrees on most checks"), r)

    def test_no_check_on_file_keeps_the_rule_labels(self):
        r = self.row(t1_check_file="t1-check.txt")
        self.assertEqual(r["status"], doctor.OFF)
        self.assertTrue(r["reason"].startswith("set: not checked yet"), r)
        self.assertIn("rule labels are used", r["reason"])

    def test_a_failing_check_on_file_keeps_the_rule_labels(self):
        for words in ("agrees on few checks", "unknown: every call failed"):
            r = self.row(words + "\n", t1_check_file="t1-check.txt")
            self.assertEqual(r["status"], doctor.OFF)
            self.assertTrue(r["reason"].startswith(f"set: checked, {words}"), r)
            self.assertIn("rule labels are used", r["reason"])
        r = self.row("agrees on most checks\n", t1_check_file="t1-check.txt", t1_min_agreement="all")
        self.assertEqual(r["status"], doctor.OFF)

    def test_no_check_file_set_is_not_checked_yet_and_unchanged_otherwise(self):
        r = self.row("agrees on all checks\n")
        self.assertEqual(r["status"], doctor.LIVE)
        self.assertTrue(r["reason"].startswith("set: not checked yet"), r)
        self.assertNotIn("rule labels are used", r["reason"])

    def test_another_command_says_it_too(self):
        r = self.row("agrees on all checks\n", t1_check_file="t1-check.txt", t1_model_cmd=f'"{self.bin}"')
        self.assertEqual(r["status"], doctor.LIVE)
        self.assertTrue(r["reason"].startswith("set: checked, agrees on all checks"), r)

    def test_off_and_broken_rows_are_unchanged(self):
        self.assertEqual(doctor.local_labeler_row({"t1_check_file": "t1-check.txt"}, {})["reason"],
                         doctor.LOCAL_WORDS["off"][1])
        r = doctor.local_labeler_row(dict(self.cfg, t1_check_file="t1-check.txt",
                                          t1_model=str(self.dir / "gone.gguf")), {})
        self.assertEqual(r["reason"], doctor.LOCAL_WORDS["no files"][1])


if __name__ == "__main__":
    unittest.main()
