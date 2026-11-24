"""The state card says, in words, when phone pushes cannot reach the person (push_reach), on a line of its own,
cached with the card (a cache hit opens no push log) and through tier_audit.gate like every other line.

Synthetic state (tests/fixtures/state), synthetic Hermes homes with and without the sender profile, synthetic
kevin-push logs, a fixed clock and day, env passed explicitly. Nothing is run or sent."""
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

from limitless import card, delivery_audit, tier_audit  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "state"
NOW = 1894708800.0
TODAY = date(2030, 1, 15)
PROFILE = "sender-a"
SENDER_MISSING = "Phone pushes are not reaching you: the sender profile is missing"
SEND_FAILING = "Phone pushes are not reaching you: the last pushes failed to send"
PREFIX = "Phone pushes are not reaching you"
GENERIC = ". Reply with a profile that has a Telegram bot."   # push_reach.hint: an open outage, no ready profile
DAY = TODAY - timedelta(days=3)   # well inside the seven-day window in any local zone


def log_row(hour, how="telegram"):
    at = int(datetime(DAY.year, DAY.month, DAY.day, hour, 0, tzinfo=timezone.utc).timestamp())
    return {"at": at, "tag": "x", "cls": "decision", "title": "Pick one", "how": how,
            "body": "Keep the loop?\nReply: Yes / No"}


RC1 = "log (telegram rc=1)"
DELIVERED_LAST = [log_row(10, RC1), log_row(11, RC1), log_row(12)]
FAILING_LAST = [log_row(10), log_row(11, RC1), log_row(12, RC1)]


def write_log(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.st = root / "st"
        shutil.copytree(FIX, self.st)
        self.hermes = root / "hermes"
        (self.hermes / "profiles" / "other").mkdir(parents=True)
        self.log = self.st / "push-log.jsonl"
        self.cfg = root / "config.json"
        self.cfg.write_text(json.dumps({"push_profile": PROFILE, "push_log": "push-log.jsonl"}))
        self.env = {"HOME": str(root), "HERMES_HOME": str(self.hermes), "LIMITLESS_STATE": str(self.st),
                    "LIMITLESS_CONFIG": str(self.cfg)}
        self.r = StateReader(self.st)

    def sender(self, present=True):
        p = self.hermes / "profiles" / PROFILE
        if present:
            p.mkdir(exist_ok=True)
            (p / "config.yaml").write_text("")   # a Hermes identity marker: the dir is a live profile
        elif p.exists():
            (p / "config.yaml").unlink()
            p.rmdir()

    def build(self, **kw):
        return card.build(self.r, NOW, TODAY, env=self.env, **kw)

    @staticmethod
    def bump(p):
        st = p.stat()
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 9))


class Build(Base):
    def test_a_missing_sender_is_its_own_line(self):
        write_log(self.log, DELIVERED_LAST)
        c = self.build()
        self.assertIn(SENDER_MISSING, c["lines"])
        self.assertEqual(c["items"]["delivery"]["value"], SENDER_MISSING)

    def test_failed_last_pushes_are_their_own_line(self):
        self.sender()
        write_log(self.log, FAILING_LAST)
        self.assertIn(SEND_FAILING + GENERIC, self.build()["lines"])

    def test_the_broken_sender_wins(self):
        write_log(self.log, FAILING_LAST)
        lines = self.build()["lines"]
        self.assertIn(SENDER_MISSING + GENERIC, lines)
        self.assertEqual([ln for ln in lines if ln.startswith(PREFIX)], [SENDER_MISSING + GENERIC])

    def test_a_set_sender_and_a_delivered_last_push_say_nothing(self):
        self.sender()
        write_log(self.log, DELIVERED_LAST)
        c = self.build()
        self.assertNotIn(PREFIX, c["text"])
        self.assertIsNone(c["items"]["delivery"]["value"])

    def test_unknown_says_nothing(self):
        shutil.rmtree(self.hermes)        # the Hermes home is gone: push_sender cannot tell
        self.cfg.write_text("{}")         # and no push log is set
        self.assertNotIn(PREFIX, self.build()["text"])

    def test_the_line_survives_a_full_card_and_holds_no_digit(self):
        write_log(self.log, DELIVERED_LAST)
        c = self.build()
        self.assertGreaterEqual(len(c["lines"]), card.MAX_LINES)   # sanity: the fixture card is full
        self.assertIn(SENDER_MISSING, c["lines"])
        self.assertEqual(re.findall(r"\d", c["text"]), [])

    def test_the_line_comes_before_the_offers_that_must_stay_last(self):
        write_log(self.log, DELIVERED_LAST)
        lines = self.build(explain_offer="Explain back: offer. Reply: Voice / Later")["lines"]
        self.assertEqual(lines[-1], "Explain back: offer. Reply: Voice / Later")
        self.assertEqual(lines[-2], SENDER_MISSING)


