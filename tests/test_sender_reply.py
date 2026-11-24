"""limitless.sender_reply: the owner's whole "push via <profile>" reply, checked against the Hermes home, and the
push-sender.json it writes, which push_sender.profile reads after $KEVIN_PUSH_PROFILE and before config
``push_profile``.

Synthetic Hermes homes, synthetic state dirs and made-up profile names only. Nothing here sends, runs hermes or
starts a process.
"""
from hermetic_env import TEST_HOME  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

sys.path.insert(0, os.path.dirname(__file__))
from limitless import push_sender as ps, sender_reply as sr  # noqa: E402
from hermes_profile_fixture import ready_profile  # noqa: E402

UTC = timezone.utc
H = 3600
NOW = datetime(2030, 1, 6, 9, 0, tzinfo=UTC).timestamp()
GOOD, OTHER, GONE = "sender-synth", "sender-other", "sender-gone"


def no_process(*a, **k):
    raise AssertionError("sender_reply started a process")


class Parse(unittest.TestCase):
    def test_a_whole_push_via_message_names_the_profile(self):
        self.assertEqual(sr.parse("push via default"), "default")
        self.assertEqual(sr.parse(f"push via {GOOD}"), GOOD)
        self.assertEqual(sr.parse("push via a_b-9"), "a_b-9")

    def test_case_and_surrounding_space_are_ignored(self):
        self.assertEqual(sr.parse("  Push Via Default \n"), "default")
        self.assertEqual(sr.parse("PUSH VIA Sender-Synth"), GOOD)
        self.assertEqual(sr.parse("push   via\tdefault"), "default")

    def test_the_phrase_inside_a_longer_message_is_ignored(self):
        for text in ("please push via default", "push via default please", "push via default.",
                     "ok, push via default", "I said: push via default", "push via default\nthanks",
                     "thanks\npush via default", '"push via default"', "> push via default",
                     "Reply 'push via default' to pick the sender"):
            self.assertIsNone(sr.parse(text), text)

    def test_anything_but_a_profile_name_is_ignored(self):
        for text in ("push via", "push via ", "push via two words", "push via ../x", "push via a/b", "push via -a",
                     "push via _a", "push via " + "a" * 65, "push via sender.synth", "push  default", "pushvia default",
                     "push via\ndefault", "", None, 3, b"push via default"):
            self.assertIsNone(sr.parse(text), repr(text))

    def test_the_longest_name_hermes_resolves_is_kept(self):
        self.assertEqual(sr.parse("push via " + "a" * 64), "a" * 64)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.st = self.dir / "state"
        self.st.mkdir()
        self.hermes = self.dir / "hermes"
        for home in (self.hermes, self.hermes / "profiles" / GOOD, self.hermes / "profiles" / OTHER):
            ready_profile(home)   # each can reach Telegram (sender_reply asks readiness after check)
        self.env = {"HERMES_HOME": str(self.hermes), "LIMITLESS_STATE": str(self.st)}
        self.reply = self.st / sr.SENDER_FILE
        patcher = mock.patch.object(subprocess, "Popen", side_effect=no_process)
        patcher.start()
        self.addCleanup(patcher.stop)

    def ingest(self, replies, write=True, now=NOW, env=None):
        return sr.ingest(self.st, replies, now, write=write, env=self.env if env is None else env)

    def assertWordsOnly(self, text):
        self.assertNotRegex(text, r"\d", text)
        for leak in (GOOD, OTHER, GONE, "push via", str(self.dir), str(TEST_HOME)):
            self.assertNotIn(leak, text)


