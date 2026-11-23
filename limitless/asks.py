"""Asks: every needs-the-person ask carries a window class; at most one decision per peak window.

An ask is one row of a host's queue of things that need the person (an approval, a decision, an FYI).
This module is the adapter between that queue and the decision window; it never rebuilds the queue.

``classify(ask)`` reads the ask's own fields, never the clock:

- ``kind: decision``, or ``kind: approval`` with ``effort: deep`` -> ``peak``;
- ``kind: approval`` with ``effort: light`` (or no effort) -> ``anytime``;
- ``kind: fyi`` -> ``trough``;
- anything else -> ``anytime``: an ask with an unknown kind is never dropped.

``plan(asks, window, sent_this_window)`` says what happens to each ask now, as
``(ask_id, action, reason)`` with action deliver | hold | fold, in queue order:

- ``urgent: true`` delivers whatever the window and never counts against the peak limit;
- a focus block (a provider with ``hold_asks``, e.g. Glide) holds everything else until it ends;
- ``trough`` (an FYI) folds into the next brief line;
- asleep holds the rest until wake;
- ``anytime`` delivers, which means: it passes to the send gate (dedupe, daily cap);
- ``peak`` delivers in a peak window, at most ONE per window, oldest first, and only when
  ``sent_this_window`` is zero; every other peak ask holds for the next peak window.

The window comes from the decision-window chain (``window_chain.first_known``), a
``decision_window.WindowState`` or a ``window.py`` envelope; nothing here reads a clock.

Stdlib only, Python 3.9+.
"""
from __future__ import annotations

from typing import Any, Iterable, List, Optional, Tuple

from . import decision_window, jobs
from .state_reader import parse_ts

PEAK, TROUGH, ANYTIME = "peak", "trough", "anytime"
DELIVER, HOLD, FOLD = "deliver", "hold", "fold"
ACTIONS = (DELIVER, HOLD, FOLD)

Row = Tuple[Any, str, str]


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


def _open_peak(state) -> bool:
    return (state is not None and state.cls == PEAK and state.confidence >= decision_window.MIN_CONFIDENCE)


def _count(sent: Any) -> int:
    if isinstance(sent, bool):
        return int(sent)
    if isinstance(sent, (int, float)):
        return max(0, int(sent))
    try:
        return len(sent)  # a list of the asks already delivered in this window
    except TypeError:
        return 0


def _age_order(rows: list) -> list:
    """Indexes of rows, oldest ``at`` first; undated rows last, in queue order."""
    def k(i):
        t = parse_ts(rows[i].get("at")) if isinstance(rows[i], dict) else None
        return (t is None, t if t is not None else 0.0, i)
    return sorted(range(len(rows)), key=k)


def _why_not_peak(state) -> str:
    if state is None or state.cls not in decision_window.WINDOW_CLASSES \
            or state.confidence < decision_window.MIN_CONFIDENCE:
        return "decision held: the window is unknown; waits for a peak window"
    return f"decision held: a {state.cls} window is open; waits for a peak window"


def _decide(ask: Any, cls: str, state, asleep: bool, peak_free: bool) -> Tuple[str, str]:
    if isinstance(ask, dict) and ask.get("urgent") is True:
        return DELIVER, "urgent: delivers whatever the window"
    if state is not None and state.hold_asks:
        return HOLD, "focus block running: holds until it ends"
    if cls == TROUGH:
        return FOLD, "for your information: folds into the next brief line"
    if asleep:
        return HOLD, "asleep: holds until wake"
    if cls == ANYTIME:
        return DELIVER, "anytime ask: passes to the send gate"
    if not _open_peak(state):
        return HOLD, _why_not_peak(state)
    if not peak_free:
        return HOLD, "decision held: one decision per peak window; waits for the next peak window"
    return DELIVER, "peak window open: the one decision for this window"


def plan(asks: Optional[Iterable], window: Any, sent_this_window: Any = 0) -> List[Row]:
    """One (ask_id, deliver | hold | fold, reason) per ask, in queue order. Pure: sends nothing."""
    rows = list(asks or ())
    state, asleep = jobs._window(window)
    peak_free = _count(sent_this_window) == 0
    out = {}
    for i in _age_order(rows):
        ask = rows[i]
        cls = classify(ask)
        action, why = _decide(ask, cls, state, asleep, peak_free)
        if action == DELIVER and cls == PEAK and not (isinstance(ask, dict) and ask.get("urgent") is True):
            peak_free = False
        out[i] = (ask.get("id") if isinstance(ask, dict) else None, action, why)
    return [out[i] for i in range(len(rows))]
