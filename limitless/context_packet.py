"""The state card as one data-free context packet, so another long-horizon agent knows the person's state
without raw data.

    packet(state_dir, now, today) -> dict          # pure: reads what the card reads, writes nothing
    packet_path(env)                               # config "context_packet_path"; None (write nothing) by default
    write(p, path)                                 # atomic (temp file, fsync, rename), mode 0600

The shape (schema ``limitless.context/1``)::

    {"schema": "limitless.context/1", "generated_at": "<ISO UTC>",
     "rows": [{"key", "words", "modality", "evidence_tier", "age_words"}, ...],
     "window": "<words>", "asks": "<words>"}

It wraps card.build, the builder the pre_llm_call hook uses, and keeps only its T1 parts: one row per card item
(``items``: sleep, readiness, window, owner_message, habit_today, in that order), ``window`` from the window
item and ``asks`` from whether the card holds its "asks waiting on you" line. Nothing here reads a state file
itself, and a row takes only whitelisted fields of the item's envelope: never ``value`` when it holds a digit
(the owner item's value is a time; only its T1 label goes in), never ``raw``, never ``age_h`` (the age is in
words). The raw opt-in (LIMITLESS_RAW_IN_PROMPT) is ignored: the card is always built with raw off. No string
in the packet holds a digit except ``schema`` and ``generated_at``; a string that would is replaced by plain
words. No score, no count, no clock-time rule. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import os
import time
from datetime import date
from pathlib import Path
from typing import Mapping, Optional

from . import card, doctor, labeler as _labeler
from .state_reader import StateReader

SCHEMA = "limitless.context/1"
CONFIG_KEY = "context_packet_path"
ASKS_WAITING = "asks waiting on you"
NO_ASKS = "no asks on the card"
UNKNOWN = "unknown"
NO_WORDS = "known, but held back: no digit-free words for it"
AGE_UNKNOWN = "age unknown"
ROW_FIELDS = ("key", "words", "modality", "evidence_tier", "age_words")


def _clean(s) -> bool:
    return isinstance(s, str) and bool(s.strip()) and not any(c.isdigit() for c in s)


def _words(env: Mapping) -> str:
    """The item in words: its T1 label, else its value when that is digit-free text, else why it is unknown."""
    lab = env.get("label")
    word = lab.get("label") if isinstance(lab, Mapping) else None
    value = env.get("value")
    if value is not None and _clean(word):
        return word
    if _clean(value):
        return value
    if value is None:
        reason = env.get("reason")
        return f"{UNKNOWN}: {reason}" if _clean(reason) else UNKNOWN
    return NO_WORDS


def _word_or_none(v) -> Optional[str]:
    return v if _clean(v) else None


def _age_words(age_h) -> str:
    if isinstance(age_h, bool) or not isinstance(age_h, (int, float)) or age_h < 0:
        return AGE_UNKNOWN
    return doctor.age_words(float(age_h))


def row(key: str, env: Mapping) -> dict:
    """One packet row from one card item's envelope; whitelisted fields only, every string digit-free."""
    return {"key": key if _clean(key) else UNKNOWN, "words": _words(env),
            "modality": _word_or_none(env.get("modality")),
            "evidence_tier": _word_or_none(env.get("evidence_tier")) or "none",
            "age_words": _age_words(env.get("age_h"))}


def generated_at(now: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))


def packet(state_dir, now: float, today: date, env: Optional[Mapping[str, str]] = None) -> dict:
    """The context packet for ``now``/``today`` from card.build's T1 parts (raw always off). Writes nothing."""
    e = os.environ if env is None else env
    c = card.build(StateReader(Path(state_dir)), now, today, raw=False, labeler=_labeler.from_config(e), env=e)
    items = c["items"]
    win = items.get("window") or {}
    return {"schema": SCHEMA, "generated_at": generated_at(now),
            "rows": [row(k, v) for k, v in items.items() if isinstance(v, Mapping)],
            "window": _word_or_none(win.get("value")) or UNKNOWN,
            "asks": ASKS_WAITING if ASKS_WAITING in c["lines"] else NO_ASKS}
