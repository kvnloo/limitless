"""The NOOP export as an event job: limitless-jobs runs noop_export.main in-process after a sync that copied the
NOOP database (its runs.jsonl row says so in ``noop``), once per such row, as config ``noop_export`` says.

Synthetic runs.jsonl rows and the synthetic NOOP DB of tests/noop_fixture.py only. UTC stands in for the local
zone. Nothing here sends, pushes or starts a process.
"""
import json
import os
import re
import stat
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import jobs, jobs_runner  # noqa: E402
from noop_fixture import RING, hr_before, make_db, stages  # noqa: E402

UTC = timezone.utc
H = 3600
FIRST = date(2030, 1, 1)
NOW = datetime(2030, 1, 6, 9, 0, tzinfo=UTC).timestamp()
JOB = "NOOP export"


def at(d, hh, mm=0):
    return int(datetime.combine(d, time(hh, mm), UTC).timestamp())


def iso(t):
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def nights(n, first=FIRST, bpm=60):
    sessions, hr = [], []
    for i in range(n):
        on = at(first + timedelta(days=i), 23)
        sessions.append((RING, on, on + 8 * H, 0.9, stages(on, 7 * H, H)))
        hr += hr_before(RING, on, bpm + (i % 3))
    return sessions, hr


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.st = self.dir / "state"
        self.st.mkdir()
        self.cfg_path = self.dir / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg_path), "LIMITLESS_STATE": str(self.st)}
        self.sleep = self.st / "sleep.jsonl"
        self.pre = self.st / "presleep-hr.jsonl"
        self.mark = self.st / "noop-export.json"
        sessions, hr = nights(4)
        make_db(self.st / "noop-copy.db", sessions=sessions, hr=hr)

    def config(self, **kw):
        cfg = {"noop_db": "noop-copy.db", "sleep_file": "sleep.jsonl", "presleep_hr_file": "presleep-hr.jsonl"}
        cfg.update(kw)
        self.cfg_path.write_text(json.dumps({k: v for k, v in cfg.items() if v is not None}))

    def runs(self, *rows):
        (self.st / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def copied(self, t, **kw):
        row = {"at": iso(t), "job": "sync", "ok": True, "took_s": 9.5, "noop": {"copied": True}}
        row.update(kw)
        return row

    def once(self, now=NOW, dry_run=False):
        return jobs_runner.run_once(self.st, now, push=None, dry_run=dry_run, env=self.env, home=self.dir, tz=UTC)

    def row(self, rows):
        got = [r for r in rows if r["job"] == JOB]
        self.assertEqual(len(got), 1, rows)
        return got[0]

    def load_mark(self):
        return json.loads(self.mark.read_text())


class Off(Base):
    def test_off_is_the_default_and_never_due(self):
        self.config()
        self.runs(self.copied(NOW - H))
        rows = self.once()
        self.assertEqual([r for r in rows if r["job"] == JOB], [])
        self.assertEqual(len(rows), len(jobs.SPECS))
        self.assertFalse(self.mark.exists())
        self.assertFalse(self.sleep.exists())
        self.assertFalse(self.pre.exists())

    def test_off_said_in_words_is_off_too(self):
        for v in ("off", "OFF", False, None, "sometimes"):
            self.config(noop_export=v)
            self.runs(self.copied(NOW - H))
            self.assertEqual([r for r in self.once() if r["job"] == JOB], [], v)
            self.assertFalse(self.mark.exists(), v)


class Due(Base):
    def test_due_once_per_fresh_copy_row_and_not_again_for_the_same_row(self):
        self.config(noop_export="dry_run")
        self.runs(self.copied(NOW - 2 * H))
        first = self.row(self.once())
        self.assertEqual(first["action"], jobs.RUN, first)
        self.assertEqual(self.load_mark()["row_at"], NOW - 2 * H)
        again = self.row(self.once(NOW + 60))
        self.assertEqual(again["action"], jobs.DROP, again)
        self.assertIn("already ran after this sync", again["reason"])
        self.runs(self.copied(NOW - 2 * H), self.copied(NOW))
        third = self.row(self.once(NOW + 120))
        self.assertEqual(third["action"], jobs.RUN, third)
        self.assertEqual(self.load_mark()["row_at"], NOW)

    def test_not_due_when_the_newest_row_did_not_copy_the_noop_database(self):
        self.config(noop_export="dry_run")
        for last in ({"at": iso(NOW - H), "job": "sync", "ok": True},
                     {"at": iso(NOW - H), "job": "sync", "ok": True, "noop": {"copied": False}},
                     {"at": iso(NOW - H), "job": "sync", "ok": True, "noop": False},
                     self.copied(NOW - H, ok=False)):
            self.runs(self.copied(NOW - 3 * H), last)
            r = self.row(self.once())
            self.assertEqual(r["action"], jobs.NOT_TRIGGERED, (last, r))
            self.assertFalse(self.mark.exists(), last)

    def test_no_runs_file_is_not_triggered(self):
        self.config(noop_export="dry_run")
        r = self.row(self.once())
        self.assertEqual(r["action"], jobs.NOT_TRIGGERED)
        self.assertIn("no sync run", r["reason"])

    def test_the_noop_field_says_copied_in_any_of_its_forms(self):
        for v in (True, "copied", "fresh", {"copied": True}, {"fresh": True}):
            self.assertTrue(jobs.noop_copied({"at": iso(NOW), "noop": v}), v)
        for v in (None, False, "", "stale", {"copied": False}, {"available": True}, 1, [True]):
            self.assertFalse(jobs.noop_copied({"at": iso(NOW), "noop": v}), v)
        self.assertFalse(jobs.noop_copied({"at": iso(NOW), "ok": False, "noop": True}))
        self.assertFalse(jobs.noop_copied({"noop": True}), "no time, no event")

    def test_a_dry_run_of_limitless_jobs_gives_the_verdict_and_writes_nothing(self):
        self.config(noop_export="write")
        self.runs(self.copied(NOW - H))
        r = self.row(self.once(dry_run=True))
        self.assertEqual(r["action"], jobs.RUN)
        self.assertIn("not run", r["reason"])
        self.assertFalse(self.mark.exists())
        self.assertFalse(self.sleep.exists())

    def test_a_copy_row_from_the_future_is_not_acted_on(self):
        self.config(noop_export="dry_run")
        self.runs(self.copied(NOW + H))
        r = self.row(self.once())
        self.assertEqual(r["action"], jobs.NOT_TRIGGERED)
        self.assertFalse(self.mark.exists())


class DryRunMode(Base):
    def test_dry_run_reads_and_records_counts_only(self):
        self.config(noop_export="dry_run")
        self.runs(self.copied(NOW - H))
        r = self.row(self.once())
        self.assertEqual(r["action"], jobs.RUN, r)
        self.assertFalse(self.sleep.exists())
        self.assertFalse(self.pre.exists())
        m = self.load_mark()
        self.assertEqual(m["mode"], "dry_run")
        self.assertEqual(m["outcome"], "done")
        self.assertIn("four nights of wearable sleep", " ".join(m["said"]))
        self.assertIn("four nights of wearable sleep", r["reason"])


if __name__ == "__main__":
    unittest.main()
