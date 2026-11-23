"""Explain back: one optional thirty-second offer after work lands, in a trough only.

After an agent's work lands (a done item in the work queue, overnight.py), the state card may carry one line:

    "Explain back: say what landed in one breath. Reply: Voice / Later"

``offer(landed_count, window, already_offered_today)`` is that line or "". It offers only when something landed
since the last offer, a trough job would deliver now (decision_window.decide for a ``trough`` job: never in a
peak, asleep, an unknown window, a focus block or focused mode, which callers apply with modes.apply), and it has
not been offered yet this wake day. The wake day is keyed on the wake event, never a clock time: an unknown
``already_offered_today`` counts as offered.

It is a suggestion: no score, no streak, no XP, no push of its own and no job. A skipped or Later offer is not
logged. Pure: nothing here reads a clock, a file or sends. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import math

from . import decision_window, jobs, one_tap

CHOICES = ("Voice", "Later")
ASK = "Explain back: say what landed in one breath."
OFFER = f"{ASK} {one_tap.choices_line(CHOICES)}"


def _count(n) -> int:
    if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or n != int(n):
        return 0
    return int(n)


def offer(landed_count, window, already_offered_today) -> str:
    """OFFER when ``landed_count`` (work landed since the last offer) is at least one, a trough job would deliver
    in ``window`` (a decision_window.WindowState, a window.py envelope or a ``{"cls"}`` dict) and
    ``already_offered_today`` is exactly False; else "". Pure."""
    if already_offered_today is not False or _count(landed_count) < 1:
        return ""
    if not isinstance(window, (decision_window.WindowState, dict)):
        return ""
    state, asleep = jobs._window(window)
    d = decision_window.decide("trough", state, budget_left=1, asleep=asleep)
    return OFFER if d.action == decision_window.DELIVER else ""
