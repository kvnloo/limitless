"""The doctor's apps ask row: off, waiting, told recently or not needed, in words only; never an app name.
Synthetic state dirs only.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import apps_ask, apps_reply, doctor  # noqa: E402

NOW = 1894708800.0
D = 86400.0


class Row(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.st = Path(tmp.name)
        p = mock.patch.dict(os.environ, {}, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def row(self, **cfg):
        cfg.setdefault("state", str(self.st))
        r = doctor.apps_ask_row(cfg, NOW)
        self.assertEqual((r["name"], r["kind"]), (doctor.APPS_ASK_ROW, "source"))
        self.assertEqual(doctor.APPS_ASK_ROW, "apps ask")
        self.assertNotRegex(r["reason"], r"\d")
        self.assertNotIn("zqeditor", json.dumps(r))
        return r

    def test_off(self):
        r = self.row(apps_ask="off")
        self.assertEqual((r["status"], r["reason"].split(":")[0]), (doctor.OFF, "off"))

    def test_waiting(self):
        r = self.row()
        self.assertEqual((r["status"], r["reason"].split(":")[0]), (doctor.LIVE, "waiting"))

    def test_told_recently_then_waiting_again(self):
        apps_ask.tell(self.st, NOW - 5 * D)
        r = self.row()
        self.assertEqual((r["status"], r["reason"].split(":")[0]), (doctor.LIVE, "told recently"))
        apps_ask.tell(self.st, NOW - 8 * D)
        self.assertEqual(self.row()["reason"].split(":")[0], "waiting")

    def test_not_needed_when_a_list_is_set(self):
        r = self.row(flow_work_apps=["zqeditor"])
        self.assertEqual((r["status"], r["reason"].split(":")[0]), (doctor.LIVE, "not needed"))
        apps_reply.ingest(self.st, [(NOW - 60, "feed apps: zqeditor")], NOW, dry_run=False)
        self.assertEqual(self.row()["reason"].split(":")[0], "not needed")

    def test_off_beats_not_needed(self):
        self.assertEqual(self.row(apps_ask=False, feed_apps=["zqeditor"])["status"], doctor.OFF)

    def test_the_report_has_it_right_after_the_apps_lists_row(self):
        rows = doctor.report({"state": str(self.st)}, NOW)
        names = [r["name"] for r in rows]
        self.assertEqual(names.index(doctor.APPS_ASK_ROW), names.index(doctor.APPS_ROW) + 1)

    def test_the_row_reads_no_app_time(self):
        with mock.patch("limitless.app_candidates.read_for", side_effect=AssertionError("read app time")):
            self.row()


if __name__ == "__main__":
    unittest.main()