class Cache(Base):
    def setUp(self):
        super().setUp()
        self.c = card.CardCache()

    def get(self):
        return self.c.get(self.r, NOW, TODAY, env=self.env)

    def test_a_cache_hit_opens_no_push_log_and_reads_no_config(self):
        write_log(self.log, FAILING_LAST)
        self.sender()
        self.assertIn(SEND_FAILING, self.get())
        real_log, real_cfg = delivery_audit.read_log, card._config
        with mock.patch.object(delivery_audit, "read_log", side_effect=real_log) as rl, \
                mock.patch.object(card, "_config", side_effect=real_cfg) as rc:
            self.assertIn(SEND_FAILING, self.get())
            self.assertIn(SEND_FAILING, self.get())
        self.assertEqual(self.c.builds, 1)
        self.assertEqual((rl.call_count, rc.call_count), (0, 0))

    def test_a_push_log_change_rebuilds(self):
        self.sender()
        write_log(self.log, FAILING_LAST)
        self.assertIn(SEND_FAILING, self.get())
        write_log(self.log, FAILING_LAST + [log_row(13)])
        self.bump(self.log)
        self.assertNotIn(PREFIX, self.get())
        self.assertEqual(self.c.builds, 2)

    def test_the_sender_profile_coming_back_rebuilds(self):
        write_log(self.log, DELIVERED_LAST)
        self.assertIn(SENDER_MISSING, self.get())
        self.sender()
        self.assertNotIn(PREFIX, self.get())
        self.assertEqual(self.c.builds, 2)

    def test_a_config_change_rebuilds(self):
        self.sender()
        write_log(self.log, FAILING_LAST)
        self.assertIn(SEND_FAILING, self.get())
        self.cfg.write_text(json.dumps({"push_profile": PROFILE}))   # no push log set any more: unknown
        self.bump(self.cfg)
        self.assertNotIn(PREFIX, self.get())


class Hook(Base):
    def hook(self):
        return card.make_pre_llm_call(env=self.env, clock=lambda: NOW, today=lambda: TODAY)

    def test_the_line_reaches_the_prompt_through_the_tier_gate(self):
        write_log(self.log, FAILING_LAST)
        seen = []
        real = tier_audit.gate

        def spy(hook, text, *a, **k):
            seen.append((hook, text))
            return real(hook, text, *a, **k)

        with mock.patch.object(tier_audit, "gate", side_effect=spy):
            out = self.hook()(user_message="hi")
        self.assertIn(SENDER_MISSING + GENERIC, out["context"].splitlines())
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][0], "pre_llm_call")
        self.assertIn(SENDER_MISSING, seen[0][1])

    def test_a_card_the_gate_drops_carries_no_line(self):
        write_log(self.log, FAILING_LAST)
        with mock.patch.object(tier_audit, "gate", return_value=None):
            self.assertIsNone(self.hook()(user_message="hi"))


if __name__ == "__main__":
    unittest.main()
