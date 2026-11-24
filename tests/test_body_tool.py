"""limitless_body: the body trend as an evidence envelope, counts and a T1 label by default.

Synthetic rows only. Raw numbers (medians, change) appear only under LIMITLESS_RAW_IN_PROMPT=1, the same
opt-in the state card uses. No file or no rows is value None with a reason: unknown, not zero.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
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
COUNT_KEYS = ("recent_rows", "prior_rows")


def rows(prior=(22.4, 22.6, 22.5), recent=(21.4, 21.6, 21.5), calibrated=True):
    out = [{"day": (TODAY - timedelta(days=27 - 2 * i)).isoformat(), "bf_pct": v, "method": "synthetic-scale",
            "calibrated": calibrated} for i, v in enumerate(prior)]
    out += [{"day": (TODAY - timedelta(days=13 - 2 * i)).isoformat(), "bf_pct": v, "method": "synthetic-scale",
             "calibrated": calibrated} for i, v in enumerate(recent)]
    return out


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
        self.cfg.write_text(json.dumps(dict({"body_file": "body.jsonl"}, **extra)))

    def write(self, data):
        p = self.st / "body.jsonl"
        p.write_text("".join(json.dumps(r) + "\n" for r in data))
        os.utime(p, (NOW - 3 * 3600, NOW - 3 * 3600))

    def tool(self, raw=False):
        return tools.body(StateReader(self.st), NOW, TODAY, raw=raw, env=self.env, home=self.root)


class Tool(Base):
    def test_default_value_is_counts_and_the_label(self):
        self.configure()
        self.write(rows())
        out = self.tool()
        self.assertTrue(FIELDS <= set(out))
        self.assertEqual(out["value"], {"recent_rows": 3, "prior_rows": 3,
                                        "label": "body fat trending down (calibrated estimate)"})
        self.assertEqual(out["label"], {"label": "body fat trending down (calibrated estimate)", "tier": "T1",
                                        "modality": "measured"})
        self.assertEqual((out["modality"], out["age_h"], out["evidence_tier"]), ("measured", 3.0, "direct"))

    def test_uncalibrated_rows_are_a_proxy(self):
        self.configure()
        self.write(rows(calibrated=False))
        out = self.tool()
        self.assertEqual((out["modality"], out["evidence_tier"]), ("proxy", "indirect"))
        self.assertEqual(out["label"]["label"], "body fat trending down (uncalibrated estimate)")

    def test_raw_numbers_only_under_the_opt_in(self):
        self.configure()
        self.write(rows())
        out = self.tool(raw=True)
        self.assertEqual(out["value"]["recent_median"], 21.5)
        self.assertEqual(out["value"]["prior_median"], 22.5)
        self.assertEqual(out["value"]["change"], -1.0)
        for k in ("recent_median", "prior_median", "change"):
            self.assertNotIn(k, self.tool()["value"])

    def test_not_enough_measurements_is_a_value_with_counts(self):
        self.configure()
        self.write(rows(prior=(22.0,)))
        out = self.tool()
        self.assertEqual(out["value"], {"recent_rows": 3, "prior_rows": 1, "label": "not enough measurements"})
        self.assertEqual(out["label"]["label"], "not enough measurements")

    def test_the_configured_flat_threshold_is_used(self):
        self.configure(body_flat_points=2.0)
        self.write(rows())
        self.assertEqual(self.tool()["label"]["label"], "body fat trending flat (calibrated estimate)")

    def test_no_file_configured_is_unknown_with_a_reason(self):
        self.write(rows())
        out = self.tool()
        self.assertIsNone(out["value"])
        self.assertEqual(out["evidence_tier"], "none")
        self.assertIn("body_file", out["reason"])
        self.assertNotIn("label", out)

    def test_a_missing_file_or_no_valid_row_is_unknown_not_zero(self):
        self.configure()
        out = self.tool()
        self.assertIsNone(out["value"])
        self.assertTrue(out["reason"])
        self.write([{"day": "bad"}, {"day": (TODAY + timedelta(days=1)).isoformat(), "bf_pct": 20.0,
                                     "method": "m", "calibrated": True}])
        out = self.tool()
        self.assertIsNone(out["value"])
        self.assertNotIn(str(self.st), out["reason"])
        self.assertNotIn("body.jsonl", out["reason"])

    def test_default_results_have_no_digit_outside_counts_and_ages(self):
        cases = [rows(), rows(calibrated=False), rows(prior=()), [], None]
        for case in cases:
            if case is None:
                self.cfg.write_text("{}")
            else:
                self.configure()
                self.write(case)
            out = self.tool()
            text = json.dumps(without_counts_and_ages(out))
            self.assertEqual(re.findall(r"\d", text), [], (case, text))
            for k in COUNT_KEYS:
                if out["value"] is not None:
                    self.assertIsInstance(out["value"][k], int)


class Plugin(Base):
    def call(self, extra=None):
        env = dict(self.env, **(extra or {}))
        with mock.patch.dict(os.environ, env), mock.patch("time.time", return_value=NOW):
            ctx = FakeCtx()
            plugin.register(ctx)
            return json.loads(ctx.tools["limitless_body"]["handler"]({}))

    def test_the_tool_is_registered_read_only_with_no_arguments(self):
        ctx = FakeCtx()
        plugin.register(ctx)
        t = ctx.tools["limitless_body"]
        self.assertEqual(t["toolset"], "limitless")
        self.assertEqual(t["schema"]["parameters"]["properties"], {})
        self.assertIn("body fat", t["description"])

    def test_the_handler_returns_the_trend_label_not_an_age_label(self):
        self.configure()
        self.write(rows())
        out = self.call()
        self.assertEqual(out["label"]["label"], "body fat trending down (calibrated estimate)")
        self.assertNotIn("recent_median", out["value"])

    def test_the_handler_honours_the_raw_opt_in(self):
        self.configure()
        self.write(rows())
        self.assertEqual(self.call({"LIMITLESS_RAW_IN_PROMPT": "1"})["value"]["recent_median"], 21.5)

    def test_tier_audit_logs_the_result_as_t1(self):
        self.configure()
        self.write(rows())
        log = self.root / "audit.jsonl"
        self.call({tier_audit.ENV_KEY: str(log)})
        (row,) = [json.loads(ln) for ln in log.read_text().splitlines()]
        self.assertEqual((row["hook"], row["tier"], row["digits"], row["blocked"], row["opt_in"]),
                         ("tool:limitless_body", "T1", 0, False, False))
        self.assertNotIn("trending", log.read_text())

    def test_no_data_through_the_handler_is_null_with_a_reason_and_nothing_audited(self):
        log = self.root / "audit.jsonl"
        out = self.call({tier_audit.ENV_KEY: str(log)})
        self.assertIsNone(out["value"])
        self.assertTrue(out["reason"])
        self.assertFalse(log.exists())

    def test_the_body_file_is_never_written(self):
        self.configure()
        self.write(rows())
        p = self.st / "body.jsonl"
        before = (p.read_bytes(), p.stat().st_mtime_ns)
        self.call()
        self.assertEqual((p.read_bytes(), p.stat().st_mtime_ns), before)
        self.assertEqual(sorted(x.name for x in self.st.iterdir()), ["body.jsonl"])


if __name__ == "__main__":
    unittest.main()
