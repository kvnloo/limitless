"""Memory palace: one optional, trough-only offer of a short walk in the person's own memory-palace app.

The plugin never rebuilds the app: it only offers its link. Config ``palace_link`` (a deep link or URL such as
``palace://example``; unset by default) and ``palace_label`` (default "memory palace"). Unset is off,
everywhere, with the one reason NO_LINK. A link rides in a line the person reads, so it is checked as the
breathing link is (wind_down.breathing_link: a scheme, ``://``, printable ASCII, no space, no digit).

The offer (``offer(state, cfg)``) is the one line "A short memory palace walk fits now. <link>", or None.
``state`` is a dict of what this turn already knows:

- ``window``: a decision_window.WindowState, a window.py envelope or a ``{"cls"}`` dict, focused mode already
  applied (modes.apply). The checks are the ones anki.offer uses, called, not copied: decision_window.decide
  for a ``trough`` job (so never asleep, in a focus block, a peak, an unknown window or any other window);
- ``muted``: quiet.check's held flag (pushes muted: quiet, quiet tonight or snoozed);
- ``anki_offered``: the Anki trough offer is on this turn's card (one learning offer per trough);
- ``offered_today``: a palace offer was already made for this wake event (the mark file).

Every flag must be exactly False to offer: an unknown is treated as muted, offered or not clear, so an unknown
never offers. ``status`` gives the word and the plain reason; ``words`` the one phrase the tool shows ("off",
"fits now" or "not now: <reason>"). Digit-free and no clock time: the wake day is keyed on the wake event.
It is a suggestion: no score, no streak, no count of walks, no push of its own and no job. Pure: reads no
clock and no file. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

from typing import Mapping, Optional

from . import decision_window, jobs
from . import wind_down as _wind_down

LINK_KEY, LABEL_KEY = "palace_link", "palace_label"
DEFAULT_LABEL = "memory palace"
MAX_LABEL_CHARS = 40
NO_LINK = "no memory palace link set"
OFF, FITS, NOT_NOW = "off", "fits now", "not now"
MUTED = "pushes are muted (or quiet could not be read), so this waits until quiet ends"
ANKI = "an Anki review was offered in this trough, and one learning offer per trough is enough"
TODAY = "already offered since you woke (or it is not clear when you woke), so not again until the next wake"


def link(cfg) -> Optional[str]:
    """The configured link (spaces around it dropped), or None: unset (the default) or not a link that may ride in
    a digit-free line. The check is wind_down.breathing_link's, called, not copied."""
    v = cfg.get(LINK_KEY) if isinstance(cfg, Mapping) else None
    return _wind_down.breathing_link({_wind_down.BREATHING_KEY: v})


def label(cfg) -> str:
    """``palace_label`` when it is short, printable and digit-free; else DEFAULT_LABEL."""
    v = cfg.get(LABEL_KEY) if isinstance(cfg, Mapping) else None
    if not isinstance(v, str):
        return DEFAULT_LABEL
    v = v.strip()
    if not v or len(v) > MAX_LABEL_CHARS or not v.isprintable() or any(c.isdigit() for c in v):
        return DEFAULT_LABEL
    return v


def line(cfg) -> Optional[str]:
    """"A short <label> walk fits now. <link>", or None with no link."""
    lk = link(cfg)
    return None if lk is None else f"A short {label(cfg)} walk fits now. {lk}"


def _window_reason(window) -> Optional[str]:
    """None when a trough job would deliver in ``window`` (decision_window.decide, as anki.offer asks it), else
    decide's reason in plain words (decision_window.plain)."""
    if not isinstance(window, (decision_window.WindowState, dict)):
        window = None
    state, asleep = jobs._window(window)
    d = decision_window.decide("trough", state, budget_left=1, asleep=asleep)
    return None if d.action == decision_window.DELIVER else decision_window.plain(d.reason)


def status(state, cfg) -> tuple:
    """``(word, reason)``: (OFF, NO_LINK) with no link; (FITS, None) when the offer fits now; else
    (NOT_NOW, the first reason in plain words: the window, quiet, the Anki offer, the wake day)."""
    if link(cfg) is None:
        return OFF, NO_LINK
    state = state if isinstance(state, Mapping) else {}
    why = _window_reason(state.get("window"))
    if why is not None:
        return NOT_NOW, why
    for key, reason in (("muted", MUTED), ("anki_offered", ANKI), ("offered_today", TODAY)):
        if state.get(key) is not False:
            return NOT_NOW, reason
    return FITS, None


def words(state, cfg) -> str:
    """"off", "fits now" or "not now: <reason>": the one phrase limitless_palace shows."""
    word, why = status(state, cfg)
    return f"{NOT_NOW}: {why}" if word == NOT_NOW else word


def offer(state, cfg) -> Optional[str]:
    """The one offer line (``line``) when status says it fits now; else None. Pure."""
    return line(cfg) if status(state, cfg)[0] == FITS else None
