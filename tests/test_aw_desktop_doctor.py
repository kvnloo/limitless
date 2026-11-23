"""The doctor's desktop AW row: off, live, stale or unreachable, in words only. Synthetic server, no network."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import aw_desktop, doctor  # noqa: E402
from test_aw_desktop import PLANTED, FakeFetch, server  # noqa: E402

NOW = 1894708800.0
H = 3600.0
URL = "http://desk.example.invalid:5600"


def ev(start_h_ago, end_h_ago, **data):
    s = NOW - start_h_ago * H
    return {"timestamp": datetime.fromtimestamp(s, timezone.utc).isoformat(),
            "duration": (start_h_ago - end_h_ago) * H, "data": data}


def never(url, timeout):
    raise AssertionError("fetch must not be called")


class Row(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.st = Path(self.tmp.name)
        aw_desktop._HOLD.clear()
        self.addCleanup(aw_desktop._HOLD.clear)

    def row(self, fetch, **cfg):
        cfg.setdefault("state", str(self.st))
        return doctor.desktop_aw_row(cfg, NOW, fetch=fetch)

    def check(self, r, status, first):
        self.assertEqual((r["name"], r["kind"], r["status"]), (doctor.DESKTOP_AW_ROW, "source", status), r)
        if first:
            self.assertTrue(r["reason"].startswith(first + ":"), r)
        self.assertNotRegex(r["reason"], r"\d")
        self.assertNotIn("example", r["reason"])
        self.assertNotIn(PLANTED, json.dumps(r))

    def test_off_when_unset_and_no_fetch(self):
        r = self.row(never)
        self.check(r, doctor.OFF, None)
        self.assertIn("not set", r["reason"])
        self.assertEqual(doctor.text([r]), f"desktop AW: off: {aw_desktop.OFF_WHY}")

    def test_live_with_activity_in_the_last_day(self):
        f = FakeFetch(server([ev(3, 2, app="editor", title=PLANTED)], [ev(4, 1, status="not-afk")]))
        r = self.row(f, desktop_aw_url=URL)
        self.check(r, doctor.LIVE, None)
        self.assertIn("about two hours ago", r["reason"])

    def test_stale_when_it_answers_with_no_recent_activity(self):
        f = FakeFetch(server([], []))
        self.check(self.row(f, desktop_aw_url=URL), doctor.STALE, None)
        f = FakeFetch(server([ev(3, 2, app="editor")], [ev(3, 2, status="afk")]))
        self.check(self.row(f, desktop_aw_url=URL), doctor.STALE, None)

    def test_unreachable_when_it_does_not_answer(self):
        r = self.row(FakeFetch({}, fail=OSError("refused")), desktop_aw_url=URL)
        self.check(r, doctor.MISSING, "unreachable")
        self.assertIn(aw_desktop.NO_ANSWER, r["reason"])

    def test_unreachable_says_why_for_data_it_cannot_use(self):
        r = self.row(FakeFetch(server([ev(3, 2, app="editor")], None)), desktop_aw_url=URL)
        self.check(r, doctor.MISSING, "unreachable")
        self.assertIn("afk bucket", r["reason"])

    def test_an_export_file_is_read_relative_to_the_state_dir(self):
        b = server([ev(3, 2, app="editor", title=PLANTED)], [ev(4, 1, status="not-afk")])
        (self.st / "desk.json").write_text(json.dumps({"buckets": b}))
        self.check(self.row(never, desktop_aw_export="desk.json"), doctor.LIVE, None)
        self.check(self.row(never, desktop_aw_export="nope.json"), doctor.MISSING, "unreachable")

    def test_the_report_has_the_row_and_strict_does_not_count_it(self):
        cfg = {"state": str(self.st)}
        with mock.patch.dict(os.environ, {"LIMITLESS_STATE": str(self.st)}):
            rows = doctor.report(cfg, NOW)
        names = [r["name"] for r in rows]
        self.assertIn(doctor.DESKTOP_AW_ROW, names)
        r = rows[names.index(doctor.DESKTOP_AW_ROW)]
        self.assertEqual(r["status"], doctor.OFF)
        self.assertNotIn("source", doctor.STRICT_KINDS)


if __name__ == "__main__":
    unittest.main()
