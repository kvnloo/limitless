"""One tap or one spoken word: every message that asks the person something ends in a fixed choices line.

L14: typed prompts got no answers; asks that took one tap or one spoken word did. So an ask offers two to
four one-word replies on one plain last line, and a reply is read back whole:

    choices_line(("Done", "No", "Skip"))     -> "Reply: Done / No / Skip"
    parse("done.", ("Done", "No", "Skip"))   -> "Done"      (a voice transcript counts)
    parse("done for today", ...)             -> None        (not a tap: the ask stays unanswered)
    choices_of("Reply: Keep / Drop")         -> ("Keep", "Drop")
    asks(body)                               -> True when a line has a "?", asks for a reply in words or
                                                is a choices line
    is_one_tap(body)                         -> False when the body asks but its last line (before any
                                                "Why now" line) is not a choices line

An option is one word of letters only: no digits, no card ids, no spaces or punctuation, and no two
options alike in any case. ``parse`` takes the whole message, case-insensitive, with surrounding spaces,
trailing punctuation and at most one trailing emoji ignored; it returns the option as offered. Anything
else is None, never a No. Pure: nothing here sends, reads a clock or touches a file. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable, List, Optional, Tuple

from .send_gate import WHY_PREFIX

PREFIX, SEP = "Reply: ", " / "
MIN_OPTIONS, MAX_OPTIONS = 2, 4
YES_NO_LATER = ("Yes", "No", "Later")
# A line asks for input when it has a question mark or one of these words (whole words, any case).
_ASKS_INPUT = re.compile(r"(?i)\b(reply|replies|answer|respond|tell me|let me know)\b")
_MODIFIERS = {"\ufe0f", "\ufe0e", "\u200d", "\u20e3"} | {chr(c) for c in range(0x1F3FB, 0x1F400)}


def _word_ok(w) -> bool:
    return isinstance(w, str) and w.isalpha() and w.isascii()


def options_ok(options) -> bool:
    """True for 2-4 one-word, letters-only options, no two alike in any case."""
    try:
        opts = tuple(options)
    except TypeError:
        return False
    return (MIN_OPTIONS <= len(opts) <= MAX_OPTIONS and all(_word_ok(o) for o in opts)
            and len({o.lower() for o in opts}) == len(opts))


def choices_line(options: Iterable[str]) -> str:
    """``Reply: A / B / C``: the one plain line an ask ends with. ValueError for options that are not
    2-4 single letter-only words (no digits, no card ids), or that repeat."""
    opts = tuple(options) if not isinstance(options, str) else (options,)
    if not options_ok(opts):
        raise ValueError(f"choices must be {MIN_OPTIONS}-{MAX_OPTIONS} different one-word options, got {opts!r}")
    return PREFIX + SEP.join(opts)


def choices_of(line) -> Optional[Tuple[str, ...]]:
    """The options of a choices line (as choices_line writes it); None for any other line."""
    if not isinstance(line, str) or not line.startswith(PREFIX) or "\n" in line.strip():
        return None
    opts = tuple(o.strip() for o in line.strip()[len(PREFIX):].split("/"))
    return opts if options_ok(opts) else None


def _strip_tail(w: str) -> str:
    while w and (w[-1].isspace() or unicodedata.category(w[-1]).startswith("P")):
        w = w[:-1]
    return w


def _strip_one_emoji(w: str) -> str:
    while w and w[-1] in _MODIFIERS:
        w = w[:-1]
    if w and unicodedata.category(w[-1]) in ("So", "Sk"):
        w = w[:-1]
        while w and w[-1] in _MODIFIERS:
            w = w[:-1]
    return w


def parse(text, options: Iterable[str]) -> Optional[str]:
    """The option the whole reply names (as offered), or None. Case-insensitive; surrounding spaces,
    trailing punctuation and one trailing emoji are ignored, so a voice transcript like "done." counts."""
    if not isinstance(text, str):
        return None
    word = _strip_tail(_strip_one_emoji(_strip_tail(text.strip()))).strip()
    if not _word_ok(word):
        return None
    for o in options or ():
        if isinstance(o, str) and o.lower() == word.lower():
            return o
    return None


def _lines(body) -> List[str]:
    """The body's non-blank lines without the trailing "Why now" line(s) send_gate.outgoing adds."""
    lines = [ln.strip() for ln in (body if isinstance(body, str) else "").splitlines() if ln.strip()]
    while lines and lines[-1].startswith(WHY_PREFIX):
        lines.pop()
    return lines


def asks(body) -> bool:
    """True when the body asks the person something: it has a choices line, or a line (other than the why-now
    line) with a question mark or one that asks for input in words (reply, answer, respond, tell me, let me
    know)."""
    return any(choices_of(ln) is not None or "?" in ln or _ASKS_INPUT.search(ln) for ln in _lines(body))


def is_one_tap(body) -> bool:
    """True when the body asks nothing, or asks and its last line (before any why-now line) is a choices
    line of 2-4 one-word options. Pure: a check, never a rewrite."""
    if not asks(body):
        return True
    lines = _lines(body)
    return bool(lines) and choices_of(lines[-1]) is not None
