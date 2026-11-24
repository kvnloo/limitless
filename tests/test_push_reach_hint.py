"""The state card's push-outage line names the one reply that fixes it (push_reach.hint): while push_recovery.stage
is missing with WAITING_REPLY / REFUSED / UNKNOWN_FAILED, the line goes on with "Reply push via <name> to fix it."
for one ready profile, "Reply push via one of: a, b." for several, else "Reply with a profile that has a Telegram
bot." A maybe is never offered as sure, a name with a digit is never printed, and the line stays one line.

Synthetic state (tests/fixtures/state), synthetic Hermes homes (profiles with and without a made-up bot token and
chat key), synthetic kevin-push logs, a fixed clock and day, env passed explicitly. Nothing is run or sent."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import card, delivery_audit, push_reach, sender_reply, tier_audit  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "state"
NOW = 1894708800.0
TODAY = date(2030, 1, 15)
DAY = TODAY - timedelta(days=3)
PROFILE = "sender-a"
PREFIX = "Phone pushes are not reaching you: "
SEND_FAILING = PREFIX + "the last pushes failed to send"
SENDER_MISSING = PREFIX + "the sender profile is missing"
GENERIC = "Reply with a profile that has a Telegram bot."
ONE = "Reply push via helper to fix it."
RC1 = "log (telegram rc=1)"


def log_row(hour, how="telegram"):
    at = int(datetime(DAY.year, DAY.month, DAY.day, hour, 0, tzinfo=timezone.utc).timestamp())
    return {"at": at, "tag": "x", "cls": "decision", "title": "Pick one", "how": how,
            "body": "Keep the loop?\nReply: Yes / No"}


FAILING_LAST = [log_row(10), log_row(11, RC1), log_row(12, RC1)]    # an open outage: WAITING_REPLY
DELIVERED_LAST = [log_row(10, RC1), log_row(11, RC1), log_row(12)]  # closed by a delivery: no open outage


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.st = root / "st"
        shutil.copytree(FIX, self.st)
        self.hermes = root / "hermes"
        (self.hermes / "profiles" / PROFILE).mkdir(parents=True)   # the sender: there, but no bot
        self.log = self.st / "push-log.jsonl"
        self.cfg_path = root / "config.json"
        self.cfg = {"push_profile": PROFILE, "push_to": "telegram", "push_log": "push-log.jsonl"}
        self.cfg_path.write_text(json.dumps(self.cfg))
        self.env = {"HOME": str(root), "HERMES_HOME": str(self.hermes), "LIMITLESS_STATE": str(self.st),
                    "LIMITLESS_CONFIG": str(self.cfg_path)}
        self.r = StateReader(self.st)

    def profile(self, name, kind="ready"):
        """A synthetic profile: ``ready`` has a made-up token and home channel key, ``maybe`` keeps its token in a
        secret source (readiness cannot tell), ``none`` has no token."""
        p = self.hermes / "profiles" / name
        p.mkdir(parents=True, exist_ok=True)
        env_file = p / ".env"
        if kind == "ready":
            env_file.write_text("TELEGRAM_BOT_TOKEN=made-up-token\nTELEGRAM_HOME_CHANNEL=made-up-chat\n")
        elif env_file.exists():
            env_file.unlink()
        if kind == "maybe":
            (p / "config.yaml").write_text("secrets:\n  vault:\n    kind: example\n")
        return p

    def write_log(self, rows):
        self.log.write_text("".join(json.dumps(r) + "\n" for r in rows))

    def write_state(self, name, data):
        (self.st / name).write_text(json.dumps(data))

    def hint(self):
        return push_reach.hint(self.cfg, self.st, self.env)

    def build(self, **kw):
        return card.build(self.r, NOW, TODAY, env=self.env, **kw)

    def outage_lines(self, lines=None):
        return [ln for ln in (self.build()["lines"] if lines is None else lines) if ln.startswith(PREFIX)]


class Hint(Base):
    def test_one_ready_profile_is_named_in_exact_words(self):
        self.profile("helper")
        self.write_log(FAILING_LAST)
        self.assertEqual(self.hint(), ONE)
        self.assertEqual(self.outage_lines(), [SEND_FAILING + ". " + ONE])

    def test_two_ready_profiles_are_both_named(self):
        self.profile("helper")
        self.profile("relay")
        self.write_log(FAILING_LAST)
        self.assertEqual(self.hint(), "Reply push via one of: helper, relay.")
        self.assertEqual(self.outage_lines(), [SEND_FAILING + ". Reply push via one of: helper, relay."])

    def test_only_maybes_get_the_generic_words(self):
        self.profile("helper", "maybe")
        self.profile("relay", "none")
        self.write_log(FAILING_LAST)
        self.assertEqual(self.hint(), GENERIC)
        line = self.outage_lines()[0]
        self.assertEqual(line, SEND_FAILING + ". " + GENERIC)
        self.assertNotIn("helper", line)

    def test_a_ready_name_with_a_digit_is_not_printed(self):
        self.profile("helper")
        self.profile("relay2")
        self.write_log(FAILING_LAST)
        self.assertEqual(self.hint(), ONE)
        self.profile("helper", "none")
        self.assertEqual(self.hint(), GENERIC)

    def test_the_failing_sender_itself_is_not_offered(self):
        self.profile(PROFILE)     # the sender that is failing looks ready on files
        self.write_log(FAILING_LAST)
        self.assertEqual(self.hint(), GENERIC)

    def test_no_outage_no_hint(self):
        self.profile("helper")
        self.write_log(DELIVERED_LAST)
        self.assertIsNone(self.hint())
        self.assertEqual(self.outage_lines(), [])

    def test_a_missing_sender_without_an_open_outage_gets_no_hint(self):
        self.profile("helper")
        self.cfg["push_profile"] = "gone"
        self.cfg_path.write_text(json.dumps(self.cfg))
        self.write_log(DELIVERED_LAST)
        self.assertEqual(self.outage_lines(), [SENDER_MISSING])

    def test_a_refused_reply_gets_the_hint(self):
        self.profile("helper")
        self.write_log(FAILING_LAST)
        self.write_state(sender_reply.MARK, {"refused_at": NOW})
        self.assertIsNotNone(sender_reply.refused_at(self.st))   # sanity: the mark is read as a refusal
        self.assertEqual(self.hint(), ONE)

    def test_an_applied_maybe_that_failed_gets_the_hint(self):
        self.profile("helper")
        self.profile("vaulted", "maybe")
        self.write_log(FAILING_LAST)
        self.write_state("push-sender.json", {"profile": "vaulted", "at": NOW})
        self.write_state(sender_reply.MARK, {"applied_unknown": True})
        self.write_state("sender-confirm.json", {"reply_at": NOW, "outcome": "failed"})
        self.assertEqual(self.hint(), ONE)
        self.assertEqual(len(self.outage_lines()), 1)
        self.assertTrue(self.outage_lines()[0].endswith("another profile. " + ONE))

    def test_a_pending_confirmation_gets_no_hint(self):
        self.profile("helper")
        self.write_log(FAILING_LAST)
        self.write_state("push-sender.json", {"profile": "helper", "at": NOW})
        self.assertIsNone(self.hint())

    def test_no_push_log_or_no_hermes_home_never_raises(self):
        self.assertIsNone(push_reach.hint({}, self.st, self.env))
        self.assertIsNone(push_reach.hint(None, None, {}))
        self.write_log(FAILING_LAST)
        shutil.rmtree(self.hermes)
        self.assertEqual(self.hint(), GENERIC)

    def test_one_line_within_max_lines_and_no_digit(self):
        self.profile("helper")
        self.profile("relay")
        self.write_log(FAILING_LAST)
        c = self.build()
        self.assertEqual(len(self.outage_lines(c["lines"])), 1)
        self.assertLessEqual(len([ln for ln in c["lines"] if not ln.startswith(PREFIX)]), card.MAX_LINES)
        self.assertEqual(re.findall(r"\d", c["text"]), [])
        self.assertNotIn(self.tmp.name, c["text"])
        self.assertNotIn("/", self.outage_lines(c["lines"])[0])

    def test_the_status_item_keeps_the_bare_reason(self):
        self.profile("helper")
        self.write_log(FAILING_LAST)
        self.assertEqual(self.build()["items"]["delivery"]["value"], SEND_FAILING)

    def test_line_without_a_hint_is_unchanged(self):
        self.assertEqual(push_reach.line(push_reach.SEND_FAILING), SEND_FAILING)
        self.assertEqual(push_reach.line(push_reach.SEND_FAILING, ONE), SEND_FAILING + ". " + ONE)
        self.assertIsNone(push_reach.line(None, ONE))


class Cache(Base):
    def setUp(self):
        super().setUp()
        self.c = card.CardCache()

    def get(self):
        return self.c.get(self.r, NOW, TODAY, env=self.env)

    def test_a_new_ready_profile_rebuilds_and_a_hit_reads_nothing(self):
        self.write_log(FAILING_LAST)
        self.assertIn(SEND_FAILING + ". " + GENERIC, self.get())
        self.profile("helper")
        prof = self.hermes / "profiles"
        st = prof.stat()
        os.utime(prof, ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 9))
        self.assertIn(SEND_FAILING + ". " + ONE, self.get())
        self.assertEqual(self.c.builds, 2)
        real = delivery_audit.read_log
        with mock.patch.object(delivery_audit, "read_log", side_effect=real) as rl:
            self.get()
        self.assertEqual((self.c.builds, rl.call_count), (2, 0))


class Hook(Base):
    def test_the_hint_goes_through_the_tier_gate(self):
        self.profile("helper")
        self.write_log(FAILING_LAST)
        seen = []
        real = tier_audit.gate

        def spy(hook, text, *a, **k):
            seen.append(text)
            return real(hook, text, *a, **k)

        with mock.patch.object(tier_audit, "gate", side_effect=spy):
            out = card.make_pre_llm_call(env=self.env, clock=lambda: NOW, today=lambda: TODAY)(user_message="hi")
        want = SEND_FAILING + ". " + ONE
        self.assertIn(want, out["context"].splitlines())
        self.assertEqual(len(seen), 1)
        self.assertIn(want, seen[0])


if __name__ == "__main__":
    unittest.main()
