"""limitless_sleep: the wearable and the phone proxy side by side as an evidence envelope.

Synthetic rows only. The value is counts and the T1 label; per-night minutes only under LIMITLESS_RAW_IN_PROMPT=1.
modality is "measured" only when the wearable covers the newest night, else "proxy"; age is the newest datum's.
No data is value None with a reason that never echoes the path. tier_audit logs the label.
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

from limitless import plugin, sleep, tier_audit, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from test_plugin import FakeCtx  # noqa: E402

TODAY = date(2030, 1, 28)
NOW = datetime.combine(TODAY, time(9)).timestamp()   # local 09:00, as plugin's date.fromtimestamp reads it
H = 3600
FIELDS = {"value", "modality", "age_h", "evidence_tier", "label"}
COUNT_KEYS = ("wearable_nights", "proxy_only_nights", "unknown_nights")


def local(day, hour):
    return datetime.combine(day, time(0)).timestamp() + hour * H


def wear(ago, hours=7.0, source="synthetic-ring"):
    return {"night": (TODAY - timedelta(days=ago)).isoformat(), "asleep_s": int(hours * H), "source": source}


def screen(ago, start_h=23.0, hours=8.0):
    """Two unlocks around one quiet span that starts on the evening ``ago`` days before TODAY."""
    s = local(TODAY - timedelta(days=ago), start_h)
    return [{"ts": int(s * 1000), "type": "KEYGUARD_HIDDEN", "pkg": "synthetic"},
            {"ts": int((s + hours * H) * 1000), "type": "KEYGUARD_HIDDEN", "pkg": "synthetic"}]


def without_counts_and_ages(v):
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

    def configure(self):
        self.cfg.write_text(json.dumps({"sleep_file": "sleep.jsonl"}))

    def wearable(self, rows):
        (self.st / "sleep.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def phone(self, *spans):
        rows = [r for s in spans for r in s]
        (self.st / "screen-events.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def tool(self, raw=False):
        return tools.sleep(StateReader(self.st), NOW, TODAY, raw=raw, env=self.env, home=self.root)


class Tool(Base):
    def test_default_value_is_counts_and_the_label(self):
        self.configure()
        self.wearable([wear(a, 7) for a in range(1, 7)])
        self.phone(*(screen(a, 23, 8) for a in range(1, 8)))
        out = self.tool()
        self.assertTrue(FIELDS <= set(out))
        word = "sleep: wearable on most nights; phone proxy says longer"
        self.assertEqual(out["value"], {"wearable_nights": 6, "proxy_only_nights": 1, "unknown_nights": 0,
                                        "label": word, "regularity": "phone estimate: sleep times steady"})
        self.assertEqual(out["label"], {"label": word, "tier": "T1", "modality": "measured"})
        self.assertEqual(out["modality"], "measured")
        self.assertEqual((out["age_h"], out["evidence_tier"]), (2.0, "direct"))   # the 07:00 unlock

    def test_proxy_when_the_wearable_misses_the_newest_night(self):
        self.configure()
        self.wearable([wear(a) for a in range(2, 8)])
        self.phone(screen(1, 23, 7))
        out = self.tool()
        self.assertEqual((out["modality"], out["label"]["modality"]), ("proxy", "proxy"))
        self.assertEqual((out["age_h"], out["evidence_tier"]), (3.0, "indirect"))
        self.assertEqual(out["value"]["proxy_only_nights"], 1)

    def test_a_stale_wearable_and_no_phone_is_old_not_fresh(self):
        self.configure()
        self.wearable([wear(4)])                       # night four days ago: dated at the following midnight
        out = self.tool()
        self.assertEqual(out["modality"], "proxy")
        self.assertEqual((out["age_h"], out["evidence_tier"]), (3 * 24 + 9.0, "stale"))
        self.assertEqual(out["value"], {"wearable_nights": 1, "proxy_only_nights": 0, "unknown_nights": 6,
                                        "label": "sleep: wearable on some nights; phone proxy has no night to compare",
                                        "regularity": "unknown: no nights with sleep times from the wearable or the "
                                                      "phone estimate"})

    def test_nights_with_neither_are_unknown_never_zero(self):
        self.configure()
        self.wearable([wear(20)])
        out = self.tool()
        self.assertEqual(out["value"]["unknown_nights"], 7)
        out = self.tool(raw=True)
        self.assertEqual({(n["wearable_min"], n["proxy_min"]) for n in out["value"]["nights"]}, {(None, None)})

    def test_per_night_minutes_only_under_the_opt_in(self):
        self.configure()
        self.wearable([wear(1, 7)])
        self.phone(screen(1, 23, 7.5))
        self.assertNotIn("nights", self.tool()["value"])
        raw = self.tool(raw=True)["value"]["nights"]
        self.assertEqual(len(raw), 7)
        self.assertEqual(raw[-1], {"night": (TODAY - timedelta(days=1)).isoformat(), "wearable_min": 420,
                                   "proxy_min": 450})

    def test_the_phone_alone_works_without_a_sleep_file(self):
        self.phone(screen(1), screen(2))
        out = self.tool()
        self.assertEqual(out["modality"], "proxy")
        self.assertEqual(out["value"]["label"], "sleep: wearable on no nights; phone proxy has no night to compare")
        self.assertEqual(out["value"]["proxy_only_nights"], 2)

    def test_no_data_is_null_with_a_reason_that_never_echoes_the_path(self):
        out = self.tool()
        self.assertIsNone(out["value"])
        self.assertEqual(out["evidence_tier"], "none")
        self.assertIn("sleep_file", out["reason"])
        self.assertNotIn("label", out)
        self.configure()
        self.wearable([{"night": "bad"}, wear(-3)])
        out = self.tool()
        self.assertIsNone(out["value"])
        self.assertTrue(out["reason"])
        for bad in (str(self.st), "sleep.jsonl", str(self.root)):
            self.assertNotIn(bad, out["reason"])

    def test_default_results_have_no_digit_outside_counts_and_ages(self):
        cases = [([wear(a) for a in range(1, 8)], [screen(a) for a in range(1, 8)]),
                 ([wear(3)], []), ([], [screen(2, 22, 5)]), ([wear(1, 8)], [screen(1, 23, 6)]), ([], [])]
        for w, p in cases:
            for f in self.st.iterdir():
                f.unlink()
            self.configure()
            self.wearable(w)
            self.phone(*p)
            out = self.tool()
            text = json.dumps(without_counts_and_ages(out))
            self.assertEqual(re.findall(r"\d", text), [], (w, p, text))
            if out["value"] is not None:
                self.assertIn(out["value"]["label"], sleep.LABELS)

    def test_never_carries_other_wearable_fields(self):
        self.configure()
        self.wearable([dict(wear(1), hrv_ms=999, resting_hr=999)])
        for raw in (False, True):
            text = json.dumps(self.tool(raw=raw))
            self.assertNotIn("999", text)
            self.assertNotIn("hr", text)


class Plugin(Base):
    def call(self, extra=None):
        env = dict(self.env, **(extra or {}))
        with mock.patch.dict(os.environ, env), mock.patch("time.time", return_value=NOW):
            ctx = FakeCtx()
            plugin.register(ctx)
            return json.loads(ctx.tools["limitless_sleep"]["handler"]({}))

    def test_the_tool_is_registered_read_only_with_no_arguments(self):
        ctx = FakeCtx()
        plugin.register(ctx)
        t = ctx.tools["limitless_sleep"]
        self.assertEqual(t["toolset"], "limitless")
        self.assertEqual(t["schema"]["parameters"]["properties"], {})
        self.assertIn("proxy", t["description"])
        for bad in ("should", "go to bed", "bed at", "goal", "aim for"):
            self.assertNotIn(bad, t["description"].lower())

    def test_the_handler_returns_the_sleep_label_and_honours_the_opt_in(self):
        self.configure()
        self.wearable([wear(1, 7)])
        self.phone(screen(1, 23, 7))
        out = self.call()
        self.assertEqual(out["label"]["label"], "sleep: wearable on some nights; phone proxy says about the same")
        self.assertNotIn("nights", out["value"])
        self.assertEqual(self.call({"LIMITLESS_RAW_IN_PROMPT": "1"})["value"]["nights"][-1]["wearable_min"], 420)

    def test_tier_audit_logs_the_result_as_t1_with_no_digit_in_the_default_label(self):
        self.configure()
        self.wearable([wear(a) for a in range(1, 8)])
        log = self.root / "audit.jsonl"
        out = self.call({tier_audit.ENV_KEY: str(log)})
        self.assertEqual(re.findall(r"\d", out["label"]["label"]), [])
        (row,) = [json.loads(ln) for ln in log.read_text().splitlines()]
        self.assertEqual((row["hook"], row["tier"], row["digits"], row["blocked"], row["opt_in"]),
                         ("tool:limitless_sleep", "T1", 0, False, False))
        self.assertNotIn("wearable", log.read_text())

    def test_no_data_through_the_handler_is_null_and_nothing_audited(self):
        log = self.root / "audit.jsonl"
        out = self.call({tier_audit.ENV_KEY: str(log)})
        self.assertIsNone(out["value"])
        self.assertFalse(log.exists())

    def test_nothing_is_written(self):
        self.configure()
        self.wearable([wear(1)])
        self.phone(screen(1))
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.st.iterdir()}
        self.call()
        self.assertEqual({p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.st.iterdir()}, before)


if __name__ == "__main__":
    unittest.main()
