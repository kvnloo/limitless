"""The doctor's Open Wearables row: off by config, live after a run that read the server, failing (status stale)
after a run that could not, in words only, from the mark open-wearables.json. It never calls the server.
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

from limitless import doctor, open_wearables as ow  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

NOW = 1894708800.0
H = 3600
NAME = "export Open Wearables"


class Row(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.st = Path(self.tmp.name)

    def mark(self, **kw):
        (self.st / ow.MARK).write_text(json.dumps(kw))

    def row(self, **cfg):
        return doctor.open_wearables_row(StateReader(self.st), cfg, NOW)

    def check(self, r, status, *words):
        self.assertEqual((r["name"], r["kind"], r["status"]), (NAME, "export", status), r)
        for w in words:
            self.assertIn(w, r["reason"])
        self.assertNotRegex(r["reason"], r"\d")

    def test_off_by_default(self):
        self.check(self.row(), "off", "the Open Wearables export is off (config open_wearables_export)")
        self.check(self.row(open_wearables_export="nope"), "off")

    def test_on_but_never_run(self):
        self.check(self.row(open_wearables_export="dry_run"), "stale", "on (dry run mode", "has not run yet")

    def test_live_after_a_run_that_read_the_server(self):
        self.mark(ran_at=NOW - 2 * H, mode="write", outcome="done", said="sleep file: written, two nights new or changed")
        self.check(self.row(open_wearables_export="write"), "live", "write mode: ran about two hours ago",
                   "sleep file: written")

    def test_failing_after_a_run_that_could_not_read_it(self):
        self.mark(ran_at=NOW - 3 * H, mode="write", outcome="failed", said=ow.REFUSED)
        self.check(self.row(open_wearables_export="write"), "stale", "failing", ow.REFUSED)

    def test_stale_when_the_last_good_run_is_over_a_day_old(self):
        self.mark(ran_at=NOW - 50 * H, mode="write", outcome="done", said="sleep file: unchanged")
        self.check(self.row(open_wearables_export="write"), "stale", "about two days ago")

    def test_a_malformed_mark_is_never_run(self):
        (self.st / ow.MARK).write_text("{not json")
        self.check(self.row(open_wearables_export="write"), "stale", "has not run yet")

    def test_the_report_has_the_row_before_the_noop_job_and_strict_ignores_it(self):
        cfg = {"state": str(self.st), "open_wearables_export": "write"}
        p = self.st / "config.json"
        p.write_text(json.dumps(cfg))
        env = {k: v for k, v in os.environ.items() if not k.startswith("LIMITLESS_")}
        env.update(HOME=str(self.st), LIMITLESS_CONFIG=str(p))
        with mock.patch.dict(os.environ, env, clear=True):
            rows = doctor.report(cfg, NOW)
        names = [r["name"] for r in rows]
        self.assertEqual(names[-2:], [NAME, "job NOOP export"])
        live = [dict(r, status="live") for r in rows if r["name"] != NAME]
        self.assertFalse(doctor.strict_failed(live + [rows[-2]]))


if __name__ == "__main__":
    unittest.main()
