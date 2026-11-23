"""Asks: every needs-the-person ask carries a window class; at most one decision per peak window.

An ask is one row of a host's queue of things that need the person (an approval, a decision, an FYI).
This module is the adapter between that queue and the decision window; it never rebuilds the queue.

``classify(ask)`` reads the ask's own fields, never the clock:

- ``kind: decision``, or ``kind: approval`` with ``effort: deep`` -> ``peak``;
- ``kind: approval`` with ``effort: light`` (or no effort) -> ``anytime``;
- ``kind: fyi`` -> ``trough``;
- anything else -> ``anytime``: an ask with an unknown kind is never dropped.

Stdlib only, Python 3.9+.
"""
from __future__ import annotations

from typing import Any

PEAK, TROUGH, ANYTIME = "peak", "trough", "anytime"


def _word(v: Any) -> str:
    return v.strip().lower() if isinstance(v, str) else ""


def classify(ask: Any) -> str:
    """peak | trough | anytime from the ask's ``kind`` and ``effort``."""
    if not isinstance(ask, dict):
        return ANYTIME
    kind, effort = _word(ask.get("kind")), _word(ask.get("effort"))
    if kind == "decision" or (kind == "approval" and effort == "deep"):
        return PEAK
    if kind == "fyi":
        return TROUGH
    return ANYTIME
