"""The sender ingest's readiness gate: a "push via <name>" reply naming a profile that cannot reach Telegram is not
applied.

push_sender.check says SET for any profile that exists (``default`` always), but a profile can exist and still have
no Telegram bot token or no chat to send to. sender_reply.ingest asks push_sender.readiness about the named profile
(files only, presence only): a definite no (no token, no chat) leaves push-sender.json as it was and records the
refusal in the mark (push-sender-ingest.json, words and epochs only); ready or any ``unknown: ...`` still applies.
While the push outage is open, the doctor's sender ingest row and the push recovery stage say so in words.

Synthetic Hermes homes, synthetic state dirs, a synthetic session DB (tests/hermes_db_fixture.py), made-up profile
names and a made-up token placeholder. Nothing here sends or runs hermes: a fake ``hermes`` on PATH records any
call, and process starts are patched to fail.
"""
from hermetic_env import TEST_HOME  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from limitless import doctor, jobs_runner, push_recovery as pr, push_sender as ps, sender_reply as sr  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from hermes_db_fixture import make_db  # noqa: E402

UTC = timezone.utc
H = 3600
NOW = datetime(2030, 1, 6, 9, 0, tzinfo=UTC).timestamp()
READY_P, BOTLESS, CHATLESS, VAULT, OLD, GONE = ("sender-ready", "sender-botless", "sender-chatless",
                                               "sender-vault", "sender-old", "sender-gone")
NAMES = (READY_P, BOTLESS, CHATLESS, VAULT, OLD, GONE)
TOKEN = "placeholder-token-not-real"
NO_BOT_SAID = "your reply named a profile with no Telegram bot, so it was not applied"
NO_CHAT_SAID = "your reply named a profile with no Telegram chat to send to, so it was not applied"
REFUSED = "pushes are failing; your last reply named a profile that cannot reach Telegram"
FAIL = ps.NO_SENDER_HOW


def no_process(*a, **k):
    raise AssertionError("the sender ingest started a process")


