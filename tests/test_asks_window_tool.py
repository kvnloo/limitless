"""limitless_window gains asks: {deliver, hold, fold} and a digit-free T1 label. Synthetic fixtures only."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures" / "state"
QUEUE = HERE / "fixtures" / "asks" / "asks.jsonl"
GLIDE = HERE / "fixtures" / "glide"
NOW = 1894708800.0  # fixture clock: five hours after the fixture wake event (peak)
LABELS = ("one decision ready", "decisions waiting", "nothing waiting")


class WindowAsks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def env(self, **kw):
        return dict({"LIMITLESS_CONFIG": str(self.dir / "no-config.json")}, **kw)

    def window(self, **kw):
        return tools.window(StateReader(FIX), NOW, env=self.env(**kw))

    def test_window_value_is_unchanged_and_asks_are_counted(self):
        res = self.window(LIMITLESS_ASKS=str(QUEUE))
        self.assertEqual(res["value"], "peak")
        a = res["asks"]
        self.assertEqual({k: a[k] for k in ("deliver", "hold", "fold")}, {"deliver": 2, "hold": 1, "fold": 1})
        self.assertEqual(a["label"], {"label": "one decision ready", "tier": "T1", "modality": None})

    def test_a_decision_delivered_since_the_wake_event_holds_the_rest(self):
        q = self.dir / "asks.jsonl"
        extra = {"id": "x", "kind": "decision", "title": "an earlier synthetic choice",
                 "at": "2030-01-15T07:30:00Z", "delivered_at": "2030-01-15T10:30:00Z"}
        q.write_text(QUEUE.read_text() + json.dumps(extra) + "\n")
        a = self.window(LIMITLESS_ASKS=str(q))["asks"]
        self.assertEqual({k: a[k] for k in ("deliver", "hold", "fold")}, {"deliver": 1, "hold": 2, "fold": 1})
        self.assertEqual(a["label"]["label"], "decisions waiting")

    def test_a_focus_block_holds_every_ask(self):
        a = self.window(LIMITLESS_ASKS=str(QUEUE), LIMITLESS_GLIDE_ATTENTION=str(GLIDE / "focus-block.json"))["asks"]
        self.assertEqual({k: a[k] for k in ("deliver", "hold", "fold")}, {"deliver": 0, "hold": 4, "fold": 0})
        self.assertEqual(a["label"]["label"], "decisions waiting")

    def test_no_queue_or_a_broken_one_is_nothing_waiting(self):
        bad = self.dir / "bad.jsonl"
        bad.write_bytes(b"\xff{not json")
        for kw in ({}, {"LIMITLESS_ASKS": str(bad)}, {"LIMITLESS_ASKS": str(self.dir / "absent.jsonl")}):
            a = self.window(**kw)["asks"]
            self.assertEqual({k: a[k] for k in ("deliver", "hold", "fold")}, {"deliver": 0, "hold": 0, "fold": 0})
            self.assertEqual(a["label"]["label"], "nothing waiting")

    def test_only_fyi_and_anytime_asks_are_nothing_waiting(self):
        q = self.dir / "asks.jsonl"
        rows = [json.loads(ln) for ln in QUEUE.read_text().splitlines()]
        q.write_text("".join(json.dumps(r) + "\n" for r in rows if r.get("effort") != "deep"
                             and r["kind"] != "decision"))
        self.assertEqual(self.window(LIMITLESS_ASKS=str(q))["asks"]["label"]["label"], "nothing waiting")

    def test_label_is_digit_free_and_one_of_three(self):
        for kw in ({}, {"LIMITLESS_ASKS": str(QUEUE)},
                   {"LIMITLESS_ASKS": str(QUEUE), "LIMITLESS_GLIDE_ATTENTION": str(GLIDE / "focus-block.json")}):
            word = self.window(**kw)["asks"]["label"]["label"]
            self.assertIn(word, LABELS)
            self.assertFalse(any(c.isdigit() for c in word))

    def test_the_queue_is_never_written(self):
        before, mtime = QUEUE.read_bytes(), QUEUE.stat().st_mtime_ns
        self.window(LIMITLESS_ASKS=str(QUEUE))
        self.assertEqual((QUEUE.read_bytes(), QUEUE.stat().st_mtime_ns), (before, mtime))

    def test_the_asks_view_carries_no_titles_or_card_ids(self):
        text = json.dumps(self.window(LIMITLESS_ASKS=str(QUEUE))["asks"])
        self.assertNotIn("synthetic", text)
        self.assertNotRegex(text, r"\bt_[0-9a-f]{6,12}\b")


class ThroughThePlugin(unittest.TestCase):
    def test_limitless_window_handler_returns_asks(self):
        from test_plugin import FakeCtx, load_plugin
        ctx = FakeCtx()
        load_plugin().register(ctx)
        with tempfile.TemporaryDirectory() as d:
            env = {"LIMITLESS_STATE": str(FIX), "LIMITLESS_ASKS": str(QUEUE),
                   "LIMITLESS_CONFIG": str(Path(d) / "none.json")}
            with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(time, "time", return_value=NOW):
                res = json.loads(ctx.tools["limitless_window"]["handler"]({}, task_id="t", session_id="s"))
        self.assertEqual(res["value"], "peak")
        self.assertEqual(res["asks"]["label"]["label"], "one decision ready")
        self.assertIn("asks", ctx.tools["limitless_window"]["schema"]["description"])


if __name__ == "__main__":
    unittest.main()
