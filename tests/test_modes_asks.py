"""focused mode holds non-urgent asks exactly like a focus block (asks.py, hold_asks); no new gate. Synthetic only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import asks, decision_window, modes, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures" / "state"
QUEUE = HERE / "fixtures" / "asks" / "asks.jsonl"
GLIDE = HERE / "fixtures" / "glide"
NOW = 1894708800.0  # fixture clock: five hours after the fixture wake event (peak)
COUNTS = ("deliver", "hold", "fold")
PEAK = decision_window.WindowState(cls="peak", since="wake", source="test")
FOCUS = decision_window.WindowState(cls="peak", since="focus_start", source="test", hold_asks=True)


class Apply(unittest.TestCase):
    def rows(self):
        return [json.loads(ln) for ln in QUEUE.read_text().splitlines()]

    def test_focused_plans_exactly_like_a_focus_block(self):
        rows = self.rows()
        self.assertEqual(asks.plan(rows, modes.apply(PEAK, "focused")), asks.plan(rows, FOCUS))
        for env in ({"value": "peak", "since": "wake"}, {"value": "trough"}, {"value": "unknown"}, None):
            self.assertEqual([a for _, a, _ in asks.plan(rows, modes.apply(env, "focused"))], ["hold"] * len(rows))

    def test_focused_lets_an_urgent_ask_through(self):
        rows = self.rows() + [{"id": "u", "kind": "decision", "title": "a synthetic urgent choice", "urgent": True}]
        got = asks.plan(rows, modes.apply(PEAK, "focused"))
        self.assertEqual(got[-1][1], "deliver")
        self.assertEqual([a for _, a, _ in got[:-1]], ["hold"] * (len(rows) - 1))

    def test_other_modes_and_none_change_nothing(self):
        rows = self.rows()
        for m in ("brainstorm", "pm", "copilot", "none", "off", "sprint", None):
            for w in (PEAK, {"value": "peak", "since": "wake"}, {"value": "asleep"}, None, FOCUS):
                self.assertIs(modes.apply(w, m), w)
                self.assertEqual(asks.plan(rows, modes.apply(w, m)), asks.plan(rows, w))

    def test_asleep_stays_asleep(self):
        for w in ({"value": "asleep"}, decision_window.WindowState(cls="asleep")):
            self.assertIs(modes.apply(w, "focused"), w)


class WindowTool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.st = Path(self.tmp.name) / "state"
        shutil.copytree(FIX, self.st)
        self.env = {"LIMITLESS_CONFIG": str(Path(self.tmp.name) / "none.json"), "LIMITLESS_ASKS": str(QUEUE)}

    def asks_now(self, **kw):
        a = tools.window(StateReader(self.st), NOW, env=dict(self.env, **kw))["asks"]
        return {k: a[k] for k in COUNTS}, a["label"]["label"]

    def test_no_mode_is_as_before(self):
        self.assertEqual(self.asks_now(), ({"deliver": 2, "hold": 1, "fold": 1}, "one decision ready"))

    def test_focused_holds_like_the_glide_focus_block(self):
        glide = self.asks_now(LIMITLESS_GLIDE_ATTENTION=str(GLIDE / "focus-block.json"))
        modes.save(self.st, "focused")
        self.assertEqual(self.asks_now(), glide)
        self.assertEqual(glide, ({"deliver": 0, "hold": 4, "fold": 0}, "decisions waiting"))

    def test_off_ends_the_hold(self):
        before = self.asks_now()
        modes.save(self.st, "focused")
        modes.save(self.st, "off")
        self.assertEqual(self.asks_now(), before)

    def test_presentation_modes_leave_the_plan_alone(self):
        before = self.asks_now()
        for m in ("brainstorm", "pm", "copilot"):
            modes.save(self.st, m)
            self.assertEqual(self.asks_now(), before, m)

    def test_the_queue_is_never_written(self):
        before, mtime = QUEUE.read_bytes(), QUEUE.stat().st_mtime_ns
        modes.save(self.st, "focused")
        self.asks_now()
        self.assertEqual((QUEUE.read_bytes(), QUEUE.stat().st_mtime_ns), (before, mtime))


if __name__ == "__main__":
    unittest.main()
