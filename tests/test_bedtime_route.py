"""bedtime.route: in an asleep or wind_down window an owner message is saved for tomorrow, not started.
The window comes from state (a class name), never a clock time. Synthetic text only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import bedtime  # noqa: E402

IDEA = "an idea for the synthetic widget demo"


class Route(unittest.TestCase):
    def test_asleep_and_wind_down_capture_with_one_plain_reply(self):
        for cls in ("asleep", "wind_down"):
            out = bedtime.route(IDEA, cls, False)
            self.assertEqual(out, {"action": "capture", "reply": "Saved for tomorrow."}, cls)

    def test_reply_has_no_digits_and_is_one_line(self):
        reply = bedtime.route(IDEA, "asleep", False)["reply"]
        self.assertFalse(any(c.isdigit() for c in reply))
        self.assertEqual(len(reply.splitlines()), 1)

    def test_awake_or_unknown_windows_pass(self):
        for cls in ("peak", "trough", "anytime", "unknown", "", None, "ASLEEP"):
            self.assertEqual(bedtime.route(IDEA, cls, False), {"action": "pass", "reply": None}, cls)

    def test_opt_out_passes(self):
        self.assertEqual(bedtime.route(IDEA, "asleep", True), {"action": "pass", "reply": None})

    def test_commands_pass(self):
        for text in ("/stop", "  /new", "/status now please"):
            self.assertEqual(bedtime.route(text, "asleep", False)["action"], "pass", text)

    def test_default_urgent_words_pass_case_insensitive_whole_words(self):
        for text in ("URGENT: the demo build is red", "do it now", "Now!"):
            self.assertEqual(bedtime.route(text, "wind_down", False)["action"], "pass", text)
        for text in ("nowhere to put this idea", "knowledge base cleanup"):
            self.assertEqual(bedtime.route(text, "wind_down", False)["action"], "capture", text)

    def test_urgent_words_are_configurable(self):
        self.assertEqual(bedtime.route("do it now", "asleep", False, urgent_words=["asap"])["action"], "capture")
        self.assertEqual(bedtime.route("asap please", "asleep", False, urgent_words=["asap"])["action"], "pass")
        self.assertEqual(bedtime.DEFAULT_URGENT_WORDS, ("urgent", "now"))

    def test_empty_or_non_text_passes(self):
        for text in ("", "   ", None, 7):
            self.assertEqual(bedtime.route(text, "asleep", False)["action"], "pass", repr(text))

    def test_a_bare_miq_answer_passes(self):
        # the MIQ goes out at wind-down and ends in "Reply: Yes / No / Later": its one-tap reply is no idea
        for text in ("Yes", "yes.", "Later", "later 👍", "No"):
            self.assertEqual(bedtime.route(text, "wind_down", False)["action"], "pass", text)
        self.assertEqual(bedtime.route("yes and also a new idea", "wind_down", False)["action"], "capture")

    def test_a_bare_habit_or_week_answer_passes(self):
        # the habit check-in and week review read these replies from the session; never swallow them
        for text in ("Done", "skip", "No.", "Keep", "drop"):
            self.assertEqual(bedtime.route(text, "wind_down", False)["action"], "pass", text)
        self.assertEqual(bedtime.route("No meetings on demo day", "wind_down", False)["action"], "capture")


class Config(unittest.TestCase):
    def test_off_by_default(self):
        self.assertFalse(bedtime.enabled({}))
        self.assertFalse(bedtime.enabled({"bedtime_capture": "off"}))
        self.assertFalse(bedtime.enabled({"bedtime_capture": "yes please"}))
        self.assertTrue(bedtime.enabled({"bedtime_capture": "on"}))

    def test_urgent_words_from_config(self):
        self.assertEqual(bedtime.urgent_words({}), ["urgent", "now"])
        self.assertEqual(bedtime.urgent_words({"bedtime_urgent_words": ["asap", " Fire "]}), ["asap", "fire"])
        self.assertEqual(bedtime.urgent_words({"bedtime_urgent_words": "asap"}), ["urgent", "now"])
        self.assertEqual(bedtime.urgent_words({"bedtime_urgent_words": []}), [])


if __name__ == "__main__":
    unittest.main()
