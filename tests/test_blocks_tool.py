"""limitless_blocks: focus blocks as a read-only envelope (a proxy) with a plain T1 label. Synthetic data only."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import plugin, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from test_flow_week import make_db  # noqa: E402

NOW = 2_000_000_000.0
M = 60.0
LABELS = ("in a long block", "between blocks", "unknown")


class BlocksTool(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.db = self.root / "aw.db"
        self.cfg = self.root / "config.json"
        self.cfg.write_text(json.dumps({"flow_work_apps": ["editor"]}))
        self.env = {"LIMITLESS_CONFIG": str(self.cfg), "LIMITLESS_AW_DB": str(self.db),
                    "LIMITLESS_STATE": str(self.st)}

    def tearDown(self):
        self.tmp.cleanup()

    def tool(self, now=NOW, env=None):
        return tools.blocks(StateReader(self.st), now, env=self.env if env is None else env, home=self.root)

    def test_no_db_is_unknown_with_a_reason(self):
        out = self.tool(env={"LIMITLESS_CONFIG": str(self.cfg)})
        self.assertIsNone(out["value"])
        self.assertIn("aw_db", out["reason"])
        self.assertEqual(out["modality"], "proxy")
        self.assertEqual(out["label"], {"label": "unknown", "tier": "T1", "modality": "proxy"})

    def test_no_work_apps_is_unknown_never_zero(self):
        make_db(self.db, spans=[(NOW - 100 * M, NOW - M, "editor")])
        self.cfg.write_text("{}")
        out = self.tool()
        self.assertIsNone(out["value"])
        self.assertIn("flow_work_apps", out["reason"])
        self.assertEqual(out["label"]["label"], "unknown")

    def test_no_activity_rows_is_unknown(self):
        make_db(self.db, spans=[(NOW - 3 * 86400, NOW - 3 * 86400 + 600, "editor")])
        out = self.tool()
        self.assertIsNone(out["value"])
        self.assertEqual(out["label"]["label"], "unknown")

    def test_in_a_long_block(self):
        make_db(self.db, spans=[(NOW - 100 * M, NOW - 6 * M, "editor")])
        out = self.tool()
        self.assertEqual(out["value"], {"in_block": True, "long": True, "blocks": 1, "long_blocks": 1})
        self.assertEqual(out["label"], {"label": "in a long block", "tier": "T1", "modality": "proxy"})
        self.assertEqual((out["modality"], out["age_h"], out["evidence_tier"]), ("proxy", 0.1, "indirect"))

    def test_a_short_block_going_is_between_blocks(self):
        make_db(self.db, spans=[(NOW - 30 * M, NOW - M, "editor")])
        out = self.tool()
        self.assertEqual(out["value"], {"in_block": True, "long": False, "blocks": 1, "long_blocks": 0})
        self.assertEqual(out["label"]["label"], "between blocks")

    def test_after_a_long_block_is_between_blocks(self):
        make_db(self.db, spans=[(NOW - 200 * M, NOW - 60 * M, "editor"), (NOW - 60 * M, NOW - M, "scroller")])
        out = self.tool()
        self.assertEqual(out["value"], {"in_block": False, "long": False, "blocks": 1, "long_blocks": 1})
        self.assertEqual(out["label"]["label"], "between blocks")

    def test_labels_are_the_three_plain_words(self):
        make_db(self.db, spans=[(NOW - 100 * M, NOW - M, "editor")])
        for now in (NOW, NOW + 3600):
            self.assertIn(self.tool(now)["label"]["label"], LABELS)

    def test_read_only(self):
        make_db(self.db, spans=[(NOW - 100 * M, NOW - M, "editor")])
        before = (self.db.read_bytes(), sorted(p.name for p in self.st.iterdir()))
        self.tool()
        self.assertEqual((self.db.read_bytes(), sorted(p.name for p in self.st.iterdir())), before)

    def test_plugin_handler(self):
        make_db(self.db, spans=[(NOW - 100 * M, NOW - M, "editor")])
        self.assertIn("limitless_blocks", plugin.TOOLS)
        with mock.patch.dict(os.environ, self.env), mock.patch("time.time", return_value=NOW):
            res = json.loads(plugin._handler(plugin.TOOLS["limitless_blocks"][1])({}))
        self.assertEqual(res["label"]["label"], "in a long block")
        self.assertEqual(res["modality"], "proxy")


if __name__ == "__main__":
    unittest.main()
