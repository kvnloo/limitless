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

Fewer than three logged days never climb. A ``rung`` key in the claim is ignored. Pure: nothing here reads a
clock, a file or sends. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

from typing import Any

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
    return _out(None, "no evidence yet", "nothing measured, judged or cited")
