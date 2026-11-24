"""is_one_tap: a message that asks something ends in a choices line, and every job body that asks passes.

Covers every job spec (and its per-habit variants) with every extra line the runner can add. Synthetic
habit and lines only; nothing sends.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import feeds_evidence, jobs, jobs_runner, one_tap, send_gate  # noqa: E402

HABIT = {"habit": "Synthetic habit", "week_of": "2031-01-06", "checkins": {"2031-01-06": "Done"}}
EXTRA = dict(flow="Flow: not recording this week (no ActivityWatch data).",
             passive="Phone data (a proxy, not a check-in): not enough this week to say.",
             body_line="Body fat: not enough data.", rides_line="No rides this week.",
             sleep_line="Sleep: not enough nights.", overnight="Overnight: a few tasks running, one queued")
ASKING = {jobs.HABIT_CHECKIN.name, jobs.WEEK_REVIEW.name, jobs.MIQ.name}


def specs():
    out = list(jobs.SPECS.values()) + [jobs.wake_brief(decision=True)]
    out += [jobs.habit_checkin(dict(HABIT, cue=c)) for c in ("wake", "wind_down", "focus_end")]
    out += [jobs.week_review(HABIT)]
    return out


def bodies():
    """(spec, body) for every spec, bare and with every extra line and every phone hint."""
    phones = [None, {"seen": None, "count": 0}, {"seen": True, "count": 2}, {"seen": False, "count": 0}]
    for spec in specs():
        for habit in (None, HABIT):
            yield spec, jobs_runner.body(spec, habit)
            for phone in phones:
                yield spec, jobs_runner.body(spec, habit, phone=phone, synced={}, **EXTRA)


class IsOneTap(unittest.TestCase):
    def test_a_question_without_choices_fails(self):
        self.assertFalse(one_tap.is_one_tap("Did you do it today?"))
        self.assertFalse(one_tap.is_one_tap("Did you do it today?\nA hint line."))

    def test_asking_for_input_without_choices_fails(self):
        for body in ("Reply Done, No or Skip.", "Synthetic habit: no days logged. Reply Keep or Drop.",
                     "Tell me the one thing for tomorrow.", "Let me know which one.", "Please answer when free."):
            self.assertFalse(one_tap.is_one_tap(body), body)

    def test_choices_as_the_last_line_passes(self):
        self.assertTrue(one_tap.is_one_tap("Did you do it today?\nReply: Done / No / Skip"))
        self.assertTrue(one_tap.is_one_tap("Did you?\nA hint line.\nReply: Yes / No"))

    def test_the_why_line_may_follow(self):
        body = send_gate.outgoing("Did you?\nReply: Yes / No", "Why now: you woke up")
        self.assertTrue(one_tap.is_one_tap(body))

    def test_choices_not_last_fails(self):
        self.assertFalse(one_tap.is_one_tap("Reply: Yes / No\nDid you?"))
        self.assertFalse(one_tap.is_one_tap("Did you?\nReply: Yes / No\nOne more line."))

    def test_a_bad_choices_line_fails(self):
        self.assertFalse(one_tap.is_one_tap("Did you?\nReply: Yes / Not now"))
        self.assertFalse(one_tap.is_one_tap("Did you?\nReply: Yes"))

    def test_a_message_that_asks_nothing_passes(self):
        for body in ("You are up. Your brief comes next.", "", None, "Overnight: a few tasks running"):
            self.assertTrue(one_tap.is_one_tap(body), body)
            self.assertFalse(one_tap.asks(body), body)

    def test_asks(self):
        self.assertTrue(one_tap.asks("Did you?\nReply: Yes / No"))
        self.assertTrue(one_tap.asks("Reply Keep or Drop."))


class JobBodies(unittest.TestCase):
    def test_every_job_body_is_one_tap(self):
        n = 0
        for spec, body in bodies():
            n += 1
            self.assertTrue(one_tap.is_one_tap(body), (spec.name, body))
            self.assertTrue(one_tap.is_one_tap(send_gate.outgoing(body, "Why now: you woke up")), spec.name)
        self.assertGreater(n, 20)

    def test_every_job_that_asks_ends_in_its_own_choices(self):
        seen = set()
        for spec, body in bodies():
            if spec.name not in ASKING:
                self.assertFalse(one_tap.asks(body), (spec.name, body))
                continue
            seen.add(spec.name)
            self.assertTrue(one_tap.asks(body), (spec.name, body))
            want = spec.answers or jobs_runner.MIQ_ANSWERS
            self.assertEqual(one_tap.choices_of(body.splitlines()[-1]), tuple(want), (spec.name, body))
        self.assertEqual(seen, ASKING)

    def test_habit_week_and_miq_choices(self):
        self.assertEqual(jobs_runner.body(jobs.HABIT_CHECKIN, HABIT).splitlines()[-1], "Reply: Done / No / Skip")
        self.assertEqual(jobs_runner.body(jobs.week_review(HABIT), HABIT).splitlines()[-1], "Reply: Keep / Drop")
        self.assertEqual(jobs_runner.body(jobs.MIQ).splitlines()[-1], "Reply: Yes / No / Later")

    def test_the_choices_are_read_back_like_habit_replies(self):
        # every offered habit or week choice, tapped or spoken, reads back to the word habit_replies logs
        from limitless import habit_replies
        for opt in jobs.HABIT_CHECKIN.answers:
            for said in (opt, opt.lower() + ".", opt.upper() + " 👍"):
                self.assertEqual(one_tap.parse(said, jobs.HABIT_CHECKIN.answers), opt)
                self.assertEqual(habit_replies.tap(said), jobs.habit_answer(opt))
        for opt in jobs.WEEK_REVIEW.answers:
            self.assertEqual(habit_replies.decision(opt.lower() + "."), opt)

    def test_no_digits_or_card_ids_in_any_choices_line(self):
        for _, body in bodies():
            last = body.splitlines()[-1]
            if one_tap.choices_of(last):
                self.assertFalse(any(c.isdigit() for c in last), last)
                self.assertEqual(send_gate.scrub(last), last)


if __name__ == "__main__":
    unittest.main()
