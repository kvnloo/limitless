"""The habit week's stop rule: picked from a short fixed list when the week starts, read at the week review.

    stop_rule.rule("most_done")           -> "most_done" (a listed id), else None
    stop_rule.verdict(habit, "most_done", synced)   -> keep | drop | your call | unknown
    stop_rule.review_line("keep")         -> "Your rule says: keep it" (the week review's line; "" for unknown)
    stop_rule.record_loop(state_dir, habit, "Keep", decided_at)   # one loop row per week, after the reply
    stop_rule.loop_rows(state_dir)        -> the weekly loop rows, oldest first
    habit_start.start_week(..., stop_rule="most_done", write=True)   # stored in habit.json as "stop_rule"

The weekly review keeps the one habit or drops it by a rule the person set before the week began, not by
mood at the end. The rule only suggests; the person's Keep or Drop reply decides, always.

Rules are ids with plain wording (RULES). There is no free-text rule, no clock time and no number a person
sees: what "most" means stays in code (more than half of the logged days). Pure: nothing here sends, reads
a clock or touches a file, except record_loop, which appends the week's one loop row.

``verdict`` reads the week's seven days as jobs.habit_day gives them (a tap wins over the sync's met/missed).
Only Done and No are answers: Skipped and a day with no answer are unlogged and never count against the
habit. A week with no Done or No at all, no started week, or no listed rule is ``unknown``, never drop.

The loop row closes the week (observe, one small change, a locked prediction, the outcome, the decision):
after the person's Keep or Drop reply (habit_replies.decide, not a dry run) ONE row per week is appended to
the existing prediction ledger, predictions.jsonl (prediction._append: 0600, append-only, no second store):
``{kind: "loop", week_of, habit, prediction: "prediction locked" | "none", outcome: the receipt's verdict |
"unknown", outcome_modality, outcome_at, rule, verdict, decision: Keep | Drop, decided_at}``. Nothing is
written before the reply; a week that already has a loop row never gets another. The outcome is the receipt
as it stands at the reply: a receipt written later is in the ledger beside it, the loop row is not rewritten. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from . import habit_card, jobs, prediction as _prediction
from .envelope import MODALITIES
from .state_reader import StateReader, normalize_digest

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


def _inputs(habit: Optional[dict], synced: Optional[dict], rid: Optional[str]) -> Optional[dict]:
    """habit_card.verdict_inputs for the started week (Done days, Done + No days; Skipped and unlogged stay
    out); None when no week is started."""
    start = jobs._week_start(habit)
    return None if start is None else habit_card.verdict_inputs(jobs.week_card_state(habit, synced), start, rid)


def verdict(habit_week: Optional[dict], rule_id: Any, synced: Optional[dict] = None) -> str:
    """keep | drop | your call | unknown for the week in ``habit_week`` (habit.json) under ``rule_id``.

    It only suggests: the person's Keep or Drop reply decides. Unknown when no week is started, the rule is
    not a listed one, or no day of the week has a Done or No answer.
    """
    rid = rule(rule_id)
    inputs = _inputs(habit_week, synced, rid)
    if rid is None or inputs is None or inputs["logged"] == 0:
        return UNKNOWN
    done, logged = inputs["done"], inputs["logged"]
    if rid == "most_done":
        return KEEP if done * 2 > logged else DROP     # "most" = more than half of the logged days
    if rid == "any_done":
        return KEEP if done else DROP
    if rid == "not_a_chore":
        return KEEP                                    # whether it felt like a chore is the person's reply
    return YOUR_CALL


REVIEW_PREFIX = "Your rule says: "
_REVIEW_WORDS = {KEEP: "keep it", DROP: "drop it", YOUR_CALL: "your call"}


def review_line(v: Any) -> str:
    """The week review's line for a verdict: "Your rule says: keep it" / "drop it" / "your call"; "" for
    unknown or anything else (no line: the review is as it was). Digit-free; the reply still decides."""
    w = _REVIEW_WORDS.get(v) if isinstance(v, str) else None
    return REVIEW_PREFIX + w if w else ""


LOOP = "loop"
NO_PREDICTION, LOCKED_LABEL, NO_OUTCOME = "none", "prediction locked", "unknown"


def loop_rows(state_dir) -> list:
    """The loop rows in the prediction ledger, oldest first: the first row of each week (later ones are never
    written; a stray copy is not read)."""
    seen, out = set(), []
    for r in _prediction.rows(state_dir):
        if r.get("kind") == LOOP and isinstance(r.get("week_of"), str) and r["week_of"] not in seen:
            seen.add(r["week_of"])
            out.append(r)
    return out


def _outcome_modality(state_dir, metric) -> Optional[str]:
    """How the receipt's outcome was observed: self_report for logged days (the person's taps), else the
    modality the state metric's digest rows carry (the newest one named), else None."""
    if metric == _prediction.LOGGED:
        return "self_report"
    found = None
    for raw in StateReader(Path(state_dir)).digests():
        row = normalize_digest(raw)
        cell = row.get("metrics", {}).get(metric) if isinstance(row, dict) and isinstance(row.get("metrics"), dict) \
            else None
        m = cell.get("modality") if isinstance(cell, dict) else None
        if m in MODALITIES:
            found = m
    return found


def loop_row(state_dir, habit: dict, decision: str, decided_at: Optional[str], synced: Optional[dict] = None,
             now: Optional[float] = None) -> dict:
    """The loop row for habit.json's week and the person's decision (not written)."""
    week_of = str(habit.get("week_of"))
    p = _prediction.locked(state_dir, week_of)
    r = _prediction.receipt_for(state_dir, week_of) if p is not None else None
    rid = rule_of(habit)
    return {"kind": LOOP, "week_of": week_of, "habit": habit.get("habit"),
            "prediction": LOCKED_LABEL if p is not None else NO_PREDICTION,
            "outcome": r.get("verdict") if r is not None and isinstance(r.get("verdict"), str) else NO_OUTCOME,
            "outcome_modality": _outcome_modality(state_dir, p.get("metric")) if r is not None else None,
            "outcome_at": r.get("at") if r is not None else None,
            "rule": rid, "verdict": verdict(habit, rid, synced), "decision": decision, "decided_at": decided_at,
            "at": _prediction._now_iso(now)}


def record_loop(state_dir, habit: Optional[dict], decision: Any, decided_at: Optional[str],
                synced: Optional[dict] = None, now: Optional[float] = None) -> Optional[dict]:
    """Append the week's loop row after the person's Keep or Drop; the row, or None when nothing is written
    (no started week, no Keep or Drop, or the week already has its row)."""
    if jobs._week_start(habit) is None or decision not in jobs.DECISIONS:
        return None
    week_of = str(habit.get("week_of"))
    if any(r["week_of"] == week_of for r in loop_rows(state_dir)):
        return None
    row = loop_row(state_dir, habit, decision, decided_at, synced, now)
    _prediction._append(state_dir, row)
    return row
