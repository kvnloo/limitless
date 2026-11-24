"""bin/limitless-t1-local: a CPU-only runner for a llama.cpp-style CLI that meets LocalModelLabeler's contract.

A fake llama binary written into a temp dir stands in for the model: no download, no network, no real model
file (the model path is a made-up empty `tiny-model.gguf`). Every child gets env=child_env(...).
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from hermetic_env import child_env

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import labeler, t1_local  # noqa: E402
from limitless.labeler import LocalModelLabeler  # noqa: E402

WRAPPER = ROOT / "bin" / "limitless-t1-local"
PROMPT = labeler.PROMPT.format(kind="sleep_h", allowed="short, ok, long", value=5.3)

FAKE = """#!{python} -I
import json, os, sys, time
args = sys.argv[1:]
log = os.environ.get("FAKE_LOG")
if log:
    with open(log, "w") as f:
        json.dump({{"argv": args, "cuda": os.environ.get("CUDA_VISIBLE_DEVICES"),
                   "hip": os.environ.get("HIP_VISIBLE_DEVICES"), "pid": os.getpid()}}, f)
prompt = args[args.index("-p") + 1] if "-p" in args else ""
mode = os.environ.get("FAKE_MODE", "ok")
if mode == "ok":
    print("ok")
elif mode == "chatty":
    print("Sure. The sleep was ok, I think.")
elif mode == "echo":
    print(prompt + " long")
elif mode == "two":
    print("long, or maybe short")
elif mode == "junk":
    print("banana")
elif mode == "digits":
    print("7 hours, so ok")
elif mode == "fail":
    print("ok"); sys.exit(3)
elif mode == "slow":
    sys.stdout.flush(); time.sleep(30); print("ok")
elif mode == "quiet":
    print("quiet for a while")
