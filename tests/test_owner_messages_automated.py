"""owner_messages: a role ``user`` row in a session Hermes started itself (a cron run, a kanban worker, a
delegated subagent) is the agent's own prompt, not the person writing. It never counts as the person's
newest message, on either query path. Synthetic data only.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from limitless import owner_messages as om  # noqa: E402
from test_owner_messages import CONTENT, H, HERMES_INDEX, NOW, make_db  # noqa: E402

FLAT_INDEX = "CREATE INDEX idx_messages_ts ON messages(timestamp);"
SESSIONS = (("s-tg", "telegram"), ("s-cron", "cron"), ("s-kan", "kanban"), ("s-sub", "subagent"))


class AutomatedSessions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.rows = [
            ("s-tg", "user", CONTENT + " person", NOW - 20 * H),
            ("s-cron", "user", CONTENT + " cron prompt", NOW - 0.2 * H),
            ("s-kan", "user", CONTENT + " card brief", NOW - 0.4 * H),
            ("s-sub", "user", CONTENT + " child goal", NOW - 0.6 * H),
        ]

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, index, name):
        db = make_db(self.dir / name, self.rows, index=index, sessions=SESSIONS)
        out = om.newest_user_message([db], NOW)
        self.assertEqual(out["at"], "2030-01-14T16:00:00+00:00")
        self.assertAlmostEqual(out["age_h"], 20.0)
        self.assertEqual((out["sources_read"], out["sources_failed"]), (1, 0))

    def test_per_session_path_skips_cron_kanban_and_subagent_prompts(self):
        self.check(HERMES_INDEX, "per-session.db")

    def test_flat_path_skips_cron_kanban_and_subagent_prompts(self):
        self.check(FLAT_INDEX, "flat.db")

    def test_no_index_path_skips_them_too(self):
        self.check(None, "plain.db")

    def test_a_store_with_only_automated_prompts_has_no_message_from_the_person(self):
        rows = [r for r in self.rows if r[0] != "s-tg"]
        db = make_db(self.dir / "bots.db", rows, sessions=SESSIONS)
        out = om.newest_user_message([db], NOW)
        self.assertIsNone(out["at"])
        self.assertEqual((out["sources_read"], out["sources_failed"]), (1, 0))

    def test_the_automated_sources_are_named_in_one_place(self):
        self.assertEqual(set(om.AUTOMATED_SOURCES), {"cron", "kanban", "subagent"})


if __name__ == "__main__":
    unittest.main()
