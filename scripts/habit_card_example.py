"""The synthetic habit-card example in docs/habit-card.md: python3 -I scripts/habit_card_example.py

One synthetic card and one synthetic week (Done, Done, nothing, No, Skip, nothing, Done). Reads no state,
writes no file, sends nothing, reads no clock.
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from limitless import habit_card, jobs, schedule_cards, stop_rule  # noqa: E402
from limitless.habit_card import HabitCard  # noqa: E402

START = date(2030, 1, 7)
WEEK = ("Done", "Done", None, "No", "Skip", None, "Done")   # None: no reply that day


def show(label, value):
    print(f"{label}: {json.dumps(value, default=list)}")


def main():
    card = HabitCard("Lights down", "wind_down", start_s=120)
    show("card", {"name": card.name, "cue": card.cue, "start_s": card.start_s, "replies": card.replies})

    state = {}
    for i, r in enumerate(WEEK):
        if r is not None:
            state = habit_card.record(state, (START + timedelta(days=i)).isoformat(), r)
    show("state", state)
    show("week_number", habit_card.week_number(state, START))
    show("verdict_inputs", habit_card.verdict_inputs(state, START, "most_done"))

    # The same week as limitless keeps it: habit.json, with Skip marked Skipped.
    habit = {"habit": card.name, "week_of": START.isoformat(), "cue": card.cue, "stop_rule": "most_done"}
    for i, r in enumerate(WEEK):
        if r is not None:
            habit = jobs.record_checkin(habit, (START + timedelta(days=i)).isoformat(), r)
    show("habit.json checkins", habit["checkins"])
    print(f"limitless stop rule: {stop_rule.verdict(habit, stop_rule.rule_of(habit))}")
    print(f"limitless week review: {jobs.week_review_text(habit)}")

    for spec in (jobs.habit_checkin(habit), jobs.week_review(habit)):
        c = schedule_cards.card_for(spec)
        show(f"schedule card {c['id']}", {"name": c["name"], "trigger": c["trigger"], "ends": c["ends"],
                                          "answers": c["words"]["answers"]})


if __name__ == "__main__":
    main()
