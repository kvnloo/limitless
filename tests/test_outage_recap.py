"""limitless/outage_recap.py: one plain recap of the pushes an outage swallowed, from kevin-push's log rows.

Synthetic rows only, a fixed clock (the fixture clock, 2030-01-15T12:00:00Z) and UTC."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import os
import re
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import delivery_audit, jobs, one_tap  # noqa: E402
from limitless import outage_recap as rc  # noqa: E402

UTC = timezone.utc
NOW = 1894708800.0   # 2030-01-15T12:00:00Z
H, D = 3600, 86400
RC1, NO_SENDER = "log (telegram rc=1)", "log (no sender profile)"
WHY = "Why now: wake event; any time you are awake"


def row(at, title, how, body="Something happened.\nReply: Yes / No"):
    return {"at": int(at), "tag": "limitless", "cls": "decision", "title": title, "body": body + "\n" + WHY,
            "how": how}


WAKE, MIQ, NAP = jobs.WAKE_BRIEF.send_title, jobs.MIQ.send_title, jobs.NAP.send_title


def closed_outage(start=NOW - D - 2 * H):
    """A delivery, then three failed pushes (wake brief, MIQ prompt, back from nap) from yesterday, then a delivery."""
    return [row(start - H, "Week review", "telegram"),
            row(start, WAKE, RC1), row(start + 600, WAKE, RC1),      # the runner's retry of the same brief
            row(start + 2 * H, MIQ, NO_SENDER), row(start + 3 * H, "Pick one", "held (sleep mode)"),
            row(start + 4 * H, NAP, RC1),
            row(NOW - 600, "Habit check-in", "telegram")]


class FindsTheOutage(unittest.TestCase):
    def test_an_outage_closed_by_a_delivery_is_found(self):
        o = rc.outage(closed_outage())
        self.assertEqual(o["state"], rc.CLOSED)
        self.assertEqual(o["first_at"], int(NOW - D - 2 * H))
        self.assertEqual(o["closed_at"], int(NOW - 600))
        self.assertEqual([r["title"] for r in o["failed"]], [WAKE, WAKE, MIQ, NAP])

    def test_an_outage_still_open_is_open_and_gives_no_recap(self):
        rows = closed_outage()[:-1]
        self.assertEqual(rc.outage(rows)["state"], rc.OPEN)
        self.assertIsNone(rc.outage(rows)["closed_at"])
        self.assertIsNone(rc.recap(rows, NOW, UTC))

    def test_no_outage_is_nothing(self):
        self.assertIsNone(rc.outage([]))
        self.assertIsNone(rc.outage(None))
        self.assertIsNone(rc.recap([row(NOW - H, WAKE, "telegram")], NOW, UTC))
        # one failure between deliveries is under SEND_FAIL_RUN: not an outage
        one = [row(NOW - 3 * H, WAKE, "telegram"), row(NOW - 2 * H, MIQ, RC1), row(NOW - H, NAP, "telegram")]
        self.assertIsNone(rc.outage(one))
        self.assertEqual(rc.SEND_FAIL_RUN, delivery_audit.SEND_FAIL_RUN)

    def test_rows_that_never_reached_the_transport_neither_close_nor_break_a_run(self):
        rows = [row(NOW - 5 * H, WAKE, RC1), row(NOW - 4 * H, "x", "held (sleep mode)"),
                row(NOW - 3 * H, MIQ, RC1), row(NOW - 2 * H, "x", "log (duplicate)")]
        self.assertEqual(rc.outage(rows)["state"], rc.OPEN)

    def test_two_outages_only_the_last_counts(self):
        first = [row(NOW - 3 * D, WAKE, RC1), row(NOW - 3 * D + H, MIQ, RC1), row(NOW - 3 * D + 2 * H, NAP, "telegram")]
        o = rc.outage(first + closed_outage())
        self.assertEqual(o["first_at"], int(NOW - D - 2 * H))
        self.assertNotEqual(rc.recap(first + closed_outage(), NOW, UTC)["key"], rc.recap(first, NOW, UTC)["key"])

    def test_a_closed_outage_then_a_single_new_failure_still_recaps_the_closed_one(self):
        rows = closed_outage() + [row(NOW - 60, MIQ, RC1)]
        self.assertEqual(rc.outage(rows)["state"], rc.CLOSED)

    def test_bad_rows_are_skipped_and_order_is_by_time(self):
        rows = list(reversed(closed_outage())) + [{"at": "x", "how": RC1}, "junk", {"how": RC1}]
        self.assertEqual(rc.outage(rows)["first_at"], int(NOW - D - 2 * H))


class TheRecap(unittest.TestCase):
    def test_the_body_names_the_kinds_in_order_of_first_miss_how_many_and_since_when(self):
        got = rc.recap(closed_outage(), NOW, UTC)
        lines = got["body"].splitlines()
        self.assertEqual(lines[0], rc.FIRST_LINE)
        self.assertEqual(lines[1], "Missed since yesterday: a few messages (wake brief, MIQ prompt, back from nap).")
        self.assertEqual(lines[-1], "Reply: OK / More")
        self.assertEqual(got["title"], rc.TITLE)

    def test_the_once_key_comes_from_the_first_failed_row_and_is_stable_across_polls(self):
        rows = closed_outage()
        a = rc.recap(rows, NOW, UTC)
        b = rc.recap(rows + [row(NOW - 30, "Week review", "telegram")], NOW + 300, UTC)
        self.assertEqual(a["key"], f"outage_recap:{int(NOW - D - 2 * H)}")
        self.assertEqual(a["key"], b["key"])

    def test_no_digit_body_text_profile_target_or_path(self):
        rows = closed_outage()
        rows[1]["body"] = "Secret body text 42 sender-a telegram:someone /tmp/x\n" + WHY
        body = rc.recap(rows, NOW, UTC)["body"] + rc.TITLE
        self.assertIsNone(re.search(r"\d", body))
        for bad in ("Secret", "sender-a", "telegram:", "/tmp", "Something happened", "Why now"):
            self.assertNotIn(bad, body)

    def test_it_is_one_tap(self):
        body = rc.recap(closed_outage(), NOW, UTC)["body"]
        self.assertTrue(one_tap.is_one_tap(body))
        self.assertEqual(one_tap.choices_of(body.splitlines()[-1]), rc.ANSWERS)

    def test_how_many_counts_distinct_messages_in_words(self):
        self.assertEqual([rc.count_word(n) for n in (1, 2, 4, 5, 40)], ["one", "a few", "a few", "many", "many"])
        two = [row(NOW - 3 * H, WAKE, RC1), row(NOW - 2 * H, WAKE, RC1), row(NOW - H, NAP, "telegram")]
        self.assertIn("one message (wake brief)", rc.recap(two, NOW, UTC)["body"])

    def test_since_in_words_from_the_local_date(self):
        f = lambda dt: datetime(*dt, tzinfo=UTC).timestamp()   # noqa: E731
        self.assertEqual(rc.since_words(f((2030, 1, 15, 1)), NOW, UTC), "since earlier today")
        self.assertEqual(rc.since_words(f((2030, 1, 14, 23)), NOW, UTC), "since yesterday")
        self.assertEqual(rc.since_words(f((2030, 1, 13, 9)), NOW, UTC), "since two days ago")
        self.assertEqual(rc.since_words(f((2030, 1, 10, 9)), NOW, UTC), "since five days ago")
        self.assertEqual(rc.since_words(f((2029, 12, 1, 9)), NOW, UTC), "since over a week ago")

    def test_kinds_from_titles(self):
        self.assertEqual(rc.kind(WAKE), "wake brief")
        self.assertEqual(rc.kind(MIQ), "MIQ prompt")
        self.assertEqual(rc.kind(NAP), "back from nap")
        self.assertEqual(rc.kind(jobs.HABIT_CHECKIN.send_title), "habit check-in")
        self.assertEqual(rc.kind("Pick one?"), "pick one")
        for odd in ("Room 42 at 9", "a/b/c", "", None, "one two three four five six seven"):
            self.assertEqual(rc.kind(odd), rc.OTHER)

    def test_many_kinds_are_cut_to_a_short_list(self):
        titles = [WAKE, MIQ, NAP, "Week review", "Habit check-in", "Long focus block"]
        rows = [row(NOW - (10 - i) * H, t, RC1) for i, t in enumerate(titles)] + [row(NOW - H, "x", "telegram")]
        line = rc.recap(rows, NOW, UTC)["body"].splitlines()[1]
        self.assertTrue(line.endswith("(wake brief, MIQ prompt, back from nap, week review and others)."), line)
        self.assertIn("many messages", line)


if __name__ == "__main__":
    unittest.main()
