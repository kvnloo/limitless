"""jobs.to_schedule_card says the cron gate's window and expiry in words, read from jobs.to_cron_fields.

The card's ``window`` line and its ``stale`` line ("dropped if more than three hours late") come from
to_cron_fields(spec), the same two fields the Hermes cron decision-window gate stores, so the card and the
gate cannot drift. Synthetic specs only; no clock, no network.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import os
import re
import sys
import unittest
from dataclasses import replace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import jobs, schedule_cards  # noqa: E402

# The one test table: the card's window words -> the cron gate's window_class.
WORDS_TO_CLASS = {
    "in a peak window, at most one decision per window": "peak",
    "in a low-energy window, for a review or an easy read": "trough",
    "once your wind-down has started": "wind_down",
    "any time you are awake": "anytime",
}

# Every spec a card is made for: the message jobs, the per-decision and per-cue variants, the jobs that send
# nothing, the ledger, and one synthetic spec per window class.
SYNTH = [jobs.JobSpec(f"synth_{w}", "wake", w, "Synthetic job", 1, "sleep_mode_on", stale_after_s=s)
         for w, s in (("peak", 90), ("trough", 5400), ("wind_down", 7200), ("anytime", 2 * 86400))]
ALL = (list(jobs.SPECS.values()) + schedule_cards.specs({"cue": "wind_down"}) + SYNTH +
       [jobs.wake_brief(decision=True), jobs.NOOP_EXPORT, jobs.APPS_INGEST, jobs.RANKED_INGEST,
        jobs.SENDER_INGEST, jobs.FIT_INGEST, jobs.OUTAGE_RECAP, jobs.SENDER_CONFIRM, schedule_cards.LEDGER_SPEC])

STALE = re.compile(r"dropped if more than (an?|[a-z -]+) (second|minute|hour|day)s? late")


def word_seconds(stale_line):
    """The seconds a stale line says, read back from its number words (the inverse the test needs)."""
    m = STALE.fullmatch(stale_line)
    if not m:
        raise AssertionError(f"not a stale line: {stale_line!r}")
    count, unit = m.group(1), m.group(2)
    n = 1 if count in ("a", "an") else words_to_int(count)
    return n * {"second": 1, "minute": 60, "hour": 3600, "day": 86400}[unit]


_SMALL = {w: i for i, w in enumerate(("zero one two three four five six seven eight nine ten eleven twelve "
                                      "thirteen fourteen fifteen sixteen seventeen eighteen nineteen").split())}
_TENS = {w: 10 * i for i, w in enumerate("_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if i > 1}
_SCALE = {"hundred": 100, "thousand": 1000, "million": 10 ** 6}


def words_to_int(text):
    total = cur = 0
    for w in re.split(r"[ -]", text):
        if w in _SMALL:
            cur += _SMALL[w]
        elif w in _TENS:
            cur += _TENS[w]
        elif w == "hundred":
            cur *= 100
        elif w in _SCALE:
            total += cur * _SCALE[w]
            cur = 0
        else:
            raise AssertionError(f"not a number word: {w!r} in {text!r}")
    return total + cur


class CardSaysTheGatesWindow(unittest.TestCase):
    def test_window_words_map_back_to_the_cron_window_class(self):
        for spec in ALL:
            card, cron = jobs.to_schedule_card(spec), jobs.to_cron_fields(spec)
            self.assertIn(card["window"], WORDS_TO_CLASS, spec.name)
            self.assertEqual(WORDS_TO_CLASS[card["window"]], cron["window_class"], spec.name)

    def test_stale_words_say_the_cron_stale_after_s(self):
        for spec in ALL:
            card, cron = jobs.to_schedule_card(spec), jobs.to_cron_fields(spec)
            if "stale_after_s" in cron:
                self.assertEqual(word_seconds(card["stale"]), cron["stale_after_s"], spec.name)
            else:
                self.assertNotIn("stale", card, spec.name)

    def test_known_stale_lines(self):
        card = jobs.to_schedule_card
        self.assertEqual(card(jobs.MIQ)["stale"], "dropped if more than three hours late")
        self.assertEqual(card(jobs.NAP)["stale"], "dropped if more than an hour late")
        self.assertEqual(card(jobs.BREAK_NUDGE)["stale"], "dropped if more than six hours late")
        self.assertEqual(card(jobs.OUTAGE_RECAP)["stale"], "dropped if more than twelve hours late")
        self.assertEqual(card(SYNTH[0])["stale"], "dropped if more than ninety seconds late")
        self.assertEqual(card(SYNTH[1])["stale"], "dropped if more than ninety minutes late")
        self.assertEqual(card(SYNTH[3])["stale"], "dropped if more than two days late")
        odd = replace(SYNTH[0], stale_after_s=3661.5)   # to_cron_fields rounds up: the card says what the gate holds
        self.assertEqual(card(odd)["stale"],
                         "dropped if more than three thousand six hundred sixty-two seconds late")


class OneSource(unittest.TestCase):
    def test_mutating_cron_window_changes_the_card(self):
        before = jobs.to_schedule_card(jobs.MIQ)
        with mock.patch.dict(jobs.CRON_WINDOW, {"wind_down": "anytime"}):
            after = jobs.to_schedule_card(jobs.MIQ)
            self.assertEqual(jobs.to_cron_fields(jobs.MIQ)["window_class"], "anytime")
        self.assertEqual(before["window"], "once your wind-down has started")
        self.assertEqual(after["window"], "any time you are awake")
        self.assertNotEqual(before, after)

    def test_card_follows_to_cron_fields(self):
        with mock.patch.object(jobs, "to_cron_fields", return_value={"window_class": "trough",
                                                                      "stale_after_s": 1200}):
            c = jobs.to_schedule_card(jobs.WAKE_BRIEF)
        self.assertEqual(c["window"], "in a low-energy window, for a review or an easy read")
        self.assertEqual(c["stale"], "dropped if more than twenty minutes late")


class StaysPlain(unittest.TestCase):
    def test_digit_free_and_no_clock_time(self):
        for spec in ALL:
            for k, v in jobs.to_schedule_card(spec).items():
                self.assertNotRegex(v, r"\d|\b(am|pm|o'clock|noon|midnight)\b", f"{spec.name}.{k}: {v!r}")

    def test_jobs_with_no_expiry_keep_todays_card_byte_for_byte(self):
        self.assertEqual(jobs.to_schedule_card(jobs.NOOP_EXPORT), {
            "name": "NOOP export",
            "speaks": "after a sync that copied the NOOP database, at most once",
            "window": "any time you are awake",
            "ends": "at the next sync that copies the NOOP database",
            "delivery": "you, through the send gate; this job never sends by itself"})
        self.assertEqual(jobs.to_schedule_card(schedule_cards.LEDGER_SPEC), {
            "name": "Idea ledger",
            "speaks": "when your wind-down starts, at most once",
            "window": "once your wind-down has started",
            "ends": "when Sleep mode goes on",
            "delivery": "you, through the send gate; this job never sends by itself"})


if __name__ == "__main__":
    unittest.main()
