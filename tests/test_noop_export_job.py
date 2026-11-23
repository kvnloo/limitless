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


class WriteMode(Base):
    def test_write_mode_writes_both_files_and_a_rerun_is_byte_identical(self):
        self.config(noop_export="write")
        self.runs(self.copied(NOW - 2 * H))
        r = self.row(self.once())
        self.assertEqual(r["action"], jobs.RUN, r)
        self.assertIn("sleep file: written, four nights new or changed", r["reason"])
        self.assertEqual(len(self.sleep.read_text().splitlines()), 4)
        self.assertEqual(len(self.pre.read_text().splitlines()), 4)
        for p in (self.sleep, self.pre):
            self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)
        before = {p: (p.read_bytes(), os.stat(p).st_mtime_ns) for p in (self.sleep, self.pre)}
        self.runs(self.copied(NOW - 2 * H), self.copied(NOW - H))      # the next sync copied the same DB again
        again = self.row(self.once(NOW + 60))
        self.assertEqual(again["action"], jobs.RUN, again)
        self.assertIn("sleep file: unchanged", again["reason"])
        self.assertIn("pre-sleep heart-rate file: unchanged", again["reason"])
        self.assertEqual({p: (p.read_bytes(), os.stat(p).st_mtime_ns) for p in (self.sleep, self.pre)}, before)
        self.assertEqual(self.load_mark()["outcome"], "done")


class PlainReasons(Base):
    def test_no_noop_db_is_the_plain_reason_recorded_once_never_a_loop(self):
        self.config(noop_export="write", noop_db=None)
        self.runs(self.copied(NOW - H))
        r = self.row(self.once())
        self.assertEqual(r["action"], jobs.RUN)
        self.assertIn("no NOOP database configured", r["reason"])
        m = self.load_mark()
        self.assertEqual((m["outcome"], m["row_at"]), ("nothing to export", NOW - H))
        self.assertEqual(self.row(self.once(NOW + 60))["action"], jobs.DROP, "the same copy is not retried")
        self.assertFalse(self.sleep.exists())

    def test_a_missing_db_file_is_nothing_to_export(self):
        self.config(noop_export="write", noop_db="gone.db")
        self.runs(self.copied(NOW - H))
        self.assertIn("no NOOP database at the configured path", self.row(self.once())["reason"])
        self.assertEqual(self.load_mark()["outcome"], "nothing to export")

    def test_an_unconfigured_output_is_named_and_the_other_still_written(self):
        for missing, written, other in (("sleep_file", self.pre, self.sleep),
                                        ("presleep_hr_file", self.sleep, self.pre)):
            for p in (self.sleep, self.pre, self.mark):
                if p.exists():
                    p.unlink()
            self.config(noop_export="write", **{missing: None})
            self.runs(self.copied(NOW - H))
            r = self.row(self.once())
            self.assertIn(f'not configured (set "{missing}" in config.json), not written', r["reason"])
            self.assertTrue(written.exists(), missing)
            self.assertFalse(other.exists(), missing)
            self.assertEqual(self.load_mark()["outcome"], "done")
            self.assertEqual(self.row(self.once(NOW + 60))["action"], jobs.DROP)


class MarkFile(Base):
    def test_mark_is_0600_digit_free_except_epochs_and_has_no_path(self):
        self.config(noop_export="write")
        self.runs(self.copied(NOW - H))
        self.once()
        self.assertEqual(stat.S_IMODE(os.stat(self.mark).st_mode), 0o600)
        m = self.load_mark()
        self.assertEqual(set(m), {"row_at", "ran_at", "mode", "outcome", "said"})
        self.assertEqual((m["row_at"], m["ran_at"]), (NOW - H, NOW))
        rest = json.dumps({k: v for k, v in m.items() if k not in ("row_at", "ran_at")})
        self.assertNotRegex(rest, r"\d")
        for bad in ("/", "\\", self.tmp.name, "noop-copy", ".db", ".jsonl", RING, "bpm", "asleep_s"):
            self.assertNotIn(bad, self.mark.read_text(), bad)
        self.assertEqual([p.name for p in self.st.iterdir() if p.name.startswith(".")], [], "no temp file left")

    def test_a_malformed_mark_is_no_mark(self):
        self.config(noop_export="dry_run")
        self.runs(self.copied(NOW - H))
        self.mark.write_text("not json")
        self.assertEqual(self.row(self.once())["action"], jobs.RUN)
        self.assertEqual(self.load_mark()["row_at"], NOW - H)


class NeverSends(Base):
    def test_it_never_pushes_even_with_a_push_and_send(self):
        calls = []
        self.config(noop_export="write")
        self.runs(self.copied(NOW - H))
        rows = jobs_runner.run_once(self.st, NOW, push=lambda *a, **k: calls.append(a) or "telegram",
                                    dry_run=False, env=self.env, home=self.dir, tz=UTC)
        self.assertEqual(self.row(rows)["action"], jobs.RUN)
        self.assertEqual(calls, [])
        self.assertFalse((self.st / "jobs-sent.jsonl").exists())

    def test_the_job_module_starts_no_process_and_opens_no_socket(self):
        src = (ROOT / "limitless" / "jobs_runner.py").read_text()
        start = src.index("NOOP_MARK = ")
        part = src[start:src.index("def run_once(")]
        for word in ("subprocess", "os.system", "os.kill", "signal", "socket", "urllib", "Popen", "systemctl",
                     "push("):
            self.assertNotIn(word, part, word)


if __name__ == "__main__":
    unittest.main()
