"""limitless_feed_reflex: the envelope, T0 counts only under the raw opt-in, unknown never zero, read-only.

Synthetic ActivityWatch DBs only (made-up app names)."""
import hashlib
import json
import os
import sys
import tempfile
import unittest
from datetime import timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from limitless import feed_reflex, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from test_aw_reader import make_db  # noqa: E402

NOW = 1894708800.0
H = 3600.0
UTC = timezone.utc


def often_spans(n=6, feed=4):
    """n unlocks over the last day, an hour apart; the first ``feed`` open a feed first, the rest a notes app."""
    unlocks, spans = [], []
    for i in range(n):
        u = NOW - (i + 2) * H
        unlocks.append(u)
        spans.append((u + 2, u + 300, "feedapp" if i < feed else "notes"))
    return unlocks, spans


class Tool(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.st = Path(tmp.name)
        self.reader = StateReader(self.st)

    def env(self, **cfg):
        p = self.st / "config.json"
        p.write_text(json.dumps(cfg))
        return {"LIMITLESS_CONFIG": str(p)}

    def db(self, unlocks, spans):
        make_db(self.st / "aw.db", unlocks=unlocks, spans=spans)

    def call(self, env, raw=False):
        return tools.feed_reflex(self.reader, NOW, raw=raw, env=env, tz=UTC)

    def test_often_in_words_and_counts_only_with_raw(self):
        self.db(*often_spans())
        env = self.env(aw_db="aw.db", feed_apps=["FeedApp"])
        out = self.call(env)
        self.assertEqual(set(out) - {"label"}, {"value", "modality", "age_h", "evidence_tier"})
        self.assertEqual(out["modality"], "proxy")
        self.assertEqual(out["evidence_tier"], "indirect")
        self.assertEqual(out["value"], {"label": feed_reflex.OFTEN})
        self.assertEqual(out["label"], {"tier": "T1", "modality": "proxy", "label": feed_reflex.OFTEN})
        self.assertNotRegex(json.dumps(out["value"]), r"\d")
        self.assertIsNotNone(out["age_h"])
        raw = self.call(env, raw=True)["value"]
        self.assertEqual((raw["unlocks"], raw["feed_first"]), (6, 4))
        self.assertEqual(sum(d["unlocks"] for d in raw["days"]), 6)
        self.assertEqual(raw["gap_s"], feed_reflex.REFLEX_GAP_S)

    def test_rarely(self):
        self.db(*often_spans(n=6, feed=0))
        out = self.call(self.env(aw_db="aw.db", feed_apps="feedapp, other"))
        self.assertEqual(out["value"]["label"], feed_reflex.RARELY)

    def test_the_desktop_source_is_never_read(self):
        self.db(*often_spans(n=6, feed=0))
        env = self.env(aw_db="aw.db", feed_apps=["feedapp"], desktop_aw_export="no-such-export.json")
        out = self.call(env)   # a set, unreadable desktop source changes nothing: only phone rows count
        self.assertEqual(out["value"]["label"], feed_reflex.RARELY)

    def test_no_feed_apps_is_unknown_with_a_reason(self):
        self.db(*often_spans())
        out = self.call(self.env(aw_db="aw.db"))
        self.assertIsNone(out["value"])
        self.assertEqual(out["evidence_tier"], "none")
        self.assertIn("feed_apps", out["reason"])
        self.assertEqual(out["label"]["label"], "unknown: " + feed_reflex.NO_FEEDS)

    def test_no_db_or_no_unlock_is_unknown_never_zero(self):
        out = self.call(self.env(feed_apps=["feedapp"]))
        self.assertIsNone(out["value"])
        self.assertTrue(out["label"]["label"].startswith("unknown: "))
        self.db([], [(NOW - 2 * H, NOW - H, "feedapp")])
        out = self.call(self.env(aw_db="aw.db", feed_apps=["feedapp"]))
        self.assertIsNone(out["value"])
        self.assertEqual(out["label"]["label"], "unknown: " + feed_reflex.NO_UNLOCKS)
        self.assertEqual(self.call(self.env(aw_db="aw.db", feed_apps=["feedapp"]), raw=True)["value"], None)

    def test_too_few_unlocks_is_unknown(self):
        self.db(*often_spans(n=2, feed=2))
        out = self.call(self.env(aw_db="aw.db", feed_apps=["feedapp"]))
        self.assertIsNone(out["value"])
        self.assertEqual(out["label"]["label"], "unknown: " + feed_reflex.TOO_FEW)

    def test_the_gap_is_config(self):
        unlocks = [NOW - (i + 2) * H for i in range(6)]
        spans = [(u + 40, u + 300, "feedapp") for u in unlocks]
        self.db(unlocks, spans)
        self.assertEqual(self.call(self.env(aw_db="aw.db", feed_apps=["feedapp"]))["value"]["label"],
                         feed_reflex.RARELY)
        self.assertEqual(self.call(self.env(aw_db="aw.db", feed_apps=["feedapp"], feed_reflex_gap_s=60))
                         ["value"]["label"], feed_reflex.OFTEN)

    def test_nothing_written(self):
        self.db(*often_spans())
        env = self.env(aw_db="aw.db", feed_apps=["feedapp"])
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.st.iterdir()}
        self.call(env)
        self.call(env, raw=True)
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.st.iterdir()}
        self.assertEqual(before, after)



class Plugin(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.st = Path(tmp.name)

    def test_registered_read_only_with_no_arguments_in_manifest_order(self):
        from unittest import mock
        from limitless import plugin
        from test_plugin import FakeCtx, manifest_list
        self.assertIn("limitless_feed_reflex", plugin.TOOLS)
        listed = manifest_list("provides_tools")
        self.assertEqual(listed.index("limitless_feed_reflex"), listed.index("limitless_flow_ledger") + 1)
        ctx = FakeCtx()
        plugin.register(ctx)
        t = ctx.tools["limitless_feed_reflex"]
        self.assertEqual(t["schema"]["parameters"]["properties"], {})
        for word in ("unlock", "feed", "Read-only", "raw opt-in", "never blocks"):
            self.assertIn(word, t["schema"]["description"])
        make_db(self.st / "aw.db", *often_spans())
        cfg = self.st / "config.json"
        cfg.write_text(json.dumps({"aw_db": "aw.db", "feed_apps": ["feedapp"]}))
        env = {"LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(cfg)}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch("time.time", return_value=NOW):
            out = json.loads(t["handler"]({}))
        self.assertEqual(out["modality"], "proxy")
        self.assertIn(out["value"]["label"], feed_reflex.WORDS)
        self.assertNotIn("unlocks", out["value"])


if __name__ == "__main__":
    unittest.main()
