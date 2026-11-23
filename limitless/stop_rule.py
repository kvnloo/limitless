"""The habit week's stop rule: picked from a short fixed list when the week starts, read at the week review.

    stop_rule.rule("most_done")           -> "most_done" (a listed id), else None
    habit_start.start_week(..., stop_rule="most_done", write=True)   # stored in habit.json as "stop_rule"

The weekly review keeps the one habit or drops it by a rule the person set before the week began, not by
mood at the end. The rule only suggests; the person's Keep or Drop reply decides, always.

Rules are ids with plain wording (RULES). There is no free-text rule, no clock time and no number a person
sees: what "most" means stays in code (more than half of the logged days). Pure: nothing here sends, reads
a clock or touches a file. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

from typing import Any, Optional

RULES = {
    "most_done": "drop it unless most logged days were Done",
    "any_done": "keep it if any logged day was Done",
    "not_a_chore": "keep it unless it felt like a chore",
    "no_rule": "no rule: decide at the review",
}
CONFIG_KEY = "stop_rule"      # the habit.json key, beside week_of


def rule(v: Any) -> Optional[str]:
    """The listed rule id ``v`` names (case and surrounding spaces ignored); None for anything else."""
    if not isinstance(v, str):
        return None
    rid = v.strip().lower()
    return rid if rid in RULES else None


def rule_of(habit: Optional[dict]) -> Optional[str]:
    """The stop rule stored in habit.json, when it is a listed one; else None (no rule was set)."""
    return rule(habit.get(CONFIG_KEY)) if isinstance(habit, dict) else None
