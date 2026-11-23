"""How strong a claim is, on the person's evidential-strength ladder, in words.

    strength.LADDER -> ("measured", "derived", "association", "preregistered", "repeated", "replicated")
    strength.strength_of({"readings": 1})              -> {"rung": "measured", "words": ..., "why": ...}

The envelope (envelope.py) labels how a value was obtained. This labels how strong a claim is ("this habit
helps my sleep"), weakest rung first. It never changes an envelope's four fields; it is an extra word beside
them. No score and no number: ``words`` and ``why`` have no digit. Pure: nothing here reads a clock, a file
or sends. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

from typing import Any

LADDER = ("measured", "derived", "association", "preregistered", "repeated", "replicated")
MEASURED, DERIVED, ASSOCIATION, PREREGISTERED, REPEATED, REPLICATED = LADDER


def _out(rung, words: str, why: str) -> dict:
    return {"rung": rung, "words": words if rung is None else f"{rung}: {words}", "why": why}


def _count(v: Any) -> int:
    return v if type(v) is int and v > 0 else 0


def strength_of(claim: Any) -> dict:
    """``{rung, words, why}`` for a small claim dict; rung None when there is nothing to stand on."""
    c = claim if isinstance(claim, dict) else {}
    readings = _count(c.get("readings"))
    if readings and c.get("computed") is True:
        return _out(DERIVED, "computed from readings", "a value worked out from readings, not one reading")
    if readings:
        return _out(MEASURED, "one reading", "a single reading, nothing more")
    return _out(None, "no evidence yet", "nothing measured, judged or cited")
