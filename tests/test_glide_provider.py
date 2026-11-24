"""GlideProvider: Glide's attention.json -> WindowState. Synthetic fixtures only (tests/fixtures/glide/)."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import decision_window as dw  # noqa: E402
from limitless import glide_provider as gp  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "glide"
ANCHOR = 1894708800.0  # every fixture's event happens at this instant
M, H = 60.0, 3600.0


def shifted(name, delta):
    """The fixture with every Glide timestamp moved by `delta` seconds."""
    data = json.loads((FIX / name).read_text())
    if data.get("block"):
        data["block"]["start"] += delta
        data["block"]["end"] += delta
    for item in data.get("queue", []):
        item["at"] += delta
    if data.get("resume"):
        data["resume"]["saved"] += delta
    return data


class Tmp(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.addCleanup(self._d.cleanup)

    def write(self, data):
        p = Path(self._d.name) / "attention.json"
        p.write_text(json.dumps(data))
        return str(p)

    def state(self, name=None, now=ANCHOR, data=None, **kw):
        path = str(FIX / name) if name else self.write(data)
        return gp.GlideProvider(path, now=now, **kw).current()


class FocusBlock(Tmp):
    def test_active_block_is_peak_since_focus_start_with_asks_held(self):
        st = self.state("focus-block.json", now=ANCHOR + 10 * M)
        self.assertEqual((st.cls, st.since, st.source), ("peak", "focus_start", "glide"))
        self.assertTrue(st.hold_asks)

    def test_block_that_has_ended_is_unknown(self):
        st = self.state("focus-block.json", now=ANCHOR + 51 * M)
        self.assertEqual(st.cls, "unknown")
        self.assertFalse(st.hold_asks)

    def test_block_that_starts_after_now_is_unknown(self):
        self.assertEqual(self.state("focus-block.json", now=ANCHOR - M).cls, "unknown")

    def test_active_block_wins_over_an_earlier_wind_down(self):
        data = shifted("wind-down.json", -H)
        data["block"] = {"start": ANCHOR, "end": ANCHOR + 50 * M, "minutes": 50}
        self.assertEqual(self.state(data=data, now=ANCHOR + M).cls, "peak")


class WindDown(Tmp):
    def test_wind_down_nudge_opens_wind_down(self):
        st = self.state("wind-down.json", now=ANCHOR + 20 * M)
        self.assertEqual((st.cls, st.since, st.source), ("wind_down", "wind_down", "glide"))
        self.assertFalse(st.hold_asks)

    def test_stale_wind_down_is_unknown(self):
        now = ANCHOR + gp.WIND_DOWN_MAX_S + 1
        self.assertEqual(self.state("wind-down.json", now=now).cls, "unknown")

    def test_max_age_is_a_parameter(self):
        self.assertEqual(self.state("wind-down.json", now=ANCHOR + 2 * H, wind_down_max_s=H).cls, "unknown")
        self.assertEqual(self.state("wind-down.json", now=ANCHOR + 2 * H, wind_down_max_s=3 * H).cls, "wind_down")

    def test_wind_down_saved_after_now_is_unknown(self):
        self.assertEqual(self.state("wind-down.json", now=ANCHOR - M).cls, "unknown")


class Unknown(Tmp):
    def test_idle_glide_is_unknown(self):
        self.assertEqual(self.state("idle.json").cls, "unknown")

    def test_missing_file_is_unknown(self):
        self.assertEqual(gp.GlideProvider(str(FIX / "nope.json"), now=ANCHOR).current().cls, "unknown")

    def test_malformed_file_is_unknown(self):
        self.assertEqual(self.state("malformed.json").cls, "unknown")

    def test_wrong_shapes_are_unknown_not_errors(self):
        bad = [[], "x", {"block": "x"}, {"block": {"start": "a", "end": ANCHOR + H}},
               {"block": {"start": True, "end": ANCHOR + H}}, {"resume": {"saved": "yesterday"}},
               {"resume": ["x"]}, {"block": None, "resume": None}]
        for data in bad:
            self.assertEqual(self.state(data=data).cls, "unknown", data)

    def test_unknown_has_zero_confidence_so_decide_holds(self):
        st = self.state("idle.json")
        self.assertEqual(st.confidence, 0.0)
        self.assertEqual(dw.decide("wind_down", st, budget_left=1, asleep=False).action, "hold")


class NoClock(Tmp):
    def test_without_now_it_is_unknown(self):
        self.assertEqual(gp.GlideProvider(str(FIX / "wind-down.json")).current().cls, "unknown")

    def test_now_may_be_a_callable(self):
        st = gp.GlideProvider(str(FIX / "wind-down.json"), now=lambda: ANCHOR + M).current()
        self.assertEqual(st.cls, "wind_down")

    def test_never_reads_the_clock(self):
        with mock.patch("time.time", side_effect=AssertionError("clock read")):
            self.assertEqual(self.state("wind-down.json", now=ANCHOR + M).cls, "wind_down")

    def test_class_is_the_same_at_every_hour_of_the_day(self):
        for hour in range(24):
            d = hour * H
            self.assertEqual(self.state(data=shifted("wind-down.json", d), now=ANCHOR + d + M).cls, "wind_down")
            self.assertEqual(self.state(data=shifted("focus-block.json", d), now=ANCHOR + d + M).cls, "peak")
            self.assertEqual(self.state(data=shifted("idle.json", d), now=ANCHOR + d + M).cls, "unknown")

    def test_is_a_window_provider(self):
        self.assertIsInstance(gp.GlideProvider(str(FIX / "idle.json"), now=ANCHOR), dw.WindowProvider)


class HeldAsks(unittest.TestCase):
    def focus(self):
        return gp.GlideProvider(str(FIX / "focus-block.json"), now=ANCHOR + M).current()

    def test_focus_block_holds_every_non_critical_job(self):
        for job in dw.WINDOW_CLASSES:
            d = dw.decide(job, self.focus(), budget_left=1, asleep=False)
            self.assertEqual(d.action, "hold", job)
            self.assertIn("focus", d.reason)

    def test_critical_still_delivers_during_a_block(self):
        self.assertEqual(dw.decide("peak", self.focus(), budget_left=1, asleep=False, critical=True).action,
                         "deliver")


class FromConfig(unittest.TestCase):
    def test_env_path_wins(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "config.json"
            cfg.write_text(json.dumps({"glide_attention": "from-config.json"}))
            env = {"LIMITLESS_GLIDE_ATTENTION": "from-env.json", "LIMITLESS_CONFIG": str(cfg)}
            self.assertEqual(gp.GlideProvider.from_config(env=env, home=Path(d), now=ANCHOR).path, "from-env.json")

    def test_config_key(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d) / "config.json"
            cfg.write_text(json.dumps({"glide_attention": "from-config.json"}))
            p = gp.GlideProvider.from_config(env={"LIMITLESS_CONFIG": str(cfg)}, home=Path(d), now=ANCHOR)
            self.assertEqual(p.path, "from-config.json")

    def test_not_configured_is_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(gp.GlideProvider.from_config(env={}, home=Path(d), now=ANCHOR))


if __name__ == "__main__":
    unittest.main()
