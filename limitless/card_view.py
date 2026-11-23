"""limitless_card_view: today's state card, the week review or the skill tree as one ephemeral HTML card
(ui_card.py).

    view(state_dir, now, today, "state" | "week" | "skill_tree")   # an envelope; writes at most one card file

The rows are lines the plugin already makes, never new words: ``state`` is card.build's state card (the
same lines the pre_llm_call hook injects, with the hook's Anki offer and post-wake peak, then the attention
mode's line; the model-facing header line is left out); ``week`` is the week review's message
(jobs_runner.week_review_body, the text the week review push sends) without its ``Reply: Keep / Drop`` ask,
since a card takes no tap; ``skill_tree`` is skill_tree.lines over the tree limitless_skill_tree returns (one
row per layer: Foundation, Learning, Flow, Enhancement, each habit with its state word; a later layer's row
says it is waiting, so its chip is held). The raw opt-in is never applied, and lines are built unmasked so that
ui_card.render's tier_audit.gate drops (and counts) any line that holds a digit instead of showing a mask.

The envelope: value ``{path, rows, dropped}`` (path null when no card dir is set; ``note`` then says why),
modality ``derived`` (built from other values, not measured), ``age_h`` null, evidence_tier that of the
inputs (the state card's weakest part; the habit week's self-report; the newest Keep or Drop for the skill
tree), and the T1 label "a state card with three rows" / "a week card with two rows" / "a skill tree card
with four rows" (count in words, digit-free). No push, no job, no score, no level, no streak.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Callable, Mapping, Optional

from . import card, jobs, jobs_runner, labeler as _labeler, modes, one_tap, skill_tree, tools, ui_card
from .envelope import _tier, missing
from .state_reader import StateReader, parse_ts
from .window import window

MODALITY = "derived"
_WORDS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")
LABEL = {"state": "a state card with {n}", "week": "a week card with {n}",
         "skill_tree": "a skill tree card with {n}"}


def count_words(n: int) -> str:
    """"no rows", "one row", "three rows"; "many rows" past ten. Never a digit."""
    word = _WORDS[n] if 0 <= n < len(_WORDS) else "many"
    return f"{word} {'row' if n == 1 else 'rows'}"


def state_lines(reader: StateReader, now: float, today: date, env: Mapping[str, str], bands=None,
                labeler: Optional[Callable] = None):
    """(lines, evidence_tier) of the pre_llm_call state card, without its header line; raw never applied."""
    win = window(reader, now, bands)
    c = card.build(reader, now, today, raw=False, win=win, bands=bands, labeler=labeler, env=env,
                   anki_offer=card.anki_offer(reader, now, win, env), mask=False)
    lines = list(c["lines"][1:])
    mode_line = modes.line(modes.load(reader.path))
    if mode_line:
        lines.append(mode_line)
    mods = [e["modality"] for e in c["items"].values()
            if isinstance(e, dict) and e.get("value") is not None and e.get("modality")]
    tier = "none" if not mods else _tier(max(mods, key=card._WEAKEST_LAST.index), c["age_h"])
    return lines, tier


def week_lines(reader: StateReader, now: float, today: date, env: Mapping[str, str],
               home: Optional[Path] = None, tz=None):
    """(lines, evidence_tier) of the week review's message without its one-tap ask line. The tier is the
    habit week's (self-reported, aged by habit.json's ``at`` as limitless_habit does); none with no week."""
    habit = reader.habit()
    text = jobs_runner.week_review_body(reader.path, habit, reader.habit_days(), env, home, tz, today, now)
    ask = one_tap.choices_line(jobs.week_review(habit).answers)
    lines = [ln for ln in text.splitlines() if ln.strip() and ln != ask]
    if not isinstance(habit, dict):
        return lines, "none"
    at = parse_ts(habit.get("at"))
    return lines, _tier("self_report", None if at is None else max(0.0, now - at) / 3600)


def skill_tree_lines(state_dir, now: float, today: date):
    """(lines, evidence_tier) of the skill tree: one line per layer (skill_tree.lines) over the same tree and
    tier limitless_skill_tree returns. Read-only."""
    t, tier = tools.skill_tree_parts(state_dir, now, today)
    return skill_tree.lines(t), tier


def view(state_dir, now: float, today: date, kind: str = "state", env: Optional[Mapping[str, str]] = None,
         home: Optional[Path] = None, bands=None, labeler: Optional[Callable] = None, tz=None) -> dict:
    """The limitless_card_view envelope for ``kind`` (state, week or skill_tree). Writes one card file only when a card
    dir is set (ui_card.card_dir); never sends, schedules or starts anything."""
    env = os.environ if env is None else env
    if kind not in ui_card.KINDS:
        return missing("kind must be state, week or skill_tree")
    reader = StateReader(Path(state_dir))
    if not reader.exists():
        return missing("the state dir does not exist")
    lab = labeler or _labeler.from_config(env)
    if kind == "state":
        lines, tier = state_lines(reader, now, today, env, bands, lab)
    elif kind == "week":
        lines, tier = week_lines(reader, now, today, env, home, tz)
    else:
        lines, tier = skill_tree_lines(reader.path, now, today)
    r = ui_card.render(ui_card.TITLES[kind], lines, kind, env=env, now=now)
    out_dir = ui_card.card_dir(env, home)
    path = ui_card.write(out_dir, r["html"]) if out_dir is not None else None
    out = {"value": {"path": path, "rows": r["rows"], "dropped": r["dropped"]}, "modality": MODALITY,
           "age_h": None, "evidence_tier": tier,
           "label": {"label": LABEL[kind].format(n=count_words(r["rows"])), "tier": "T1", "modality": MODALITY}}
    if path is None:
        out["note"] = ui_card.NO_DIR
    return out
