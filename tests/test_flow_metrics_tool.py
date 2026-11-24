"""limitless_flow_metrics: the last seven days' work fragmentation as a read-only proxy envelope with T1 words.

Synthetic ActivityWatch DBs only. Raw numbers appear only under LIMITLESS_RAW_IN_PROMPT=1.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import plugin, tier_audit, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from test_flow_week import make_db  # noqa: E402
from test_plugin import FakeCtx  # noqa: E402

UTC = timezone.utc
NOW = 2_000_000_000.0
M = 60.0
D = 86400.0


def long_day(end):
    """One synthetic day: a hundred-minute editor block ending at ``end`` with one short look away."""
    s = end - 100 * M
    return [(s, s + 50 * M, "editor"), (s + 50 * M, s + 52 * M, "chat"), (s + 52 * M, end, "editor")]


def broken_day(end):
    """One synthetic day: six short editor runs, each followed by a feed app for longer than the block gap."""
    out, t = [], end - 120 * M
    for _ in range(6):
        out += [(t, t + 8 * M, "editor"), (t + 8 * M, t + 20 * M, "feed")]
        t += 20 * M
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.db = self.root / "aw.db"
        self.cfg = self.root / "config.json"
        self.cfg.write_text(json.dumps({"flow_work_apps": ["editor"]}))
        self.env = {"LIMITLESS_CONFIG": str(self.cfg), "LIMITLESS_AW_DB": str(self.db),
                    "LIMITLESS_STATE": str(self.st)}

    def tool(self, raw=False, env=None):
        return tools.flow_metrics(StateReader(self.st), NOW, raw=raw, env=self.env if env is None else env,
                                  home=self.root, tz=UTC)


class Tool(Base):
    def test_no_db_is_unknown_with_a_reason(self):
        out = self.tool(env={"LIMITLESS_CONFIG": str(self.cfg)})
        self.assertIsNone(out["value"])
        self.assertEqual(out["modality"], "proxy")
        self.assertEqual(out["evidence_tier"], "none")
        self.assertIn("aw_db", out["reason"])
        self.assertEqual(out["label"], {"label": "unknown: no readable ActivityWatch DB (aw_db)", "tier": "T1",
                                        "modality": "proxy"})

    def test_no_work_apps_is_unknown_never_zero(self):
        make_db(self.db, spans=long_day(NOW - M))
        self.cfg.write_text("{}")
        out = self.tool()
        self.assertIsNone(out["value"])
        self.assertEqual(out["label"]["label"], "unknown: no work apps set (flow_work_apps)")

    def test_no_rows_in_the_week_is_unknown(self):
        make_db(self.db, spans=long_day(NOW - 10 * D))
        out = self.tool()
        self.assertIsNone(out["value"])
        self.assertEqual(out["label"]["label"], "unknown: no activity rows in the last seven days")

    def test_long_blocks(self):
        make_db(self.db, spans=long_day(NOW - 6 * M) + long_day(NOW - D))
        out = self.tool()
        self.assertEqual(out["value"], {"days": 2, "work_days": 2, "label": "work stayed in long blocks"})
        self.assertEqual(out["label"], {"label": "work stayed in long blocks", "tier": "T1", "modality": "proxy"})
        self.assertEqual((out["modality"], out["age_h"], out["evidence_tier"]),
                         ("proxy", 0.1, "observed-activity"))

    def test_broken_up(self):
        make_db(self.db, spans=broken_day(NOW - M))
        self.assertEqual(self.tool()["label"]["label"], "work was broken up")

    def test_old_data_is_stale_not_observed_now(self):
        make_db(self.db, spans=long_day(NOW - 3 * D))
        out = self.tool()
        self.assertEqual(out["evidence_tier"], "stale")
        self.assertEqual(out["label"]["label"], "work stayed in long blocks")

    def test_raw_numbers_only_with_the_opt_in(self):
        make_db(self.db, spans=long_day(NOW - M))
        self.assertNotIn("switches_per_work_h", self.tool()["value"])
        v = self.tool(raw=True)["value"]
        self.assertEqual(v["switches_per_work_h"], 0.61)                 # one switch in ninety-eight minutes
        self.assertEqual(v["long_block_share"], 1.0)
        self.assertEqual(v["median_return_min"], 2.0)
        self.assertEqual(v["per_day"], [{"day": "2033-05-18", "work_h": 1.63, "switches_per_work_h": 0.61,
                                         "long_block_share": 1.0, "median_return_min": 2.0,
                                         "label": "work stayed in long blocks"}])

    def test_without_the_opt_in_nothing_but_counts_has_a_digit(self):
        make_db(self.db, spans=broken_day(NOW - M) + long_day(NOW - 2 * D))
        out = self.tool()
        v = dict(out["value"])
        self.assertIsInstance(v.pop("days"), int)
        self.assertIsInstance(v.pop("work_days"), int)
        text = json.dumps({k: out[k] for k in out if k not in ("value", "age_h", "label")}) + json.dumps(v)
        text += out["label"]["label"]             # the label word (its tier is named T1)
        self.assertEqual(re.findall(r"\d", text), [], text)

    def test_the_db_is_never_written(self):
        make_db(self.db, spans=long_day(NOW - M))
        before = (self.db.read_bytes(), self.db.stat().st_mtime_ns)
        self.tool(raw=True)
        self.assertEqual((self.db.read_bytes(), self.db.stat().st_mtime_ns), before)


class Plugin(Base):
    def call(self, extra=None):
        env = dict(self.env, **(extra or {}))
        with mock.patch.dict(os.environ, env), mock.patch("time.time", return_value=NOW):
            ctx = FakeCtx()
            plugin.register(ctx)
            return json.loads(ctx.tools["limitless_flow_metrics"]["handler"]({}))

    def test_registered_read_only_with_no_arguments(self):
        ctx = FakeCtx()
        plugin.register(ctx)
        t = ctx.tools["limitless_flow_metrics"]
        self.assertEqual(t["toolset"], "limitless")
        self.assertEqual(t["schema"]["parameters"]["properties"], {})
        for word in ("observed", "proxy", "Read-only"):
            self.assertIn(word, t["description"])
        for word in ("concentration", "productiv", "score"):
            self.assertNotIn(word, t["description"].lower().replace("no score", ""))

    def test_the_handler_returns_the_words_and_honours_the_raw_opt_in(self):
        make_db(self.db, spans=long_day(NOW - M))
        out = self.call()
        self.assertEqual(out["label"]["label"], "work stayed in long blocks")
        self.assertNotIn("switches_per_work_h", out["value"])
        self.assertEqual(self.call({"LIMITLESS_RAW_IN_PROMPT": "1"})["value"]["long_block_share"], 1.0)

    def test_tier_audit_records_it_as_t_one(self):
        make_db(self.db, spans=long_day(NOW - M))
        log = self.root / "audit.jsonl"
        self.call({tier_audit.ENV_KEY: str(log)})
        (row,) = [json.loads(x) for x in log.read_text().splitlines()]
        self.assertEqual((row["hook"], row["tier"], row["blocked"]), ("tool:limitless_flow_metrics", "T1", False))


if __name__ == "__main__":
    unittest.main()
