"""The habit week's stop rule: picked from a short fixed list when the week starts, read at the week review.

    stop_rule.rule("most_done")           -> "most_done" (a listed id), else None
    stop_rule.verdict(habit, "most_done", synced)   -> keep | drop | your call | unknown
    habit_start.start_week(..., stop_rule="most_done", write=True)   # stored in habit.json as "stop_rule"

The weekly review keeps the one habit or drops it by a rule the person set before the week began, not by
mood at the end. The rule only suggests; the person's Keep or Drop reply decides, always.

Rules are ids with plain wording (RULES). There is no free-text rule, no clock time and no number a person
sees: what "most" means stays in code (more than half of the logged days). Pure: nothing here sends, reads
a clock or touches a file.

``verdict`` reads the week's seven days as jobs.habit_day gives them (a tap wins over the sync's met/missed).
Only Done and No are answers: Skipped and a day with no answer are unlogged and never count against the
habit. A week with no Done or No at all, no started week, or no listed rule is ``unknown``, never drop. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

from typing import Any, Optional

from . import weekly_target

RULES = {
    "most_done": "drop it unless most logged days were Done",
    "any_done": "keep it if any logged day was Done",
    "not_a_chore": "keep it unless it felt like a chore",
    "no_rule": "no rule: decide at the review",
}
CONFIG_KEY = "stop_rule"      # the habit.json key, beside week_of
KEEP, DROP, YOUR_CALL, UNKNOWN = "keep", "drop", "your call", "unknown"
VERDICTS = (KEEP, DROP, YOUR_CALL, UNKNOWN)


def rule(v: Any) -> Optional[str]:
    """The listed rule id ``v`` names (case and surrounding spaces ignored); None for anything else."""
    if not isinstance(v, str):
        return None
    rid = v.strip().lower()
    return rid if rid in RULES else None


def rule_of(habit: Optional[dict]) -> Optional[str]:
    """The stop rule stored in habit.json, when it is a listed one; else None (no rule was set)."""
    return rule(habit.get(CONFIG_KEY)) if isinstance(habit, dict) else None


def _answers(habit: Optional[dict], synced: Optional[dict]):
    """(Done days, Done + No days) over the started week's seven days; Skipped and unlogged stay out."""
    days = list(weekly_target.week_days(habit, synced).values())
    return days.count("Done"), days.count("Done") + days.count("No")


def verdict(habit_week: Optional[dict], rule_id: Any, synced: Optional[dict] = None) -> str:
    """keep | drop | your call | unknown for the week in ``habit_week`` (habit.json) under ``rule_id``.

    It only suggests: the person's Keep or Drop reply decides. Unknown when no week is started, the rule is
    not a listed one, or no day of the week has a Done or No answer.
    """
    rid = rule(rule_id)
    done, logged = _answers(habit_week, synced)
    if rid is None or logged == 0:
        return UNKNOWN
    if rid == "most_done":
        return KEEP if done * 2 > logged else DROP     # "most" = more than half of the logged days
    if rid == "any_done":
        return KEEP if done else DROP
    if rid == "not_a_chore":
        return KEEP                                    # whether it felt like a chore is the person's reply
    return YOUR_CALL
