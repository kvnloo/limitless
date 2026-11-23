"""limitless_rides: the weekly ride count as an evidence envelope, counts and a T1 label by default.

Synthetic rows only. Total minutes appear only under LIMITLESS_RAW_IN_PROMPT=1, the same opt-in the state
card uses. No file or no rides is value None with a reason: unknown, not zero. tier_audit logs the label.
"""
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import plugin, tier_audit, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from test_plugin import FakeCtx  # noqa: E402

TODAY = date(2030, 1, 28)
NOW = datetime.combine(TODAY, time(12)).timestamp()   # local noon, as plugin's date.fromtimestamp reads it
FIELDS = {"value", "modality", "age_h", "evidence_tier"}
COUNT_KEYS = ("this_week", "last_week")
RAW_KEYS = ("minutes_this_week", "minutes_last_week")


def ride(days_ago, minutes=10, kind="rehit"):
    d = TODAY - timedelta(days=days_ago)
    return {"start": f"{d.isoformat()}T07:00:00+00:00", "duration_s": minutes * 60, "kind": kind,
            "source": "synthetic-bike-app", "avg_hr": 999, "peak_power_w": 999}


def rides(this=2, last=1):
    return [ride(13 - i, 9) for i in range(last)] + [ride(6 - i, 11) for i in range(this)]


def without_counts_and_ages(v):
    """v without its counts, ages and the tier name "T1" (a schema constant, not data)."""
    if isinstance(v, dict):
        return {k: without_counts_and_ages(x) for k, x in v.items()
                if k not in COUNT_KEYS + ("age_h",) and not (k == "tier" and x == "T1")}
    if isinstance(v, list):
        return [without_counts_and_ages(x) for x in v]
    return v


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.cfg = self.root / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg), "LIMITLESS_STATE": str(self.st)}

    def configure(self, **extra):
        self.cfg.write_text(json.dumps(dict({"rides_file": "rides.jsonl"}, **extra)))

    def write(self, data):
        p = self.st / "rides.jsonl"
        p.write_text("".join(json.dumps(r) + "\n" for r in data))
        os.utime(p, (NOW - 3 * 3600, NOW - 3 * 3600))

    def tool(self, raw=False):
        return tools.rides(StateReader(self.st), NOW, TODAY, raw=raw, env=self.env, home=self.root)


class Tool(Base):
    def test_default_value_is_counts_and_the_label(self):
        self.configure()
        self.write(rides())
        out = self.tool()
        self.assertTrue(FIELDS <= set(out))
        self.assertEqual(out["value"], {"this_week": 2, "last_week": 1,
                                        "label": "rides this week: two, more than last week"})
        self.assertEqual(out["label"], {"label": "rides this week: two, more than last week", "tier": "T1",
                                        "modality": "measured"})
        self.assertEqual((out["modality"], out["age_h"], out["evidence_tier"]), ("measured", 3.0, "direct"))

    def test_aged_by_the_file_mtime(self):
        self.configure()
        self.write(rides())
        os.utime(self.st / "rides.jsonl", (NOW - 48 * 3600, NOW - 48 * 3600))
        out = self.tool()
        self.assertEqual((out["age_h"], out["evidence_tier"]), (48.0, "stale"))

    def test_total_minutes_only_under_the_opt_in(self):
        self.configure()
        self.write(rides())
        out = self.tool(raw=True)
        self.assertEqual((out["value"]["minutes_this_week"], out["value"]["minutes_last_week"]), (22, 9))
        for k in RAW_KEYS:
            self.assertNotIn(k, self.tool()["value"])

    def test_never_carries_heart_rate_or_power(self):
        self.configure()
        self.write(rides())
        for raw in (False, True):
            text = json.dumps(self.tool(raw=raw))
            self.assertNotIn("999", text)
            self.assertNotIn("hr", text)
            self.assertNotIn("power", text)

    def test_a_week_with_no_ride_is_none_not_missed(self):
        self.configure()
        self.write([ride(20)])
        out = self.tool()
        self.assertEqual(out["value"], {"this_week": 0, "last_week": 0,
                                        "label": "rides this week: none, same as last week"})
        self.assertNotIn("missed", json.dumps(out))

    def test_no_file_configured_is_unknown_with_a_reason(self):
        self.write(rides())
        out = self.tool()
        self.assertIsNone(out["value"])
        self.assertEqual(out["evidence_tier"], "none")
        self.assertIn("rides_file", out["reason"])
        self.assertNotIn("label", out)

    def test_a_missing_file_or_no_ride_row_is_unknown_not_zero(self):
        self.configure()
        out = self.tool()
        self.assertIsNone(out["value"])
        self.assertTrue(out["reason"])
        self.assertNotIn("rides.jsonl", out["reason"])
        self.write([{"start": "bad"}, ride(1, kind="walking"), ride(-1)])
        out = self.tool()
        self.assertIsNone(out["value"])
        self.assertNotIn(str(self.st), out["reason"])
        self.assertNotIn("rides.jsonl", out["reason"])

    def test_default_results_have_no_digit_outside_counts_and_ages(self):
        cases = [rides(), rides(0, 0) + [ride(20)], rides(5, 3), rides(1, 4), [], None]
        for case in cases:
            if case is None:
                self.cfg.write_text("{}")
            else:
                self.configure()
                self.write(case)
            out = self.tool()
            text = json.dumps(without_counts_and_ages(out))
            self.assertEqual(re.findall(r"\d", text), [], (case, text))
            if out["value"] is not None:
                for k in COUNT_KEYS:
                    self.assertIsInstance(out["value"][k], int)


