"""Bedtime capture: after wind-down or while asleep, an owner message is saved for tomorrow, not started.

    route(text, window_class, opt_out) -> {"action": "capture" | "pass", "reply": str | None}

Capture applies only when the window from state (window_chain: Glide's wind-down nudge, Sleep mode) is
``asleep`` or ``wind_down``; it never reads a clock time. A slash command, a message with an urgent word
(config ``bedtime_urgent_words``, default ``["urgent", "now"]``, whole words, any case) and a bare habit
or week answer (Done, No, Skip, Keep, Drop: their own jobs read those) pass to the agent as usual.
Config ``bedtime_capture``: ``"on"`` turns it on; anything else (the default) is off.
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import re
from typing import Iterable, Mapping, Optional

from . import habit_replies

CAPTURE_CLASSES = ("asleep", "wind_down")
DEFAULT_URGENT_WORDS = ("urgent", "now")
REPLY = "Saved for tomorrow."
CONFIG_KEY, WORDS_KEY = "bedtime_capture", "bedtime_urgent_words"
CAPTURE, PASS = "capture", "pass"


def enabled(cfg: Mapping) -> bool:
    """True only when config says ``"bedtime_capture": "on"``."""
    return isinstance(cfg, Mapping) and cfg.get(CONFIG_KEY) == "on"


def urgent_words(cfg: Mapping) -> list:
    """The configured urgent words (a list of strings, lower-cased), else the default."""
    v = cfg.get(WORDS_KEY) if isinstance(cfg, Mapping) else None
    if not isinstance(v, list):
        return list(DEFAULT_URGENT_WORDS)
    return [w.strip().lower() for w in v if isinstance(w, str) and w.strip()]


def _urgent(text: str, words: Iterable[str]) -> bool:
    low = text.lower()
    return any(re.search(r"(?<!\w)" + re.escape(w.lower()) + r"(?!\w)", low) for w in words if w)


def _pass() -> dict:
    return {"action": PASS, "reply": None}


def route(message_text, window_class: Optional[str], opt_out: bool,
          urgent_words: Iterable[str] = DEFAULT_URGENT_WORDS) -> dict:
    """Capture or pass one inbound message. ``opt_out`` True (bedtime capture off) always passes."""
    if opt_out or window_class not in CAPTURE_CLASSES:
        return _pass()
    if not isinstance(message_text, str) or not message_text.strip():
        return _pass()
    text = message_text.strip()
    if text.startswith("/") or _urgent(text, urgent_words):
        return _pass()
    if len(text.split()) == 1 and (habit_replies.tap(text) or habit_replies.decision(text)):
        return _pass()
    return {"action": CAPTURE, "reply": REPLY}
