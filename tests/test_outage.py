"""limitless/outage.py: an input that stops recording is said once, in words; recovery clears it silently.

Synthetic inputs.json snapshots in a temp state dir and a fixed clock; nothing real.
"""
import json
import os
import re
import stat
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import outage  # noqa: E402

NOW = 1894708800.0  # the fixture clock
H = 3600.0


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class OutageCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.st = Path(self.tmp.name)

    def inputs(self, at, ages):
        (self.st / "inputs.json").write_text(json.dumps({"at": iso(at), "ageHours": ages}))

    def poll(self, now, cfg=None, tell=True):
        """One brief: poll, build the line, and mark it told when there is one (as a delivered brief does)."""
        cfg = {} if cfg is None else cfg
        new = outage.poll(self.st, now, cfg)
        text = outage.line(new, cfg, now)
        if text and tell:
            outage.tell(self.st, [o["name"] for o in new], now)
        return text


class Down(OutageCase):
    def test_a_live_input_is_not_an_outage(self):
        self.inputs(NOW, {"wearable": 1.0, "phone": 2.0})
        self.assertEqual(outage.down(self.st, NOW, {}), [])

    def test_stale_and_down_inputs_are_outages_unknown_is_not(self):
        self.inputs(NOW, {"wearable": 50.0, "phone": "down", "scale": None, "laptop": 1.0})
        got = outage.down(self.st, NOW, {})
        self.assertEqual([o["name"] for o in got], ["phone", "wearable"])
        self.assertEqual({o["name"]: o["age_h"] for o in got}, {"phone": None, "wearable": 50.0})

    def test_uses_the_status_threshold_with_the_snapshot_age(self):
        self.inputs(NOW - 10 * H, {"wearable": 20.0})       # twenty plus ten: over a day now
        self.assertEqual([o["name"] for o in outage.down(self.st, NOW, {})], ["wearable"])
        self.inputs(NOW, {"wearable": 20.0})
        self.assertEqual(outage.down(self.st, NOW, {}), [])

    def test_no_inputs_file_is_no_outage(self):
        self.assertEqual(outage.down(self.st, NOW, {}), [])

    def test_the_ignore_list_is_never_an_outage(self):
        self.inputs(NOW, {"wearable": 50.0, "scale": 500.0})
        got = outage.down(self.st, NOW, {"outage_ignore": ["scale"]})
        self.assertEqual([o["name"] for o in got], ["wearable"])


class Once(OutageCase):
    def test_live_then_down_reports_once_across_many_polls(self):
        self.inputs(NOW, {"wearable": 1.0})
        self.assertEqual(self.poll(NOW), "")
        self.inputs(NOW + 30 * H, {"wearable": 30.0})
        first = self.poll(NOW + 30 * H)
        self.assertTrue(first.startswith("Not recording: wearable (since "), first)
        for k in range(1, 20):
            self.inputs(NOW + (30 + k) * H, {"wearable": 30.0 + k})
            self.assertEqual(self.poll(NOW + (30 + k) * H), "", k)

    def test_down_then_live_then_down_reports_again(self):
        self.inputs(NOW, {"wearable": 30.0})
        self.assertNotEqual(self.poll(NOW), "")
        self.assertEqual(self.poll(NOW + H), "")
        self.inputs(NOW + 2 * H, {"wearable": 0.5})
        self.assertEqual(self.poll(NOW + 2 * H), "")         # recovery: no "back" message
        self.assertEqual(outage.load_mark(self.st), {"since": {}, "told": {}})
        self.inputs(NOW + 40 * H, {"wearable": 30.0})
        self.assertNotEqual(self.poll(NOW + 40 * H), "")

    def test_an_untold_outage_is_said_at_the_next_brief(self):
        self.inputs(NOW, {"wearable": 30.0})
        self.assertNotEqual(self.poll(NOW, tell=False), "")   # built but not delivered
        self.assertNotEqual(self.poll(NOW + H), "")
        self.assertEqual(self.poll(NOW + 2 * H), "")

    def test_a_second_input_going_down_is_said_alone(self):
        self.inputs(NOW, {"wearable": 30.0, "phone": 1.0})
        self.poll(NOW)
        self.inputs(NOW + 30 * H, {"wearable": 60.0, "phone": 30.0})
        self.assertTrue(self.poll(NOW + 30 * H).startswith("Not recording: phone (since "))

    def test_the_outage_starts_at_the_first_poll_that_sees_it(self):
        self.inputs(NOW, {"phone": "down"})
        outage.poll(self.st, NOW, {})
        outage.poll(self.st, NOW + 5 * H, {})
        self.assertEqual(outage.load_mark(self.st)["since"], {"phone": NOW})

    def test_off_writes_no_mark_and_says_nothing(self):
        self.inputs(NOW, {"wearable": 30.0})
        for off in (False, "off", "false"):
            self.assertEqual(self.poll(NOW, {"input_outage": off}), "", off)
            self.assertFalse((self.st / outage.MARK_FILE).exists())
        self.assertNotEqual(self.poll(NOW, {"input_outage": True}), "")

    def test_ignored_inputs_are_never_reported(self):
        self.inputs(NOW, {"scale": 500.0})
        self.assertEqual(self.poll(NOW, {"outage_ignore": ["scale"]}), "")
        self.assertEqual(outage.load_mark(self.st)["since"], {})