"""


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.work = self.dir / "work"   # the wrapper's cwd and HOME: nothing may appear here
        self.work.mkdir()
        self.bin = self.dir / "fake-llama"
        self.bin.write_text(FAKE.format(python=sys.executable))
        self.bin.chmod(0o755)
        self.model = self.dir / "tiny-model.gguf"
        self.model.write_bytes(b"")
        self.log = self.dir / "fake.json"
        self.cfg = self.dir / "config.json"

    def env(self, mode="ok", **extra):
        base = {"PATH": os.environ.get("PATH", ""), "HOME": str(self.work), "FAKE_MODE": mode,
                "FAKE_LOG": str(self.log), "LIMITLESS_T1_BIN": str(self.bin),
                "LIMITLESS_T1_MODEL": str(self.model), "CUDA_VISIBLE_DEVICES": "", "HIP_VISIBLE_DEVICES": ""}
        base.update(extra)
        return {k: v for k, v in base.items() if v is not None}

    def run_wrapper(self, mode="ok", prompt=PROMPT, timeout=60, **extra):
        return subprocess.run([sys.executable, "-I", str(WRAPPER)], input=prompt, capture_output=True, text=True,
                              cwd=self.work, timeout=timeout, env=child_env(self.env(mode, **extra)))

    def fake_saw(self):
        return json.loads(self.log.read_text())


class Answers(Base):
    def test_an_allowed_word_is_printed_alone(self):
        r = self.run_wrapper("ok")
        self.assertEqual((r.returncode, r.stdout), (0, "ok\n"), r.stderr)

    def test_the_word_is_found_inside_chatty_output(self):
        self.assertEqual(self.run_wrapper("chatty").stdout, "ok\n")

    def test_of_two_allowed_words_the_first_in_the_output_wins(self):
        self.assertEqual(self.run_wrapper("two").stdout, "long\n")

    def test_an_echoed_prompt_is_not_read_as_the_answer(self):
        r = self.run_wrapper("echo")
        self.assertEqual(r.stdout, "long\n")
        self.assertNotIn("Label one", r.stdout + r.stderr)

    def test_a_phrase_from_the_prompts_own_list(self):
        prompt = labeler.PROMPT.format(kind="owner_message_age_h", allowed="wrote recently, quiet for a while",
                                       value=3.5)
        self.assertEqual(self.run_wrapper("quiet", prompt=prompt).stdout, "quiet for a while\n")


class NoAnswer(Base):
    def check_none(self, r):
        self.assertEqual((r.returncode, r.stdout), (1, ""), r.stderr)
        self.assertNotRegex(r.stdout + r.stderr, r"\d")
        self.assertNotIn("Label one", r.stdout + r.stderr)

    def test_junk(self):
        self.check_none(self.run_wrapper("junk"))

    def test_any_digit_in_the_output_is_doubt(self):
        self.check_none(self.run_wrapper("digits"))

    def test_a_non_zero_exit(self):
        self.check_none(self.run_wrapper("fail"))

    def test_a_missing_binary(self):
        self.check_none(self.run_wrapper(LIMITLESS_T1_BIN=str(self.dir / "no-such-llama")))

    def test_a_missing_model_file(self):
        self.check_none(self.run_wrapper(LIMITLESS_T1_MODEL=str(self.dir / "no-such-model.gguf")))
        self.assertFalse(self.log.exists())   # the binary never ran

    def test_no_default_paths(self):
        self.check_none(self.run_wrapper(LIMITLESS_T1_BIN=None))
        self.check_none(self.run_wrapper(LIMITLESS_T1_MODEL=None))
        self.assertFalse(self.log.exists())

    def test_a_prompt_without_an_allowed_list(self):
        self.check_none(self.run_wrapper("ok", prompt="say something\n"))
        self.check_none(self.run_wrapper("ok", prompt=""))

    def test_an_allowed_list_with_a_digit_is_never_printed(self):
        prompt = labeler.PROMPT.format(kind="x", allowed="ok7, short", value=1)
        r = self.run_wrapper("ok", prompt=prompt)
        self.assertEqual(r.stdout, "")

    def test_a_timeout_kills_the_model_and_stays_under_the_labelers(self):
        self.cfg.write_text(json.dumps({"t1_timeout_s": 0.5}))
        t = time.monotonic()
        r = self.run_wrapper("slow", LIMITLESS_CONFIG=str(self.cfg))
        self.assertLess(time.monotonic() - t, 10)
        self.check_none(r)
        pid = self.fake_saw()["pid"]
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            self.fail("the fake model is still running after the timeout")

    def test_the_default_timeout_is_below_the_labelers(self):
        self.assertLess(t1_local.TIMEOUT_S, labeler.TIMEOUT_S)
        self.assertEqual(t1_local.timeout_s({"t1_timeout_s": 60}), t1_local.TIMEOUT_S)  # never above
        self.assertEqual(t1_local.timeout_s({"t1_timeout_s": 1.5}), 1.5)
        for bad in (0, -1, "2", True, None, float("nan")):
            self.assertEqual(t1_local.timeout_s({"t1_timeout_s": bad}), t1_local.TIMEOUT_S, bad)


class CpuOnly(Base):
    def test_refuses_to_start_with_a_visible_gpu(self):
        for key in ("CUDA_VISIBLE_DEVICES", "HIP_VISIBLE_DEVICES"):
            r = self.run_wrapper("ok", **{key: "0"})
            self.assertNotEqual(r.returncode, 0)
            self.assertEqual(r.stdout, "")
            self.assertIn("GPU", r.stderr)
        self.assertFalse(self.log.exists())   # the binary never ran

    def test_unset_gpu_vars_are_fine(self):
        r = self.run_wrapper("ok", CUDA_VISIBLE_DEVICES=None, HIP_VISIBLE_DEVICES=None)
        self.assertEqual(r.stdout, "ok\n")

    def test_cpu_flags_greedy_and_a_short_token_cap(self):
        self.run_wrapper("ok")
        saw = self.fake_saw()
        argv = saw["argv"]
        self.assertEqual(argv[argv.index("-m") + 1], str(self.model))
        self.assertEqual(argv[argv.index("-ngl") + 1], "0")
        self.assertEqual(argv[argv.index("-t") + 1], "2")
        self.assertEqual(argv[argv.index("--temp") + 1], "0")
        self.assertLessEqual(int(argv[argv.index("-n") + 1]), 16)
        self.assertEqual(argv[argv.index("-p") + 1], PROMPT)
        self.assertEqual((saw["cuda"], saw["hip"]), ("", ""))

    def test_threads_and_paths_from_config(self):
        self.cfg.write_text(json.dumps({"t1_bin": str(self.bin), "t1_model": str(self.model), "t1_threads": 4}))
        r = self.run_wrapper("ok", LIMITLESS_CONFIG=str(self.cfg), LIMITLESS_T1_BIN=None, LIMITLESS_T1_MODEL=None)
        self.assertEqual(r.stdout, "ok\n", r.stderr)
        argv = self.fake_saw()["argv"]
        self.assertEqual(argv[argv.index("-t") + 1], "4")

    def test_bad_threads_fall_back_to_two(self):
        for bad in (0, -3, "4", True, 2.5, None):
            self.assertEqual(t1_local.threads({"t1_threads": bad}), 2, bad)
        self.assertEqual(t1_local.threads({}), 2)

    def test_it_never_writes_a_file(self):
        before = sorted(p.name for p in ROOT.rglob("*") if "__pycache__" in p.parts)
        for mode in ("ok", "junk", "fail"):
            self.run_wrapper(mode)
        self.assertEqual(list(self.work.iterdir()), [])
        self.assertEqual(sorted(p.name for p in ROOT.rglob("*") if "__pycache__" in p.parts), before)


class ThroughTheLabeler(Base):
    """End to end: LocalModelLabeler with LIMITLESS_T1_CMD pointing at the wrapper."""

    def lab(self, mode, **extra):
        cmd = f'"{sys.executable}" -I "{WRAPPER}"'
        env = {k: v for k, v in self.env(mode, **extra).items() if k != "HOME"}
        with mock.patch.dict(os.environ, env):
            for k in [k for k, v in extra.items() if v is None]:
                os.environ.pop(k, None)
            return labeler.from_config(env={"LIMITLESS_T1_CMD": cmd}).label("sleep_h", 5.3, "proxy")

    def test_an_allowed_word_wins(self):
        self.assertEqual(self.lab("ok"), {"label": "ok", "tier": "T1", "modality": "proxy"})  # the rule says short

    def test_junk_digits_and_failure_fall_back_to_the_rule(self):
        for mode in ("junk", "digits", "fail"):
            self.assertEqual(self.lab(mode)["label"], "short", mode)

    def test_a_timeout_falls_back_to_the_rule(self):
        self.cfg.write_text(json.dumps({"t1_timeout_s": 0.5}))
        self.assertEqual(self.lab("slow", LIMITLESS_CONFIG=str(self.cfg))["label"], "short")

    def test_the_default_timeout_beats_the_labelers(self):
        t = time.monotonic()
        self.assertEqual(self.lab("slow")["label"], "short")
        self.assertLess(time.monotonic() - t, labeler.TIMEOUT_S)

    def test_a_missing_binary_falls_back_to_the_rule(self):
        self.assertEqual(self.lab("ok", LIMITLESS_T1_BIN=str(self.dir / "no-such-llama"))["label"], "short")

    def test_the_labeler_still_never_asks_for_a_missing_value(self):
        cmd = f'"{sys.executable}" -I "{WRAPPER}"'
        with mock.patch.dict(os.environ, {k: v for k, v in self.env("ok").items() if k != "HOME"}):
            out = LocalModelLabeler(cmd).label("sleep_h", None, "proxy")
        self.assertEqual(out["label"], "unknown")
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
