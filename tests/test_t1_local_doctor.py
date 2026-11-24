"""limitless-doctor's local labeler row: off with no t1_model_cmd; set when the command, the runner's model binary
and model file exist (the model is never run); broken when one is missing. Words only: no digit, no path, no
command. The doctor's own tool calls use the rule labels, so a configured model never runs during a report.
Synthetic config and a fake model binary only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import doctor, labeler  # noqa: E402

NOW = 1894708800.0
WRAPPER = ROOT / "bin" / "limitless-t1-local"
# a fake model binary that leaves a mark when it runs; the doctor must never run it
FAKE = "#!{python} -I\nimport sys\nopen({mark!r}, 'w').write('ran')\nprint('ok')\n"


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "box-42"   # a digit in every path: it must never reach a row
        self.dir.mkdir()
        self.mark = self.dir / "ran.txt"
        self.bin = self.dir / "llama-cli-7"
        self.bin.write_text(FAKE.format(python=sys.executable, mark=str(self.mark)))
        self.bin.chmod(0o755)
        self.model = self.dir / "tiny-model-3.gguf"
        self.model.write_bytes(b"")
        self.cmd = f'"{sys.executable}" -I "{WRAPPER}"'

    def row(self, cfg, env=None):
        r = doctor.local_labeler_row(cfg, {} if env is None else env)
        self.assertEqual(set(r), {"name", "kind", "status", "reason"})
        self.assertEqual((r["name"], r["kind"]), (doctor.LOCAL_LABELER_ROW, "labeler"))
        out = doctor.text([r]) + doctor.as_json([r])
        self.assertNotRegex(out, r"\d", r)
        for planted in ("box", "llama", "tiny-model", sys.executable, "-I"):
            self.assertNotIn(planted, r["reason"])
        self.assertFalse(self.mark.exists(), "the doctor ran the model")
        return r

    def full(self, **extra):
        return dict({"t1_model_cmd": self.cmd, "t1_bin": str(self.bin), "t1_model": str(self.model)}, **extra)


class Row(Base):
    def test_off_without_a_command(self):
        r = self.row({})
        self.assertEqual(r["status"], doctor.OFF)
        self.assertEqual(r["reason"], "no local model command set, so the rule labels are used")
        self.assertIn("rule labels", r["reason"])
        self.assertEqual(self.row({"t1_model_cmd": "  "})["status"], doctor.OFF)
        self.assertEqual(self.row({"t1_model_cmd": ["a", "b"]})["status"], doctor.OFF)

    def test_set_from_config(self):
        r = self.row(self.full())
        self.assertEqual(r["status"], doctor.LIVE)
        self.assertTrue(r["reason"].startswith("set:"), r)
        self.assertIn("not run", r["reason"])

    def test_set_from_env(self):
        env = {"LIMITLESS_T1_CMD": self.cmd, "LIMITLESS_T1_BIN": str(self.bin), "LIMITLESS_T1_MODEL": str(self.model)}
        self.assertEqual(self.row({}, env)["status"], doctor.LIVE)

    def test_broken_when_the_model_file_is_missing(self):
        r = self.row(self.full(t1_model=str(self.dir / "gone-9.gguf")))
        self.assertEqual(r["status"], doctor.MISSING)
        self.assertTrue(r["reason"].startswith("broken:"), r)

    def test_broken_when_the_binary_is_missing(self):
        r = self.row(self.full(t1_bin=str(self.dir / "gone-llama-9")))
        self.assertEqual((r["status"], r["reason"][:7]), (doctor.MISSING, "broken:"))

    def test_broken_when_the_runner_has_no_paths(self):
        for cfg in ({"t1_model_cmd": self.cmd}, {"t1_model_cmd": self.cmd, "t1_bin": str(self.bin)}):
            r = self.row(cfg)
            self.assertEqual((r["status"], r["reason"][:7]), (doctor.MISSING, "broken:"), cfg)

    def test_broken_when_the_command_does_not_exist(self):
        for cmd in (str(self.dir / "no-such-runner-5"), "no-such-runner-on-path-5",
                    f'"{sys.executable}" -I "{self.dir / "limitless-t1-local"}"'):
            r = self.row(self.full(t1_model_cmd=cmd))
            self.assertEqual((r["status"], r["reason"][:7]), (doctor.MISSING, "broken:"), cmd)

    def test_broken_when_the_command_cannot_be_parsed(self):
        r = self.row(self.full(t1_model_cmd='"unclosed'))
        self.assertEqual((r["status"], r["reason"][:7]), (doctor.MISSING, "broken:"))

    def test_another_command_that_exists_is_set(self):
        r = self.row({"t1_model_cmd": f'"{self.bin}" --flag-8'})
        self.assertEqual(r["status"], doctor.LIVE)

    def test_it_starts_no_process(self):
        boom = mock.Mock(side_effect=AssertionError("the doctor started a process"))
        with mock.patch("subprocess.Popen", boom), mock.patch("subprocess.run", boom):
            for cfg in ({}, self.full(), self.full(t1_model="/nope")):
                self.row(cfg)
        boom.assert_not_called()


class Report(Base):
    def test_after_the_delivery_row_not_strict_and_the_model_never_runs(self):
        st = self.dir / "state"
        st.mkdir()
        for f in (ROOT / "tests" / "fixtures" / "state").iterdir():
            (st / f.name).write_bytes(f.read_bytes())
        cfg = self.full(state=str(st))
        path = self.dir / "config.json"
        path.write_text(json.dumps(cfg))
        with mock.patch.dict(os.environ, {"LIMITLESS_CONFIG": str(path), "LIMITLESS_T1_CMD": self.cmd}):
            rows = doctor.report(cfg, NOW)
        self.assertFalse(self.mark.exists(), "a tool row ran the configured model")
        names = [r["name"] for r in rows]
        self.assertEqual(names.count(doctor.LOCAL_LABELER_ROW), 1)
        at = names.index(doctor.LOCAL_LABELER_ROW)
        self.assertEqual(names[at - 6:at], [doctor.UPTIME_ROW, doctor.DELIVERY_ROW, doctor.PUSH_SENDER_ROW,
                                            doctor.SENDER_CANDIDATES_ROW, doctor.PUSH_RECOVERY_ROW,
                                            doctor.SLEEP_MODE_ROW])
        self.assertEqual(names[at + 1], "tool " + doctor.manifest_tools()[0])
        self.assertEqual(rows[at]["status"], doctor.LIVE)
        self.assertNotIn("labeler", doctor.STRICT_KINDS)

    def test_rules_only_holds_the_local_model(self):
        with labeler.rules_only():
            self.assertIsNone(labeler.from_config(env={"LIMITLESS_T1_CMD": self.cmd}).cmd)
        self.assertIsNotNone(labeler.from_config(env={"LIMITLESS_T1_CMD": self.cmd}).cmd)


if __name__ == "__main__":
    unittest.main()
