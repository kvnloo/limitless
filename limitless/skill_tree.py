"""The Training Facility's skill tree: four stacked layers, Foundation first, in plain words only.

    skill_tree.tree(habit_catalogue.CATALOGUE, decisions, current=habit_json)
        -> [{name, open, habits: [{name, state}]}] for Foundation, Learning, Flow, Enhancement, in that order
    skill_tree.lines(t)   -> one digit-free line per layer (the skill tree card's rows)
    skill_tree.label(t)   -> "Foundation open, one habit kept" (the count in words)

Few good habits, stacked: Foundation (sleep, energy, nutrition, recovery), then Learning, then Flow, then
Enhancement. The habits are the catalogue's (habit_catalogue.CATALOGUE, by its ``layer``); the catalogue has
no Enhancement habit yet, so that layer is listed with none. This module keeps no record of its own: the
states come from the weekly loop rows in predictions.jsonl (stop_rule.loop_rows, read through
habit_catalogue.decisions) and the running week (habit.json's ``habit``).

Each habit gets one state word: ``trying`` (this week's habit), ``kept`` (the latest decision is Keep),
``dropped`` (the latest decision is Drop) or ``not tried``. Anything unknown or unreadable (no row, a row
without Keep or Drop, a habit not on the list, a torn record) is ``not tried``, never ``dropped``: a skipped
or undecided week is unlogged. A layer is open when it is Foundation or every earlier layer has at least
one kept habit; otherwise it is later.

There is no score, level, percent, XP, streak or count of days here, and no digit in any word. Pure: nothing
reads a clock, touches a file or sends. It never starts a habit: that needs the person's yes and
habit_start. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

from typing import Mapping, Optional

from . import habit_catalogue, jobs

LAYERS = ("Foundation", "Learning", "Flow", "Enhancement")
KEPT, DROPPED, TRYING, NOT_TRIED = "kept", "dropped", "trying", "not tried"
STATES = (KEPT, DROPPED, TRYING, NOT_TRIED)
_FROM_DECISION = {"Keep": KEPT, "Drop": DROPPED}
_key = habit_catalogue._key


def _decided(decisions) -> dict:
    """{normalised id or name: Keep | Drop}. A mapping is read as {id or name: decision}; a list or tuple as
    loop rows (habit_catalogue.decisions: the latest Keep or Drop wins). Anything else says nothing."""
    if isinstance(decisions, (list, tuple)):
        decisions = habit_catalogue.decisions(decisions)
    if not isinstance(decisions, Mapping):
        return {}
    return {_key(k): v for k, v in decisions.items() if _key(k) and v in jobs.DECISIONS}


def _current(current) -> str:
    if isinstance(current, Mapping):
        current = current.get("habit")
    return _key(current)


def _keys(h) -> set:
    return {k for k in (_key(h.get("id")), _key(h.get("name"))) if k}


def tree(catalogue, decisions, current=None) -> list:
    """The four layers in order, each ``{name, open, habits: [{name, state}]}``. ``decisions`` is
    {catalogue id or name: Keep | Drop} or the loop rows themselves; ``current`` is the running habit (its name
    or id, or habit.json's dict), else None. A catalogue entry without a name or a known layer is skipped."""
    seen = _decided(decisions)
    running = _current(current)
    by_layer = {name: [] for name in LAYERS}
    for h in catalogue or ():
        if not isinstance(h, Mapping) or not isinstance(h.get("name"), str) or not h["name"].strip():
            continue
        layer = h.get("layer").strip().capitalize() if isinstance(h.get("layer"), str) else None
        if layer not in by_layer:
            continue
        keys = _keys(h)
        if running and running in keys:
            state = TRYING
        else:
            word = next((seen[k] for k in keys if k in seen), None)
            state = _FROM_DECISION.get(word, NOT_TRIED)
        by_layer[layer].append({"name": h["name"].strip(), "state": state})
    out, all_kept = [], True
    for i, name in enumerate(LAYERS):
        habits = by_layer[name]
        out.append({"name": name, "open": i == 0 or all_kept, "habits": habits})
        all_kept = all_kept and any(h["state"] == KEPT for h in habits)
    return out


_COUNT = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")
EMPTY = "no habits on the list yet"
WAITING = "waiting for a kept habit in every earlier layer"


def _count(n: int, noun: str) -> str:
    """"no habit", "one habit", "three habits"; "many habits" past ten. Never a digit."""
    word = _COUNT[n] if 0 <= n < len(_COUNT) else "many"
    return f"{word} {noun if n == 1 or n == 0 else noun + 's'}"


def lines(t) -> list:
    """One line per layer: "Foundation open: <habit> kept; <habit> not tried", "Flow later, waiting for a kept
    habit in every earlier layer: ...", "Enhancement open: no habits on the list yet". Digit-free words."""
    out = []
    for layer in t or ():
        head = f"{layer['name']} {'open' if layer['open'] else 'later'}"
        if not layer["open"]:
            head += f", {WAITING}"
        body = "; ".join(f"{h['name']} {h['state']}" for h in layer["habits"]) or EMPTY
        out.append(f"{head}: {body}")
    return out


def label(t) -> str:
    """"<the last open layer> open, <how many habits are kept, in words> kept"."""
    t = list(t or ())
    last = [layer["name"] for layer in t if layer["open"]]
    kept = sum(h["state"] == KEPT for layer in t for h in layer["habits"])
    return f"{last[-1] if last else LAYERS[0]} open, {_count(kept, 'habit')} kept"
