"""owner_messages.newest_user_message(until=...): the newest message from the person at or before a bound,
so a caller can ask for the message before this turn's own. Synthetic data only."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import owner_messages as om  # noqa: E402
from test_owner_messages import NOW, H, make_db  # noqa: E402


class Until(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = make_db(Path(self.tmp.name) / "a.db", [
            ("s-tg", "user", "synthetic", NOW - 30 * H),
            ("s-tg", "user", "synthetic", NOW - 10),        # this turn's own message
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_bound_sees_the_newest(self):
        got = om.newest_user_message([self.db], NOW)
        self.assertAlmostEqual(got["age_h"], 10 / H, places=3)

    def test_until_skips_messages_after_the_bound(self):
        got = om.newest_user_message([self.db], NOW, until=NOW - 120)
        self.assertAlmostEqual(got["age_h"], 30.0, places=3)
        self.assertEqual(got["sources_read"], 1)

    def test_until_before_every_message_is_none(self):
        got = om.newest_user_message([self.db], NOW, until=NOW - 40 * H)
        self.assertIsNone(got["at"])
        self.assertEqual(got["sources_read"], 1)


if __name__ == "__main__":
    unittest.main()
