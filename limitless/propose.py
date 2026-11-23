"""Propose: the one small thing that fits now, from a short rule table the person can read; NO_SUGGESTION
by default.

    r = propose(state)   # {"action", "because", "rule_id", "evidence": [label names used]}

``state`` is a plain dict of labels other tools already computed (STATE_KEYS). The rules are read in order
and the first one whose every condition holds wins; when none holds the answer is NO_SUGGESTION. Doing
nothing is the default: a suggestion only appears when a rule clearly beats it.

A condition is a label name and the exact values that satisfy it. A label that is missing, unknown, of
another type or any other word satisfies no condition, so an unknown input never triggers a rule (``1`` is
not ``True`` here, and ``"yes"`` is not ``True`` either).

Every rule is an event or a state, never a clock time: there is no time of day anywhere in this module, and
nothing here reads the clock. The words are digit-free, and ``because`` cites the label names, never a
number. Pure: nothing here writes, sends, schedules or starts anything. It only suggests; the agent asks
the person before doing anything. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

from typing import Any, Mapping

NO_SUGGESTION = "NO_SUGGESTION"
DEFAULT_ID = "nothing-fits"
DEFAULT_BECAUSE = "no rule clearly fits the labels right now, so doing nothing is the suggestion"

# The labels propose reads, and the values each one can take (anything else is unknown).
STATE_KEYS = {
    "asleep": (True, False),
    "quiet": ("on", "off", "quiet tonight", "snoozed"),
    "focus_block": ("in a block", "between blocks"),
    "mode": ("none", "brainstorm", "pm", "copilot", "focused"),
}

# The rule table, in order. ``when``: label name -> the values that satisfy it (all must hold).
RULES = (
    {"id": "asleep", "when": {"asleep": (True,)}, "action": NO_SUGGESTION,
     "because": "asleep: nothing is suggested until the person wakes"},
    {"id": "quiet", "when": {"quiet": ("off", "quiet tonight", "snoozed")}, "action": NO_SUGGESTION,
     "because": "quiet is set: nothing is suggested while the person asked for quiet"},
    {"id": "focus-block", "when": {"focus_block": ("in a block",)}, "action": NO_SUGGESTION,
     "because": "focus block: nothing is suggested until the block ends"},
    {"id": "focused-mode", "when": {"mode": ("focused",)}, "action": NO_SUGGESTION,
     "because": "focused mode: nothing is suggested while the person is focused"},
)


def _holds(value: Any, allowed) -> bool:
    """True when ``value`` is one of ``allowed`` with the same type (so ``1`` never stands for ``True``)."""
    return any(type(value) is type(a) and value == a for a in allowed)


def _matches(rule: Mapping, state: Mapping) -> bool:
    return all(k in state and _holds(state[k], allowed) for k, allowed in rule["when"].items())


def propose(state: Any) -> dict:
    """The first rule in RULES whose conditions all hold for ``state``, as ``{action, because, rule_id,
    evidence}``; NO_SUGGESTION (DEFAULT_ID, no evidence) when none does or ``state`` is not a dict."""
    if isinstance(state, Mapping):
        for rule in RULES:
            if _matches(rule, state):
                return {"action": rule["action"], "because": rule["because"], "rule_id": rule["id"],
                        "evidence": list(rule["when"])}
    return {"action": NO_SUGGESTION, "because": DEFAULT_BECAUSE, "rule_id": DEFAULT_ID, "evidence": []}
