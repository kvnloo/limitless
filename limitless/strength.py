"""How strong a claim is, on the person's evidential-strength ladder, in words.

    strength.LADDER -> ("measured", "derived", "association", "preregistered", "repeated", "replicated")
    strength.strength_of({"readings": 1})              -> {"rung": "measured", "words": ..., "why": ...}

The envelope (envelope.py) labels how a value was obtained. This labels how strong a claim is ("this habit
helps my sleep"), weakest rung first. It never changes an envelope's four fields; it is an extra word beside
them. No score and no number: ``words`` and ``why`` have no digit.

A claim is a small dict; every key is optional and anything unreadable counts as absent:

    readings   whole number: readings the claim stands on (one or more: measured)
    computed   True: the value was worked out from those readings (derived)
    days       whole number: days the habit and the outcome were both logged, no prediction locked
               (three or more: association)
    weeks      [{week_of, locked, verdict, logged_days}]: habit weeks with a locked prediction and the
               verdict of its outcome receipt (prediction.py). A locked week whose receipt ``supports`` it,
               with at least three logged days, counts; one such week is preregistered, two or more separate
               weeks (distinct week_of) are repeated. Contradicts, inconclusive, pending or anything else
               never climbs.
    citation   non-empty text: an outside source for the claim (replicated). Only this key reaches
               replicated; the person's own data never does, however many weeks supported it.

Fewer than three logged days never climb. A ``rung`` key in the claim is ignored. ``strength_of`` is pure.

    strength.habit_claim(state_dir, "Walk after lunch")    -> {"weeks": [...]}   (the claim, from the ledger)
    strength.habit_strength(state_dir, "Walk after lunch") -> strength_of(habit_claim(...))

read the habit's weeks from the existing prediction ledger (predictions.jsonl, prediction.rows), read-only:
each first prediction row of a week is a locked week, its receipt (prediction.receipt_for) gives the verdict
(``pending`` with none yet), and the week belongs to the habit that habit-<week_of>.json or habit.json
(prediction.week_habit) or that week's loop row names, compared without case or outer spaces. With no habit
name, only ``week_of``'s own week counts. A logged-days receipt's outcome gives its logged days; a state-metric
receipt was only judged with three logged days (prediction._state_verdict), so its verdict stands for them.
The ledger never carries a citation: replicated is never reached from it. Nothing here writes, sends or reads
a clock. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from . import prediction as _prediction

LADDER = ("measured", "derived", "association", "preregistered", "repeated", "replicated")
MEASURED, DERIVED, ASSOCIATION, PREREGISTERED, REPEATED, REPLICATED = LADDER
MIN_DAYS = 3                   # the receipts' own floor (prediction.MIN_DAYS): fewer logged days never climb
SUPPORTS = "supports"
DID_NOT = ("contradicts", "inconclusive")
_NUMBER_WORDS = ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")


def _n(k: int) -> str:
    return _NUMBER_WORDS[k - 1] if 0 < k <= len(_NUMBER_WORDS) else "more than ten"


def _weeks(k: int) -> str:
    return f"{_n(k)} locked week" + ("" if k == 1 else "s")


def _out(rung, words: str, why: str) -> dict:
    return {"rung": rung, "words": words if rung is None else f"{rung}: {words}", "why": why}


def _count(v: Any) -> int:
    return v if type(v) is int and v > 0 else 0


def _judged(weeks: Any):
    """(distinct supported locked weeks with enough logged days, distinct locked weeks that did not)."""
    good, bad = set(), set()
    for w in weeks if isinstance(weeks, (list, tuple)) else ():
        if not isinstance(w, dict) or w.get("locked") is not True or not isinstance(w.get("week_of"), str):
            continue
        if w.get("verdict") == SUPPORTS and _count(w.get("logged_days")) >= MIN_DAYS:
            good.add(w["week_of"])
        elif w.get("verdict") in DID_NOT:
            bad.add(w["week_of"])
    return good, bad - good


def strength_of(claim: Any) -> dict:
    """``{rung, words, why}`` for a small claim dict (see the module doc); rung None when there is nothing to
    stand on. The highest rung the claim reaches wins; words and why are digit-free."""
    c = claim if isinstance(claim, dict) else {}
    cite = c.get("citation")
    if isinstance(cite, str) and cite.strip():
        return _out(REPLICATED, "an outside source is cited for it",
                    "an outside source was cited; the person's own data never reaches this rung")
    good, bad = _judged(c.get("weeks"))
    tail = f", {_weeks(len(bad))} did not" if bad else ""
    if len(good) >= 2:
        return _out(REPEATED, f"{_weeks(len(good))} supported it{tail}",
                    "the same habit's locked prediction was supported in separate weeks")
    if good:
        return _out(PREREGISTERED, f"one locked week supported it{tail}",
                    "a prediction locked before the week, and its outcome receipt supported it")
    days = _count(c.get("days"))
    if days >= MIN_DAYS:
        words = "seen together across days; the locked weeks did not bear it out" if bad \
            else "seen together across days, no locked prediction yet"
        return _out(ASSOCIATION, words, "co-occurrence across logged days, without a prediction that held")
    readings = _count(c.get("readings"))
    if readings and c.get("computed") is True:
        return _out(DERIVED, "computed from readings", "a value worked out from readings, not one reading")
    if readings:
        return _out(MEASURED, "read directly", "a reading as it was taken, nothing worked out or judged")
    if bad:
        return _out(None, f"no rung yet: {_weeks(len(bad))} did not bear it out",
                    "a locked week that did not support it never climbs")
    return _out(None, "no evidence yet", "nothing measured, judged or cited")


_LOGGED_OUTCOME = re.compile(r"^\d+ of (\d+) logged days$")


def _name(v: Any) -> Optional[str]:
    return " ".join(v.split()).casefold() if isinstance(v, str) and v.strip() else None


def _week_name(state_dir, week_of: str, loops: dict) -> Optional[str]:
    start = _prediction._day(week_of)
    h = _prediction.week_habit(state_dir, start) if start is not None else None
    return _name(h.get("habit")) if isinstance(h, dict) and _name(h.get("habit")) else loops.get(week_of)


def _logged_days(p: dict, r: Optional[dict]) -> int:
    if not isinstance(r, dict):
        return 0
    m = _LOGGED_OUTCOME.match(str(r.get("outcome") or ""))
    if p.get("metric") == _prediction.LOGGED:
        return int(m.group(1)) if m else 0
    return MIN_DAYS if r.get("verdict") == SUPPORTS else 0


def habit_claim(state_dir, habit: Optional[str], week_of: Optional[str] = None) -> dict:
    """``{"weeks": [{week_of, locked, verdict, logged_days}]}`` for ``habit`` from the prediction ledger, oldest
    first (see the module doc); with no habit name, only ``week_of``'s week. Read-only."""
    rows = _prediction.rows(state_dir)
    loops = {}
    for r in rows:
        if r.get("kind") == "loop" and isinstance(r.get("week_of"), str) and r["week_of"] not in loops:
            loops[r["week_of"]] = _name(r.get("habit"))
    want, seen, weeks = _name(habit), set(), []
    for p in rows:
        w = p.get("week_of")
        if p.get("kind") != "prediction" or not isinstance(w, str) or w in seen:
            continue
        seen.add(w)
        mine = w == week_of if want is None else _week_name(state_dir, w, loops) == want
        if not mine:
            continue
        r = _prediction.receipt_for(state_dir, w)
        verdict = r.get("verdict") if isinstance(r, dict) and isinstance(r.get("verdict"), str) else \
            (_prediction.PENDING if r is None else _prediction.INCONCLUSIVE)
        weeks.append({"week_of": w, "locked": True, "verdict": verdict, "logged_days": _logged_days(p, r)})
    return {"weeks": weeks}


def habit_strength(state_dir, habit: Optional[str], week_of: Optional[str] = None) -> dict:
    """strength_of(habit_claim(...)): the habit's rung from its locked weeks, in words. Read-only."""
    return strength_of(habit_claim(state_dir, habit, week_of))
