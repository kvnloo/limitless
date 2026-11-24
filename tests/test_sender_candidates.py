"""Which Hermes profiles could send kevin-push's pushes: push_sender.candidates, limitless-doctor's "sender
candidates" row, and the push recovery words that name them while pushes fail.

    candidates(cfg, env, hermes_home) -> [(name, readiness words)] sorted by name, or None (no Hermes home)

Synthetic Hermes homes in temp dirs, synthetic profile names (alpha, beta, ...), a made-up placeholder token.
Files only: a fake ``hermes`` on PATH records any call and process starts are patched to fail, so a test fails
if anything runs a process.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from limitless import doctor, push_recovery as pr, push_sender as ps  # noqa: E402
from limitless import sender_ingest_job as sij, sender_reply as sr  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from hermes_profile_fixture import TOKEN, ready_profile  # noqa: E402

NOW = 1894708800.0   # a fixed made-up clock
H = 3600.0
FAIL = ps.NO_SENDER_HOW
ROW = "sender candidates"
SECRET_YAML = "secrets:\n  telegram:\n    source: synthetic-vault\n"


def no_process(*a, **k):
    raise AssertionError("a process was started")


class Home(unittest.TestCase):
    """A synthetic Hermes home (the root, ``default``, has no Telegram bot) and a fake hermes on PATH."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.hermes = self.dir / "hermes"
        (self.hermes / "profiles").mkdir(parents=True)
        (self.hermes / "config.yaml").write_text("model: synthetic\n")
        self.st = self.dir / "state"
        self.st.mkdir()
        fakebin = self.dir / "fakebin"
        fakebin.mkdir()
        self.calls = self.dir / "hermes-calls"
        fake = fakebin / "hermes"
        fake.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> '{self.calls}'\nexit 0\n")
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        path = f"{fakebin}{os.pathsep}{os.environ.get('PATH', '')}"
        self.env = {"HERMES_HOME": str(self.hermes), "HOME": str(self.dir), "PATH": path,
                    "LIMITLESS_STATE": str(self.st)}
        p = mock.patch.dict(os.environ, {"PATH": path})
        p.start()
        self.addCleanup(p.stop)
        for target in ((subprocess, "Popen"), (os, "fork"), (os, "posix_spawn"), (os, "system")):
            if hasattr(*target):
                p = mock.patch.object(*target, side_effect=no_process)
                p.start()
                self.addCleanup(p.stop)
        self.cfg = {"push_profile": "gone", "push_to": "telegram"}

    def tearDown(self):
        self.assertFalse(self.calls.exists(), "hermes was run")

    def ready(self, name):
        return ready_profile(self.hermes / "profiles" / name)

    def botless(self, name):
        home = self.hermes / "profiles" / name
        home.mkdir(parents=True)
        (home / ".env").write_text("TELEGRAM_HOME_CHANNEL=placeholder-chat\n")
        return home

    def vault(self, name):
        home = self.hermes / "profiles" / name
        home.mkdir(parents=True)
        (home / "config.yaml").write_text(SECRET_YAML)
        return home

    def tombstone(self, name):
        mark = self.hermes / "profiles" / ".deleted" / name
        mark.parent.mkdir(parents=True, exist_ok=True)
        mark.write_bytes(b"deleted\n")

    def candidates(self, cfg=None, env=None):
        return ps.candidates(self.cfg if cfg is None else cfg, self.env if env is None else env)

    def row(self, cfg=None, env=None):
        return doctor.sender_candidates_row(self.cfg if cfg is None else cfg, self.env if env is None else env)

    def reason(self, **kw):
        return self.row(**kw)["reason"]


