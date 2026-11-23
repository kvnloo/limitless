"""The work-app and feed-app lists, set from one reply: ``work apps: A, B`` / ``feed apps: C, D``.

    got = parse(text)        # {"work_apps": (...), "feed_apps": (...)} for the lists named, or None

A whole message is read. Its first non-empty line must start with ``work apps:`` or ``feed apps:`` (any
case, loose spacing); names follow on that line and the next ones, comma or newline separated, trimmed and
de-duplicated (case-insensitively, the first spelling kept), until a line that starts the other list. Both
lists may be in one message. ``none`` alone clears a list. A list with no name, more than MAX_NAMES names or
a name longer than MAX_LEN characters, the same list twice, or any text before the first prefix makes the
whole message not a command: it changes nothing. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

WORK, FEED = "work_apps", "feed_apps"
MAX_NAMES, MAX_LEN = 20, 60
CLEAR = "none"
_PREFIX = re.compile(r"^\s*(work|feed)\s+apps\s*:(.*)$", re.IGNORECASE | re.DOTALL)
_KEYS = {"work": WORK, "feed": FEED}


def clean(items: Iterable) -> tuple:
    """Trimmed, non-empty strings, de-duplicated case-insensitively in first-seen order."""
    out, seen = [], set()
    for v in items or ():
        w = v.strip() if isinstance(v, str) else ""
        if w and w.casefold() not in seen:
            seen.add(w.casefold())
            out.append(w)
    return tuple(out)


def _names(parts: list) -> Optional[tuple]:
    names = clean(p for chunk in parts for p in chunk.split(","))
    if not names:
        return None
    if len(names) == 1 and names[0].casefold() == CLEAR:
        return ()
    if len(names) > MAX_NAMES or any(len(n) > MAX_LEN for n in names):
        return None
    return names


def parse(text) -> Optional[dict]:
    """``{list key: names}`` for each list a whole message sets (``()`` clears), or None for anything else."""
    if not isinstance(text, str):
        return None
    lists, key = {}, None
    for line in text.splitlines():
        m = _PREFIX.match(line)
        if m:
            key = _KEYS[m.group(1).lower()]
            if key in lists:
                return None
            lists[key] = [m.group(2)]
        elif key is not None:
            lists[key].append(line)
        elif line.strip():
            return None
    if not lists:
        return None
    out = {}
    for k, parts in lists.items():
        names = _names(parts)
        if names is None:
            return None
        out[k] = names
    return out