class Ingest(Base):
    def test_a_reply_naming_an_existing_profile_writes_push_sender_json(self):
        got = self.ingest([(NOW - 2 * H, f"push via {GOOD}")])
        self.assertEqual(got["action"], sr.WRITE)
        self.assertEqual(json.loads(self.reply.read_text()), {"profile": GOOD, "at": NOW - 2 * H})
        self.assertEqual(stat.S_IMODE(self.reply.stat().st_mode), 0o600)
        self.assertEqual(got["after"], NOW - 2 * H)
        self.assertWordsOnly(got["reason"])

    def test_default_always_exists(self):
        got = self.ingest([(NOW - H, "push via Default")])
        self.assertEqual(got["action"], sr.WRITE)
        self.assertEqual(json.loads(self.reply.read_text())["profile"], "default")

    def test_a_reply_naming_a_missing_profile_changes_nothing(self):
        self.reply.write_text(json.dumps({"profile": OTHER, "at": NOW - 9 * H}) + "\n")
        before = self.reply.read_bytes()
        got = self.ingest([(NOW - H, f"push via {GONE}")])
        self.assertEqual(got["action"], sr.MISSING)
        self.assertIn("that sender profile does not exist", got["reason"])
        self.assertEqual(self.reply.read_bytes(), before)
        self.assertWordsOnly(got["reason"])

    def test_a_missing_profile_with_no_file_writes_none(self):
        got = self.ingest([(NOW - H, f"push via {GONE}")])
        self.assertEqual(got["action"], sr.MISSING)
        self.assertFalse(self.reply.exists())
        self.assertEqual(list(self.st.iterdir()), [], "ingest itself writes no mark")

    def test_the_newest_reply_wins_even_when_it_names_a_missing_profile(self):
        got = self.ingest([(NOW - 3 * H, f"push via {GOOD}"), (NOW - 2 * H, f"push via {GONE}")])
        self.assertEqual(got["action"], sr.MISSING)
        self.assertFalse(self.reply.exists(), "there is never a fallback to an older reply")

    def test_the_newest_of_two_good_replies_wins(self):
        got = self.ingest([(NOW - 2 * H, f"push via {OTHER}"), (NOW - 3 * H, f"push via {GOOD}")])
        self.assertEqual(got["action"], sr.WRITE)
        self.assertEqual(json.loads(self.reply.read_text())["profile"], OTHER)

    def test_other_messages_are_ignored_and_a_longer_message_never_counts(self):
        got = self.ingest([(NOW - 3 * H, f"push via {GOOD}"), (NOW - 2 * H, f"please push via {OTHER} now"),
                           (NOW - H, "a made-up note")])
        self.assertEqual(got["action"], sr.WRITE)
        self.assertEqual(json.loads(self.reply.read_text())["profile"], GOOD)
        self.assertEqual(got["after"], NOW - H, "the mark moves past every message read")

    def test_only_a_longer_message_is_nothing(self):
        got = self.ingest([(NOW - H, f"please push via {GOOD}")])
        self.assertEqual(got["action"], sr.NOTHING)
        self.assertFalse(self.reply.exists())
        self.assertEqual(got["after"], NOW - H)

    def test_no_message_is_nothing_and_the_mark_stays(self):
        got = self.ingest([])
        self.assertEqual(got["action"], sr.NOTHING)
        self.assertIsNone(got["after"])
        self.assertWordsOnly(got["reason"])

    def test_a_dry_run_writes_nothing_and_never_moves_the_mark(self):
        got = self.ingest([(NOW - H, f"push via {GOOD}")], write=False)
        self.assertEqual(got["action"], sr.WOULD_WRITE)
        self.assertFalse(self.reply.exists())
        self.assertIsNone(got["after"])
        self.assertEqual(list(self.st.iterdir()), [])

    def test_messages_up_to_the_mark_and_after_now_are_not_read(self):
        sr.write_mark(self.st, {"after": NOW - 2 * H})
        got = self.ingest([(NOW - 2 * H, f"push via {GOOD}"), (NOW + 60, f"push via {OTHER}")])
        self.assertEqual(got["action"], sr.NOTHING)
        self.assertFalse(self.reply.exists())

    def test_a_first_run_reads_only_the_last_day(self):
        got = self.ingest([(NOW - sr.FIRST_READ_S - 60, f"push via {GOOD}")])
        self.assertEqual(got["action"], sr.NOTHING)
        self.assertFalse(self.reply.exists())

    def test_an_unknown_hermes_home_changes_nothing_and_keeps_the_mark_for_a_retry(self):
        env = {"HERMES_HOME": str(self.dir / "nowhere"), "LIMITLESS_STATE": str(self.st)}
        got = self.ingest([(NOW - H, f"push via {GOOD}")], env=env)
        self.assertEqual(got["action"], sr.UNKNOWN)
        self.assertIn("the Hermes home does not exist", got["reason"])
        self.assertIsNone(got["after"])
        self.assertFalse(self.reply.exists())
        self.assertWordsOnly(got["reason"])

    def test_the_check_asks_about_the_named_profile_not_the_env_one(self):
        env = dict(self.env, KEVIN_PUSH_PROFILE=GONE)
        got = self.ingest([(NOW - H, f"push via {GOOD}")], env=env)
        self.assertEqual(got["action"], sr.WRITE)
        env = dict(self.env, KEVIN_PUSH_PROFILE=GOOD)
        got = self.ingest([(NOW - H + 1, f"push via {GONE}")], env=env)
        self.assertEqual(got["action"], sr.MISSING)

    def test_bad_timestamps_are_skipped(self):
        got = self.ingest([(None, f"push via {GOOD}"), (True, f"push via {GOOD}"), ("x", f"push via {GOOD}")])
        self.assertEqual(got["action"], sr.NOTHING)

    def test_the_mark_file_is_words_free_and_private(self):
        sr.write_mark(self.st, {"row_at": NOW - H, "ran_at": NOW, "mode": "write", "action": sr.WRITE,
                                "after": NOW - 2 * H})
        p = self.st / sr.MARK
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
        self.assertEqual(sr.load_mark(self.st), {"row_at": NOW - H, "ran_at": NOW, "mode": "write",
                                                 "action": sr.WRITE, "after": NOW - 2 * H})
        self.assertEqual(sr.read_after(self.st, NOW), NOW - 2 * H)

    def test_a_broken_mark_reads_as_none(self):
        (self.st / sr.MARK).write_text("not json")
        self.assertEqual(sr.load_mark(self.st), {})
        self.assertEqual(sr.read_after(self.st, NOW), NOW - sr.FIRST_READ_S)
        (self.st / sr.MARK).write_text(json.dumps({"after": True, "action": "made-up", "mode": "loud"}))
        m = sr.load_mark(self.st)
        self.assertEqual((m["after"], m["action"], m["mode"]), (None, None, None))


