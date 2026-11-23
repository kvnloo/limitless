"""pre_llm_call state card: <= 6 lines, privacy tier T2 (coarse labels, no raw numbers unless opted in),
cached until the window class or a state file mtime changes. Synthetic fixtures only."""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import card  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "state"
NOW = 1894708800.0
TODAY = date(2030, 1, 15)
H = 3600.0


def fixture_numbers():
    """Every digit sequence inside any number (or digit-bearing string) in the fixture files."""
    seqs = set()

    def walk(v):
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, (int, float, str)):
            seqs.update(re.findall(r"\d+", str(v)))
        elif isinstance(v, dict):
            for k, x in v.items():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    for f in FIX.iterdir():
        for ln in f.read_text().splitlines() if f.suffix in (".json", ".jsonl") else []:
            try:
                walk(json.loads(ln))
            except ValueError:
                pass
    return seqs


class Labels(unittest.TestCase):
    def test_sleep(self):
        self.assertEqual([card.sleep_label(h) for h in (5.3, 7.6, 9.6)], ["short", "ok", "long"])

    def test_readiness(self):
        self.assertEqual([card.readiness_label(v) for v in (27, 50, 71)], ["low", "moderate", "high"])


class CardT2(unittest.TestCase):
    def setUp(self):
        self.text = card.build(StateReader(FIX), NOW, TODAY)["text"]

    def test_at_most_six_lines(self):
        self.assertLessEqual(len(self.text.splitlines()), 6)

    def test_coarse_labels(self):
        self.assertIn("sleep short (proxy)", self.text)
        self.assertIn("readiness low (imported)", self.text)
        self.assertIn("window: peak", self.text)
        self.assertIn("not recording: anki, bike, scale", self.text)
        self.assertIn("habit this week: Lights down when wind-down starts; today Done", self.text)
        self.assertIn("asks waiting on you", self.text)

    def test_no_digits_from_the_fixture_reach_the_prompt(self):
        nums = fixture_numbers()
        self.assertIn("27", nums)  # sanity: the fixture really is full of numbers
        self.assertEqual([s for s in nums if s in self.text], [])
        self.assertEqual(re.findall(r"\d", self.text), [])

    def test_digits_in_free_text_are_masked(self):
        with tempfile.TemporaryDirectory() as d:
            st = Path(d) / "st"
            shutil.copytree(FIX, st)
            h = json.loads((st / "habit.json").read_text())
            h["habit"] = "Walk 15 minutes"
            (st / "habit.json").write_text(json.dumps(h))
            text = card.build(StateReader(st), NOW, TODAY)["text"]
        self.assertIn("Walk # minutes", text)
        self.assertEqual(re.findall(r"\d", text), [])

    def test_raw_numbers_only_when_opted_in(self):
        text = card.build(StateReader(FIX), NOW, TODAY, raw=True)["text"]
        self.assertIn("sleep short (proxy, 5.3 h)", text)
        self.assertIn("readiness low (imported, 27)", text)
        self.assertLessEqual(len(text.splitlines()), 6)

    def test_stale_digest_is_unknown_not_yesterdays_numbers(self):
        text = card.build(StateReader(FIX), NOW + 30 * H, date(2030, 1, 16))["text"]
        self.assertIn("sleep unknown", text)
        self.assertIn("readiness unknown", text)
        self.assertNotIn("short", text)

    def test_empty_state_dir_is_all_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            text = card.build(StateReader(Path(d)), NOW, TODAY)["text"]
        self.assertIn("window: unknown", text)
        self.assertIn("sleep unknown", text)
        self.assertIn("habit: none set this week", text)
        self.assertLessEqual(len(text.splitlines()), 6)