class Candidates(Home):
    def test_every_resolvable_profile_with_its_readiness_sorted_by_name(self):
        self.ready("beta")
        self.ready("alpha")
        self.botless("gamma")
        self.vault("delta")
        self.assertEqual(self.candidates(), [("alpha", ps.READY), ("beta", ps.READY), ("default", ps.NO_TOKEN),
                                             ("delta", ps.SECRET_SOURCE), ("gamma", ps.NO_TOKEN)])

    def test_each_answer_is_what_readiness_says_for_that_profile_as_the_sender(self):
        self.ready("alpha")
        self.botless("gamma")
        for name, words in self.candidates():
            self.assertEqual(words, ps.readiness(self.cfg, dict(self.env, KEVIN_PUSH_PROFILE=name)))

    def test_the_answer_is_for_kevin_push_target(self):
        home = self.hermes / "profiles" / "alpha"
        home.mkdir()
        (home / ".env").write_text(f"TELEGRAM_BOT_TOKEN={TOKEN}\n")   # a bot, no home channel
        self.assertIn(("alpha", ps.NO_CHAT), self.candidates({"push_to": "telegram"}))
        self.assertIn(("alpha", ps.READY), self.candidates({"push_to": "telegram:-100123"}))

    def test_a_tombstoned_profile_is_skipped(self):
        self.ready("alpha")
        self.ready("epsilon")
        self.tombstone("epsilon")
        self.assertEqual([n for n, _ in self.candidates()], ["alpha", "default"])

    def test_names_hermes_never_resolves_and_plain_files_are_skipped(self):
        self.ready("alpha")
        ready_profile(self.hermes / "profiles" / "Upper")
        ready_profile(self.hermes / "profiles" / ".hidden")
        ready_profile(self.hermes / "profiles" / "-dash")
        (self.hermes / "profiles" / "file-only").write_text("not a dir")
        self.assertEqual([n for n, _ in self.candidates()], ["alpha", "default"])

    def test_a_ready_root_is_listed_as_default(self):
        ready_profile(self.hermes)
        self.assertEqual(self.candidates(), [("default", ps.READY)])

    def test_no_profiles_dir_is_only_default(self):
        (self.hermes / "profiles").rmdir()
        self.assertEqual(self.candidates(), [("default", ps.NO_TOKEN)])

    def test_a_profile_home_as_hermes_home_resolves_against_its_root(self):
        self.ready("alpha")
        env = dict(self.env, HERMES_HOME=str(self.hermes / "profiles" / "alpha"))
        self.assertEqual([n for n, _ in self.candidates(env=env)], ["alpha", "default"])

    def test_an_explicit_hermes_home_wins(self):
        other = self.dir / "other"
        ready_profile(other / "profiles" / "zeta")
        self.assertEqual([n for n, _ in ps.candidates(self.cfg, self.env, other)], ["default", "zeta"])

    def test_no_hermes_home_is_none(self):
        self.assertIsNone(self.candidates(env={"PATH": self.env["PATH"]}))
        self.assertIsNone(self.candidates(env=dict(self.env, HERMES_HOME=str(self.dir / "nowhere"))))

    def test_it_never_holds_a_token_value(self):
        self.ready("alpha")
        self.assertNotIn(TOKEN, repr(self.candidates(env=dict(self.env, TELEGRAM_BOT_TOKEN=TOKEN + "-env"))))