class Resolve(Base):
    def write(self, obj):
        self.reply.write_text(json.dumps(obj) + "\n")

    def test_the_reply_wins_over_an_old_config_value(self):
        self.write({"profile": GOOD, "at": NOW})
        self.assertEqual(ps.profile({"push_profile": OTHER}, self.env), GOOD)

    def test_env_still_wins_over_everything(self):
        self.write({"profile": GOOD, "at": NOW})
        env = dict(self.env, KEVIN_PUSH_PROFILE=OTHER)
        self.assertEqual(ps.profile({"push_profile": "sender-cfg"}, env), OTHER)

    def test_no_reply_file_is_config_then_the_default(self):
        self.assertEqual(ps.profile({"push_profile": OTHER}, self.env), OTHER)
        self.assertEqual(ps.profile({}, self.env), ps.PROFILE_DEFAULT)

    def test_a_broken_or_odd_reply_file_is_skipped(self):
        for raw in ("not json", "[]", json.dumps({"profile": ""}), json.dumps({"profile": 3}),
                    json.dumps({"profile": "../x"}), json.dumps({"at": NOW})):
            self.reply.write_text(raw)
            self.assertEqual(ps.profile({"push_profile": OTHER}, self.env), OTHER, raw)

    def test_the_state_dir_is_env_then_config_then_home(self):
        self.write({"profile": GOOD, "at": NOW})
        self.assertEqual(ps.profile({"state": str(self.st)}, {}), GOOD)
        home = self.dir / "home"
        (home / ".local/state/limitless").mkdir(parents=True)
        (home / ".local/state/limitless" / sr.SENDER_FILE).write_text(json.dumps({"profile": OTHER, "at": NOW}))
        self.assertEqual(ps.profile({}, {"HOME": str(home)}), OTHER)
        self.assertEqual(ps.profile({}, {}), ps.PROFILE_DEFAULT, "no state dir known: no reply file")
        self.assertEqual(ps.profile({}, {}, state_dir=self.st), GOOD)

    def test_check_and_readiness_follow_the_reply(self):
        self.write({"profile": GOOD, "at": NOW})
        self.assertEqual(ps.check({"push_profile": GONE}, self.env), ps.SET)
        self.write({"profile": GONE, "at": NOW})
        self.assertEqual(ps.check({"push_profile": GOOD}, self.env), ps.BROKEN)
        self.assertEqual(ps.readiness({"push_profile": GOOD}, self.env), ps.MISSING)


if __name__ == "__main__":
    unittest.main()
