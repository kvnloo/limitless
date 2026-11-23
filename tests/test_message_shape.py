"""message_shape: every push held to a size, the TLDR first. Synthetic text only."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from limitless import message_shape as ms  # noqa: E402

WHY = "Why now: you woke up"
REPLY = "Reply: Keep / Drop"


def lines(text):
    return [ln for ln in text.splitlines() if ln.strip()]


def digits(text):
    return sum(c.isdigit() for c in text)


class Limits(unittest.TestCase):
    def test_defaults(self):
        self.assertEqual(ms.limits({}), {"max_lines": 6, "max_line_chars": 160})
        self.assertEqual(ms.limits(None), {"max_lines": 6, "max_line_chars": 160})

    def test_config_values_are_read(self):
        self.assertEqual(ms.limits({"message_max_lines": 8, "message_max_line_chars": 100}),
                         {"max_lines": 8, "max_line_chars": 100})

    def test_bad_values_fall_back_to_defaults(self):
        for bad in (True, "8", 0, -3, 2.5, None, [], 3):
            self.assertEqual(ms.limits({"message_max_lines": bad})["max_lines"], 6, bad)
        for bad in (False, "100", 0, -1, 1.5, None, 10):
            self.assertEqual(ms.limits({"message_max_line_chars": bad})["max_line_chars"], 160, bad)


class Unchanged(unittest.TestCase):
    def test_a_short_body_comes_back_as_it_is(self):
        body = "You are up. Your brief comes next.\n\n" + WHY
        self.assertEqual(ms.shape("Wake-up brief", body, ms.limits({})), body)

    def test_empty_body(self):
        self.assertEqual(ms.shape("t", "", ms.limits({})), "")

    def test_limits_none_means_defaults(self):
        body = "\n".join(["TLDR"] + [f"line {w}" for w in "abcdefgh"] + [WHY])
        self.assertEqual(ms.shape("t", body, None), ms.shape("t", body, ms.limits({})))


class Fold(unittest.TestCase):
    def body(self, n_middle, reply=True, why=True):
        mid = [f"Middle line {w}." for w in "abcdefghijklmnopqrstuvwxyz"[:n_middle]]
        return "\n".join(["Habit kept this week."] + mid + ([REPLY] if reply else []) + ([WHY] if why else []))

    def test_middle_lines_past_the_limit_fold_into_one_line_in_words(self):
        out = lines(ms.shape("Week review", self.body(6), ms.limits({})))
        self.assertEqual(out, ["Habit kept this week.", "Middle line a.", "Middle line b.",
                               "and four more lines in the plugin", REPLY, WHY])

    def test_tldr_reply_and_why_are_always_kept(self):
        for n in range(0, 20):
            out = lines(ms.shape("t", self.body(n), ms.limits({})))
            self.assertEqual(out[0], "Habit kept this week.")
            self.assertEqual(out[-2:], [REPLY, WHY])
            self.assertLessEqual(len(out), 6)

    def test_one_extra_line_still_folds_two_lines(self):
        out = lines(ms.shape("t", self.body(4), ms.limits({})))
        self.assertEqual(out[3], "and two more lines in the plugin")
        self.assertEqual(len(out), 6)

    def test_exactly_at_the_limit_is_not_folded(self):
        body = self.body(3)
        self.assertEqual(ms.shape("t", body, ms.limits({})), body)

    def test_without_reply_or_why_more_middle_lines_fit(self):
        out = lines(ms.shape("t", self.body(9, reply=False, why=False), ms.limits({})))
        self.assertEqual(len(out), 6)
        self.assertEqual(out[-1], "and five more lines in the plugin")

    def test_a_reply_line_only_counts_as_last(self):
        body = "\n".join(["TLDR", REPLY] + [f"m {w}" for w in "abcdef"])
        out = lines(ms.shape("t", body, ms.limits({})))
        self.assertEqual(out[0], "TLDR")
        self.assertEqual(out[-1], "and three more lines in the plugin")

    def test_many_folded_lines_say_many(self):
        out = lines(ms.shape("t", self.body(25), ms.limits({})))
        self.assertIn("and many more lines in the plugin", out)

    def test_the_count_is_said_in_words_never_digits(self):
        for n in range(4, 26):
            body = self.body(n)
            out = ms.shape("t", body, ms.limits({}))
            self.assertLessEqual(digits(out), digits(body))

    def test_a_tighter_limit(self):
        out = lines(ms.shape("t", self.body(5), ms.limits({"message_max_lines": 4})))
        self.assertEqual(out, ["Habit kept this week.", "and five more lines in the plugin", REPLY, WHY])


class Cut(unittest.TestCase):
    def test_a_long_middle_line_is_cut_at_a_word_boundary_with_an_ellipsis(self):
        long = " ".join(["word"] * 60)
        out = lines(ms.shape("t", f"TLDR\n{long}\n{WHY}", ms.limits({})))
        self.assertEqual(out[0], "TLDR")
        self.assertLessEqual(len(out[1]), 160)
        self.assertTrue(out[1].endswith("…"))
        self.assertTrue(long.startswith(out[1][:-1]))
        self.assertFalse(out[1][:-1].endswith(" "))
        self.assertTrue(out[1][:-1].endswith("word"))

    def test_a_single_long_word_is_cut_hard(self):
        out = lines(ms.shape("t", "TLDR\n" + "x" * 300, ms.limits({})))
        self.assertEqual(len(out[1]), 160)
        self.assertTrue(out[1].endswith("…"))

    def test_the_tldr_and_reply_line_are_kept_as_they_are(self):
        tldr = " ".join(["Brief"] * 50)
        body = f"{tldr}\nmiddle\n{REPLY}\n{WHY}"
        out = lines(ms.shape("t", body, ms.limits({})))
        self.assertEqual(out[0], tldr)
        self.assertEqual(out[-2], REPLY)

    def test_a_long_why_line_is_cut_but_kept(self):
        why = "Why now: " + "; ".join(["your wind-down started"] * 12)
        out = lines(ms.shape("t", f"TLDR\n{why}", ms.limits({})))
        self.assertTrue(out[-1].startswith("Why now: "))
        self.assertLessEqual(len(out[-1]), 160)

    def test_a_line_with_a_link_is_never_cut(self):
        line = "Screens down and lights low, or slow breathing in your app: https://example.org/" + "b" * 150
        out = lines(ms.shape("t", f"TLDR\n{line}\n{WHY}", ms.limits({})))
        self.assertEqual(out[1], line)

    def test_cutting_adds_no_digit(self):
        body = "TLDR\n" + " ".join(["about one"] * 40) + "\n" + WHY
        self.assertEqual(digits(ms.shape("t", body, ms.limits({}))), 0)


class Fit(unittest.TestCase):
    def test_fit_reports_counts(self):
        body = "\n".join(["TLDR"] + [f"m {w}" for w in "abcdefg"] + ["y " * 120, REPLY, WHY])
        text, folded, cut = ms.fit("t", body, ms.limits({}))
        self.assertEqual(text, ms.shape("t", body, ms.limits({})))
        self.assertEqual(folded, 6)
        self.assertEqual(cut, 0)   # the long line was folded, not cut

    def test_nothing_to_do_reports_zero(self):
        self.assertEqual(ms.fit("t", "TLDR\n" + WHY, ms.limits({}))[1:], (0, 0))

    def test_cut_count(self):
        text, folded, cut = ms.fit("t", "TLDR\n" + "z " * 200, ms.limits({}))
        self.assertEqual((folded, cut), (0, 1))


if __name__ == "__main__":
    unittest.main()
