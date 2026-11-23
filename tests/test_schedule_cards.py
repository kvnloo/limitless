"""schedule_cards: every JobSpec as one Hermes proactivity schedule card (event trigger, never a clock time)."""
import json
import os
import re
import sys
import unittest
from datetime import timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import jobs, jobs_runner, schedule_cards, send_gate  # noqa: E402

FIELDS = {"id", "kind", "name", "description", "trigger", "ends", "window", "stale_after_s", "once_key",
          "budget", "per_window", "sender", "words"}
# A clock time or a cron string in any form: 07:30, 7am, 7 pm, "0 7 * * *", @daily, "every day at".
CLOCK = re.compile(r"\d|:\d|\b(am|pm)\b|\*|@(daily|hourly|weekly|midnight)|\bevery\b|\bcron\b|o'clock", re.I)
T0 = 1894708800.0   # synthetic trigger time


class Cards(unittest.TestCase):
    def test_one_card_per_job_spec_in_spec_order(self):
        self.assertEqual([c["id"] for c in schedule_cards.cards()], list(jobs.SPECS))

    def test_wake_brief_card(self):
        c = schedule_cards.card_for(jobs.WAKE_BRIEF)
        self.assertEqual(set(c), FIELDS)
        self.assertEqual(c["id"], "wake_brief")
        self.assertEqual(c["kind"], "schedule")          # #158289's approval kind for a new job
        self.assertEqual(c["name"], "Wake-up brief")
        self.assertEqual(c["trigger"], "wake")
        self.assertEqual(c["ends"], "sleep_mode_on")
        self.assertEqual(c["window"], "anytime")
        self.assertEqual(c["stale_after_s"], jobs.WAKE_STALE_S)
        self.assertEqual(c["once_key"], "wake_brief:<wake event time>")
        self.assertEqual(c["budget"], send_gate.DAILY_CAP)
        self.assertEqual(c["per_window"], 1)
        self.assertEqual(c["sender"], "plugin")
        self.assertEqual(c["words"], jobs.to_schedule_card(jobs.WAKE_BRIEF))
        self.assertEqual(c["description"], 'Schedule "Wake-up brief" (when you wake up, at most once; any time '
                                           'you are awake): ends when Sleep mode goes on; you, through the send '
                                           'gate; this job never sends by itself')

    def test_no_card_has_a_cron_or_clock_time_trigger(self):
        every = schedule_cards.cards() + schedule_cards.cards(habit={"cue": "wind_down"}) + \
            [schedule_cards.card_for(jobs.wake_brief(decision=True))]
        for c in every:
            self.assertIn(c["trigger"], jobs.EVENTS, c["id"])
            self.assertIn(c["ends"], jobs.EVENTS, c["id"])
            for k in ("trigger", "ends", "once_key", "description"):
                self.assertNotRegex(c[k], CLOCK, f"{c['id']}.{k}: {c[k]!r}")
            for k, v in c["words"].items():
                self.assertNotRegex(v, CLOCK, f"{c['id']}.words.{k}: {v!r}")
            self.assertNotIn("schedule", set(c) - {"kind"} - FIELDS)   # never #158289's clock `schedule` field

    def test_once_key_template_names_the_key_the_runner_uses(self):
        habit = {"habit": "Synthetic habit", "week_of": "2030-01-07"}
        for spec in jobs.SPECS.values():
            card = schedule_cards.card_for(spec)
            v = jobs.Verdict(jobs.DELIVER, "synthetic", T0)
            real = jobs_runner._key(spec, v, [], timezone.utc, habit)
            self.assertEqual(card["once_key"].split(":", 1)[0], real.split(":", 1)[0], spec.name)
            self.assertRegex(card["once_key"], r"^[a-z_]+:<[^<>\d]+>$", spec.name)

    def test_once_keys_in_words(self):
        k = {c["id"]: c["once_key"] for c in schedule_cards.cards()}
        self.assertEqual(k, {"wake_brief": "wake_brief:<wake event time>",
                             "nap": "nap:<nap event time>",
                             "miq": "miq:<night date>",
                             "habit_checkin": "habit_checkin:<habit cue event time>",
                             "week_review": "week_review:<habit week start date>",
                             "break_nudge": "break:<focus block start time>"})

    def test_stale_after_and_window_come_from_the_spec(self):
        for spec in jobs.SPECS.values():
            c = schedule_cards.card_for(spec)
            self.assertEqual(c["stale_after_s"], spec.stale_after_s)
            self.assertEqual(c["window"], spec.window_class)
            self.assertEqual(c["per_window"], spec.max_per_window)
            self.assertEqual(c["budget"], send_gate.DAILY_CAP)
        self.assertEqual(schedule_cards.card_for(jobs.wake_brief(decision=True))["window"], "peak")

    def test_sender_external_for_jobs_another_sender_owns(self):
        by = {c["id"]: c["sender"] for c in schedule_cards.cards(external=["miq", "not_a_job"])}
        self.assertEqual(by["miq"], "external")
        self.assertEqual({v for k, v in by.items() if k != "miq"}, {"plugin"})
        self.assertNotIn("not_a_job", by)

    def test_habit_cue_moves_both_habit_cards(self):
        by = {c["id"]: c for c in schedule_cards.cards(habit={"cue": "wind_down"})}
        self.assertEqual(by["habit_checkin"]["trigger"], "wind_down")
        self.assertEqual(by["week_review"]["trigger"], "wind_down")
        self.assertEqual(by["habit_checkin"]["once_key"], "habit_checkin:<wind-down event time>")
        self.assertEqual(by["wake_brief"]["trigger"], "wake")

    def test_cards_are_plain_json_data_and_fresh_each_call(self):
        a, b = schedule_cards.cards(), schedule_cards.cards()
        self.assertEqual(json.loads(json.dumps(a)), a)
        a[0]["name"] = "changed"
        a[0]["words"]["name"] = "changed"
        self.assertEqual(b[0]["name"], "Wake-up brief")
        self.assertEqual(schedule_cards.cards()[0]["words"]["name"], "Wake-up brief")

    def test_description_is_one_digit_free_line(self):
        for c in schedule_cards.cards():
            self.assertRegex(c["description"], r"^Schedule \"[^\"\n]+\" \([^\n]+\): [^\n]+$")
            self.assertFalse(any(ch.isdigit() for ch in c["description"]), c["description"])


if __name__ == "__main__":
    unittest.main()
