"""push_reach: one words-only line when phone pushes cannot reach the person, from kevin-push's sender profile
(push_sender.check) and its own log (delivery_audit send_failures). Synthetic Hermes homes and kevin-push logs,
a fixed clock and day, env passed explicitly. Nothing is run, written to a real home or sent."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import push_reach  # noqa: E402

UTC = timezone.utc
TODAY = date(2030, 1, 15)
NOW = datetime(2030, 1, 15, 18, 0, tzinfo=UTC).timestamp()
PROFILE, TARGET = "sender-a", "telegram:example-a"
SENDER_MISSING = "Phone pushes are not reaching you: the sender profile is missing"
SEND_FAILING = "Phone pushes are not reaching you: the last pushes failed to send"


def log_row(hour, how="telegram", day=TODAY):
    at = int(datetime(day.year, day.month, day.day, hour, 0, tzinfo=UTC).timestamp())
    return {"at": at, "tag": "x", "cls": "decision", "title": "Pick one", "how": how,
            "body": "Keep the loop?\nReply: Yes / No"}


DELIVERED_LAST = [log_row(9, "log (telegram rc=1)"), log_row(10), log_row(11)]
FAILING_LAST = [log_row(9), log_row(10, "log (telegram rc=1)"), log_row(11, "log (telegram rc=1)")]


class Home:
    """A temp dir with a limitless state dir, a config, a Hermes home (with or without the sender profile) and
    a kevin-push log; ``env`` is the explicit env every call gets."""

    def __init__(self, sender=True, rows=None, hermes=True, push_log=True):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.state = root / "state"
        self.state.mkdir()
        self.hermes = root / "hermes"
        if hermes:
            (self.hermes / "profiles" / "other").mkdir(parents=True)
            if sender:
                (self.hermes / "profiles" / PROFILE).mkdir()
        self.log = self.state / "push-log.jsonl"
        if rows is not None:
            self.log.write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.cfg = {"push_profile": PROFILE, "push_to": TARGET}
        if push_log:
            self.cfg["push_log"] = "push-log.jsonl"
        self.config = root / "config.json"
        self.config.write_text(json.dumps(self.cfg))
        self.env = {"HOME": str(root), "HERMES_HOME": str(self.hermes), "LIMITLESS_STATE": str(self.state),
                    "LIMITLESS_CONFIG": str(self.config)}

    def reason(self):
        return push_reach.reason(self.cfg, self.state, TODAY, self.env, tz=UTC)

    def close(self):
        self.tmp.cleanup()


class Line(unittest.TestCase):
    def home(self, **kw):
        h = Home(**kw)
        self.addCleanup(h.close)
        return h

    def test_a_missing_sender_profile_is_worded(self):
        self.assertEqual(push_reach.line(self.home(sender=False, rows=DELIVERED_LAST).reason()), SENDER_MISSING)

    def test_failed_last_pushes_are_worded(self):
        self.assertEqual(push_reach.line(self.home(rows=FAILING_LAST).reason()), SEND_FAILING)

    def test_a_set_sender_and_a_delivered_last_attempt_say_nothing(self):
        h = self.home(rows=DELIVERED_LAST)
        self.assertIsNone(h.reason())
        self.assertIsNone(push_reach.line(h.reason()))

    def test_a_broken_sender_wins_over_failed_pushes(self):
        self.assertEqual(push_reach.line(self.home(sender=False, rows=FAILING_LAST).reason()), SENDER_MISSING)

    def test_unknown_is_silent(self):
        # no Hermes home (push_sender unknown) and no push log set: neither can be told
        self.assertIsNone(self.home(hermes=False, push_log=False).reason())
        # no Hermes home and a log that cannot be read
        self.assertIsNone(self.home(hermes=False).reason())
        # a set sender and no push row at all
        self.assertIsNone(self.home(rows=[]).reason())

    def test_failed_pushes_are_worded_even_when_the_sender_cannot_be_told(self):
        self.assertEqual(push_reach.line(self.home(hermes=False, rows=FAILING_LAST).reason()), SEND_FAILING)

    def test_one_failure_after_a_delivery_is_not_an_outage(self):
        self.assertIsNone(self.home(rows=[log_row(9), log_row(10, "log (telegram rc=1)")]).reason())

    def test_the_words_hold_no_digit_name_target_or_path(self):
        h = self.home(sender=False, rows=FAILING_LAST)
        for words in (SENDER_MISSING, SEND_FAILING, push_reach.line(h.reason())):
            self.assertFalse(any(c.isdigit() for c in words), words)
            for leak in (PROFILE, TARGET, "kevin", "/", str(h.hermes), "push-log"):
                self.assertNotIn(leak, words)


if __name__ == "__main__":
    unittest.main()
