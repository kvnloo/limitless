"""limitless_habit adds phone_hint (seen / not seen / unknown, evidence_tier proxy); the check-ins stay taps.

Synthetic AW DBs and synthetic app names only. NOW is an arbitrary epoch; only differences matter.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from limitless import tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from test_aw_reader import make_db  # noqa: E402

NOW = 2_000_000_000.0
H = 3600.0
TODAY = date.fromtimestamp(NOW)
WAKE = NOW - 2 * H
EVENING = WAKE - 9 * H
HABIT = {"habit": "Synthetic habit", "week_of": TODAY.isoformat(), "checkins": {TODAY.isoformat(): "Done"}}


class PhoneHint(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.db = self.st / "aw.db"
        (self.st / "habit.json").write_text(json.dumps(HABIT))
        self.env = {"LIMITLESS_CONFIG": str(self.root / "no-config.json"), "LIMITLESS_AW_DB": str(self.db),
                    "LIMITLESS_FEED_APPS": "feedapp"}

    def tearDown(self):
        self.tmp.cleanup()

    def habit(self, env):
        return tools.habit(StateReader(self.st), NOW, TODAY, env=env, home=self.root)

    def test_seen(self):
        make_db(self.db, unlocks=[EVENING, WAKE],
                spans=[(WAKE + 600, WAKE + 900, "feedapp"), (WAKE + H + 60, WAKE + H + 90, "reader")])
        self.assertEqual(self.habit(self.env)["phone_hint"], {"value": "seen", "evidence_tier": "proxy"})

    def test_not_seen(self):
        make_db(self.db, unlocks=[EVENING, WAKE],
                spans=[(WAKE + 600, WAKE + 900, "reader"), (WAKE + H + 60, WAKE + H + 90, "reader")])
        self.assertEqual(self.habit(self.env)["phone_hint"], {"value": "not seen", "evidence_tier": "proxy"})

    def test_unknown_when_data_stops_inside_the_hour(self):
        make_db(self.db, unlocks=[EVENING, WAKE], spans=[(WAKE + 600, WAKE + 900, "reader")])
        self.assertEqual(self.habit(self.env)["phone_hint"], {"value": "unknown", "evidence_tier": "proxy"})

    def test_unknown_with_no_feed_list(self):
        make_db(self.db, unlocks=[EVENING, WAKE],
                spans=[(WAKE + 600, WAKE + 900, "feedapp"), (WAKE + H + 60, WAKE + H + 90, "reader")])
        env = {k: v for k, v in self.env.items() if k != "LIMITLESS_FEED_APPS"}
        self.assertEqual(self.habit(env)["phone_hint"], {"value": "unknown", "evidence_tier": "proxy"})

    def test_unknown_with_no_wake_or_no_db(self):
        env = dict(self.env, LIMITLESS_AW_DB=str(self.root / "absent.db"))
        self.assertEqual(self.habit(env)["phone_hint"], {"value": "unknown", "evidence_tier": "proxy"})

    def test_unknown_while_the_first_hour_is_still_open(self):
        wake = NOW - 0.5 * H
        make_db(self.db, unlocks=[wake - 9 * H, wake], spans=[(wake + 60, wake + 90, "reader")])
        self.assertEqual(self.habit(self.env)["phone_hint"], {"value": "unknown", "evidence_tier": "proxy"})

    def test_the_hint_changes_no_check_in_and_has_no_digits(self):
        make_db(self.db, unlocks=[EVENING, WAKE],
                spans=[(WAKE + 600, WAKE + 900, "feedapp"), (WAKE + H + 60, WAKE + H + 90, "reader")])
        with_hint = self.habit(self.env)
        without = self.habit({k: v for k, v in self.env.items() if k != "LIMITLESS_FEED_APPS"})
        self.assertEqual(with_hint["value"], without["value"])
        self.assertEqual(with_hint["value"]["today"], "Done")
        self.assertIsNone(re.search(r"\d", json.dumps(with_hint["phone_hint"])))
        self.assertNotIn("feedapp", json.dumps(with_hint))


if __name__ == "__main__":
    unittest.main()