class Cache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Path(self.tmp.name) / "st"
        shutil.copytree(FIX, self.st)
        self.r = StateReader(self.st)
        self.c = card.CardCache()

    def tearDown(self):
        self.tmp.cleanup()

    def test_same_inputs_build_once(self):
        a = self.c.get(self.r, NOW, TODAY)
        b = self.c.get(self.r, NOW + 60, TODAY)
        self.assertEqual(a, b)
        self.assertEqual(self.c.builds, 1)

    def test_state_file_mtime_change_rebuilds(self):
        self.c.get(self.r, NOW, TODAY)
        p = self.st / "digests.jsonl"
        st = p.stat()
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
        self.c.get(self.r, NOW, TODAY)
        self.assertEqual(self.c.builds, 2)

    def test_window_class_change_rebuilds(self):
        self.c.get(self.r, NOW, TODAY)
        with open(self.st / "sleepmode.jsonl", "a") as f:  # same file content for the card...
            f.write('{"at": "2030-01-15T11:59:30Z", "on": true}\n')  # ...but now asleep
        text = self.c.get(self.r, NOW, TODAY)
        self.assertEqual(self.c.builds, 2)
        self.assertIn("window: asleep", text)

    def test_raw_flag_is_part_of_the_key(self):
        self.c.get(self.r, NOW, TODAY)
        self.c.get(self.r, NOW, TODAY, raw=True)
        self.assertEqual(self.c.builds, 2)


class Hook(unittest.TestCase):
    def test_returns_context_from_the_state_dir(self):
        hook = card.make_pre_llm_call(env={"LIMITLESS_STATE": str(FIX)}, clock=lambda: NOW,
                                      today=lambda: TODAY)
        out = hook(session_id="s", user_message="hi", conversation_history=[], is_first_turn=True,
                   model="m", platform="cli")
        self.assertEqual(set(out), {"context"})
        self.assertIn("readiness low (imported)", out["context"])
        self.assertEqual(re.findall(r"\d", out["context"]), [])

    def test_owner_message_label_reaches_the_prompt_without_a_digit(self):
        from unittest import mock
        from test_owner_messages import CONTENT, make_db
        with tempfile.TemporaryDirectory() as d:
            db = make_db(Path(d) / "owner.db", [("s-cli", "user", CONTENT + " 1234", NOW - 1234.5)])
            env = {"LIMITLESS_STATE": str(FIX), "LIMITLESS_OWNER_DBS": str(db),
                   "LIMITLESS_CONFIG": str(Path(d) / "none.json")}
            for mask in (True, False):
                with mock.patch.object(card, "MASK_DIGITS", mask):
                    out = card.make_pre_llm_call(env=env, clock=lambda: NOW, today=lambda: TODAY)()
                self.assertIn("messages: wrote recently", out["context"])
                self.assertEqual(re.findall(r"\d", out["context"]), [], mask)
                self.assertNotIn("synthetic", out["context"])

    def test_raw_opt_in_via_env(self):
        hook = card.make_pre_llm_call(env={"LIMITLESS_STATE": str(FIX), "LIMITLESS_RAW_IN_PROMPT": "1"},
                                      clock=lambda: NOW, today=lambda: TODAY)
        self.assertIn("27", hook()["context"])

    def test_no_state_dir_injects_nothing(self):
        hook = card.make_pre_llm_call(env={"LIMITLESS_STATE": "/definitely/not/here"}, clock=lambda: NOW,
                                      today=lambda: TODAY)
        self.assertIsNone(hook(user_message="hi"))


class StateTool(unittest.TestCase):
    def test_envelope_with_card_and_items(self):
        env = card.state(StateReader(FIX), NOW, TODAY)
        self.assertEqual(env["modality"], "proxy")  # weakest of its parts
        self.assertEqual(env["age_h"], 4.8)          # the digest is from 07:12Z
        v = env["value"]
        self.assertLessEqual(len(v["card"]), 6)
        self.assertEqual(v["items"]["sleep"]["value"], "short")
        self.assertEqual(v["items"]["readiness"]["value"], "low")
        self.assertNotIn("raw", v["items"]["sleep"])
        self.assertEqual(re.findall(r"\d", json.dumps(v["card"])), [])

    def test_raw_items_when_opted_in(self):
        v = card.state(StateReader(FIX), NOW, TODAY, raw=True)["value"]
        self.assertEqual(v["items"]["sleep"]["raw"], 5.3)

    def test_missing_dir(self):
        env = card.state(StateReader(Path("/definitely/not/here")), NOW, TODAY)
        self.assertIsNone(env["value"])
        self.assertIn("state dir", env["reason"])


if __name__ == "__main__":
    unittest.main()
