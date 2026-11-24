"""limitless-jobs --ingest: the timer's pass runs the three reply ingests (apps, ranked, sender) for real, exactly as
--send runs them, and every other job stays a plain dry run: nothing is pushed, kevin-push and limitless-brief are
never called, no hermes is started and nothing is logged as sent. --ingest with --send is --send.

Synthetic state dirs, a synthetic Hermes home (made-up profile names), synthetic ranked ledgers and the synthetic
session DB of tests/hermes_db_fixture.py only. Every fake binary only records that it was called.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from limitless import apps_reply, doctor, jobs, jobs_runner, schedule_cards, sender_reply  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from hermes_db_fixture import make_db  # noqa: E402

UTC = timezone.utc
H = 3600.0
NOW = datetime(2030, 1, 6, 9, 0, tzinfo=UTC).timestamp()
CLI = ROOT / "bin" / "limitless-jobs"
GOOD, OLD = "sender-synth", "sender-old"
ITEM, OTHER = "synthetic-item-a", "synthetic-item-b"
INGESTS = ("Apps ingest", "Ranked ingest", "Sender ingest")
MODES = ("apps_ingest", "ranked_ingest", "sender_ingest")
NOT_RUN = "dry run of limitless-jobs: not run"

# Records every call (argv) in $FAKE_CALLS and says it delivered; it never sends anything.
RECORDER = """#!{py}
import json, os, sys
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(json.dumps({{"bin": os.path.basename(sys.argv[0]), "argv": sys.argv[1:],
                        "strict": os.environ.get("KEVIN_PUSH_STRICT")}}) + "\\n")
