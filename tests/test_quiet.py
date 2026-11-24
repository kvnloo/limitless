"""quiet.py: the quiet / snooze / off state and its pure check. Synthetic data only; nothing sends."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import quiet  # noqa: E402

NOW = 2_000_000_000.0
SINCE_T = NOW - 1200
SINCE = "2033-05-18T03:13:20+00:00"          # SINCE_T in UTC


def wake(at):
    return {"event": "wake", "at": at}


class Active(unittest.TestCase):
    def test_missing_state_is_on(self):
        self.assertEqual(quiet.active(None, [], None, NOW)[0], False)

    def test_on_is_not_held(self):
        held, why = quiet.active({"mode": "on", "since": SINCE}, [], None, NOW)
        self.assertFalse(held)
        self.assertTrue(why.startswith("on"))

    def test_off_holds_until_an_explicit_on(self):
        held, why = quiet.active({"mode": "off", "since": SINCE}, [wake(NOW - 60)], NOW - 30, NOW)
        self.assertTrue(held)
        self.assertEqual(why, "quiet: off until you reply on")

    def test_off_needs_no_since(self):
        self.assertTrue(quiet.active({"mode": "off"}, [], None, NOW)[0])

    def test_quiet_tonight_holds_before_the_next_wake(self):
        held, why = quiet.active({"mode": "quiet_tonight", "since": SINCE}, [wake(SINCE_T - 3600)], None, NOW)
        self.assertTrue(held)
        self.assertEqual(why, "quiet: quiet tonight, until you wake up")

    def test_quiet_tonight_ends_at_the_next_wake(self):
        held, why = quiet.active({"mode": "quiet_tonight", "since": SINCE}, [wake(NOW - 60)], None, NOW)
        self.assertFalse(held)
        self.assertIn("woke", why)

    def test_quiet_tonight_ignores_a_wake_after_now(self):
        self.assertTrue(quiet.active({"mode": "quiet_tonight", "since": SINCE}, [wake(NOW + 60)], None, NOW)[0])

    def test_quiet_tonight_ignores_other_events(self):
        evs = [{"event": "wind_down", "at": NOW - 60}, {"event": "sleep_mode_on", "at": NOW - 30}]
        self.assertTrue(quiet.active({"mode": "quiet_tonight", "since": SINCE}, evs, None, NOW)[0])

    def test_quiet_tonight_is_not_ended_by_a_message(self):
        self.assertTrue(quiet.active({"mode": "quiet_tonight", "since": SINCE}, [], NOW - 10, NOW)[0])

    def test_snoozed_holds_until_the_person_writes_again(self):
        held, why = quiet.active({"mode": "snoozed", "since": SINCE}, [], SINCE_T, NOW)
        self.assertTrue(held)
        self.assertEqual(why, "quiet: snoozed until you write again")

    def test_snoozed_holds_with_no_message_seen(self):
        self.assertTrue(quiet.active({"mode": "snoozed", "since": SINCE}, [], None, NOW)[0])

    def test_snoozed_ends_at_a_newer_message(self):
        held, why = quiet.active({"mode": "snoozed", "since": SINCE}, [], SINCE_T + 1, NOW)
        self.assertFalse(held)
        self.assertIn("wrote", why)

    def test_snoozed_is_not_ended_by_a_wake(self):
        self.assertTrue(quiet.active({"mode": "snoozed", "since": SINCE}, [wake(NOW - 5)], None, NOW)[0])

    def test_unknown_mode_fails_open(self):
        self.assertFalse(quiet.active({"mode": "shh", "since": SINCE}, [], None, NOW)[0])

    def test_not_a_dict_fails_open(self):
        for bad in ([], "off", 3, {"since": SINCE}):
            self.assertFalse(quiet.active(bad, [], None, NOW)[0], bad)

    def test_event_based_modes_without_a_valid_since_fail_open(self):
        for mode in ("quiet_tonight", "snoozed"):
            for since in (None, "yesterday", 5, "2033-05-18T03:13:20"):   # last one: no timezone
                self.assertFalse(quiet.active({"mode": mode, "since": since}, [], None, NOW)[0], (mode, since))

    def test_bad_event_rows_are_skipped(self):
        evs = [None, {"event": "wake"}, {"event": "wake", "at": "x"}, {"event": "wake", "at": True}]
        self.assertTrue(quiet.active({"mode": "quiet_tonight", "since": SINCE}, evs, None, NOW)[0])

    def test_every_why_is_digit_free(self):
        cases = [(None, [], None), ({"mode": "off"}, [], None),
                 ({"mode": "quiet_tonight", "since": SINCE}, [], None),
                 ({"mode": "quiet_tonight", "since": SINCE}, [wake(NOW - 1)], None),
                 ({"mode": "snoozed", "since": SINCE}, [], None),
                 ({"mode": "snoozed", "since": SINCE}, [], NOW - 1), ({"mode": "x"}, [], None)]
        for state, evs, seen in cases:
            why = quiet.active(state, evs, seen, NOW)[1]
            self.assertFalse(any(c.isdigit() for c in why), why)

    def test_label_is_a_plain_word(self):
        self.assertEqual(quiet.label("on"), "on")
        self.assertEqual(quiet.label("off"), "off")
        self.assertEqual(quiet.label("quiet_tonight"), "quiet tonight")
        self.assertEqual(quiet.label("snoozed"), "snoozed")


class StateFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_reads_as_none(self):
        self.assertIsNone(quiet.load(self.st))

    def test_broken_file_reads_as_none(self):
        for text in ("{not json", "[]", '"off"', ""):
            (self.st / quiet.QUIET_FILE).write_text(text)
            self.assertIsNone(quiet.load(self.st), text)

    def test_write_is_0600_and_round_trips(self):
        quiet.write(self.st, "snoozed", SINCE_T)
        p = self.st / quiet.QUIET_FILE
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
        self.assertEqual(quiet.load(self.st), {"mode": "snoozed", "since": SINCE})

    def test_write_replaces_atomically_and_leaves_no_temp_file(self):
        quiet.write(self.st, "off", SINCE_T)
        quiet.write(self.st, "on", SINCE_T + 60)
        self.assertEqual([p.name for p in self.st.iterdir()], [quiet.QUIET_FILE])
        self.assertEqual(json.loads((self.st / quiet.QUIET_FILE).read_text())["mode"], "on")

    def test_write_refuses_an_unknown_mode(self):
        with self.assertRaises(ValueError):
            quiet.write(self.st, "until ten", SINCE_T)
        self.assertFalse((self.st / quiet.QUIET_FILE).exists())


class Check(unittest.TestCase):
    """check(): quiet.json plus the wake events and the person's last message, read from the state dir."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Path(self.tmp.name)
        self.env = {"LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(self.st / "none.json")}

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, **env):
        return quiet.check(self.st, NOW, env=dict(self.env, **env), home=self.st)

    def test_no_file_is_on(self):
        self.assertEqual(self.check()[0], False)

    def test_off_holds(self):
        quiet.write(self.st, "off", SINCE_T)
        self.assertTrue(self.check()[0])

    def test_quiet_tonight_reads_the_wake_from_events_jsonl(self):
        quiet.write(self.st, "quiet_tonight", SINCE_T)
        self.assertTrue(self.check()[0])
        (self.st / "events.jsonl").write_text(json.dumps({"event": "wake", "at": NOW - 60}) + "\n")
        self.assertFalse(self.check()[0])

    def test_snoozed_with_no_message_source_fails_open(self):
        quiet.write(self.st, "snoozed", SINCE_T)
        held, why = self.check()
        self.assertFalse(held)
        self.assertIn("cannot see", why)

    def test_snoozed_reads_the_owner_beacon(self):
        quiet.write(self.st, "snoozed", SINCE_T)
        beacon = self.st / "beacon.json"
        beacon.write_text(json.dumps({"at": SINCE, "v": 1}))
        self.assertTrue(self.check(LIMITLESS_OWNER_BEACONS=str(beacon))[0])
        beacon.write_text(json.dumps({"at": "2033-05-18T03:20:00+00:00", "v": 1}))
        self.assertFalse(self.check(LIMITLESS_OWNER_BEACONS=str(beacon))[0])


if __name__ == "__main__":
    unittest.main()
