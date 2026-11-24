"""The owner drop-reply ingest as an event job: limitless-jobs reads the owner's "drop: <id>[, <id>...]" replies
from the Hermes session DB once per new sync row in runs.jsonl, as config ``ranked_ingest`` says (off, dry_run,
write), through ranked_ledger.ingest.

Synthetic ledgers, synthetic runs.jsonl rows and the synthetic session DB of tests/hermes_db_fixture.py only.
Invented ids only. Nothing here sends, pushes or starts a process.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import re
import stat
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from limitless import jobs, jobs_runner, ranked_ledger as rl, scorecard, tier_audit  # noqa: E402
from hermes_db_fixture import make_db  # noqa: E402

UTC = timezone.utc
H = 3600
NOW = datetime(2030, 1, 6, 9, 0, tzinfo=UTC).timestamp()
JOB = "Ranked ingest"
A, B, UNKNOWN = "synthetic-item-a", "synthetic-item-b", "synthetic-item-unknown"
PRIVATE = "synthetic-private-words"
OPEN = lambda i: {"id": i, "status": "open", "by": "agent", "evidence": ""}   # noqa: E731
DROP = lambda i: {"id": i, "status": "dropped", "by": scorecard.OWNER, "evidence": "owner reply"}   # noqa: E731
EPOCHS = ("row_at", "ran_at")


def iso(t):
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sync(t, **kw):
    row = {"at": iso(t), "job": "sync", "ok": True, "took_s": 9.5}
    row.update(kw)
    return row


def passes_tier_audit(text):
    return not tier_audit.event("cli:limitless-jobs", text, opt_in=False, now=NOW)["blocked"]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.st = self.dir / "state"
        self.st.mkdir()
        self.cfg_path = self.dir / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg_path), "LIMITLESS_STATE": str(self.st)}
        self.status = self.st / "ranked-ingest.json"
        self.drops = self.st / rl.MARK
        self.ledger = self.dir / "ranked.jsonl"
        self.ledger.write_text(json.dumps(OPEN(A)) + "\n" + json.dumps(OPEN(B)) + "\n")
        make_db(self.st / "hermes.db", [("user", PRIVATE, NOW - 3 * H),
                                        ("user", f"drop: {A}, {UNKNOWN}", NOW - 2 * H),
                                        ("assistant", f"drop: {B}", NOW - 2 * H + 10)],
                started=NOW - 4 * H)

    def config(self, **kw):
        cfg = {"hermes_db": "hermes.db", "ranked_ledger": str(self.ledger)}
        cfg.update(kw)
        self.cfg = {k: v for k, v in cfg.items() if v is not None}
        self.cfg_path.write_text(json.dumps(self.cfg))

    def runs(self, *rows):
        (self.st / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def once(self, now=NOW, dry_run=False):
        return jobs_runner.run_once(self.st, now, push=None, dry_run=dry_run, env=self.env, home=self.dir, tz=UTC)

    def row(self, rows):
        got = [r for r in rows if r["job"] == JOB]
        self.assertEqual(len(got), 1, rows)
        return got[0]

    def no_row(self, rows):
        self.assertEqual([r for r in rows if r["job"] == JOB], [])

    def ledger_rows(self):
        return [json.loads(ln) for ln in self.ledger.read_text().splitlines()]

    def row_ten(self):
        return rl.summary(self.st, self.cfg, self.env)

    def load_status(self):
        return json.loads(self.status.read_text())

    def assertNoSecrets(self, text):
        for w in (A, B, UNKNOWN, PRIVATE, "drop:", "owner reply", str(self.dir)):
            self.assertNotIn(w, text)

    def assertWordsOnly(self, text):
        self.assertNotRegex(text, r"\d", text)
        self.assertNoSecrets(text)
        self.assertTrue(passes_tier_audit(text), text)


class Off(Base):
    def test_off_is_the_default_and_reads_nothing(self):
        self.config()
        self.runs(sync(NOW - H))
        before = self.ledger.read_bytes()
        self.no_row(self.once())
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertFalse(self.status.exists())
        self.assertFalse(self.drops.exists())

    def test_anything_but_dry_run_or_write_is_off(self):
        for v in ("off", "OFF", False, None, "sometimes", 1, True):
            self.config(ranked_ingest=v)
            self.runs(sync(NOW - H))
            self.no_row(self.once())
            self.assertFalse(self.status.exists(), v)
            self.assertFalse(self.drops.exists(), v)

    def test_mode_reads_the_config(self):
        self.assertEqual(jobs.ranked_mode({}), jobs.RANKED_OFF)
        self.assertEqual(jobs.ranked_mode({"ranked_ingest": " Dry_Run "}), jobs.RANKED_DRY_RUN)
        self.assertEqual(jobs.ranked_mode({"ranked_ingest": "write"}), jobs.RANKED_WRITE)
        self.assertEqual(jobs.ranked_mode(None), jobs.RANKED_OFF)
        self.assertEqual(jobs.ranked_mode({"apps_ingest": "write"}), jobs.RANKED_OFF, "its own key")


class DryRun(Base):
    def test_dry_run_leaves_the_ledger_and_the_drops_mark_unchanged(self):
        self.config(ranked_ingest="dry_run")
        self.runs(sync(NOW - H))
        self.drops.write_text(json.dumps({"after": NOW - 5 * H}) + "\n")
        ledger, mark, ten = self.ledger.read_bytes(), self.drops.read_bytes(), self.row_ten()
        r = self.row(self.once())
        self.assertEqual(r["action"], jobs.RUN, r)
        self.assertIn("would append one owner drop row", r["reason"])
        self.assertEqual(self.ledger.read_bytes(), ledger)
        self.assertEqual(self.drops.read_bytes(), mark)
        self.assertEqual(self.row_ten(), ten, "row ten's counts move only in write mode")
        s = self.load_status()
        self.assertEqual((s["row_at"], s["ran_at"], s["mode"], s["action"]), (NOW - H, NOW, "dry_run", "would write"))
        self.assertNotIn("line", r)

    def test_dry_run_with_no_drops_mark_never_writes_one(self):
        self.config(ranked_ingest="dry_run")
        self.runs(sync(NOW - H))
        self.once()
        self.assertFalse(self.drops.exists())
        self.assertEqual(sorted(p.name for p in self.st.iterdir()),
                         ["hermes.db", "ranked-ingest.json", "runs.jsonl"])

    def test_a_dry_run_of_limitless_jobs_reads_and_writes_nothing(self):
        self.config(ranked_ingest="write")
        self.runs(sync(NOW - H))
        before = self.ledger.read_bytes()
        r = self.row(self.once(dry_run=True))
        self.assertEqual(r["action"], jobs.RUN)
        self.assertIn("not run", r["reason"])
        self.assertFalse(self.status.exists())
        self.assertFalse(self.drops.exists())
        self.assertEqual(self.ledger.read_bytes(), before)


class Write(Base):
    def test_a_drop_after_a_sync_moves_row_ten_in_write_mode(self):
        self.config(ranked_ingest="write")
        self.runs(sync(NOW - H))
        label, counts = self.row_ten()
        self.assertEqual(counts["owner_dropped"], 0)
        before = self.ledger.read_bytes()
        r = self.row(self.once())
        self.assertEqual(r["action"], jobs.RUN, r)
        self.assertIn("appended one owner drop row", r["reason"])
        self.assertTrue(self.ledger.read_bytes().startswith(before), "append only")
        self.assertEqual(self.ledger_rows()[2:], [DROP(A)])
        label2, counts2 = self.row_ten()
        self.assertEqual((counts2["owner_dropped"], counts2["open"], counts2["items"]), (1, 1, 2))
        self.assertNotEqual(label2, label)
        self.assertEqual(rl.load_mark(self.st), NOW - 2 * H, "the drops mark moves to the newest owner message")
        self.assertEqual(self.load_status()["action"], "write")

    def test_the_status_file_is_0600_atomic_and_words_only(self):
        for mode in ("dry_run", "write"):
            self.config(ranked_ingest=mode)
            self.runs(sync(NOW - H))
            if self.status.exists():
                self.status.unlink()
            r = self.row(self.once())
            self.assertEqual(stat.S_IMODE(self.status.stat().st_mode), 0o600)
            self.assertEqual([p.name for p in self.st.iterdir() if p.name.endswith(".tmp")], [], "no temp file")
            s = self.load_status()
            self.assertEqual(set(s), {"row_at", "ran_at", "mode", "action"})
            words = json.dumps({k: v for k, v in s.items() if k not in EPOCHS})
            self.assertWordsOnly(words)
            self.assertNoSecrets(self.status.read_text())
            self.assertWordsOnly(r["reason"])

    def test_nothing_new_after_a_write(self):
        self.config(ranked_ingest="write")
        self.runs(sync(NOW - H))
        self.once()
        self.runs(sync(NOW - H), sync(NOW))
        r = self.row(self.once(NOW + 60))
        self.assertEqual(r["action"], jobs.RUN, r)
        self.assertIn("no new owner message", r["reason"])
        self.assertEqual(self.load_status()["action"], "nothing")
        self.assertEqual(len(self.ledger_rows()), 3)

    def test_a_drop_of_only_unknown_ids_appends_nothing(self):
        make_db(self.st / "other.db", [("user", f"drop: {UNKNOWN}", NOW - 2 * H)], started=NOW - 4 * H)
        self.config(ranked_ingest="write", hermes_db="other.db")
        self.runs(sync(NOW - H))
        before = self.ledger.read_bytes()
        r = self.row(self.once())
        self.assertIn("no owner drop to append", r["reason"])
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertEqual(self.load_status()["action"], "ignore")

    def test_the_job_sends_nothing(self):
        self.config(ranked_ingest="write")
        self.runs(sync(NOW - H))
        pushed = []
        rows = jobs_runner.run_once(self.st, NOW, push=lambda *a, **k: pushed.append(a), dry_run=False,
                                    env=self.env, home=self.dir, tz=UTC)
        self.row(rows)
        self.assertEqual(pushed, [])
        self.assertFalse((self.st / jobs_runner.SENT_LOG).exists())


class AgentRows(Base):
    def test_an_agent_row_never_becomes_dropped_through_this_path(self):
        self.config(ranked_ingest="write")
        self.runs(sync(NOW - H))
        self.once()
        newest = rl.newest(self.ledger)
        self.assertEqual(newest[B], OPEN(B), "the assistant's drop line is not the owner's")
        added = self.ledger_rows()[2:]
        self.assertTrue(added)
        for r in added:
            self.assertEqual((r["status"], r["by"], r["evidence"]), ("dropped", scorecard.OWNER, "owner reply"))
        self.assertFalse(any(r["status"] == "dropped" and r["by"] == "agent" for r in self.ledger_rows()))


class Due(Base):
    def test_second_pass_after_the_same_sync_row_says_it_already_ran(self):
        self.config(ranked_ingest="write")
        self.runs(sync(NOW - H))
        self.assertEqual(self.row(self.once())["action"], jobs.RUN)
        ledger, status = self.ledger.read_bytes(), self.status.read_bytes()
        again = self.row(self.once(NOW + 60))
        self.assertEqual(again["action"], jobs.DROP, again)
        self.assertIn("already ran after this sync", again["reason"])
        self.assertEqual((self.ledger.read_bytes(), self.status.read_bytes()), (ledger, status))
        self.runs(sync(NOW - H), sync(NOW + 90))
        third = self.row(self.once(NOW + 120))
        self.assertEqual(third["action"], jobs.RUN, third)
        self.assertEqual(self.load_status()["row_at"], NOW + 90)

    def test_a_failed_newest_row_or_no_runs_file_is_not_triggered(self):
        self.config(ranked_ingest="write")
        r = self.row(self.once())
        self.assertEqual(r["action"], jobs.NOT_TRIGGERED)
        self.assertIn("no sync run", r["reason"])
        self.runs(sync(NOW - 2 * H, ok=False))
        self.assertEqual(self.row(self.once())["action"], jobs.NOT_TRIGGERED)
        self.assertFalse(self.status.exists())
        self.assertEqual(len(self.ledger_rows()), 2)

    def test_a_future_row_is_not_triggered(self):
        self.config(ranked_ingest="write")
        self.runs(sync(NOW + H))
        self.assertEqual(self.row(self.once())["action"], jobs.NOT_TRIGGERED)

    def test_no_hermes_db_is_skipped_with_a_plain_reason(self):
        self.config(ranked_ingest="write", hermes_db=None)
        self.runs(sync(NOW - H))
        r = self.row(self.once())
        self.assertEqual(r["action"], jobs.NOT_TRIGGERED, r)
        self.assertIn("skipped: no Hermes DB set (config hermes_db)", r["reason"])
        self.assertFalse(self.status.exists())

    def test_no_ranked_ledger_is_skipped_with_a_plain_reason(self):
        self.config(ranked_ingest="write", ranked_ledger=None)
        self.runs(sync(NOW - H))
        r = self.row(self.once())
        self.assertEqual(r["action"], jobs.NOT_TRIGGERED, r)
        self.assertIn("skipped: no ranked ledger set", r["reason"])
        self.assertFalse(self.status.exists())
        self.assertFalse(self.drops.exists())

    def test_the_ledger_comes_from_the_env_too(self):
        self.config(ranked_ingest="write", ranked_ledger=None)
        self.env["LIMITLESS_RANKED_LEDGER"] = str(self.ledger)
        self.runs(sync(NOW - H))
        self.assertEqual(self.row(self.once())["action"], jobs.RUN)
        self.assertEqual(self.ledger_rows()[2:], [DROP(A)])

    def test_never_on_a_clock_time(self):
        spec = jobs.RANKED_INGEST
        self.assertEqual((spec.name, spec.trigger_event, spec.expires), ("ranked_ingest", "sync", "sync"))
        self.assertNotIn(spec.name, jobs.SPECS, "not a message job")

    def test_the_row_comes_after_the_apps_ingest_row(self):
        self.config(ranked_ingest="dry_run", apps_ingest="dry_run")
        self.runs(sync(NOW - H))
        jobs_ = [r["job"] for r in self.once()]
        self.assertEqual(jobs_.index(JOB), jobs_.index("Apps ingest") + 1)


CLOCK = r"\d{1,2}:\d{2}|\b\d{1,2}\s*(am|pm)\b|\bcron\b|\*/"


class ScheduleCard(Base):
    def card(self):
        from limitless import schedule_cards
        return schedule_cards.ranked_ingest_card()

    def test_one_card_on_the_sync_event_that_sends_nothing(self):
        from limitless import schedule_cards
        c = self.card()
        self.assertEqual(set(c), set(schedule_cards.apps_ingest_card()))
        self.assertEqual((c["id"], c["kind"], c["name"]), ("ranked_ingest", "schedule", JOB))
        self.assertEqual((c["trigger"], c["ends"]), ("sync", "sync"))
        self.assertEqual((c["budget"], c["sender"], c["per_window"], c["stale_after_s"]),
                         (0, schedule_cards.LOCAL, 1, None))
        self.assertEqual(c["once_key"], "ranked_ingest:<sync run time>")
        self.assertIn("after each sync run", c["description"])
        self.assertIn("nothing is sent", c["description"])
        self.assertEqual(c["words"]["runs"], "limitless-jobs --ingest or --send")

    def test_the_card_is_digit_free_with_no_clock(self):
        c = self.card()
        self.assertNotRegex(c["description"], r"\d")
        self.assertNotRegex(c["once_key"].replace("<sync run time>", ""), CLOCK)
        for k, v in c["words"].items():
            self.assertNotRegex(v, r"\d", k)
            self.assertNotRegex(v, CLOCK, k)
        self.assertNoSecrets(json.dumps(c))

    def test_cards_add_it_only_when_the_job_is_on(self):
        from limitless import schedule_cards
        self.assertEqual([x["id"] for x in schedule_cards.cards()], list(jobs.SPECS))
        self.assertEqual([x["id"] for x in schedule_cards.cards(noop=True, apps=True, ranked=True)],
                         list(jobs.SPECS) + ["noop_export", "apps_ingest", "ranked_ingest"])
        self.assertEqual([x["id"] for x in schedule_cards.cards(ranked=True)], list(jobs.SPECS) + ["ranked_ingest"])

    def test_the_schedule_tool_shows_it_when_config_turns_it_on(self):
        from limitless import tools
        from limitless.state_reader import StateReader
        self.config()
        ids = [x["id"] for x in tools.schedule(StateReader(self.st), NOW, self.env, self.dir)["value"]["cards"]]
        self.assertNotIn("ranked_ingest", ids)
        self.config(ranked_ingest="dry_run")
        got = tools.schedule(StateReader(self.st), NOW, self.env, self.dir)
        self.assertIn("ranked_ingest", [x["id"] for x in got["value"]["cards"]])
        self.assertIn("label", got, "the plain words stay digit-free")

    def test_a_host_gets_the_card_at_register_when_the_job_is_on(self):
        sys.path.insert(0, str(ROOT / "tests"))
        from test_schedule_register import CardCtx, HostRegistration
        self.config(ranked_ingest="write")
        ctx = CardCtx()
        reg = HostRegistration("test_the_method_name_is_the_documented_one")
        reg.register(ctx, {"LIMITLESS_CONFIG": str(self.cfg_path), "LIMITLESS_STATE": str(self.st)})
        reg.doCleanups()
        self.assertEqual([c["id"] for c in ctx.cards], list(jobs.SPECS) + ["ranked_ingest"])


class Doctor(Base):
    def doc_row(self, now=NOW):
        from limitless import doctor
        from limitless.state_reader import StateReader, config
        return doctor.ranked_ingest_row(StateReader(self.st), config(self.env, self.dir), now, env=self.env)

    def check(self, r, status, *words):
        self.assertEqual((r["name"], r["kind"], r["status"]), ("job ranked ingest", "job", status), r)
        for w in words:
            self.assertIn(w, r["reason"])
        self.assertWordsOnly(r["reason"])
        self.assertNotIn("/", r["reason"])

    def test_off_by_default(self):
        self.config()
        self.check(self.doc_row(), "off", "off (config ranked_ingest)")

    def test_on_with_no_ledger_is_broken(self):
        self.config(ranked_ingest="write", ranked_ledger=None)
        self.runs(sync(NOW - H))
        self.check(self.doc_row(), "missing", "broken", "no ranked ledger set")

    def test_on_with_no_hermes_db_is_broken(self):
        self.config(ranked_ingest="write", hermes_db=None)
        self.runs(sync(NOW - H))
        self.check(self.doc_row(), "missing", "broken", "no Hermes DB set (config hermes_db)")

    def test_on_with_no_sync_yet_is_stale(self):
        self.config(ranked_ingest="write")
        self.check(self.doc_row(), "stale", "no sync run")

    def test_a_sync_it_has_not_run_after_is_stale(self):
        self.config(ranked_ingest="write")
        self.runs(sync(NOW - H))
        self.check(self.doc_row(), "stale", "has not run after it", "limitless-jobs --ingest or --send runs it")

    def test_live_after_a_write(self):
        self.config(ranked_ingest="write")
        self.runs(sync(NOW - 3 * H))
        self.once(NOW - 2 * H + 60)
        self.check(self.doc_row(), "live", "write mode", "about an hour ago", "appended owner drop rows")

    def test_live_in_dry_run_says_it_writes_nothing(self):
        self.config(ranked_ingest="dry_run")
        self.runs(sync(NOW - H))
        self.once()
        self.check(self.doc_row(), "live", "dry run", "would append owner drop rows", "under an hour ago")

    def test_live_with_nothing_new(self):
        self.config(ranked_ingest="write")
        self.runs(sync(NOW - H))
        self.once()
        self.runs(sync(NOW - H), sync(NOW))
        self.once(NOW + 60)
        self.check(self.doc_row(NOW + 60), "live", "no new owner message")

    def test_the_row_reads_only(self):
        self.config(ranked_ingest="write")
        self.runs(sync(NOW - H))
        before = sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in self.dir.rglob("*"))
        self.doc_row()
        after = sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in self.dir.rglob("*"))
        self.assertEqual(after, before)

    def test_the_row_follows_the_ranked_ledger_row_and_strict_ignores_it(self):
        from limitless import doctor
        from unittest import mock
        self.config(ranked_ingest="write")
        with mock.patch.dict(os.environ, self.env):
            rows = doctor.report(dict(self.cfg, state=str(self.st)), NOW)
        names = [r["name"] for r in rows]
        self.assertEqual(names.count("job ranked ingest"), 1)
        self.assertEqual(names.index("job ranked ingest"), names.index(doctor.RANKED_ROW) + 1)
        self.assertEqual(names.index(doctor.SENDER_INGEST_ROW), names.index("job ranked ingest") + 1)
        self.assertEqual(names.index(doctor.VOICE_MIQ_ROW), names.index(doctor.SENDER_INGEST_ROW) + 1)
        r = rows[names.index("job ranked ingest")]
        live = [dict(x, status="live") for x in rows if x["kind"] != "job"]
        self.assertFalse(doctor.strict_failed(live + [r]))


class Docs(unittest.TestCase):
    DOC = ROOT / "docs" / "ranked-ledger.md"

    def test_the_doc_section_says_what_the_job_does_and_never_does(self):
        text = self.DOC.read_text()
        self.assertIn("## As an event job", text)
        section = text.split("## As an event job", 1)[1].split("\n## ", 1)[0].lower()
        for word in ("ranked_ingest", "ranked-ingest.json", "0600", "runs.jsonl", "off", "dry_run", "write",
                     "hermes_db", "ranked-drops.json", "already ran after this sync", "never sends",
                     "never restarts, kills or starts a process", "no clock time", "job ranked ingest",
                     "after each sync run", "limitless-jobs --send", "only the owner"):
            self.assertIn(word, section)
        self.assertNotRegex(text, r"/(Users|home)/")

    def test_the_job_example_is_the_scripts_real_output(self):
        import subprocess
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "ranked_ingest_job_example.py")],
                           capture_output=True, text=True, timeout=120, env=child_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        blocks = re.findall(r"```text\n(.*?)```", self.DOC.read_text(), re.S)
        self.assertIn(r.stdout, blocks)
        for w in ("Ranked ingest: run: a sync ran; appended one owner drop row", "already ran after this sync",
                  "would append one owner drop row", "job ranked ingest: live"):
            self.assertIn(w, r.stdout)
        self.assertNotIn(PRIVATE, r.stdout)


if __name__ == "__main__":
    unittest.main()
