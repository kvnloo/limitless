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

The tool (``limitless_propose``, tools.propose) wraps the result in ``derived(result, tiers)``: an envelope
with modality ``derived`` (computed from other tools' labels, not measured), ``age_h`` None, and the weakest
``evidence_tier`` of the labels the rule used (direct > indirect > stale > none). The default has no
evidence, so it takes the weakest tier among the inputs that were known, or none when nothing was known.
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
    "post_wake_peak": ("open", "in use", "closed"),
    "peak_ask": ("waiting", "spent", "none"),
    "window": ("peak", "trough", "anytime", "wind_down"),
    "anki": ("set", "not set"),
    "habit_week": ("running", "not running"),
    "habit_today": ("Done", "No", "Skipped", "unlogged"),
}

# How each ``because`` names a label (the words it cites, never a number).
LABEL_WORDS = {"asleep": "asleep", "quiet": "quiet", "focus_block": "focus block", "mode": "mode",
               "post_wake_peak": "post-wake peak", "peak_ask": "peak ask", "window": "window", "anki": "Anki",
               "habit_week": "habit week", "habit_today": "today"}

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
    {"id": "peak-ask", "when": {"post_wake_peak": ("open",), "peak_ask": ("waiting",)},
     "action": "decide the one waiting ask",
     "because": "post-wake peak is open and a peak ask is waiting: one decision fits this stretch"},
    {"id": "anki-trough", "when": {"window": ("trough",), "anki": ("set",)}, "action": "a short Anki review",
     "because": "a trough window is open and an Anki collection is set: a light review fits a lighter moment"},
    {"id": "habit-checkin", "when": {"habit_week": ("running",), "habit_today": ("unlogged",)},
     "action": "answer today's habit check-in",
     "because": "a habit week is running and today has no answer yet: one tap answers it"},
)

ACTIONS = tuple(dict.fromkeys([NO_SUGGESTION] + [r["action"] for r in RULES]))   # every answer propose gives


def _holds(value: Any, allowed) -> bool:
    """True when ``value`` is one of ``allowed`` with the same type (so ``1`` never stands for ``True``)."""
    return any(type(value) is type(a) and value == a for a in allowed)


def _matches(rule: Mapping, state: Mapping) -> bool:
    return all(k in state and _holds(state[k], allowed) for k, allowed in rule["when"].items())


MODALITY = "derived"
NOTE = "a suggestion only: nothing was done; ask the person before doing anything"
TIERS = ("direct", "indirect", "stale", "none")   # strongest first


def _weakest(tiers) -> str:
    known = [t for t in tiers if t in TIERS]
    return max(known, key=TIERS.index) if known else "none"


def label(result: Mapping) -> dict:
    """The T1 label: the action words, or "no suggestion"."""
    act = result.get("action") if isinstance(result, Mapping) else None
    word = act if act in ACTIONS and act != NO_SUGGESTION else "no suggestion"
    return {"label": word, "tier": "T1", "modality": MODALITY}


def derived(result: Mapping, tiers: Mapping) -> dict:
    """``result`` (from propose) as a derived evidence envelope with NOTE, its tier and its T1 label."""
    tiers = tiers if isinstance(tiers, Mapping) else {}
    used = list(result.get("evidence") or ())
    tier = _weakest(tiers.get(k) for k in used) if used else \
        _weakest(t for t in tiers.values() if t != "none")
    return {"value": dict(result, note=NOTE), "modality": MODALITY, "age_h": None, "evidence_tier": tier,
            "label": label(result)}


def propose(state: Any) -> dict:
    """The first rule in RULES whose conditions all hold for ``state``, as ``{action, because, rule_id,
    evidence}``; NO_SUGGESTION (DEFAULT_ID, no evidence) when none does or ``state`` is not a dict."""
    if isinstance(state, Mapping):
        for rule in RULES:
            if _matches(rule, state):
                return {"action": rule["action"], "because": rule["because"], "rule_id": rule["id"],
                        "evidence": list(rule["when"])}
    return {"action": NO_SUGGESTION, "because": DEFAULT_BECAUSE, "rule_id": DEFAULT_ID, "evidence": []}
