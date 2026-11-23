"""Explain back: one optional thirty-second offer after work lands, in a trough only.

After an agent's work lands (a done item in the work queue, overnight.py), the state card may carry one line:

    "Explain back: say what landed in one breath. Reply: Voice / Later"

``offer(landed_count, window, already_offered_today)`` is that line or "". It offers only when something landed
since the last offer, a trough job would deliver now (decision_window.decide for a ``trough`` job: never in a
peak, asleep, an unknown window, a focus block or focused mode, which callers apply with modes.apply), and it has
not been offered yet this wake day. The wake day is keyed on the wake event, never a clock time: an unknown
``already_offered_today`` counts as offered.

On the card (card.py): ``for_turn`` gives the line for this pre_llm_call turn and the hook adds it on a line of
its own after the card (outside MAX_LINES, like the mode line, so its Reply choices stay whole), before
tier_audit.gate. Landed = done items in the work queue (overnight.counts: file names and mtimes only) whose mtime
is after the last offer, or after overnight.since (last night's wind-down) when there was none. Once the gate let
the card through, ``mark`` writes ``explain-back.json`` in the state dir, ``{"wake_at", "offered_at"}`` (epoch
seconds, mode 0600, never any text): the wake event it was offered for, so the rest of that wake day carries
nothing. No wake seen (or one older than window.MAX_AWAKE_H) is unknown: no offer.

The reply (``reply``): Later, or a bare Voice tap, records nothing. Any other text (the spoken answer as a
transcript, or typed) is saved through capture.capture as ``kind: "explain_back"``, verbatim, so it lands in the
one idea ledger when one is set. ``unknowns`` holds only the person's own "I could not explain X" phrases,
verbatim; nothing else is derived. The answer is never graded and nothing here asks a follow-up.

It is a suggestion: no score, no streak, no XP, no push of its own and no job. A skipped or Later offer is not
logged. ``offer`` is pure; only ``mark`` and ``reply`` write. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Mapping, Optional

from . import capture, decision_window, jobs, one_tap
from . import overnight as _overnight
from .envelope import missing
from .window import MAX_AWAKE_H

CHOICES = ("Voice", "Later")
ASK = "Explain back: say what landed in one breath."
OFFER = f"{ASK} {one_tap.choices_line(CHOICES)}"
MARK_FILE = "explain-back.json"


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


# --- this turn, from the state dir ----------------------------------------------------------------------------

def _num(v) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def wake_at(events: Optional[list], now: float) -> Optional[float]:
    """The latest wake event at or before ``now`` (jobs.wake_times), or None when there is none or it is older
    than MAX_AWAKE_H (missing data, not a long day)."""
    wakes = jobs.wake_times(list(events or ()), now)
    w = wakes[-1] if wakes else None
    return None if w is None or now - w > MAX_AWAKE_H * 3600 else float(w)


def load_mark(state_dir) -> Optional[dict]:
    """``{"wake_at", "offered_at"}`` from explain-back.json, or None (missing, unreadable or malformed)."""
    try:
        data = json.loads((Path(state_dir) / MARK_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    w, o = _num(data.get("wake_at")), _num(data.get("offered_at"))
    return None if w is None or o is None else {"wake_at": w, "offered_at": o}


def mark(state_dir, wake: float, now: float) -> bool:
    """Write explain-back.json for ``wake`` (atomic, 0600). True when written; never raises."""
    try:
        d = Path(state_dir)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".explain-back.", suffix=".tmp")
        try:
            os.write(fd, json.dumps({"wake_at": float(wake), "offered_at": float(now)}).encode("utf-8"))
        finally:
            os.close(fd)
        os.chmod(tmp, 0o600)
        os.replace(tmp, d / MARK_FILE)
        return True
    except Exception:  # noqa: BLE001 - a failed mark must not break the turn
        return False


def _events(reader, env, home) -> list:
    from . import jobs_runner   # jobs_runner imports overnight: import at call time
    return jobs_runner.events(reader, env=env, home=home)


def for_turn(reader, now: float, window, env: Optional[Mapping[str, str]] = None,
             home: Optional[Path] = None) -> tuple:
    """``(line, wake)`` for this turn: offer() over the work landed since the last offer (or since
    overnight.since when there was none), ``window`` (focused mode and the Glide block already applied by the
    caller) and whether ``wake`` already had its offer. ``("", None)`` when no wake is seen."""
    evs = _events(reader, env, home)
    wake = wake_at(evs, now)
    if wake is None:
        return "", None
    m = load_mark(reader.path)
    since = m["offered_at"] if m is not None else _overnight.since(evs, now)
    c = _overnight.counts(_overnight.items_for(reader, env, home), since)
    landed = 0 if c is None else c["done_since"]
    already = m is not None and m["wake_at"] == wake
    return offer(landed, window, already), wake


# --- the reply ------------------------------------------------------------------------------------------------

KIND = "explain_back"
SOURCE = "explain_back"
_UNKNOWN = re.compile(r"(?i)\bI (?:could not|couldn['\u2019]t) explain\b[^.!?\n]*[.!?]?")
LATER = "Later: nothing recorded (a skipped explain-back is not logged)"
VOICE = "Voice: nothing recorded until the spoken answer arrives as text"


def unknowns(text) -> list:
    """Every "I could not explain X" (or "I couldn't explain X") phrase in ``text``, verbatim, up to the end of
    its sentence. Nothing else is derived; [] for anything else."""
    if not isinstance(text, str):
        return []
    return [m.group(0).strip() for m in _UNKNOWN.finditer(text)]


def reply(state_dir, text, now: float) -> dict:
    """Save an explain-back answer through capture.capture as kind ``explain_back`` (with ``unknowns`` when the
    person said "I could not explain X"). The one-tap Later, or a bare Voice tap, records nothing. The answer is
    never graded and nothing follows up: the result is capture's envelope, which never echoes the text."""
    tap = one_tap.parse(text, CHOICES)
    if tap == "Later":
        return missing(LATER)
    if tap == "Voice":
        return missing(VOICE)
    return capture.capture(state_dir, text, now, source=SOURCE, kind=KIND, unknowns=unknowns(text))
