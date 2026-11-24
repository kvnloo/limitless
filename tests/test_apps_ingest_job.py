"""The apps ingest as an event job: limitless-jobs reads the "work apps: ..." / "feed apps: ..." reply from the
Hermes session DB once per new sync row in runs.jsonl, as config ``apps_ingest`` says (off, dry_run, write).

Synthetic runs.jsonl rows and the synthetic session DB of tests/hermes_db_fixture.py only. Nothing here sends,
pushes or starts a process.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
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
            wrote = {"wrote_at", "wrote"} if mode == "write" else set()     # which lists, in words
            self.assertEqual(set(self.load_mark()), {"row_at", "ran_at", "mode", "action"} | wrote)


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


CLOCK = r"\d{1,2}:\d{2}|\b\d{1,2}\s*(am|pm)\b|\bcron\b|\*/"


class ScheduleCard(Base):
    def card(self):
        from limitless import schedule_cards
        return schedule_cards.apps_ingest_card()

    def test_one_card_on_the_sync_event_that_sends_nothing(self):
        from limitless import schedule_cards
        c = self.card()
        self.assertEqual(set(c), {"id", "kind", "name", "description", "trigger", "ends", "window",
                                  "stale_after_s", "once_key", "budget", "per_window", "sender", "words"})
        self.assertEqual((c["id"], c["kind"], c["name"]), ("apps_ingest", "schedule", JOB))
        self.assertEqual((c["trigger"], c["ends"]), ("sync", "sync"))
        self.assertIn(c["trigger"], jobs.EVENTS)
        self.assertEqual((c["budget"], c["sender"], c["per_window"]), (0, schedule_cards.LOCAL, 1))
        self.assertEqual(c["once_key"], "apps_ingest:<sync run time>")
        self.assertIn("after each sync run", c["description"])
        self.assertIn("nothing is sent", c["description"])
        self.assertEqual(c["words"]["runs"], "limitless-jobs --ingest or --send")

    def test_the_card_is_digit_free_with_no_clock_no_id_and_no_name(self):
        c = self.card()
        self.assertNotRegex(c["description"], r"\d")
        self.assertNotRegex(c["once_key"].replace("<sync run time>", ""), CLOCK)
        for k, v in c["words"].items():
            self.assertNotRegex(v, r"\d", k)
            self.assertNotIn("_", v, k)
        self.assertNoNames(json.dumps(c))

    def test_cards_add_it_only_when_the_job_is_on(self):
        from limitless import schedule_cards
        self.assertEqual([x["id"] for x in schedule_cards.cards()], list(jobs.SPECS))
        self.assertEqual([x["id"] for x in schedule_cards.cards(noop=True, apps=True)],
                         list(jobs.SPECS) + ["noop_export", "apps_ingest"])

    def test_the_schedule_tool_shows_it_when_config_turns_it_on(self):
        from limitless import tools
        from limitless.state_reader import StateReader
        self.config()
        ids = [x["id"] for x in tools.schedule(StateReader(self.st), NOW, self.env, self.dir)["value"]["cards"]]
        self.assertNotIn("apps_ingest", ids)
        self.config(apps_ingest="dry_run")
        got = tools.schedule(StateReader(self.st), NOW, self.env, self.dir)
        self.assertIn("apps_ingest", [x["id"] for x in got["value"]["cards"]])
        self.assertIn("label", got, "the plain words stay digit-free")

    def test_a_host_gets_the_card_at_register_when_the_job_is_on(self):
        sys.path.insert(0, str(ROOT / "tests"))
        from test_schedule_register import CardCtx, HostRegistration
        self.config(apps_ingest="write")
        ctx = CardCtx()
        reg = HostRegistration("test_the_method_name_is_the_documented_one")
        reg.register(ctx, {"LIMITLESS_CONFIG": str(self.cfg_path), "LIMITLESS_STATE": str(self.st)})
        reg.doCleanups()
        self.assertEqual([c["id"] for c in ctx.cards], list(jobs.SPECS) + ["apps_ingest"])


class Doctor(Base):
    def doc_row(self, now=NOW):
        from limitless import doctor
        from limitless.state_reader import StateReader, config
        return doctor.apps_ingest_row(StateReader(self.st), config(self.env, self.dir), now, env=self.env)

    def check(self, r, status, *words):
        self.assertEqual((r["name"], r["kind"], r["status"]), ("job apps ingest", "job", status), r)
        for w in words:
            self.assertIn(w, r["reason"])
        self.assertNotRegex(r["reason"], r"\d")
        self.assertNotIn("/", r["reason"])
        self.assertNoNames(r["reason"])

    def test_off_by_default(self):
        self.config()
        self.check(self.doc_row(), "off", "off (config apps_ingest)")

    def test_on_with_no_hermes_db_is_stale_and_skipped(self):
        self.config(apps_ingest="write", hermes_db=None)
        self.runs(sync(NOW - H))
        self.check(self.doc_row(), "stale", "no Hermes DB set (config hermes_db)")

    def test_on_with_no_sync_yet_is_stale(self):
        self.config(apps_ingest="write")
        self.check(self.doc_row(), "stale", "no sync run")

    def test_a_sync_it_has_not_run_after_is_stale(self):
        self.config(apps_ingest="write")
        self.runs(sync(NOW - H))
        self.check(self.doc_row(), "stale", "has not run after it", "limitless-jobs --ingest or --send runs it")

    def test_live_after_a_write(self):
        self.config(apps_ingest="write")
        self.runs(sync(NOW - 3 * H))
        self.once(NOW - 2 * H)
        self.check(self.doc_row(), "live", "write mode", "about two hours ago", "wrote the app lists")

    def test_live_in_dry_run_says_it_writes_nothing(self):
        self.config(apps_ingest="dry_run")
        self.runs(sync(NOW - H))
        self.once()
        self.check(self.doc_row(), "live", "dry run", "would write the app lists", "under an hour ago")

    def test_live_with_nothing_new(self):
        self.config(apps_ingest="write")
        self.runs(sync(NOW - H))
        self.once()
        self.runs(sync(NOW - H), sync(NOW))
        self.once(NOW + 60)
        self.check(self.doc_row(NOW + 60), "live", "no new apps reply")

    def test_the_row_follows_the_apps_ask_row_and_strict_ignores_it(self):
        from limitless import doctor
        from unittest import mock
        self.config(apps_ingest="write")
        with mock.patch.dict(os.environ, self.env):
            rows = doctor.report({"state": str(self.st), "apps_ingest": "write"}, NOW)
        names = [r["name"] for r in rows]
        self.assertEqual(names.index(doctor.APPS_ASK_ROW), names.index(doctor.APPS_ROW) + 1)
        self.assertEqual(names.index("job apps ingest"), names.index(doctor.APPS_ASK_ROW) + 1)
        self.assertEqual(names[-1], "job NOOP export")
        r = rows[names.index("job apps ingest")]
        self.assertEqual(r["kind"], "job")
        live = [dict(x, status="live") for x in rows if x["kind"] != "job"]
        self.assertFalse(doctor.strict_failed(live + [r]))


class T1Line(Base):
    def test_a_write_returns_one_plain_t1_line_and_sends_nothing(self):
        self.config(apps_ingest="write")
        self.runs(sync(NOW - H))
        pushed = []
        rows = jobs_runner.run_once(self.st, NOW, push=lambda *a, **k: pushed.append(a), dry_run=False,
                                    env=self.env, home=self.dir, tz=UTC)
        r = self.row(rows)
        self.assertEqual(r["line"], "app lists set from your reply")
        self.assertEqual(pushed, [], "the job sends nothing")
        self.assertFalse((self.st / jobs_runner.SENT_LOG).exists())
        self.assertEqual(jobs_runner.apps_ingest_label(self.st),
                         {"label": "app lists set from your reply", "tier": "T1", "modality": "derived"})

    def test_no_label_unless_the_last_run_wrote(self):
        self.assertIsNone(jobs_runner.apps_ingest_label(self.st))
        self.config(apps_ingest="dry_run")
        self.runs(sync(NOW - H))
        self.once()
        self.assertIsNone(jobs_runner.apps_ingest_label(self.st))
        self.config(apps_ingest="write")
        self.runs(sync(NOW - H), sync(NOW))
        self.once(NOW + 60)
        self.assertIsNotNone(jobs_runner.apps_ingest_label(self.st))
        self.runs(sync(NOW - H), sync(NOW), sync(NOW + 90))
        self.once(NOW + 120)          # nothing new after the write: the lists were not set by this run
        self.assertIsNone(jobs_runner.apps_ingest_label(self.st))

    def test_the_line_is_digit_free_and_names_nothing(self):
        self.assertNotRegex(jobs.APPS_LINE, r"\d")
        self.assertNoNames(jobs.APPS_LINE)


if __name__ == "__main__":
    unittest.main()
