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

from limitless import apps_reply, jobs, jobs_runner, sender_reply  # noqa: E402
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
    f.write(json.dumps({{"bin": os.path.basename(sys.argv[0]), "argv": sys.argv[1:]}}) + "\\n")
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


if __name__ == "__main__":
    unittest.main()