print("kevin-push: telegram")
"""


def iso(t):
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sync(t, **kw):
    row = {"at": iso(t), "job": "sync", "ok": True, "took_s": 9.5, "noop": True}
    row.update(kw)
    return row


def load_cli():
    """bin/limitless-jobs as a module (it has no .py suffix), to call its main in-process."""
    loader = importlib.machinery.SourceFileLoader("limitless_jobs_cli", str(CLI))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class Base(unittest.TestCase):
    now = NOW

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.st = self.dir / "state"
        self.st.mkdir()
        self.hermes = self.dir / "hermes"
        for name in (GOOD, OLD):
            (self.hermes / "profiles" / name).mkdir(parents=True)
        self.ledger = self.dir / "ranked.jsonl"
        self.ledger.write_text("".join(json.dumps({"id": i, "status": "open", "by": "agent", "evidence": ""}) + "\n"
                                       for i in (ITEM, OTHER)))
        make_db(self.st / "hermes.db", [("user", "work apps: editor, terminal", self.now - 2 * H),
                                        ("user", f"drop: {ITEM}", self.now - 2 * H + 5),
                                        ("user", f"push via {GOOD}", self.now - 2 * H + 10)],
                started=self.now - 4 * H)
        self.cfg_path = self.dir / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg_path), "LIMITLESS_STATE": str(self.st),
                    "HERMES_HOME": str(self.hermes)}
        (self.st / "runs.jsonl").write_text(json.dumps(sync(self.now - H)) + "\n")

    def config(self, mode="write", **kw):
        cfg = {"hermes_db": "hermes.db", "ranked_ledger": str(self.ledger), "push_profile": OLD,
               "noop_export": "write"}
        cfg.update({k: mode for k in MODES})
        cfg.update(kw)
        self.cfg_path.write_text(json.dumps({k: v for k, v in cfg.items() if v is not None}))

    def rows_by_job(self, rows):
        return {r["job"]: r for r in rows}

    def assertNothingSent(self):
        self.assertFalse((self.st / jobs_runner.SENT_LOG).exists())

    def assertWrote(self):
        """What the three write-mode ingests leave behind: the app lists, an owner drop row, the sender."""
        self.assertTrue((self.st / apps_reply.APPS_FILE).exists())
        ledger = [json.loads(ln) for ln in self.ledger.read_text().splitlines()]
        self.assertTrue(any(r["id"] == ITEM and r["status"] == "dropped" for r in ledger), ledger)
        self.assertEqual(json.loads((self.st / sender_reply.SENDER_FILE).read_text())["profile"], GOOD)


class RunOnceIngest(Base):
    """jobs_runner.run_once(..., dry_run=True, ingest=True): the library half of --ingest."""

    def once(self, **kw):
        calls = []
        kw.setdefault("dry_run", True)
        rows = jobs_runner.run_once(self.st, self.now, push=lambda *a, **k: calls.append(a) or "telegram",
                                    env=self.env, home=self.dir, tz=UTC, **kw)
        return rows, calls

    def test_ingest_runs_the_three_ingests_for_real_in_write_mode(self):
        self.config("write")
        rows, calls = self.once(ingest=True)
        got = self.rows_by_job(rows)
        self.assertEqual(got["Apps ingest"]["reason"], "a sync ran; wrote the app lists")
        self.assertIn("appended one owner drop row", got["Ranked ingest"]["reason"])
        self.assertEqual(got["Sender ingest"]["reason"], "a sync ran; set the sender profile from your reply")
        for job in INGESTS:
            self.assertEqual(got[job]["action"], jobs.RUN, got[job])
            self.assertNotIn(NOT_RUN, got[job]["reason"])
        self.assertWrote()
        self.assertEqual(calls, [])
        self.assertNothingSent()

    def test_every_other_job_stays_a_plain_dry_run(self):
        self.config("write")
        rows, calls = self.once(ingest=True)
        got = self.rows_by_job(rows)
        self.assertIn(NOT_RUN, got["NOOP export"]["reason"])
        self.assertFalse((self.st / "noop-export.json").exists())
        self.assertEqual(calls, [])
        self.assertNothingSent()

    def test_dry_run_mode_writes_only_the_marks(self):
        self.config("dry_run")
        before = self.ledger.read_bytes()
        rows, _ = self.once(ingest=True)
        got = self.rows_by_job(rows)
        self.assertIn("would write the app lists", got["Apps ingest"]["reason"])
        self.assertIn("would append one owner drop row", got["Ranked ingest"]["reason"])
        self.assertIn("would set the sender profile from your reply", got["Sender ingest"]["reason"])
        for mark in ("apps-ingest.json", "ranked-ingest.json", sender_reply.MARK):
            self.assertTrue((self.st / mark).exists(), mark)
        self.assertFalse((self.st / apps_reply.APPS_FILE).exists())
        self.assertFalse((self.st / sender_reply.SENDER_FILE).exists())
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_off_gives_no_row_and_reads_nothing(self):
        self.config(None)
        rows, _ = self.once(ingest=True)
        self.assertEqual([r for r in rows if r["job"] in INGESTS], [])
        for mark in ("apps-ingest.json", "ranked-ingest.json", sender_reply.MARK):
            self.assertFalse((self.st / mark).exists(), mark)

    def test_the_ingest_rows_match_a_send_pass(self):
        self.config("write")
        twin = self.dir / "twin"
        shutil.copytree(self.st, twin)
        shutil.copy(self.ledger, self.dir / "ranked-twin.jsonl")
        ingest, _ = self.once(ingest=True)
        self.st = twin
        self.ledger = self.dir / "ranked-twin.jsonl"
        self.config("write")
        self.env["LIMITLESS_STATE"] = str(twin)
        send, _ = self.once(dry_run=False)
        pick = lambda rows: [r for r in rows if r["job"] in INGESTS]   # noqa: E731
        self.assertEqual(pick(ingest), pick(send))
        self.assertEqual(len(pick(ingest)), 3)

    def test_without_ingest_a_dry_run_still_runs_no_ingest(self):
        self.config("write")
        rows, _ = self.once()
        for job in INGESTS:
            self.assertIn(NOT_RUN, self.rows_by_job(rows)[job]["reason"])
        self.assertFalse((self.st / sender_reply.SENDER_FILE).exists())

    def test_the_second_pass_on_the_same_sync_is_a_drop(self):
        self.config("write")
        self.once(ingest=True)
        before = (self.st / sender_reply.SENDER_FILE).read_bytes()
        rows = jobs_runner.run_once(self.st, self.now + 60, dry_run=True, ingest=True, env=self.env, home=self.dir,
                                    tz=UTC)
        for job in INGESTS:
            self.assertEqual(self.rows_by_job(rows)[job]["action"], jobs.DROP)
        self.assertEqual((self.st / sender_reply.SENDER_FILE).read_bytes(), before)


class Fakes(Base):
    """Fake kevin-push, limitless-brief and hermes that only record a call, on PATH and in the env."""

    def setUp(self):
        self.now = time.time()   # the CLI reads its own clock
        super().setUp()
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        for name in ("kevin-push", "limitless-brief", "hermes"):
            p = self.bin / name
            p.write_text(RECORDER.format(py=sys.executable))
            p.chmod(0o755)
        self.calls = self.dir / "calls.jsonl"
        self.env.update(HOME=str(self.dir), PATH=f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}",
                        KEVIN_PUSH_BIN=str(self.bin / "kevin-push"),
                        LIMITLESS_BRIEF_BIN=str(self.bin / "limitless-brief"), FAKE_CALLS=str(self.calls))
        self.config("write", outage_recap="write", push_log="push-log.jsonl")
        n = self.now
        # A nap (Back from nap is due) and a closed outage in the push log (the outage recap is due).
        (self.st / "sleepmode.jsonl").write_text("".join(json.dumps(r) + "\n" for r in (
            {"at": iso(n - 12 * H), "on": True}, {"at": iso(n - 3 * H), "on": False},
            {"at": iso(n - 1 * H), "on": True}, {"at": iso(n - 0.1 * H), "on": False})))
        (self.st / "sleepmode-poll.json").write_text(json.dumps({"at": iso(n - 30), "ok": True}))
        (self.st / "unlocks.jsonl").write_text(json.dumps({"at": iso(n - 60)}) + "\n")
        (self.st / "push-log.jsonl").write_text("".join(json.dumps(r) + "\n" for r in (
            {"at": int(n - 5 * H), "tag": "limitless", "cls": "decision", "title": "Wake-up brief",
             "how": "log (telegram rc=1)", "body": "Synthetic body.\nWhy now: a reason"},
            {"at": int(n - 4 * H), "tag": "limitless", "cls": "decision", "title": "MIQ for tonight?",
             "how": "log (telegram rc=1)", "body": "Synthetic body.\nWhy now: a reason"},
            {"at": int(n - 600), "tag": "limitless", "cls": "decision", "title": "Habit check-in",
             "how": "telegram", "body": "Synthetic body.\nWhy now: a reason"})))

    def calls_made(self):
        return [json.loads(ln) for ln in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-I", str(CLI), *args], env=child_env(self.env),
                              capture_output=True, text=True, timeout=60)


class IngestCli(Fakes):
    def test_ingest_never_sends_while_message_jobs_are_due(self):
        r = self.run_cli("--ingest")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertTrue(any(ln.startswith("Back from nap: deliver") for ln in lines), r.stdout)
        self.assertTrue(any(ln.startswith("Outage recap: deliver") and "nothing sent" in ln for ln in lines),
                        r.stdout)
        self.assertTrue(any(ln.startswith("NOOP export: run") and NOT_RUN in ln for ln in lines), r.stdout)
        self.assertEqual(self.calls_made(), [], "no kevin-push, limitless-brief or hermes call")
        self.assertNothingSent()
        self.assertFalse((self.st / "outage-recap.json").exists())
        self.assertFalse((self.st / "noop-export.json").exists())
        for job in INGESTS:
            ln = [x for x in lines if x.startswith(f"{job}: ")]
            self.assertEqual(len(ln), 1, r.stdout)
            self.assertTrue(ln[0].startswith(f"{job}: run: a sync ran; "), ln)
            self.assertNotIn(NOT_RUN, ln[0])
        self.assertWrote()

    def test_ingest_with_send_is_send(self):
        r = self.run_cli("--ingest", "--send")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Back from nap: deliver", r.stdout)
        self.assertTrue(any(c["argv"][:2] == ["limitless", "Back from nap"] for c in self.calls_made()),
                        self.calls_made())
        self.assertTrue((self.st / jobs_runner.SENT_LOG).exists())
        self.assertWrote()

    def test_a_plain_run_is_still_a_dry_run_of_everything(self):
        r = self.run_cli()
        self.assertEqual(r.returncode, 0, r.stderr)
        for job in INGESTS:
            self.assertIn(f"{job}: run: a sync ran; {NOT_RUN}", r.stdout)
        self.assertEqual(self.calls_made(), [])
        self.assertFalse((self.st / sender_reply.SENDER_FILE).exists())

    def test_usage_names_ingest(self):
        r = self.run_cli("--nope")
        self.assertEqual(r.returncode, 2)
        self.assertIn("--ingest", r.stderr)
        self.assertIn("--confirm", r.stderr)

    def test_confirm_without_ingest_is_a_usage_error(self):
        r = self.run_cli("--confirm")
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("--confirm", r.stderr)
        self.assertEqual(r.stdout, "")
        self.assertEqual(self.calls_made(), [])
        self.assertFalse((self.st / sender_reply.SENDER_FILE).exists())

    def test_send_with_confirm_is_send(self):
        r = self.run_cli("--send", "--confirm")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(any(c["argv"][:2] == ["limitless", "Back from nap"] for c in self.calls_made()),
                        self.calls_made())
        self.assertTrue((self.st / jobs_runner.SENT_LOG).exists())

    def test_ingest_confirm_sends_only_the_confirmation(self):
        self.config("write", outage_recap="write", push_log="push-log.jsonl", sender_confirm="write")
        r = self.run_cli("--ingest", "--confirm")
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.calls_made()
        self.assertEqual(len(calls), 1, calls)
        self.assertEqual((calls[0]["bin"], calls[0]["argv"][:2], calls[0]["strict"]),
                         ("kevin-push", ["limitless", "Pushes"], "1"))
        lines = r.stdout.splitlines()
        self.assertTrue(any(ln.startswith("Sender confirm: deliver") and ln.endswith("; sent") for ln in lines),
                        r.stdout)
        self.assertTrue(any(ln.startswith("Back from nap: deliver") for ln in lines), r.stdout)
        self.assertTrue(any(ln.startswith("Outage recap: deliver") and "nothing sent" in ln for ln in lines),
                        r.stdout)
        self.assertNothingSent()
        self.assertFalse((self.st / "outage-recap.json").exists())
        self.assertWrote()

    def test_ingest_without_confirm_leaves_the_confirmation_due(self):
        self.config("write", outage_recap="write", push_log="push-log.jsonl", sender_confirm="write")
        r = self.run_cli("--ingest")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(any(ln.startswith("Sender confirm: deliver") and "nothing sent" in ln
                            for ln in r.stdout.splitlines()), r.stdout)
        self.assertEqual(self.calls_made(), [])
        self.assertFalse((self.st / "sender-confirm.json").exists())


class EveryJobDue(Fakes):
    """bin/limitless-jobs main in-process with jobs.should_fire saying deliver for every message job: --ingest still
    calls no kevin-push, no limitless-brief and no hermes (the same pass with --send does, so the jobs were due)."""

    def main(self, *args):
        cli = load_cli()
        due = lambda spec, evs, window, sent, now: jobs.Verdict(jobs.DELIVER, "synthetic: due", now - 60)  # noqa: E731
        out = io.StringIO()
        with mock.patch.dict(os.environ, child_env(self.env), clear=True), \
                mock.patch.object(jobs, "should_fire", due), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(io.StringIO()):
            rc = cli.main(["limitless-jobs", *args])
        return rc, out.getvalue()

    def test_every_message_job_due_and_nothing_is_sent(self):
        rc, out = self.main("--ingest")
        self.assertEqual(rc, 0)
        delivers = [ln for ln in out.splitlines() if ": deliver: " in ln]
        self.assertGreaterEqual(len(delivers), len(jobs.SPECS) - 2, out)   # habit gates may drop the habit two
        self.assertEqual(self.calls_made(), [])
        self.assertNothingSent()
        self.assertWrote()

    def test_the_same_pass_with_send_does_call_the_senders(self):
        rc, out = self.main("--send")
        self.assertEqual(rc, 0)
        self.assertNotEqual(self.calls_made(), [], out)

    def due_everything(self):
        """Wake brief, habit check-in, outage recap and the sender confirmation all due in one pass."""
        self.config("write", outage_recap="write", push_log="push-log.jsonl", sender_confirm="write")
        today = datetime.fromtimestamp(self.now).date().isoformat()
        (self.st / "habit.json").write_text(json.dumps({"habit": "synthetic habit", "week_of": today}))

    def test_ingest_confirm_with_everything_due_makes_exactly_one_call_the_confirmation(self):
        self.due_everything()
        rc, out = self.main("--ingest", "--confirm")
        self.assertEqual(rc, 0)
        got = {ln.split(": ")[0]: ln for ln in out.splitlines()}
        for job in ("Wake-up brief", "Habit check-in", "Outage recap", "Sender confirm"):
            self.assertIn(f"{job}: deliver: ", got.get(job, ""), out)
        self.assertIn("nothing sent", got["Outage recap"])
        self.assertTrue(got["Sender confirm"].endswith("; sent"), got["Sender confirm"])
        calls = self.calls_made()
        self.assertEqual(len(calls), 1, calls)
        argv = calls[0]["argv"]
        self.assertEqual((calls[0]["bin"], argv[:2], calls[0]["strict"]), ("kevin-push", ["limitless", "Pushes"], "1"))
        reply_at = json.loads((self.st / sender_reply.SENDER_FILE).read_text())["at"]
        self.assertEqual(argv[argv.index("--once") + 1], f"sender_confirm:{int(reply_at)}")
        self.assertNothingSent()
        self.assertFalse((self.st / "outage-recap.json").exists())
        self.assertWrote()

    def test_with_everything_due_send_calls_more_than_the_confirmation(self):
        self.due_everything()
        rc, out = self.main("--send")
        self.assertEqual(rc, 0)
        self.assertGreater(len(self.calls_made()), 1, out)



class Runner(Base):
    """The doctor rows and the schedule cards name --ingest (or --send) as what runs the three ingests."""
    RUNS = "limitless-jobs --ingest or --send"
    CONFIRM_RUNS = "limitless-jobs --ingest --confirm or --send"

    def rows(self):
        cfg = json.loads(self.cfg_path.read_text())
        r = StateReader(self.st)
        return [doctor.apps_ingest_row(r, cfg, self.now, env=self.env),
                doctor.ranked_ingest_row(r, cfg, self.now, env=self.env),
                doctor.sender_ingest_row(r, cfg, self.now, env=self.env)]

    def test_a_waiting_ingest_names_ingest_as_its_runner(self):
        self.config("write")
        for row in self.rows():
            self.assertEqual(row["status"], doctor.STALE, row)
            self.assertIn("has not run after it yet", row["reason"])
            self.assertIn(f"({self.RUNS} runs it)", row["reason"])
            self.assertNotIn("limitless-jobs --send runs it", row["reason"])

    def test_after_an_ingest_pass_the_rows_are_live(self):
        self.config("write")
        jobs_runner.run_once(self.st, self.now, dry_run=True, ingest=True, env=self.env, home=self.dir, tz=UTC)
        later = self.now + 60
        self.now = later
        for row in self.rows():
            self.assertEqual(row["status"], doctor.LIVE, row)

    def test_the_cards_say_ingest_runs_them(self):
        for card in (schedule_cards.apps_ingest_card(), schedule_cards.ranked_ingest_card(),
                     schedule_cards.sender_ingest_card()):
            self.assertEqual(card["words"]["runs"], self.RUNS, card["id"])
        self.assertEqual(schedule_cards.noop_export_card()["words"]["runs"], "limitless-jobs --send")

    def test_the_confirm_card_says_which_pass_sends_it(self):
        self.assertEqual(schedule_cards.sender_confirm_card()["words"]["runs"], self.CONFIRM_RUNS)

    def test_a_waiting_confirmation_names_the_pass_that_sends_it(self):
        self.config("write", sender_confirm="write")
        (self.st / sender_reply.SENDER_FILE).write_text(json.dumps({"profile": GOOD, "at": self.now - 120}))
        cfg = json.loads(self.cfg_path.read_text())
        row = doctor.sender_confirm_row(StateReader(self.st), cfg, self.now, env=self.env)
        self.assertIn("waiting: the sender changed; the next pass sends the confirmation", row["reason"])
        self.assertIn(f"({self.CONFIRM_RUNS} sends it)", row["reason"])
        self.assertNotIn(GOOD, row["reason"])

    def test_the_doctor_doc_names_ingest_for_the_three_ingest_rows(self):
        text = (ROOT / "docs" / "doctor.md").read_text(encoding="utf-8")
        for name in ("job apps ingest", "job ranked ingest", "job sender ingest"):
            line = [ln for ln in text.splitlines() if ln.startswith(f"| `{name}`")]
            self.assertEqual(len(line), 1, name)
            self.assertIn("`limitless-jobs --ingest` or `--send` runs it", line[0])

    def test_the_doctor_doc_names_the_confirm_pass_for_the_sender_confirm_row(self):
        text = (ROOT / "docs" / "doctor.md").read_text(encoding="utf-8")
        line = [ln for ln in text.splitlines() if ln.startswith("| `job sender confirm`")]
        self.assertEqual(len(line), 1)
        self.assertIn("`limitless-jobs --ingest --confirm` or `--send` sends it", line[0])



class TimerDoc(unittest.TestCase):
    def test_the_systemd_doc_has_a_timer_section_whose_service_adds_ingest(self):
        text = (ROOT / "docs" / "limitless-jobs-systemd.md").read_text(encoding="utf-8")
        at = text.index("## Timer: the reply ingests without sending (`--ingest`)")
        section = text[at:]
        self.assertIn("ExecStart=%h/src/limitless/bin/limitless-jobs --ingest --confirm\n", section)
        for word in ("apps_ingest", "ranked_ingest", "sender_ingest", "never sends", "`--ingest --send` is `--send`",
                     "example text only"):
            self.assertIn(word, section)
        self.assertNotIn("systemctl", section)

    def test_the_systemd_doc_says_which_pass_sends_the_sender_confirmation(self):
        text = (ROOT / "docs" / "limitless-jobs-systemd.md").read_text(encoding="utf-8")
        section = text[text.index("## Timer: the reply ingests without sending (`--ingest`)"):]
        for word in ("sender_confirm", "`--ingest --confirm`", "`--confirm` without `--ingest` is a usage error",
                     "outage recap stays a dry run"):
            self.assertIn(word, section)
        self.assertIn("`job sender confirm`", section)

    def test_the_schedule_cards_doc_says_what_runs_the_ingest_cards(self):
        text = (ROOT / "docs" / "schedule-cards.md").read_text(encoding="utf-8")
        self.assertIn("`limitless-jobs --ingest or --send` (in `words.runs`)", text)
        self.assertIn("`limitless-jobs --ingest --confirm or --send` (in `words.runs`)", text)

    def test_the_cli_docstring_names_ingest(self):
        head = CLI.read_text(encoding="utf-8").split('"""')[1]
        self.assertIn("--ingest", head.splitlines()[0])
        self.assertIn("--confirm", head.splitlines()[0])
        self.assertIn("--ingest with --send is --send", head)


if __name__ == "__main__":
    unittest.main()