class Row(Home):
    def test_two_ready_profiles_are_both_listed_ready(self):
        self.ready("alpha")
        self.ready("beta")
        self.assertEqual(self.row(), {"name": ROW, "kind": "source", "status": doctor.LIVE,
                                      "reason": "ready: alpha, beta"})

    def test_a_profile_without_a_token_is_not_listed(self):
        self.ready("alpha")
        self.botless("gamma")
        self.assertEqual(self.reason(), "ready: alpha")

    def test_a_profile_with_a_secret_source_is_maybe(self):
        self.ready("alpha")
        self.vault("delta")
        self.assertEqual(self.reason(), "ready: alpha; maybe: delta (keeps its token in a secret source)")
        self.vault("eta")
        self.assertEqual(self.reason(), "ready: alpha; maybe: delta, eta (keep their tokens in a secret source)")

    def test_only_maybe_is_missing(self):
        self.vault("delta")
        r = self.row()
        self.assertEqual((r["status"], r["reason"]), (doctor.MISSING, "maybe: delta (keeps its token in a secret source)"))

    def test_a_deleted_marker_profile_is_skipped(self):
        self.ready("alpha")
        self.ready("epsilon")
        self.tombstone("epsilon")
        self.assertEqual(self.reason(), "ready: alpha")

    def test_none_can_reach_telegram(self):
        self.botless("gamma")
        r = self.row()
        self.assertEqual((r["status"], r["reason"]), (doctor.MISSING, "none can reach Telegram"))

    def test_no_hermes_home_is_off(self):
        r = self.row(env={"PATH": self.env["PATH"]})
        self.assertEqual((r["status"], r["reason"]), (doctor.OFF, "no Hermes home is set (HERMES_HOME or HOME)"))
        r = self.row(env=dict(self.env, HERMES_HOME=str(self.dir / "nowhere")))
        self.assertEqual((r["status"], r["reason"]), (doctor.OFF, "the Hermes home does not exist"))

    def test_a_target_off_telegram_makes_every_profile_maybe(self):
        self.ready("alpha")
        self.assertEqual(self.reason(cfg={"push_to": "discord:ops"}),
                         "maybe: alpha, default (the send target is not a Telegram chat)")

    def test_a_name_with_a_digit_is_never_printed(self):
        self.ready("alpha")
        self.ready("bot2")
        self.ready("bot3")
        self.assertEqual(self.reason(), "ready: alpha, two more whose names hold a digit")
        (self.hermes / "profiles" / "bot3" / ".env").unlink()
        self.assertEqual(self.reason(), "ready: alpha, one more whose name holds a digit")

    def test_no_token_path_or_digit_in_the_words(self):
        self.ready("alpha")
        self.vault("delta")
        self.botless("gamma")
        got = self.reason(env=dict(self.env, TELEGRAM_BOT_TOKEN=TOKEN + "-env"))
        self.assertNotIn(TOKEN, got)
        self.assertIsNone(re.search(r"\d|/|placeholder", got), got)
        self.assertEqual(doctor.words(got), got)

    def test_strict_does_not_count_it(self):
        self.assertFalse(doctor.strict_failed([self.row()]))


class InTheReport(Home):
    def rows(self):
        cfg = dict(self.cfg, state=str(self.st))
        cfg_path = self.dir / "config.json"
        cfg_path.write_text(json.dumps(cfg))
        clean = {k: v for k, v in os.environ.items() if not k.startswith(("LIMITLESS_", "KEVIN_PUSH_", "HERMES_"))}
        clean.update(self.env, LIMITLESS_CONFIG=str(cfg_path))
        clean.pop("LIMITLESS_STATE")
        with mock.patch.dict(os.environ, clean, clear=True):
            return doctor.report(cfg, NOW)

    def test_right_after_the_push_sender_row(self):
        self.ready("alpha")
        rows = self.rows()
        names = [r["name"] for r in rows]
        self.assertEqual(names.count(ROW), 1)
        self.assertEqual(names[names.index(doctor.PUSH_SENDER_ROW) + 1], ROW)
        self.assertEqual(names[names.index(ROW) + 1], doctor.PUSH_RECOVERY_ROW)
        self.assertEqual(rows[names.index(ROW)]["reason"], "ready: alpha")


def log_row(at, how):
    return {"at": int(at), "tag": "limitless", "cls": "report", "title": "Wake-up brief", "body": "Synthetic body.",
            "how": how}


