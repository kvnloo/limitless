"""The apps ingest as an event job: limitless-jobs reads the "work apps: ..." / "feed apps: ..." reply from the
Hermes session DB once per new sync row in runs.jsonl, as config ``apps_ingest`` says (off, dry_run, write).

Synthetic runs.jsonl rows and the synthetic session DB of tests/hermes_db_fixture.py only. Nothing here sends,
pushes or starts a process.
"""
import json
import stat
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from limitless import apps_reply, jobs, jobs_runner  # noqa: E402
from hermes_db_fixture import make_db  # noqa: E402

UTC = timezone.utc
H = 3600
NOW = datetime(2030, 1, 6, 9, 0, tzinfo=UTC).timestamp()
JOB = "Apps ingest"
NAMES = ("editor", "terminal", "scrollerapp")
PRIVATE = "synthetic-private-words"


def iso(t):
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sync(t, **kw):
    row = {"at": iso(t), "job": "sync", "ok": True, "took_s": 9.5}
    row.update(kw)
    return row


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.st = self.dir / "state"
        self.st.mkdir()
        self.cfg_path = self.dir / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg_path), "LIMITLESS_STATE": str(self.st)}
        self.mark = self.st / "apps-ingest.json"
        self.apps = self.st / apps_reply.APPS_FILE
        make_db(self.st / "hermes.db", [("user", PRIVATE, NOW - 3 * H),
                                        ("user", "Work apps: editor, terminal\nfeed apps: scrollerapp", NOW - 2 * H),
                                        ("assistant", "work apps: not-from-the-person", NOW - 2 * H + 10)],
                started=NOW - 4 * H)

    def config(self, **kw):
        cfg = {"hermes_db": "hermes.db"}
        cfg.update(kw)
        self.cfg_path.write_text(json.dumps({k: v for k, v in cfg.items() if v is not None}))

    def runs(self, *rows):
        (self.st / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def once(self, now=NOW, dry_run=False):
        return jobs_runner.run_once(self.st, now, push=None, dry_run=dry_run, env=self.env, home=self.dir, tz=UTC)

    def row(self, rows):
        got = [r for r in rows if r["job"] == JOB]
        self.assertEqual(len(got), 1, rows)
        return got[0]

    def load_mark(self):
        return json.loads(self.mark.read_text())

    def assertNoNames(self, text):
        for w in NAMES + (PRIVATE, "not-from-the-person", "work apps:", "feed apps:"):
            self.assertNotIn(w, text)


class Off(Base):
    def test_off_is_the_default_and_does_nothing(self):
        self.config()
        self.runs(sync(NOW - H))
        rows = self.once()
        self.assertEqual([r for r in rows if r["job"] == JOB], [])
        self.assertFalse(self.mark.exists())
        self.assertFalse(self.apps.exists())

    def test_anything_but_dry_run_or_write_is_off(self):
        for v in ("off", "OFF", False, None, "sometimes", 1):
            self.config(apps_ingest=v)
            self.runs(sync(NOW - H))
            self.assertEqual([r for r in self.once() if r["job"] == JOB], [], v)
            self.assertFalse(self.mark.exists(), v)
            self.assertFalse(self.apps.exists(), v)

    def test_mode_reads_the_config(self):
        self.assertEqual(jobs.apps_mode({}), jobs.APPS_OFF)
        self.assertEqual(jobs.apps_mode({"apps_ingest": " Dry_Run "}), jobs.APPS_DRY_RUN)
        self.assertEqual(jobs.apps_mode({"apps_ingest": "write"}), jobs.APPS_WRITE)
        self.assertEqual(jobs.apps_mode(None), jobs.APPS_OFF)


class DryRun(Base):
    def test_dry_run_writes_only_the_mark(self):
        self.config(apps_ingest="dry_run")
        self.runs(sync(NOW - H))
        r = self.row(self.once())
        self.assertEqual(r["action"], jobs.RUN, r)
        self.assertIn("would write", r["reason"])
        self.assertFalse(self.apps.exists())
        m = self.load_mark()
        self.assertEqual((m["row_at"], m["ran_at"], m["mode"], m["action"]),
                         (NOW - H, NOW, "dry_run", "would write"))
        self.assertEqual(sorted(p.name for p in self.st.iterdir()), ["apps-ingest.json", "hermes.db", "runs.jsonl"])
        self.assertNotIn("line", r)

    def test_a_dry_run_of_limitless_jobs_reads_and_writes_nothing(self):
        self.config(apps_ingest="write")
        self.runs(sync(NOW - H))
        r = self.row(self.once(dry_run=True))
        self.assertEqual(r["action"], jobs.RUN)
        self.assertIn("not run", r["reason"])
        self.assertFalse(self.mark.exists())
        self.assertFalse(self.apps.exists())


class Write(Base):
    def test_write_writes_apps_json_0600_and_the_mark(self):
        self.config(apps_ingest="write")
        self.runs(sync(NOW - H))
        r = self.row(self.once())
        self.assertEqual(r["action"], jobs.RUN, r)
        self.assertEqual(apps_reply.load(self.st), {"since": apps_reply.iso(NOW - 2 * H),
                                                    "work_apps": ["editor", "terminal"],
                                                    "feed_apps": ["scrollerapp"]})
        self.assertEqual(stat.S_IMODE(self.apps.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.mark.stat().st_mode), 0o600)
        self.assertEqual(self.load_mark()["action"], "write")
        self.assertEqual([p.name for p in self.st.iterdir() if p.name.endswith(".tmp")], [], "no temp file left")

    def test_nothing_new_is_the_action_nothing(self):
        self.config(apps_ingest="write")
        self.runs(sync(NOW - H))
        self.once()
        self.runs(sync(NOW - H), sync(NOW))
        r = self.row(self.once(NOW + 60))
        self.assertEqual(r["action"], jobs.RUN, r)
        self.assertEqual(self.load_mark()["action"], "nothing")
        self.assertNotIn("line", r)

    def test_the_mark_and_the_row_never_hold_a_name_or_the_reply(self):
        for mode in ("dry_run", "write"):
            self.config(apps_ingest=mode)
            self.runs(sync(NOW - H))
            if self.mark.exists():
                self.mark.unlink()
            r = self.row(self.once())
            self.assertNoNames(self.mark.read_text())
            self.assertNoNames(json.dumps(r))
            self.assertEqual(set(self.load_mark()), {"row_at", "ran_at", "mode", "action"})


class Due(Base):
    def test_second_pass_after_the_same_sync_row_is_already_ran(self):
        self.config(apps_ingest="dry_run")
        self.runs(sync(NOW - H))
        self.assertEqual(self.row(self.once())["action"], jobs.RUN)
        again = self.row(self.once(NOW + 60))
        self.assertEqual(again["action"], jobs.DROP, again)
        self.assertIn("already ran after this sync", again["reason"])
        self.assertEqual(self.load_mark()["ran_at"], NOW, "the mark is not rewritten by a drop")
        self.runs(sync(NOW - H), sync(NOW + 90))
        third = self.row(self.once(NOW + 120))
        self.assertEqual(third["action"], jobs.RUN, third)
        self.assertEqual(self.load_mark()["row_at"], NOW + 90)

    def test_any_ok_sync_row_wakes_it_not_only_a_noop_copy(self):
        self.assertTrue(jobs.sync_ran(sync(NOW)))
        self.assertTrue(jobs.sync_ran(sync(NOW, noop={"copied": True})))
        self.assertFalse(jobs.sync_ran(sync(NOW, ok=False)))
        self.assertFalse(jobs.sync_ran({"job": "sync"}))
        self.assertFalse(jobs.sync_ran(None))

    def test_a_failed_newest_row_or_no_runs_file_is_not_triggered(self):
        self.config(apps_ingest="write")
        r = self.row(self.once())
        self.assertEqual(r["action"], jobs.NOT_TRIGGERED)
        self.assertIn("no sync run", r["reason"])
        self.runs(sync(NOW - 2 * H, ok=False))
        r = self.row(self.once())
        self.assertEqual(r["action"], jobs.NOT_TRIGGERED, r)
        self.assertFalse(self.mark.exists())
        self.assertFalse(self.apps.exists())

    def test_a_future_row_is_not_triggered(self):
        self.config(apps_ingest="write")
        self.runs(sync(NOW + H))
        self.assertEqual(self.row(self.once())["action"], jobs.NOT_TRIGGERED)

    def test_no_hermes_db_is_skipped_with_a_plain_reason(self):
        self.config(apps_ingest="write", hermes_db=None)
        self.runs(sync(NOW - H))
        r = self.row(self.once())
        self.assertEqual(r["action"], jobs.NOT_TRIGGERED, r)
        self.assertIn("skipped: no Hermes DB set (config hermes_db)", r["reason"])
        self.assertFalse(self.mark.exists())
        self.assertFalse(self.apps.exists())

    def test_the_db_comes_from_the_env_too(self):
        self.config(apps_ingest="write", hermes_db=None)
        self.env["LIMITLESS_HERMES_DB"] = str(self.st / "hermes.db")
        self.runs(sync(NOW - H))
        self.assertEqual(self.row(self.once())["action"], jobs.RUN)
        self.assertTrue(self.apps.exists())

    def test_never_on_a_clock_time(self):
        spec = jobs.APPS_INGEST
        self.assertEqual((spec.trigger_event, spec.expires), ("sync", "sync"))
        self.assertNotIn(spec.name, jobs.SPECS, "not a message job")


if __name__ == "__main__":
    unittest.main()