def iso(t):
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Home(unittest.TestCase):
    """A synthetic Hermes home with one profile per readiness answer, a state dir and a fake hermes on PATH."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.st = self.dir / "state"
        self.st.mkdir()
        self.hermes = self.dir / "hermes"
        self.hermes.mkdir()
        self.profile(READY_P, f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_HOME_CHANNEL=placeholder-chat\n")
        self.profile(BOTLESS)                                            # a dir and nothing else
        self.profile(CHATLESS, f"TELEGRAM_BOT_TOKEN={TOKEN}\n")         # a bot, but no home channel
        self.profile(VAULT, None, "secrets:\n  telegram:\n    source: synthetic-vault\n")
        self.profile(OLD, f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_HOME_CHANNEL=placeholder-chat\n")
        self.fakebin = self.dir / "fakebin"
        self.fakebin.mkdir()
        self.calls = self.dir / "hermes-calls"
        fake = self.fakebin / "hermes"
        fake.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> '{self.calls}'\nexit 0\n")
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        self.cfg = {"push_to": "telegram", "push_profile": OLD}
        self.env = {"HERMES_HOME": str(self.hermes), "LIMITLESS_STATE": str(self.st), "HOME": str(self.dir),
                    "PATH": f"{self.fakebin}{os.pathsep}{os.environ.get('PATH', '')}"}
        self.reply = self.st / sr.SENDER_FILE
        for target in ((subprocess, "Popen"), (os, "fork"), (os, "posix_spawn"), (os, "system"),
                       (os, "execv"), (os, "execve")):
            if hasattr(*target):
                p = mock.patch.object(*target, side_effect=no_process)
                p.start()
                self.addCleanup(p.stop)

    def tearDown(self):
        self.assertFalse(self.calls.exists(), "hermes was run")

    def profile(self, name, env_text=None, config_text=None):
        home = self.hermes / "profiles" / name
        home.mkdir(parents=True, exist_ok=True)
        if env_text is not None:
            (home / ".env").write_text(env_text)
        if config_text is not None:
            (home / "config.yaml").write_text(config_text)

    def ingest(self, replies, write=True, now=NOW, cfg=None):
        return sr.ingest(self.st, replies, now, write=write, env=self.env, cfg=self.cfg if cfg is None else cfg)

    def assertWordsOnly(self, text):
        self.assertNotRegex(text, r"\d", text)
        for leak in NAMES + ("push via", str(self.dir), str(TEST_HOME), TOKEN, "/"):
            self.assertNotIn(leak, text)


class Ingest(Home):
    def test_a_profile_with_no_telegram_bot_token_is_refused(self):
        got = self.ingest([(NOW - H, f"push via {BOTLESS}")])
        self.assertEqual(got["action"], sr.NO_BOT)
        self.assertEqual(got["reason"], NO_BOT_SAID)
        self.assertEqual(got["refused_at"], NOW - H)
        self.assertEqual(got["after"], NOW - H, "a definite no is not asked about again")
        self.assertFalse(self.reply.exists())
        self.assertWordsOnly(got["reason"])

    def test_a_refusal_leaves_an_earlier_reply_as_it_was(self):
        sr.write_reply(self.st, OLD, NOW - 9 * H)
        before = self.reply.read_bytes()
        got = self.ingest([(NOW - H, f"push via {BOTLESS}")])
        self.assertEqual(got["action"], sr.NO_BOT)
        self.assertEqual(self.reply.read_bytes(), before)

    def test_default_with_no_token_in_the_hermes_home_is_refused(self):
        got = self.ingest([(NOW - H, "push via default")])
        self.assertEqual(got["action"], sr.NO_BOT)
        self.assertFalse(self.reply.exists())

    def test_a_profile_with_a_bot_but_no_chat_is_refused(self):
        got = self.ingest([(NOW - H, f"push via {CHATLESS}")])
        self.assertEqual(got["action"], sr.NO_CHAT)
        self.assertEqual(got["reason"], NO_CHAT_SAID)
        self.assertFalse(self.reply.exists())
        self.assertWordsOnly(got["reason"])

    def test_the_target_is_the_one_kevin_push_uses(self):
        got = self.ingest([(NOW - H, f"push via {CHATLESS}")], cfg={"push_to": "telegram:@synthetic_chat"})
        self.assertEqual(got["action"], sr.WRITE, "a chat by @username needs no home channel")

    def test_a_profile_with_a_token_and_a_home_channel_is_applied(self):
        got = self.ingest([(NOW - H, f"push via {READY_P}")])
        self.assertEqual(got["action"], sr.WRITE)
        self.assertIsNone(got["refused_at"])
        self.assertEqual(json.loads(self.reply.read_text()), {"profile": READY_P, "at": NOW - H})

    def test_a_profile_whose_token_may_sit_in_a_secret_source_is_applied(self):
        self.assertEqual(ps.readiness(dict(self.cfg, push_profile=VAULT), self.env), ps.SECRET_SOURCE)
        got = self.ingest([(NOW - H, f"push via {VAULT}")])
        self.assertEqual(got["action"], sr.WRITE, "an unknown is never a refusal")
        self.assertEqual(json.loads(self.reply.read_text())["profile"], VAULT)

    def test_a_target_that_is_not_telegram_is_unknown_and_applied(self):
        got = self.ingest([(NOW - H, f"push via {BOTLESS}")], cfg={"push_to": "signal:synthetic"})
        self.assertEqual(got["action"], sr.WRITE)

    def test_a_token_in_the_jobs_environment_counts(self):
        self.env["TELEGRAM_BOT_TOKEN"] = TOKEN
        self.env["TELEGRAM_HOME_CHANNEL"] = "placeholder-chat"
        got = self.ingest([(NOW - H, f"push via {BOTLESS}")])
        self.assertEqual(got["action"], sr.WRITE)

    def test_a_missing_profile_is_still_missing_and_counts_as_a_refusal(self):
        got = self.ingest([(NOW - H, f"push via {GONE}")])
        self.assertEqual(got["action"], sr.MISSING)
        self.assertEqual(got["refused_at"], NOW - H)

    def test_a_dry_run_refuses_too_and_never_moves_the_mark(self):
        got = self.ingest([(NOW - H, f"push via {BOTLESS}")], write=False)
        self.assertEqual(got["action"], sr.NO_BOT)
        self.assertIsNone(got["after"])
        self.assertEqual(list(self.st.iterdir()), [])

    def test_the_readiness_asked_is_the_replys_profile_not_the_envs(self):
        self.env["KEVIN_PUSH_PROFILE"] = BOTLESS
        self.assertEqual(self.ingest([(NOW - H, f"push via {READY_P}")])["action"], sr.WRITE)
        self.env["KEVIN_PUSH_PROFILE"] = READY_P
        self.assertEqual(self.ingest([(NOW - H + 1, f"push via {BOTLESS}")])["action"], sr.NO_BOT)

    def test_the_mark_knows_the_refusal_words(self):
        for action in (sr.NO_BOT, sr.NO_CHAT):
            self.assertIn(action, sr.ACTIONS)
            self.assertNotRegex(action, r"\d")
            sr.write_mark(self.st, {"ran_at": NOW, "mode": "write", "action": action, "refused_at": NOW - H})
            self.assertEqual(sr.load_mark(self.st)["action"], action)
            self.assertEqual(sr.refused_at(self.st), NOW - H)
        self.assertEqual(sr.SAID[sr.NO_BOT], NO_BOT_SAID)
        self.assertEqual(sr.SAID[sr.NO_CHAT], NO_CHAT_SAID)


class Job(Home):
    """One limitless-jobs pass (jobs_runner.run_once) per step, in write mode, during a push outage."""

    def setUp(self):
        super().setUp()
        self.cfg_path = self.dir / "config.json"
        self.cfg = {"push_to": "telegram", "push_profile": OLD, "hermes_db": "hermes.db", "sender_ingest": "write",
                    "push_log": "push-log.jsonl"}
        self.cfg_path.write_text(json.dumps(self.cfg))
        self.env["LIMITLESS_CONFIG"] = str(self.cfg_path)
        self.first = NOW - 5 * H
        rows = [{"at": int(self.first), "tag": "limitless", "cls": "report", "title": "Wake-up brief",
                 "body": "Synthetic body.", "how": FAIL},
                {"at": int(NOW - 4 * H), "tag": "limitless", "cls": "report", "title": "MIQ for tonight?",
                 "body": "Synthetic body.", "how": FAIL}]
        (self.st / "push-log.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.db = self.st / "hermes.db"
        self.runs = []

    def says(self, messages):
        if self.db.exists():
            self.db.unlink()
        make_db(self.db, [("user", text, t) for text, t in messages], started=NOW - 6 * H)

    def sync(self, t):
        self.runs.append({"at": iso(t), "job": "sync", "ok": True, "took_s": 9.5})
        (self.st / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in self.runs))

    def once(self, now):
        rows = jobs_runner.run_once(self.st, now, push=None, dry_run=False, env=self.env, home=self.dir, tz=UTC)
        got = [r for r in rows if r["job"] == "Sender ingest"]
        self.assertEqual(len(got), 1, rows)
        return got[0]

    def mark(self):
        return json.loads((self.st / sr.MARK).read_text())

    def ingest_row(self, now):
        return doctor.sender_ingest_row(StateReader(self.st), self.cfg, now, env=self.env)

    def recovery(self, now):
        return doctor.push_recovery_row(StateReader(self.st), self.cfg, now)

    def test_a_botless_reply_is_refused_and_both_rows_say_so_while_the_outage_is_open(self):
        self.says([(f"push via {BOTLESS}", NOW - 2 * H)])
        self.sync(NOW - H)
        r = self.once(NOW - H + 60)
        self.assertEqual(r["reason"], f"a sync ran; {NO_BOT_SAID}")
        self.assertFalse(self.reply.exists())
        self.assertEqual(self.mark(), {"row_at": NOW - H, "ran_at": NOW - H + 60, "mode": "write",
                                       "action": sr.NO_BOT, "after": NOW - 2 * H, "refused_at": NOW - 2 * H})
        self.assertEqual(ps.profile(self.cfg, self.env), OLD, "never a fallback, never a pick by the code")
        d = self.ingest_row(NOW - H + 120)
        self.assertEqual(d["status"], doctor.LIVE)
        self.assertTrue(d["reason"].endswith(f": {NO_BOT_SAID}; {REFUSED}"), d)
        self.assertEqual(self.recovery(NOW - H + 120), {"name": doctor.PUSH_RECOVERY_ROW, "kind": "source",
                                                         "status": doctor.MISSING, "reason": REFUSED})
        for text in (r["reason"], d["reason"], self.recovery(NOW)["reason"], (self.st / sr.MARK).read_text()):
            for leak in NAMES + (TOKEN, "push via"):
                self.assertNotIn(leak, text)
        for text in (r["reason"], d["reason"]):
            self.assertWordsOnly(text)

        # the next sync with no new reply: the ingest says nothing new, but the refusal still shows
        self.sync(NOW - H / 2)
        r = self.once(NOW - H / 2 + 60)
        self.assertIn("no new sender reply", r["reason"])
        self.assertEqual(self.mark()["refused_at"], NOW - 2 * H)
        self.assertTrue(self.ingest_row(NOW - H / 2 + 120)["reason"].endswith(f"; {REFUSED}"))
        self.assertEqual(self.recovery(NOW - H / 2 + 120)["reason"], REFUSED)

        # a good reply then applies, and the refusal words are gone
        self.says([(f"push via {BOTLESS}", NOW - 2 * H), (f"push via {READY_P}", NOW - H / 4)])
        self.sync(NOW - H / 8)
        r = self.once(NOW - H / 8 + 60)
        self.assertEqual(r["reason"], "a sync ran; set the sender profile from your reply")
        self.assertEqual(json.loads(self.reply.read_text())["profile"], READY_P)
        self.assertNotIn("refused_at", self.mark())
        self.assertNotIn(REFUSED, self.ingest_row(NOW)["reason"])
        self.assertEqual(self.recovery(NOW)["status"], doctor.STALE)
        self.assertTrue(self.recovery(NOW)["reason"].startswith(pr.NOT_DELIVERED), self.recovery(NOW))

    def test_a_refusal_from_before_the_outage_is_not_shown(self):
        self.says([(f"push via {BOTLESS}", NOW - 5.5 * H)])
        self.sync(NOW - 5.2 * H)
        self.once(NOW - 5.2 * H + 60)
        self.assertEqual(self.mark()["refused_at"], NOW - 5.5 * H)
        self.assertEqual(self.recovery(NOW)["reason"], pr.WAITING_REPLY)
        self.assertNotIn(REFUSED, self.ingest_row(NOW)["reason"])

    def test_no_refusal_words_when_pushes_are_reaching_the_owner(self):
        (self.st / "push-log.jsonl").write_text(json.dumps({"at": int(NOW - H), "tag": "limitless", "cls": "report",
                                                            "title": "Wake-up brief", "body": "Synthetic body.",
                                                            "how": "telegram"}) + "\n")
        self.says([(f"push via {CHATLESS}", NOW - 2 * H)])
        self.sync(NOW - H)
        r = self.once(NOW - H + 60)
        self.assertEqual(r["reason"], f"a sync ran; {NO_CHAT_SAID}")
        self.assertEqual(self.recovery(NOW)["reason"], pr.NO_OUTAGE)
        self.assertNotIn(REFUSED, self.ingest_row(NOW)["reason"])


class Stage(unittest.TestCase):
    """push_recovery.stage over a synthetic log and a synthetic ingest mark (no Hermes home needed)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.st = Path(tmp.name)
        self.first = NOW - 3 * H
        self.rows = [{"at": int(self.first), "how": FAIL, "title": "Wake-up brief"},
                     {"at": int(NOW - 2 * H), "how": FAIL, "title": "MIQ for tonight?"}]

    def test_the_last_reply_decides(self):
        sr.write_mark(self.st, {"action": sr.NO_BOT, "refused_at": NOW - H})
        self.assertEqual(pr.stage(self.st, self.rows, {}, NOW), (pr.MISSING, REFUSED))
        sr.write_reply(self.st, READY_P, NOW - H / 2)     # a later reply applied: its confirmation is what waits
        self.assertEqual(pr.stage(self.st, self.rows, {}, NOW)[0], pr.STALE)
        sr.write_mark(self.st, {"action": sr.NO_CHAT, "refused_at": NOW - H / 4})   # then a later refusal
        self.assertEqual(pr.stage(self.st, self.rows, {}, NOW), (pr.MISSING, REFUSED))

    def test_the_words_hold_no_digit_path_or_name(self):
        self.assertIsNone(re.search(r"\d|/", pr.REFUSED))
        self.assertEqual(pr.REFUSED, REFUSED)


class NoStateDir(unittest.TestCase):
    """refused_at says it never raises, like push_sender.reply_at, which accepts a missing state dir."""

    def test_refused_at_is_none_without_a_state_dir(self):
        self.assertIsNone(ps.reply_at(None))
        self.assertIsNone(sr.refused_at(None))


if __name__ == "__main__":
    unittest.main()