class Recovery(Home):
    """While pushes fail and the owner must reply, the push recovery words say which profiles can send."""

    def setUp(self):
        super().setUp()
        self.cfg = dict(self.cfg, push_log="push-log.jsonl")
        self.rows = [log_row(NOW - 5 * H, "telegram"), log_row(NOW - 3 * H, FAIL), log_row(NOW - 2 * H, FAIL)]

    def stage(self, env=None):
        return pr.stage(self.st, self.rows, self.cfg, NOW, env=self.env if env is None else env)

    def test_waiting_for_a_reply_names_the_ready_profiles(self):
        self.ready("alpha")
        self.ready("beta")
        self.botless("gamma")
        self.assertEqual(self.stage(), (pr.MISSING, pr.WAITING_REPLY + "; ready profiles: alpha, beta"))

    def test_refused_says_when_no_profile_can_reach_telegram(self):
        self.botless("gamma")
        sr.write_mark(self.st, {"action": sr.NO_BOT, "refused_at": NOW - H})
        self.assertEqual(self.stage(), (pr.MISSING, pr.REFUSED + "; no profile can reach Telegram"))

    def test_only_maybe_profiles_are_named_as_maybe(self):
        self.vault("delta")
        self.assertEqual(self.stage(), (pr.MISSING, pr.WAITING_REPLY + "; profiles that may reach Telegram: delta"))

    def test_no_hermes_home_adds_nothing(self):
        self.assertEqual(self.stage(env={"PATH": self.env["PATH"]}), (pr.MISSING, pr.WAITING_REPLY))

    def test_the_words_still_start_with_the_constant(self):
        self.ready("alpha")
        status, words = self.stage()
        self.assertTrue(words.startswith(pr.WAITING_REPLY))

    def test_other_stages_add_nothing(self):
        self.ready("alpha")
        self.assertEqual(pr.stage(self.st, [log_row(NOW - H, "telegram")], self.cfg, NOW, env=self.env),
                         (pr.LIVE, pr.NO_OUTAGE))
        sr.write_reply(self.st, "alpha", NOW - H)
        self.assertEqual(self.stage()[0], pr.STALE)
        self.assertNotIn("alpha", self.stage()[1])

    def test_from_state_and_the_doctor_row_pass_the_env(self):
        self.ready("alpha")
        (self.st / "push-log.jsonl").write_text("".join(json.dumps(r) + "\n" for r in self.rows))
        self.assertEqual(pr.from_state(self.st, self.cfg, NOW, env=self.env)[1],
                         pr.WAITING_REPLY + "; ready profiles: alpha")
        r = doctor.push_recovery_row(StateReader(self.st), self.cfg, NOW, env=self.env)
        self.assertEqual(r["reason"], pr.WAITING_REPLY + "; ready profiles: alpha")

    def test_the_sender_ingest_refusal_stays_the_bare_constant(self):
        self.ready("alpha")
        (self.st / "push-log.jsonl").write_text("".join(json.dumps(r) + "\n" for r in self.rows))
        sr.write_mark(self.st, {"action": sr.NO_BOT, "refused_at": NOW - H})
        with mock.patch.dict(os.environ, {"HERMES_HOME": str(self.hermes)}):
            self.assertTrue(pr.from_state(self.st, self.cfg, NOW)[1].startswith(pr.REFUSED + "; ready profiles"))
            self.assertEqual(sij.refusal_words(self.st, self.cfg, NOW), pr.REFUSED)


class Docs(unittest.TestCase):
    def test_the_example_is_the_scripts_real_output(self):
        r = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "sender_candidates_example.py")],
                           capture_output=True, text=True, timeout=60, env=child_env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("sender candidates: live: ready: alpha, beta", r.stdout)
        self.assertNotIn("made-up-token", r.stdout)
        blocks = re.findall(r"```text\n(.*?)```", (ROOT / "docs" / "doctor.md").read_text(), re.S)
        self.assertIn(r.stdout, blocks)

    def test_doctor_md_names_the_row_and_its_words(self):
        text = (ROOT / "docs" / "doctor.md").read_text()
        for word in ("`sender candidates`, right after the push sender row", "## Sender candidates row",
                     "ready: ", "maybe: ", "none can reach Telegram", "profiles/.deleted/",
                     "; ready profiles: ", "; no profile can reach Telegram"):
            self.assertIn(word, text)

    def test_the_reply_doc_points_at_the_row(self):
        text = (ROOT / "docs" / "push-sender-reply.md").read_text()
        for word in ("sender candidates", "; ready profiles: ", "push_sender.candidates"):
            self.assertIn(word, text)


if __name__ == "__main__":
    unittest.main()
