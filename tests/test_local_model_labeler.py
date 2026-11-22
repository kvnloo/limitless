"""LocalModelLabeler: an optional small LOCAL model makes the T1 label; any error, timeout or out-of-set
answer falls back to the rule label. A fake CLI script stands in for the model: no download, no network."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import labeler  # noqa: E402
from limitless.labeler import LocalModelLabeler  # noqa: E402

FAKE = """import os, sys, time
mode = sys.argv[1]
prompt = sys.stdin.read()
log = os.environ.get("FAKE_LOG")
if log:
    with open(log, "a") as f:
        f.write(prompt + "\\n---\\n")
if mode == "ok":
    print("ok")
elif mode == "padded":
    print("  Long \\n")
elif mode == "digits":
    print("7 hours")
elif mode == "chatty":
    print("I think the answer is ok")
elif mode == "fail":
    print("ok"); sys.exit(2)
elif mode == "slow":
    time.sleep(10); print("ok")
elif mode == "gpu":
    print("ok" if os.environ.get("CUDA_VISIBLE_DEVICES") == "" else "long")
elif mode == "missing":
    print("missing")
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.script = self.dir / "fake_model.py"
        self.script.write_text(FAKE)
        self.log = self.dir / "prompts.log"

    def tearDown(self):
        self.tmp.cleanup()

    def cmd(self, mode):
        return [sys.executable, "-I", str(self.script), mode]

    def lab(self, mode, kind="sleep_h", value=5.3, modality="proxy", **kw):
        return LocalModelLabeler(self.cmd(mode), **kw).label(kind, value, modality)


class ModelAnswer(Base):
    def test_an_in_set_answer_is_the_label(self):
        self.assertEqual(self.lab("ok"), {"label": "ok", "tier": "T1", "modality": "proxy"})  # rule says short

    def test_whitespace_and_case_are_trimmed(self):
        self.assertEqual(self.lab("padded")["label"], "long")

    def test_it_is_callable_like_label(self):
        self.assertEqual(LocalModelLabeler(self.cmd("ok"))("sleep_h", 5.3, "proxy")["label"], "ok")

    def test_the_command_can_be_one_string(self):
        cmd = " ".join(f'"{c}"' for c in self.cmd("ok"))
        self.assertEqual(LocalModelLabeler(cmd).label("sleep_h", 5.3, "proxy")["label"], "ok")

    def test_a_fixed_prompt_on_stdin_names_the_allowed_set(self):
        os.environ["FAKE_LOG"] = str(self.log)
        try:
            self.lab("ok")
            self.lab("ok", kind="readiness", value=27, modality="imported")
        finally:
            del os.environ["FAKE_LOG"]
        p1, p2 = self.log.read_text().split("\n---\n")[:2]
        self.assertEqual(p1, labeler.PROMPT.format(kind="sleep_h", allowed="short, ok, long", value=5.3))
        self.assertIn("short, ok, long", p1)
        self.assertIn("low, moderate, high", p2)

    def test_child_sees_no_gpu(self):
        self.assertEqual(self.lab("gpu")["label"], "ok")


class FallsBackToTheRule(Base):
    def test_out_of_set_answer(self):
        self.assertEqual(self.lab("digits")["label"], "short")
        self.assertEqual(self.lab("chatty")["label"], "short")

    def test_an_answer_from_another_kinds_set(self):
        self.assertEqual(self.lab("ok", kind="readiness", value=27, modality="imported")["label"], "low")

    def test_nonzero_exit(self):
        self.assertEqual(self.lab("fail")["label"], "short")

    def test_timeout(self):
        t = time.monotonic()
        self.assertEqual(self.lab("slow", timeout_s=0.5)["label"], "short")
        self.assertLess(time.monotonic() - t, 5)

    def test_command_not_found(self):
        out = LocalModelLabeler([str(self.dir / "no-such-model")]).label("sleep_h", 5.3, "proxy")
        self.assertEqual(out["label"], "short")

    def test_no_command_is_the_rule_labeler(self):
        self.assertEqual(LocalModelLabeler(None).label("sleep_h", 7.6, "proxy"), labeler.label("sleep_h", 7.6, "proxy"))
        self.assertEqual(LocalModelLabeler("  ").label("sleep_h", 7.6, "proxy")["label"], "ok")

    def test_missing_value_never_asks_the_model(self):
        os.environ["FAKE_LOG"] = str(self.log)
        try:
            self.assertEqual(self.lab("ok", value=None)["label"], "unknown")
            self.assertEqual(self.lab("ok", kind="hrv_ms", value=38.6)["label"], "unknown")
            self.assertEqual(self.lab("ok", kind="age_h", value=None)["label"], "missing")
        finally:
            del os.environ["FAKE_LOG"]
        self.assertFalse(self.log.exists())

    def test_the_model_cannot_answer_missing_for_a_present_value(self):
        self.assertEqual(self.lab("missing", kind="age_h", value=3.7, modality="measured")["label"], "fresh")


class Config(Base):
    def test_none_by_default(self):
        with tempfile.TemporaryDirectory() as home:
            self.assertIsNone(labeler.t1_model_cmd(env={}, home=Path(home)))
            lab = labeler.from_config(env={}, home=Path(home))
        self.assertIsNone(lab.cmd)

    def test_env_wins_over_config(self):
        cfg = self.dir / "config.json"
        cfg.write_text(json.dumps({"t1_model_cmd": "from-config"}))
        env = {"LIMITLESS_CONFIG": str(cfg)}
        self.assertEqual(labeler.t1_model_cmd(env=env), "from-config")
        self.assertEqual(labeler.t1_model_cmd(env=dict(env, LIMITLESS_T1_CMD="from-env")), "from-env")

    def test_from_config_runs_the_configured_cli(self):
        cmd = " ".join(f'"{c}"' for c in self.cmd("ok"))
        self.assertEqual(labeler.from_config(env={"LIMITLESS_T1_CMD": cmd}).label("sleep_h", 5.3, "proxy")["label"],
                         "ok")

    def test_a_non_string_config_value_is_ignored(self):
        cfg = self.dir / "config.json"
        cfg.write_text(json.dumps({"t1_model_cmd": ["a", "b"]}))
        self.assertIsNone(labeler.t1_model_cmd(env={"LIMITLESS_CONFIG": str(cfg)}))


if __name__ == "__main__":
    unittest.main()
