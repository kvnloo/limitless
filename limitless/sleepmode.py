"""Phone Sleep mode as the poller records it, read-only: sleepmode.jsonl and its poll heartbeat.

    p = path(state_dir, env)          # $LIMITLESS_SLEEPMODE, else <state dir>/sleepmode.jsonl (kevin-push's rule)
    got = read(p)                     # [(epoch, row)] oldest first; None when the file is missing or unreadable
    poll_fresh(p, now)                # kevin-push's own test for "the poll is fresh" (else it fails open: awake)

The rows (one per change the poller saw): ``{"at": ISO-8601 or epoch, "on": bool}``. Newer pollers add ``"rule"``
(the phone Sleep rule's id) on an on-row and, when a rule was left on far longer than a night and the owner is
then seen up, close it with an inferred off row ``{"on": false, "inferred": "Sleep left on, owner up",
"left_on": "<rule id>"}`` and ignore that rule after. Old rows without ``rule`` or ``left_on`` read the same as
before. A line that is not JSON, not an object, has no time or no boolean ``on`` is skipped.

An activation is a run of on-rows from the first on after an off (or the start of the file) up to the next off
row, its close. NIGHT_H is how long one night keeps Sleep mode on at most: on longer,
with no close, is a rule left on that the poller has not closed yet. kevin-push holds every non-critical push
while the last row says on and the poll is fresh (POLL_FRESH_S, kevin-push's asleep()). Stdlib only; no clock:
every caller passes ``now``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping, Optional

from .state_reader import parse_ts

ENV_KEY = "LIMITLESS_SLEEPMODE"   # bin/kevin-push's override of the file
FILE, POLL_FILE = "sleepmode.jsonl", "sleepmode-poll.json"
NIGHT_H = 16.0                    # the longest one night keeps Sleep mode on; on longer than this is left on
POLL_FRESH_S = 600                # kevin-push's asleep(): an older (or not ok) poll is awake, nothing is held


def path(state_dir, env: Optional[Mapping[str, str]] = None) -> Path:
    """$LIMITLESS_SLEEPMODE, else ``state_dir``/sleepmode.jsonl: the file bin/kevin-push's asleep() reads."""
    env = os.environ if env is None else env
    v = env.get(ENV_KEY)
    return Path(v) if v else Path(state_dir) / FILE


def _ok(r) -> Optional[float]:
    if not isinstance(r, dict) or not isinstance(r.get("on"), bool):
        return None
    return parse_ts(r.get("at"))


def parse(text: str) -> list:
    """[(epoch, row)] for every readable row of sleepmode.jsonl ``text``, oldest first (file order on a tie)."""
    out = []
    for ln in (text or "").splitlines():
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        at = _ok(r)
        if at is not None:
            out.append((at, r))
    return sorted(out, key=lambda x: x[0])


def read(p) -> Optional[list]:
    """parse() of the file at ``p``; None when it is missing or cannot be read. Read-only."""
    try:
        return parse(Path(p).read_text(encoding="utf-8", errors="replace"))
    except (OSError, TypeError, ValueError):
        return None


def is_left_on(r) -> bool:
    """An inferred off row that closes a Sleep rule left on: ``on`` false with a non-empty ``left_on``."""
    return isinstance(r, dict) and r.get("on") is False and isinstance(r.get("left_on"), str) \
        and bool(r["left_on"].strip())


def since(got: list) -> Optional[float]:
    """When the current activation began (its first on-row), None when the last row is off or there is none."""
    start = None
    for at, r in got or ():
        start = (start if start is not None else at) if r["on"] else None
    return start


def poll_fresh(p, now: float) -> bool:
    """kevin-push's rule: the poll heartbeat next to the file says ok and is at most POLL_FRESH_S old."""
    try:
        poll = json.loads((Path(p).with_name(POLL_FILE)).read_text())
        at = parse_ts(poll.get("at")) if isinstance(poll, dict) else None
    except (OSError, ValueError, TypeError):
        return False
    return bool(poll.get("ok")) and at is not None and now - at <= POLL_FRESH_S
