"""limitless_flow_ledger: yesterday's focus blocks, feed leaks and landed work as a read-only envelope in words.

Synthetic ActivityWatch DBs and a synthetic work queue only. Times and app names only under LIMITLESS_RAW_IN_PROMPT=1.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from limitless import plugin, tier_audit, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from test_flow_week import make_db  # noqa: E402
from test_plugin import FakeCtx, manifest_list  # noqa: E402

UTC = timezone.utc
DS = datetime(2033, 5, 17, tzinfo=UTC).timestamp()     # yesterday, as seen from NOW
NOW = DS + 86400.0 + 8 * 3600.0
M, H = 60.0, 3600.0


def block(at, minutes=100, feed=False):
    mid = at + 40 * M
    return [(at, mid, "editor"), (mid, mid + 2 * M, "feed" if feed else "chat"), (mid + 2 * M, at + minutes * M, "editor")]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.db = self.root / "aw.db"
        self.cfg = self.root / "config.json"
        self.config()
        self.env = {"LIMITLESS_CONFIG": str(self.cfg), "LIMITLESS_AW_DB": str(self.db), "LIMITLESS_STATE": str(self.st)}

    def config(self, **extra):
        cfg = {"flow_work_apps": ["editor"], "feed_apps": ["feed"], "work_queue_dir": "lanes"}
        cfg.update(extra)
        self.cfg.write_text(json.dumps({k: v for k, v in cfg.items() if v is not None}))

    def done(self, name, mtime):
        d = self.st / "lanes" / "done"
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{name}.md"
        p.write_text("synthetic\n")
        os.utime(p, (mtime, mtime))

    def tool(self, raw=False, env=None, now=NOW):
        return tools.flow_ledger(StateReader(self.st), now, raw=raw, env=self.env if env is None else env,
                                 home=self.root, tz=UTC)


class Tool(Base):
    def test_words_envelope(self):
        make_db(self.db, spans=block(DS + 9 * H) + block(DS + 13 * H, feed=True))
        self.done("synthetic-lane", DS + 15 * H)
        out = self.tool()
        word = "two long blocks, one with a feed leak; one item landed"
        self.assertEqual(out["value"], {"label": word})
        self.assertEqual(out["label"], {"label": word, "tier": "T1", "modality": "observed"})
        self.assertEqual(out["modality"], "observed")
        self.assertEqual(out["evidence_tier"], "observed-activity")
        self.assertAlmostEqual(out["age_h"], 8 + 24 - 13 - 100 / 60, places=1)

    def test_unknown_says_why(self):
        out = self.tool(env={"LIMITLESS_CONFIG": str(self.cfg), "LIMITLESS_STATE": str(self.st)})
        self.assertIsNone(out["value"])
        self.assertEqual((out["modality"], out["evidence_tier"]), ("observed", "none"))
        self.assertEqual(out["label"]["label"], "unknown: no readable ActivityWatch DB (aw_db)")
        make_db(self.db, spans=block(DS - 30 * H))
        self.assertEqual(self.tool()["label"]["label"], "unknown: no app activity that day")
        make_db(self.root / "b.db", spans=block(DS + 9 * H))
        self.config(flow_work_apps=None)
        self.assertEqual(self.tool(env=dict(self.env, LIMITLESS_AW_DB=str(self.root / "b.db")))["label"]["label"],
                         "unknown: no work apps set (flow_work_apps)")

    def test_old_activity_is_stale(self):
        make_db(self.db, spans=block(DS + 9 * H))
        late = DS + 86400.0 + 23 * H                     # still yesterday's ledger, its newest row over a day old
        self.assertEqual(self.tool(now=late)["evidence_tier"], "stale")

    def test_raw_times_and_app_names_only_with_the_opt_in(self):
        make_db(self.db, spans=block(DS + 9 * H, feed=True))
        self.done("synthetic-lane", DS + 15 * H)
        plain = json.dumps(self.tool())
        for bad in ("editor", "feed\"", "org.example", "synthetic-lane", "start", "apps"):
            self.assertNotIn(bad, plain)
        self.assertEqual(re.findall(r"\d", json.dumps(self.tool()["value"])), [])
        v = self.tool(raw=True)["value"]
        self.assertEqual(v["label"], "one long block, with a feed leak; one item landed")
        (b,) = v["blocks"]
        self.assertEqual((b["start"], b["end"], b["long"], b["leak"]), (DS + 9 * H, DS + 9 * H + 100 * M, True, True))
        self.assertIn("editor", b["apps"])
        self.assertIn("feed", b["apps"])
        self.assertEqual((v["day"], v["long_blocks"], v["leaks"], v["landed"]), ("2033-05-17", 1, 1, 1))
        self.assertNotIn("synthetic-lane", json.dumps(v))      # file names never leave code, even raw

    def test_nothing_is_written(self):
        make_db(self.db, spans=block(DS + 9 * H))
        before = (self.db.read_bytes(), self.db.stat().st_mtime_ns, sorted(p.name for p in self.st.rglob("*")))
        self.tool(raw=True)
        self.assertEqual((self.db.read_bytes(), self.db.stat().st_mtime_ns, sorted(p.name for p in self.st.rglob("*"))),
                         before)


LDS = datetime(2033, 5, 17).timestamp()            # the handler reads this machine's zone: a local day
LNOW = LDS + 86400.0 + 8 * H


class Plugin(Base):
    def call(self, extra=None):
        env = dict(self.env, **(extra or {}))
        with mock.patch.dict(os.environ, env), mock.patch("time.time", return_value=LNOW):
            ctx = FakeCtx()
            plugin.register(ctx)
            return json.loads(ctx.tools["limitless_flow_ledger"]["handler"]({}))

    def test_registered_read_only_with_no_arguments(self):
        self.assertIn("limitless_flow_ledger", plugin.TOOLS)
        self.assertIn("limitless_flow_ledger", manifest_list("provides_tools"))
        ctx = FakeCtx()
        plugin.register(ctx)
        t = ctx.tools["limitless_flow_ledger"]
        self.assertEqual(t["schema"]["parameters"]["properties"], {})
        for word in ("observed", "feed", "Read-only", "raw opt-in"):
            self.assertIn(word, t["description"])
        for word in ("productiv", "score", "concentration"):
            self.assertNotIn(word, t["description"].lower().replace("no score", "").replace("no productivity", ""))

    def test_handler_words_and_raw_opt_in(self):
        make_db(self.db, spans=block(LDS + 9 * H))
        self.assertEqual(self.call()["label"]["label"], "one long block, no feed leak")    # no queue dir: unknown
        (self.st / "lanes").mkdir()
        out = self.call()
        self.assertEqual(out["label"]["label"], "one long block, no feed leak; nothing landed")
        self.assertNotIn("blocks", out["value"])
        self.assertIn("blocks", self.call({"LIMITLESS_RAW_IN_PROMPT": "1"})["value"])

    def test_tier_audit_records_it_as_t_one(self):
        make_db(self.db, spans=block(LDS + 9 * H))
        log = self.root / "audit.jsonl"
        self.call({tier_audit.ENV_KEY: str(log)})
        (row,) = [json.loads(x) for x in log.read_text().splitlines()]
        self.assertEqual((row["hook"], row["tier"], row["blocked"]), ("tool:limitless_flow_ledger", "T1", False))


if __name__ == "__main__":
    unittest.main()