class Plugin(Base):
    def call(self, extra=None):
        env = dict(self.env, **(extra or {}))
        with mock.patch.dict(os.environ, env), mock.patch("time.time", return_value=NOW):
            ctx = FakeCtx()
            plugin.register(ctx)
            return json.loads(ctx.tools["limitless_rides"]["handler"]({}))

    def test_the_tool_is_registered_read_only_with_no_arguments(self):
        ctx = FakeCtx()
        plugin.register(ctx)
        t = ctx.tools["limitless_rides"]
        self.assertEqual(t["toolset"], "limitless")
        self.assertEqual(t["schema"]["parameters"]["properties"], {})
        self.assertIn("rides", t["description"])

    def test_the_handler_returns_the_ride_label_not_an_age_label(self):
        self.configure()
        self.write(rides())
        out = self.call()
        self.assertEqual(out["label"]["label"], "rides this week: two, more than last week")
        self.assertNotIn("minutes_this_week", out["value"])

    def test_the_handler_honours_the_raw_opt_in(self):
        self.configure()
        self.write(rides())
        self.assertEqual(self.call({"LIMITLESS_RAW_IN_PROMPT": "1"})["value"]["minutes_this_week"], 22)

    def test_tier_audit_logs_the_result_as_t1_with_no_digit_in_the_label(self):
        self.configure()
        self.write(rides())
        log = self.root / "audit.jsonl"
        out = self.call({tier_audit.ENV_KEY: str(log)})
        self.assertEqual(re.findall(r"\d", out["label"]["label"]), [])
        (row,) = [json.loads(ln) for ln in log.read_text().splitlines()]
        self.assertEqual((row["hook"], row["tier"], row["digits"], row["blocked"], row["opt_in"]),
                         ("tool:limitless_rides", "T1", 0, False, False))
        self.assertNotIn("rides this week", log.read_text())

    def test_no_data_through_the_handler_is_null_with_a_reason_and_nothing_audited(self):
        log = self.root / "audit.jsonl"
        out = self.call({tier_audit.ENV_KEY: str(log)})
        self.assertIsNone(out["value"])
        self.assertTrue(out["reason"])
        self.assertFalse(log.exists())

    def test_the_rides_file_is_never_written(self):
        self.configure()
        self.write(rides())
        p = self.st / "rides.jsonl"
        before = (p.read_bytes(), p.stat().st_mtime_ns)
        self.call()
        self.assertEqual((p.read_bytes(), p.stat().st_mtime_ns), before)
        self.assertEqual(sorted(x.name for x in self.st.iterdir()), ["rides.jsonl"])


if __name__ == "__main__":
    unittest.main()