class Mark(OutageCase):
    def test_mark_is_atomic_private_and_names_plus_epoch_seconds_only(self):
        self.inputs(NOW, {"wearable": 30.0, "phone": "down", "laptop": 1.0})
        self.poll(NOW, {"outage_hints": {"wearable": "Open the app once to restart it."}})
        p = self.st / outage.MARK_FILE
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
        data = json.loads(p.read_text())
        self.assertEqual(set(data), {"since", "told"})
        for part in data.values():
            self.assertLessEqual(set(part), {"wearable", "phone"})
            for v in part.values():
                self.assertIsInstance(v, float)
        self.assertNotIn("Open", p.read_text())
        self.assertEqual([x.name for x in self.st.iterdir() if x.name.startswith(".")], [])

    def test_a_broken_mark_is_an_empty_mark(self):
        (self.st / outage.MARK_FILE).write_text("not json")
        self.assertEqual(outage.load_mark(self.st), {"since": {}, "told": {}})
        (self.st / outage.MARK_FILE).write_text(json.dumps({"since": {"phone": "soon"}, "told": []}))
        self.assertEqual(outage.load_mark(self.st), {"since": {}, "told": {}})


class Line(OutageCase):
    def test_one_line_for_several_inputs_with_their_hints(self):
        self.inputs(NOW, {"wearable": 50.0, "phone_screen": 30.0, "laptop": 75.0})
        cfg = {"outage_hints": {"wearable": "Open the app once to restart it.",
                                "laptop": "Wake the laptop and check the sync is on"}}
        text = self.poll(NOW, cfg)
        self.assertEqual(text, "Not recording: laptop, phone screen and wearable (since about three days ago). "
                               "Wake the laptop and check the sync is on. Open the app once to restart it.")
        self.assertEqual(len(text.splitlines()), 1)

    def test_no_hint_configured_is_no_hint_text(self):
        self.inputs(NOW, {"wearable": 50.0})
        self.assertEqual(self.poll(NOW), "Not recording: wearable (since about two days ago).")

    def test_a_down_input_counts_from_the_first_poll(self):
        self.inputs(NOW, {"phone": "down"})
        outage.poll(self.st, NOW, {})
        self.assertEqual(self.poll(NOW + 5 * H), "Not recording: phone (since about five hours ago).")

    def test_digit_free_even_with_digits_in_names_and_hints(self):
        self.inputs(NOW, {"band2": 30.0, "watch": 200.0})
        text = self.poll(NOW, {"outage_hints": {"band2": "Charge it for 10 minutes.", "watch": "Open it."}})
        self.assertIsNone(re.search(r"\d", text), text)
        self.assertIn("Open it.", text)
        self.assertNotIn("Charge", text)          # a hint with a digit is dropped, never rewritten

    def test_camel_case_input_names_read_as_plain_words(self):
        # sync writers name inputs in camelCase; the line Kevin reads splits them, keeping an acronym whole
        self.assertEqual(outage.name_words("ownerMessages"), "owner messages")
        self.assertEqual(outage.name_words("desktopAW"), "desktop AW")
        self.assertEqual(outage.name_words("phoneUnlocks"), "phone unlocks")
        self.assertEqual(outage.name_words("HRVBand"), "HRV band")
        self.assertEqual(outage.name_words("phone_screen"), "phone screen")
        self.inputs(NOW, {"phoneApps": 50.0})
        self.assertEqual(self.poll(NOW), "Not recording: phone apps (since about two days ago).")

    def test_nothing_new_is_no_line(self):
        self.assertEqual(outage.line([], {}, NOW), "")


class Current(OutageCase):
    def test_current_is_read_only_and_keeps_told_outages(self):
        self.inputs(NOW, {"wearable": 30.0, "phone": "down"})
        self.assertEqual(outage.current(self.st, NOW, {}), [{"name": "phone", "since": NOW},
                                                             {"name": "wearable", "since": NOW - 30 * H}])
        self.assertFalse((self.st / outage.MARK_FILE).exists())
        self.poll(NOW)
        self.assertEqual([o["name"] for o in outage.current(self.st, NOW + H, {})], ["phone", "wearable"])

    def test_label_in_words(self):
        self.inputs(NOW, {"wearable": 50.0})
        self.assertEqual(outage.label(outage.current(self.st, NOW, {}), NOW),
                         "not recording: wearable (since about two days ago)")
        self.assertEqual(outage.label([], NOW), "every input is recording")

    def test_label_groups_inputs_by_their_own_since(self):
        self.inputs(NOW, {"wearable": 50.0, "band": 52.0, "phone": "down"})
        self.assertEqual(outage.label(outage.current(self.st, NOW, {}), NOW),
                         "not recording: band and wearable (since about two days ago) and phone (since just now)")

    def test_under_an_hour_is_just_now(self):
        self.inputs(NOW, {"phone": "down"})
        self.assertEqual(self.poll(NOW), "Not recording: phone (since just now).")


if __name__ == "__main__":
    unittest.main()
