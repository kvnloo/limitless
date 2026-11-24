"""limitless_sleep's regularity field: how steady sleep times have been, in words; minutes only under the opt-in.

Synthetic rows only. The default value gains ``regularity`` (regularity.label's T1 words, source named); the raw
opt-in adds ``regularity_min`` (per-source spreads and drift in minutes, never a clock time).
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import plugin, regularity  # noqa: E402
from test_plugin import FakeCtx  # noqa: E402
from test_sleep_tool import NOW, TODAY, Base, local, screen, wear, without_counts_and_ages  # noqa: E402

H = 3600


def timed(ago, start_h=23.0, hours=8.0):
    s = local(TODAY - timedelta(days=ago), start_h)
    return dict(wear(ago, hours), start=s, end=s + hours * H)


class Field(Base):
    def test_default_value_carries_the_regularity_words(self):
        self.configure()
        self.wearable([timed(a, 23 + (a % 2) / 4) for a in range(1, 11)])
        out = self.tool()
        self.assertEqual(out["value"]["regularity"], "wearable: sleep times steady")
        self.assertNotIn("regularity_min", out["value"])
        self.assertEqual(re.findall(r"\d", json.dumps(without_counts_and_ages(out))), [])

    def test_the_phone_estimate_stands_in_and_drift_is_named(self):
        self.phone(*(screen(a, 22 + (8 - a) * 0.4, 7) for a in range(1, 8)))     # later each night
        self.assertEqual(self.tool()["value"]["regularity"], "phone estimate: drifting later")

    def test_wearable_rows_without_times_are_unknown_not_regular(self):
        self.configure()
        self.wearable([wear(a) for a in range(1, 8)])
        self.assertEqual(self.tool()["value"]["regularity"], regularity.UNKNOWN_FEW.replace("too few", "no"))

    def test_min_nights_from_config(self):
        self.cfg.write_text(json.dumps({"sleep_file": "sleep.jsonl", "regularity_min_nights": 8}))
        self.wearable([timed(a) for a in range(1, 6)])
        self.assertTrue(self.tool()["value"]["regularity"].startswith("unknown: too few"))

    def test_raw_minutes_only_under_the_opt_in_and_never_a_clock_time(self):
        self.configure()
        self.wearable([timed(a) for a in range(1, 6)])
        self.phone(screen(1), screen(2))
        raw = self.tool(raw=True)["value"]["regularity_min"]
        self.assertEqual(set(raw), {"wearable", "proxy"})
        self.assertEqual(raw["wearable"], {"nights": 5, "mid_spread_min": 0, "wake_spread_min": 0, "drift_min": 0})
        self.assertEqual(raw["proxy"], {"nights": 2, "mid_spread_min": None, "wake_spread_min": None,
                                        "drift_min": None})

    def test_the_handler_honours_the_opt_in(self):
        self.configure()
        self.wearable([timed(a) for a in range(1, 6)])
        with mock.patch.dict(os.environ, self.env), mock.patch("time.time", return_value=NOW):
            ctx = FakeCtx()
            plugin.register(ctx)
            out = json.loads(ctx.tools["limitless_sleep"]["handler"]({}))
        self.assertEqual(out["value"]["regularity"], "wearable: sleep times steady")
        self.assertNotIn("regularity_min", out["value"])
        self.assertIn("regular", ctx.tools["limitless_sleep"]["description"])


if __name__ == "__main__":
    unittest.main()
