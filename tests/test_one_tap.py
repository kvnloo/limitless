"""one_tap: every ask ends in one plain line of 2-4 one-word replies, and the reply is read back whole.

L14: typed prompts got no answers; one tap or one spoken word did. Synthetic text only.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import one_tap  # noqa: E402

HABIT = ("Done", "No", "Skip")


class ChoicesLine(unittest.TestCase):
    def test_one_plain_line(self):
        self.assertEqual(one_tap.choices_line(HABIT), "Reply: Done / No / Skip")
        self.assertEqual(one_tap.choices_line(["Keep", "Drop"]), "Reply: Keep / Drop")
        self.assertEqual(one_tap.choices_line(("Yes", "No", "Later", "Skip")), "Reply: Yes / No / Later / Skip")

    def test_two_to_four_options(self):
        for bad in ((), ("Yes",), ("A", "B", "C", "D", "E")):
            with self.assertRaises(ValueError, msg=bad):
                one_tap.choices_line(bad)

    def test_each_option_one_word_no_digits_no_card_ids(self):
        for bad in (("Yes", "Not now"), ("Yes", "No2"), ("t_510c250d", "No"), ("Yes", ""), ("Yes", None),
                    ("Yes", "yes"), ("Yes", "No.")):
            with self.assertRaises(ValueError, msg=bad):
                one_tap.choices_line(bad)

    def test_no_digit_and_one_line(self):
        line = one_tap.choices_line(HABIT)
        self.assertNotIn("\n", line)
        self.assertFalse(any(c.isdigit() for c in line))


class Parse(unittest.TestCase):
    def test_case_insensitive_whole_message(self):
        for text in ("Done", "done", "DONE", "  done  ", "dOnE"):
            self.assertEqual(one_tap.parse(text, HABIT), "Done", text)
        self.assertEqual(one_tap.parse("skip", HABIT), "Skip")

    def test_trailing_period_or_emoji(self):
        for text in ("Done.", "done!", "Done 👍", "Done👍🏽", "done. 👍", "Done ✅", "no.", "Skip!!"):
            self.assertIsNotNone(one_tap.parse(text, HABIT), text)
        self.assertEqual(one_tap.parse("Done 👍", HABIT), "Done")

    def test_voice_transcripts(self):
        self.assertEqual(one_tap.parse("done.", HABIT), "Done")
        self.assertEqual(one_tap.parse("No.", HABIT), "No")
        self.assertEqual(one_tap.parse(" Skip. ", HABIT), "Skip")

    def test_anything_else_is_none(self):
        for text in ("", "   ", None, 3, "done for today", "not done", "Done Skip", "dones", "maybe",
                     "Later", "👍", "Done 👍 👍", "1"):
            self.assertIsNone(one_tap.parse(text, HABIT), text)

    def test_returns_the_option_as_offered(self):
        self.assertEqual(one_tap.parse("keep", ("Keep", "Drop")), "Keep")
        self.assertEqual(one_tap.parse("LATER", ("Yes", "No", "Later")), "Later")


class ChoicesOf(unittest.TestCase):
    def test_reads_back_its_own_line(self):
        for opts in (HABIT, ("Keep", "Drop"), ("Yes", "No", "Later")):
            self.assertEqual(one_tap.choices_of(one_tap.choices_line(opts)), tuple(opts))

    def test_not_a_choices_line(self):
        for line in ("Reply Done, No or Skip.", "Reply:", "Reply: Done", "Reply: Done / two words", "Hi", None):
            self.assertIsNone(one_tap.choices_of(line), line)


if __name__ == "__main__":
    unittest.main()
