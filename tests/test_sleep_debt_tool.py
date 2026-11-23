"""limitless_sleep_debt: the debt words as an evidence envelope, from the same two sources limitless_sleep reads.

Synthetic rows only. The value is the label only; the T0 numbers appear only under LIMITLESS_RAW_IN_PROMPT=1.
Too few nights is value None with the unknown words as the reason. tier_audit logs the label; nothing is written.
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

from limitless import plugin, sleep_debt, tier_audit, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from test_plugin import FakeCtx  # noqa: E402

TODAY = date(2030, 1, 28)
NOW = datetime.combine(TODAY, time(9)).timestamp()   # local 09:00, as plugin's date.fromtimestamp reads it
H = 3600
FIELDS = {"value", "modality", "age_h", "evidence_tier", "label"}
SPAN = sleep_debt.RECENT_NIGHTS + sleep_debt.BASELINE_NIGHTS


def local(day, hour):
    return datetime.combine(day, time(0)).timestamp() + hour * H


def wear(ago, hours=8.0):
    return {"night": (TODAY - timedelta(days=ago)).isoformat(), "asleep_s": int(hours * H), "source": "synthetic"}


def screen(ago, hours=8.0, start_h=23.0):
    s = local(TODAY - timedelta(days=ago), start_h)
    return [{"ts": int(s * 1000), "type": "KEYGUARD_HIDDEN", "pkg": "synthetic"},
            {"ts": int((s + hours * H) * 1000), "type": "KEYGUARD_HIDDEN", "pkg": "synthetic"}]


def hours_for(ago, recent_h, base_h=8.0):
    return recent_h if ago <= sleep_debt.RECENT_NIGHTS else base_h


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
        self.configure()
        (self.st / "sleep.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def phone(self, spans):
        rows = [r for s in spans for r in s]
        (self.st / "screen-events.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def tool(self, raw=False):
        return tools.sleep_debt(StateReader(self.st), NOW, TODAY, raw=raw, env=self.env, home=self.root)


class Tool(Base):
    def test_short_recent_wearable_nights_are_a_lot_of_debt(self):
        self.wearable([wear(a, hours_for(a, 6)) for a in range(1, SPAN + 1)])
        out = self.tool()
        self.assertTrue(FIELDS <= set(out))
        self.assertEqual(out["value"], {"label": "a lot of sleep debt"})
        self.assertEqual(out["label"], {"label": "a lot of sleep debt", "tier": "T1", "modality": "measured"})
        self.assertEqual((out["modality"], out["evidence_tier"]), ("measured", "direct"))
        self.assertEqual(out["age_h"], 9.0)                     # the local midnight after last night

    def test_wearable_beats_proxy_on_the_same_date(self):
        self.wearable([wear(a, 8) for a in range(1, SPAN + 1)])
        self.phone([screen(a, hours_for(a, 4)) for a in range(1, SPAN + 1)])
        out = self.tool()
        self.assertEqual(out["value"], {"label": "little sleep debt"})
        self.assertEqual(out["modality"], "measured")

    def test_all_proxy_says_phone_estimate(self):
        self.phone([screen(a, hours_for(a, 6)) for a in range(1, SPAN + 1)])   # no sleep file at all
        out = self.tool()
        self.assertEqual(out["value"], {"label": "a lot of sleep debt (phone estimate)"})
        self.assertEqual((out["modality"], out["evidence_tier"]), ("proxy", "indirect"))

    def test_a_phone_night_where_the_wearable_missed_says_phone_estimate(self):
        self.wearable([wear(a, 8) for a in range(1, SPAN + 1) if a != 2])
        self.phone([screen(2, 8)])
        out = self.tool()
        self.assertEqual(out["value"], {"label": "little sleep debt (phone estimate)"})
        self.assertEqual(out["modality"], "proxy")

    def test_a_gap_night_is_unknown_not_zero(self):
        self.wearable([wear(a, 8) for a in range(1, SPAN + 1) if a != 2])
        out = self.tool()
        self.assertEqual(out["value"], {"label": "little sleep debt"})
        raw = self.tool(raw=True)["value"]
        self.assertEqual((raw["recent_nights"], raw["unknown_nights"], raw["short_min"]), (2, 1, 0))

    def test_too_few_nights_is_unknown_with_the_words_as_reason(self):
        self.wearable([wear(a, 5) for a in range(1, 4)])          # no baseline nights
        out = self.tool()
        self.assertIsNone(out["value"])
        self.assertEqual((out["evidence_tier"], out["reason"]), ("none", "unknown: too few nights"))
        self.assertNotIn("label", out)

    def test_numbers_only_under_the_opt_in(self):
        self.wearable([wear(a, hours_for(a, 7)) for a in range(1, SPAN + 1)])
        self.assertEqual(set(self.tool()["value"]), {"label"})
        raw = self.tool(raw=True)["value"]
        self.assertEqual(raw["label"], "some sleep debt")
        self.assertEqual({k: raw[k] for k in ("baseline_median_min", "recent_mean_min", "short_min",
                                              "recent_nights", "baseline_nights", "proxy_nights")},
                         {"baseline_median_min": 480, "recent_mean_min": 420, "short_min": 180, "recent_nights": 3,
                          "baseline_nights": 14, "proxy_nights": 0})
        self.assertAlmostEqual(raw["short_share"], 0.125)

    def test_default_results_have_no_digit_outside_the_age(self):
        cases = [([wear(a, hours_for(a, h)) for a in range(1, SPAN + 1)], []) for h in (4, 7, 8, 10)]
        cases += [([], [screen(a, hours_for(a, h)) for a in range(1, SPAN + 1)]) for h in (4, 7, 8)]
        cases += [([wear(1)], []), ([], [])]
        for w, p in cases:
            for f in self.st.iterdir():
                f.unlink()
            if w:
                self.wearable(w)
            if p:
                self.phone(p)
            out = self.tool()
            text = json.dumps({k: v for k, v in out.items() if k != "age_h"}).replace('"tier": "T1"', "")
            self.assertEqual(re.findall(r"\d", text), [], (w, p, text))
            if out["value"] is not None:
                self.assertIn(out["value"]["label"], sleep_debt.KNOWN_LABELS)

    def test_no_data_is_null_with_a_reason_that_never_echoes_the_path(self):
        out = self.tool()
        self.assertIsNone(out["value"])
        self.assertIn("sleep_file", out["reason"])
        self.wearable([{"night": "bad"}])
        out = self.tool()
        self.assertIsNone(out["value"])
        for bad in (str(self.st), "sleep.jsonl", str(self.root)):
            self.assertNotIn(bad, out["reason"])


class Plugin(Base):
    def call(self, extra=None):
        env = dict(self.env, **(extra or {}))
        with mock.patch.dict(os.environ, env), mock.patch("time.time", return_value=NOW):
            ctx = FakeCtx()
            plugin.register(ctx)
            return json.loads(ctx.tools["limitless_sleep_debt"]["handler"]({}))

    def test_registered_read_only_with_no_arguments_and_no_advice(self):
        ctx = FakeCtx()
        plugin.register(ctx)
        t = ctx.tools["limitless_sleep_debt"]
        self.assertEqual(t["toolset"], "limitless")
        self.assertEqual(t["schema"]["parameters"]["properties"], {})
        for bad in ("should", "go to bed", "bed at", "goal", "aim for", "score"):
            self.assertNotIn(bad, t["description"].lower())

    def test_the_handler_honours_the_opt_in(self):
        self.wearable([wear(a, hours_for(a, 7)) for a in range(1, SPAN + 1)])
        out = self.call()
        self.assertEqual(out["value"], {"label": "some sleep debt"})
        self.assertEqual(self.call({"LIMITLESS_RAW_IN_PROMPT": "1"})["value"]["short_min"], 180)

    def test_tier_audit_logs_the_result_as_t1_with_no_digit(self):
        self.wearable([wear(a, hours_for(a, 6)) for a in range(1, SPAN + 1)])
        log = self.root / "audit.jsonl"
        self.call({tier_audit.ENV_KEY: str(log)})
        (row,) = [json.loads(ln) for ln in log.read_text().splitlines()]
        self.assertEqual((row["hook"], row["tier"], row["digits"], row["blocked"], row["opt_in"]),
                         ("tool:limitless_sleep_debt", "T1", 0, False, False))
        self.assertNotIn("sleep debt", log.read_text())   # the words never reach the log

    def test_nothing_is_written_or_sent(self):
        self.wearable([wear(a, hours_for(a, 6)) for a in range(1, SPAN + 1)])
        self.phone([screen(1)])
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob("*") if p.is_file()}
        with mock.patch("urllib.request.urlopen") as net, mock.patch("subprocess.run") as run:
            self.call()
        self.assertFalse(net.called or run.called)
        after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
