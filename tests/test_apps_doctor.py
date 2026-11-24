"""The doctor's apps lists row: off, set from config or set from a reply, in words; never an app name.

Synthetic app names only.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import apps_reply, doctor, feed_reflex  # noqa: E402

NOW = 1894708800.0
NAMES = ("synthetic-editor-app", "synthetic-feed-app")


class Row(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.st = Path(tmp.name)
        p = mock.patch.dict(os.environ, {}, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def reply(self, text):
        apps_reply.ingest(self.st, [(NOW - 60, text)], NOW, dry_run=False)

    def row(self, **cfg):
        cfg.setdefault("state", str(self.st))
        r = doctor.apps_row(cfg)
        self.assertEqual((r["name"], r["kind"]), (doctor.APPS_ROW, "source"))
        for n in NAMES:
            self.assertNotIn(n, json.dumps(r))
        self.assertNotRegex(r["reason"], r"\d")
        return r

    def test_off_when_none_set(self):
        r = self.row()
        self.assertEqual(r["status"], doctor.OFF)
        self.assertEqual(r["reason"], doctor.APPS_OFF)

    def test_set_from_config(self):
        r = self.row(flow_work_apps=[NAMES[0]], feed_apps=[NAMES[1]])
        self.assertEqual(r["status"], doctor.LIVE)
        self.assertEqual(r["reason"], "work apps set from config; feed apps set from config")

    def test_set_from_a_reply(self):
        self.reply(f"work apps: {NAMES[0]}\nfeed apps: {NAMES[1]}")
        r = self.row()
        self.assertEqual(r["status"], doctor.LIVE)
        self.assertEqual(r["reason"], "work apps set from a reply; feed apps set from a reply")

    def test_mixed_and_one_unset(self):
        self.reply(f"feed apps: {NAMES[1]}")
        r = self.row(flow_work_apps=[NAMES[0]])
        self.assertEqual(r["reason"], "work apps set from config; feed apps set from a reply")
        r = self.row()
        self.assertEqual(r["reason"], "work apps not set; feed apps set from a reply")

    def test_config_beats_a_reply_in_the_row(self):
        self.reply(f"work apps: {NAMES[0]}")
        self.assertEqual(self.row(flow_work_apps=["cfg-editor"])["reason"],
                         "work apps set from config; feed apps not set")

    def test_the_env(self):
        with mock.patch.dict(os.environ, {"LIMITLESS_FLOW_WORK_APPS": NAMES[0]}):
            self.assertEqual(self.row()["reason"], "work apps set from the environment; feed apps not set")

    def test_the_report_has_it_after_the_feed_reflex_row_and_no_name_anywhere(self):
        self.reply(f"work apps: {NAMES[0]}\nfeed apps: {NAMES[1]}")
        rows = doctor.report({"state": str(self.st)}, NOW)
        names = [r["name"] for r in rows]
        self.assertEqual(names.index(doctor.APPS_ROW), names.index(doctor.FEED_REFLEX_ROW) + 1)
        for n in NAMES:
            self.assertNotIn(n, json.dumps(rows))

    def test_the_feed_reflex_label_never_names_an_app(self):
        self.reply(f"feed apps: {NAMES[1]}")
        got = feed_reflex.from_settings({}, self.st, NOW - 7 * 86400, NOW, env={})
        self.assertNotIn(NAMES[1], got["label"])
        self.assertNotIn(NAMES[1], json.dumps(doctor.feed_reflex_row({"state": str(self.st)}, NOW)))


if __name__ == "__main__":
    unittest.main()
