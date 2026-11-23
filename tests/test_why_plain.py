"""Plain why-now words: every reason decision_window.decide can return reads as plain words for the person.

The "Why now" line is the last line of every push (send_gate.why_line). decide's reasons are for logs and
rows ("anytime job and awake"); the person gets plain words, digit-free. Synthetic states only.
"""
import itertools
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import decision_window as dw  # noqa: E402
from limitless import send_gate as g  # noqa: E402

JARGON = re.compile(r"(?i)\b(window|job|anytime|peak|trough|wind_down|budget|provider|critical|delivers|holds)\b|_")
STATES = [None] + [dw.WindowState(cls=c, since=s, confidence=conf, hold_asks=h)
                   for c in dw.WINDOW_CLASSES + (dw.UNKNOWN, "bogus")
                   for s in (None, "", "wake", 1999990000)
                   for conf in (1.0, 0.2)
                   for h in (False, True)]


def every_reason():
    """Every distinct reason decide returns over every job class, window state, budget, sleep and class."""
    seen = {}
    for job, st, budget, asleep, critical in itertools.product(dw.WINDOW_CLASSES, STATES, (1, 0), (False, True),
                                                               (False, True)):
        d = dw.decide(job, st, budget_left=budget, asleep=asleep, critical=critical)
        seen.setdefault(d.reason, d.action)
    return seen


class EveryReason(unittest.TestCase):
    def test_covers_every_branch(self):
        reasons = every_reason()
        heads = {r.split(":")[0].split(" (")[0] for r in reasons}
        for want in ("critical", "asleep", "focus block running", "anytime job and awake", "window unknown",
                     "peak window open", "trough window open", "wind_down window open", "peak budget spent"):
            self.assertIn(want, heads)
        self.assertGreater(len(reasons), 20)

    def test_every_reason_has_plain_words(self):
        for reason in every_reason():
            words = dw.plain(reason)
            self.assertIsInstance(words, str)
            self.assertTrue(words.strip(), reason)
            self.assertNotEqual(words, reason, reason)
            self.assertIsNone(JARGON.search(words), (reason, words))
            self.assertFalse(any(c.isdigit() for c in words), (reason, words))
            self.assertNotIn(";", words)
            self.assertNotIn("\n", words)

    def test_the_why_line_carries_the_plain_words(self):
        for reason in every_reason():
            self.assertEqual(g.why_line(reason), g.WHY_PREFIX + dw.plain(reason), reason)

    def test_some_words(self):
        self.assertEqual(dw.plain("anytime job and awake"), "you are awake and this fits any moment")
        self.assertEqual(dw.plain("asleep: holds until wake"), "you are asleep, so this waits until you wake")
        self.assertEqual(dw.plain("peak window open (since wake)"), "your focus is high right now")
        self.assertEqual(dw.plain("critical: delivers whatever the window"),
                         "this is urgent, so it comes whatever you are doing")

    def test_anything_else_is_left_as_it_is(self):
        for text in ("you woke up", "the send gate let it through", "", "Something else"):
            self.assertEqual(dw.plain(text), text)
        self.assertEqual(dw.plain(None), "")


class WhyReason(unittest.TestCase):
    def test_why_reason_is_plain(self):
        self.assertEqual(g.why_reason("decision"), "you are awake and this fits any moment")
        self.assertEqual(g.why_reason("critical"), "this is urgent, so it comes whatever you are doing")
        self.assertEqual(g.why_reason("decision", "Wake-up brief"), "you woke up")
        for cls in ("decision", "critical", "report", None):
            self.assertIsNone(JARGON.search(g.why_reason(cls)), cls)

    def test_job_reasons_read_plainly(self):
        # jobs.should_fire's deliver reason is "<event> event; <decide reason>"
        self.assertEqual(g.why_line("wake event; anytime job and awake"),
                         "Why now: you woke up; you are awake and this fits any moment")
        self.assertEqual(g.why_line("habit cue event; anytime job and awake"),
                         "Why now: it is your habit cue; you are awake and this fits any moment")
        self.assertEqual(g.why_line("wind-down event; wind_down window open (since wind_down)"),
                         "Why now: your wind-down started; it is a good moment to close the day")
        self.assertEqual(g.why_line("nap event; peak window open (since 1999990000)"),
                         "Why now: you are back from a nap; your focus is high right now")

    def test_digits_and_card_ids_still_left_out(self):
        line = g.why_line("wake event; peak window open (since 1999990000) for t_510c250d in 3 h")
        self.assertFalse(any(c.isdigit() for c in line), line)
        self.assertNotIn("t_510c250d", line)


if __name__ == "__main__":
    unittest.main()
