"""The owner's "push via <profile>" reply as an event job: limitless-jobs reads it from the Hermes session DB once
per new sync row in runs.jsonl, as config ``sender_ingest`` says (off, dry_run, write), through
sender_reply.ingest; limitless-doctor's "job sender ingest" row and the schedule card say so in words.

Synthetic Hermes homes, synthetic runs.jsonl rows and the synthetic session DB of tests/hermes_db_fixture.py
only; made-up profile names. Nothing here sends, runs hermes or starts a service; the kevin-push tests put a fake
``hermes`` on PATH that only records its arguments.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from limitless import doctor, jobs, jobs_runner, push_sender, schedule_cards, sender_ingest_job, \
    sender_reply, tier_audit, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from hermes_db_fixture import make_db  # noqa: E402
from hermes_profile_fixture import ready_profile  # noqa: E402

UTC = timezone.utc
H = 3600
NOW = datetime(2030, 1, 6, 9, 0, tzinfo=UTC).timestamp()
JOB = "Sender ingest"
GOOD, OLD, GONE = "sender-synth", "sender-old", "sender-gone"
PRIVATE = "synthetic-private-words"
NAMES = (GOOD, OLD, GONE)


def iso(t):
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sync(t, **kw):
    row = {"at": iso(t), "job": "sync", "ok": True, "took_s": 9.5}
    row.update(kw)
    return row


def passes_tier_audit(text):
    return not tier_audit.event("cli:limitless-jobs", text, opt_in=False, now=NOW)["blocked"]


class Base(unittest.TestCase):
    messages = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.st = self.dir / "state"
        self.st.mkdir()
        self.hermes = self.dir / "hermes"
        ready_profile(self.hermes / "profiles" / GOOD)   # each can reach Telegram (the ingest asks readiness)
        ready_profile(self.hermes / "profiles" / OLD)
        self.cfg_path = self.dir / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg_path), "LIMITLESS_STATE": str(self.st),
                    "HERMES_HOME": str(self.hermes)}
        self.mark = self.st / sender_reply.MARK
        self.reply = self.st / sender_reply.SENDER_FILE
        self.db(self.messages or [("user", PRIVATE, NOW - 3 * H), ("user", f"push via {GOOD}", NOW - 2 * H),
                                  ("assistant", f"push via {OLD}", NOW - 2 * H + 10)])

    def db(self, messages, source="telegram"):
        p = self.st / "hermes.db"
        if p.exists():
            p.unlink()
        make_db(p, messages, started=NOW - 4 * H, source=source)

    def config(self, **kw):
        cfg = {"hermes_db": "hermes.db", "push_profile": OLD}
        cfg.update(kw)
        self.cfg = {k: v for k, v in cfg.items() if v is not None}
        self.cfg_path.write_text(json.dumps(self.cfg))

    def runs(self, *rows):
        (self.st / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def once(self, now=NOW, dry_run=False, env=None):
        return jobs_runner.run_once(self.st, now, push=None, dry_run=dry_run, env=self.env if env is None else env,
                                    home=self.dir, tz=UTC)

    def row(self, rows):
        got = [r for r in rows if r["job"] == JOB]
        self.assertEqual(len(got), 1, rows)
        return got[0]

    def no_row(self, rows):
        self.assertEqual([r for r in rows if r["job"] == JOB], [])

    def doc(self, now=NOW, env=None):
        return doctor.sender_ingest_row(StateReader(self.st), self.cfg, now, env=self.env if env is None else env)

    def sender(self, env=None):
        return push_sender.profile(self.cfg, self.env if env is None else env)

    def assertWordsOnly(self, text):
        self.assertNotRegex(text, r"\d", text)
        for w in NAMES + (PRIVATE, "push via", str(self.dir)):
            self.assertNotIn(w, text)
        self.assertTrue(passes_tier_audit(text), text)


class Off(Base):
    def test_off_is_the_default_and_reads_nothing(self):
        self.config()
        self.runs(sync(NOW - H))
        self.no_row(self.once())
        self.assertFalse(self.mark.exists())
        self.assertFalse(self.reply.exists())
        self.assertEqual(self.sender(), OLD)

    def test_anything_but_dry_run_or_write_is_off(self):
        for v in ("off", "OFF", False, None, "sometimes", 1, True):
            self.config(sender_ingest=v)
            self.runs(sync(NOW - H))
            self.no_row(self.once())
            self.assertFalse(self.mark.exists(), v)
            self.assertFalse(self.reply.exists(), v)

    def test_mode_reads_the_config(self):
        self.assertEqual(jobs.sender_mode({}), jobs.SENDER_OFF)
        self.assertEqual(jobs.sender_mode({"sender_ingest": " Dry_Run "}), jobs.SENDER_DRY_RUN)
        self.assertEqual(jobs.sender_mode({"sender_ingest": "write"}), jobs.SENDER_WRITE)
        self.assertEqual(jobs.sender_mode(None), jobs.SENDER_OFF)
        self.assertEqual(jobs.sender_mode({"apps_ingest": "write"}), jobs.SENDER_OFF, "its own key")

    def test_the_doctor_row_is_off(self):
        self.config()
        r = self.doc()
        self.assertEqual((r["name"], r["kind"], r["status"]), ("job sender ingest", "job", doctor.OFF))
        self.assertIn("off (config sender_ingest)", r["reason"])


class DryRun(Base):
    def test_dry_run_writes_only_the_mark(self):
        self.config(sender_ingest="dry_run")
        self.runs(sync(NOW - H))
        r = self.row(self.once())
        self.assertEqual(r["action"], jobs.RUN, r)
        self.assertIn("would set the sender profile from your reply", r["reason"])
        self.assertIn('config sender_ingest "write" sets it', r["reason"])
        self.assertFalse(self.reply.exists())
        self.assertEqual(self.sender(), OLD)
        m = json.loads(self.mark.read_text())
        self.assertEqual(m, {"row_at": NOW - H, "ran_at": NOW, "mode": "dry_run", "action": "would write"})
        self.assertEqual(stat.S_IMODE(self.mark.stat().st_mode), 0o600)
        self.assertEqual(sorted(p.name for p in self.st.iterdir()), ["hermes.db", sender_reply.MARK, "runs.jsonl"])
        self.assertWordsOnly(r["reason"])

    def test_a_dry_run_of_limitless_jobs_reads_and_writes_nothing(self):
        self.config(sender_ingest="write")
        self.runs(sync(NOW - H))
        r = self.row(self.once(dry_run=True))
        self.assertEqual(r["action"], jobs.RUN)
        self.assertIn("dry run of limitless-jobs: not run", r["reason"])
        self.assertFalse(self.mark.exists())
        self.assertFalse(self.reply.exists())

    def test_dry_run_then_write_still_applies_the_reply(self):
        self.config(sender_ingest="dry_run")
        self.runs(sync(NOW - H))
        self.once()
        self.config(sender_ingest="write")
        self.runs(sync(NOW - H), sync(NOW - H / 2))
        r = self.row(self.once(now=NOW + 60))
        self.assertIn("set the sender profile from your reply", r["reason"])
        self.assertEqual(self.sender(), GOOD)


class Write(Base):
    def test_write_sets_the_sender_from_the_reply(self):
        self.config(sender_ingest="write")
        self.runs(sync(NOW - H))
        r = self.row(self.once())
        self.assertEqual(r["action"], jobs.RUN, r)
        self.assertEqual(r["reason"], "a sync ran; set the sender profile from your reply")
        self.assertEqual(json.loads(self.reply.read_text()), {"profile": GOOD, "at": NOW - 2 * H})
        self.assertEqual(stat.S_IMODE(self.reply.stat().st_mode), 0o600)
        self.assertEqual(self.sender(), GOOD, "the reply wins over the old config value")
        self.assertEqual(push_sender.check(self.cfg, self.env), push_sender.SET)
        m = json.loads(self.mark.read_text())
        self.assertEqual(m, {"row_at": NOW - H, "ran_at": NOW, "mode": "write", "action": "write",
                             "after": NOW - 2 * H})
        for raw in (self.mark.read_text(), json.dumps(r)):
            for w in NAMES + (PRIVATE,):
                self.assertNotIn(w, raw)
        self.assertWordsOnly(r["reason"])

    def test_the_same_sync_row_is_once(self):
        self.config(sender_ingest="write")
        self.runs(sync(NOW - H))
        self.once()
        before = self.reply.read_bytes()
        r = self.row(self.once(now=NOW + 60))
        self.assertEqual(r["action"], jobs.DROP)
        self.assertIn("already ran after this sync", r["reason"])
        self.assertEqual(self.reply.read_bytes(), before)

    def test_the_next_sync_with_no_new_reply_changes_nothing(self):
        self.config(sender_ingest="write")
        self.runs(sync(NOW - H))
        self.once()
        before = self.reply.read_bytes()
        self.runs(sync(NOW - H), sync(NOW + 30))
        r = self.row(self.once(now=NOW + 60))
        self.assertIn("no new sender reply", r["reason"])
        self.assertEqual(self.reply.read_bytes(), before)
        self.assertEqual(json.loads(self.mark.read_text())["after"], NOW - 2 * H)

    def test_env_still_wins(self):
        self.config(sender_ingest="write")
        self.runs(sync(NOW - H))
        env = dict(self.env, KEVIN_PUSH_PROFILE=OLD)
        r = self.row(self.once(env=env))
        self.assertIn("set the sender profile from your reply", r["reason"])
        self.assertIn("KEVIN_PUSH_PROFILE is set and still wins", r["reason"])
        self.assertEqual(self.sender(env), OLD)
        self.assertEqual(self.sender(), GOOD)
        self.assertIn("KEVIN_PUSH_PROFILE is set and still wins", self.doc(now=NOW + 60, env=env)["reason"])
        self.assertWordsOnly(r["reason"])

    def test_no_hermes_db_is_skipped(self):
        self.config(sender_ingest="write", hermes_db=None)
        self.runs(sync(NOW - H))
        r = self.row(self.once())
        self.assertEqual(r["action"], jobs.NOT_TRIGGERED)
        self.assertIn("no Hermes DB set", r["reason"])
        self.assertFalse(self.mark.exists())
        d = self.doc()
        self.assertEqual(d["status"], doctor.STALE)
        self.assertIn("no Hermes DB set", d["reason"])

    def test_no_sync_yet_and_a_failed_sync_do_not_run(self):
        self.config(sender_ingest="write")
        r = self.row(self.once())
        self.assertEqual((r["action"], r["reason"]), (jobs.NOT_TRIGGERED, "no sync run yet"))
        self.runs(sync(NOW - H, ok=False))
        r = self.row(self.once())
        self.assertEqual(r["action"], jobs.NOT_TRIGGERED)
        self.assertFalse(self.mark.exists())

    def test_an_unwritable_state_dir_holds(self):
        self.config(sender_ingest="write")
        self.runs(sync(NOW - H))
        os.chmod(self.st, 0o500)
        self.addCleanup(os.chmod, self.st, 0o700)
        if os.access(self.st, os.W_OK):
            self.skipTest("running as a user that writes anywhere")
        r = self.row(self.once())
        self.assertEqual(r["action"], jobs.HOLD)
        self.assertIn("the next run tries again", r["reason"])


class MissingProfile(Base):
    messages = [("user", f"push via {GONE}", NOW - 2 * H)]

    def test_a_reply_naming_a_missing_profile_changes_nothing(self):
        self.config(sender_ingest="write")
        self.runs(sync(NOW - H))
        r = self.row(self.once())
        self.assertIn("that sender profile does not exist", r["reason"])
        self.assertFalse(self.reply.exists())
        self.assertEqual(self.sender(), OLD, "never a fallback, never a pick by the code")
        self.assertEqual(json.loads(self.mark.read_text())["action"], "missing")
        d = self.doc(now=NOW + 60)
        self.assertIn("that sender profile does not exist", d["reason"])
        self.assertWordsOnly(r["reason"])
        self.assertWordsOnly(d["reason"])

    def test_a_missing_profile_keeps_an_earlier_reply(self):
        sender_reply.write_reply(self.st, GOOD, NOW - 9 * H)
        before = self.reply.read_bytes()
        self.config(sender_ingest="write")
        self.runs(sync(NOW - H))
        self.once()
        self.assertEqual(self.reply.read_bytes(), before)
        self.assertEqual(self.sender(), GOOD)


class LongerMessage(Base):
    messages = [("user", f"can you push via {GOOD} from now on?", NOW - 2 * H),
                ("user", f"Reply 'push via {GOOD}' to choose", NOW - 2 * H + 5)]

    def test_the_phrase_inside_a_longer_message_is_ignored(self):
        self.config(sender_ingest="write")
        self.runs(sync(NOW - H))
        r = self.row(self.once())
        self.assertIn("no new sender reply", r["reason"])
        self.assertFalse(self.reply.exists())
        self.assertEqual(self.sender(), OLD)


class CronPrompt(Base):
    def test_a_quoted_cron_prompt_is_not_an_owner_reply(self):
        self.db([("user", f"push via {GOOD}", NOW - 2 * H)], source="cron")
        self.config(sender_ingest="write")
        self.runs(sync(NOW - H))
        r = self.row(self.once())
        self.assertIn("no new sender reply", r["reason"])
        self.assertFalse(self.reply.exists())


class Doctor(Base):
    def test_live_after_a_write_and_stale_while_a_new_sync_waits(self):
        self.config(sender_ingest="write")
        self.runs(sync(NOW - H))
        d = self.doc()
        self.assertEqual(d["status"], doctor.STALE)
        self.assertIn("has not run after it yet", d["reason"])
        self.once()
        d = self.doc(now=NOW + 60)
        self.assertEqual(d["status"], doctor.LIVE)
        self.assertEqual(d["reason"], "write mode: ran under an hour ago after a sync: set the sender profile "
                                      "from your reply")
        self.assertWordsOnly(d["reason"])

    def test_dry_run_row(self):
        self.config(sender_ingest="dry_run")
        self.runs(sync(NOW - H))
        self.once()
        d = self.doc(now=NOW + 60)
        self.assertEqual(d["status"], doctor.LIVE)
        self.assertIn("would set the sender profile from your reply", d["reason"])
        self.assertWordsOnly(d["reason"])

    def test_the_row_sits_right_after_the_ranked_ingest_row(self):
        self.config(sender_ingest="write")
        old = os.environ.get("LIMITLESS_CONFIG")
        os.environ["LIMITLESS_CONFIG"] = str(self.cfg_path)
        try:
            rows = doctor.report(self.cfg, NOW)
        finally:
            if old is None:
                del os.environ["LIMITLESS_CONFIG"]
            else:
                os.environ["LIMITLESS_CONFIG"] = old
        names = [r["name"] for r in rows]
        at = names.index(doctor.RANKED_INGEST_ROW)
        self.assertEqual(names[at + 1], doctor.SENDER_INGEST_ROW)
        self.assertEqual(names[at + 2], doctor.FIT_IMPORT_ROW)
        self.assertEqual(names[at + 3], doctor.SENDER_CONFIRM_ROW)
        self.assertEqual(names[at + 4], doctor.VOICE_MIQ_ROW)

    def test_the_doctor_and_jobs_clis_never_print_a_profile_name(self):
        self.config(sender_ingest="write")
        self.runs(sync(NOW - H))
        self.once()
        for argv in (["limitless-doctor"], ["limitless-doctor", "--json"], ["limitless-jobs"]):
            r = subprocess.run([sys.executable, "-I", str(ROOT / "bin" / argv[0]), *argv[1:]],
                               env=child_env(self.env), capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("sender ingest", r.stdout.lower(), argv)
            # the doctor's "sender candidates" row is the one row that names profiles (the owner's own labels,
            # tests/test_sender_candidates.py); every other line never does
            lines = [ln for ln in (r.stdout + r.stderr).splitlines()
                     if not ln.startswith("sender candidates:") and '"name": "sender candidates"' not in ln]
            for w in NAMES + (PRIVATE,):
                self.assertNotIn(w, "\n".join(lines), argv)


class Cards(Base):
    def test_the_card_is_on_the_sync_event_never_a_clock(self):
        c = schedule_cards.sender_ingest_card()
        self.assertEqual((c["id"], c["trigger"], c["ends"], c["budget"], c["sender"]),
                         ("sender_ingest", "sync", "sync", 0, schedule_cards.LOCAL))
        self.assertEqual(c["once_key"], "sender_ingest:<sync run time>")
        self.assertNotRegex(c["description"], r"\d")
        self.assertNotRegex(json.dumps(c), r"\d{1,2}:\d{2}|cron|\*/")
        self.assertIn("push via", c["description"])
        self.assertNotIn(c, schedule_cards.cards())
        self.assertEqual(schedule_cards.cards(sender=True)[-1], c)
        self.assertEqual(schedule_cards.cards(sender=True, recap=True)[-1], schedule_cards.outage_recap_card())

    def test_the_schedule_tool_shows_it_only_when_on(self):
        self.config()
        ids = [c["id"] for c in tools.schedule(StateReader(self.st), NOW, env=self.env, home=self.dir)
               ["value"]["cards"]]
        self.assertNotIn("sender_ingest", ids)
        self.config(sender_ingest="dry_run")
        out = tools.schedule(StateReader(self.st), NOW, env=self.env, home=self.dir)
        self.assertIn("sender_ingest", [c["id"] for c in out["value"]["cards"]])
        for w in NAMES:
            self.assertNotIn(w, json.dumps(out))

    def test_the_spec_is_not_a_message_job(self):
        self.assertNotIn(jobs.SENDER_INGEST.name, jobs.SPECS)
        self.assertEqual(jobs.SENDER_INGEST.trigger_event, "sync")


class KevinPush(Base):
    """bin/kevin-push sends through the profile the reply set; a fake hermes on PATH records the call."""

    def push(self, **extra):
        fakebin = self.dir / "fakebin"
        fakebin.mkdir(exist_ok=True)
        hermes = fakebin / "hermes"
        hermes.write_text("#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$HOME/hermes-calls\"\nexit 0\n")
        hermes.chmod(hermes.stat().st_mode | stat.S_IEXEC)
        env = {k: v for k, v in os.environ.items() if not k.startswith("KEVIN_PUSH_")}
        env.update(self.env, HOME=str(self.dir), PATH=f"{fakebin}:{os.environ['PATH']}",
                   LIMITLESS_SLEEPMODE=str(self.st / "sleepmode.jsonl"), CIRCADIAN_CLASS="decision", **extra)
        r = subprocess.run([sys.executable, "-I", str(ROOT / "bin" / "kevin-push"), "x", "Pick one",
                            f"Synthetic body {time.time()}"], env=child_env(env), capture_output=True, text=True,
                           timeout=30)
        calls = self.dir / "hermes-calls"
        return r, (calls.read_text().splitlines() if calls.exists() else [])

    def test_kevin_push_uses_the_reply_and_env_still_wins(self):
        self.config(sender_ingest="write")
        self.runs(sync(NOW - H))
        self.once()
        r, calls = self.push()
        self.assertIn("kevin-push: telegram", r.stdout, r.stderr)
        self.assertTrue(calls[-1].startswith(f"-p {GOOD} send"), calls)
        r, calls = self.push(KEVIN_PUSH_PROFILE=OLD)
        self.assertTrue(calls[-1].startswith(f"-p {OLD} send"), calls)

    def test_a_reply_file_naming_a_removed_profile_starts_no_hermes(self):
        sender_reply.write_reply(self.st, GONE, NOW - H)
        self.config()
        r, calls = self.push()
        self.assertIn("kevin-push: log (no sender profile)", r.stdout, r.stderr)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
