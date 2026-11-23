"""Delivery audit: did the pushes stay useful? Read-only, over kevin-push's own log (north-star row two).

    rows, skipped = parse_lines(text)          # log.jsonl text -> valid rows, count of bad lines
    got = read_log(path)                       # (rows, skipped), or None when the file cannot be read
    audit(rows, days=7, wake_days=None, ...)   # -> dict: T0 counts per day plus one T1 label in words

The log is the one bin/kevin-push appends, one row per call, and this module never changes how it is written:
``{"at": whole epoch seconds, "tag", "cls", "title", "body", "how"}``. The fields relied on:

- ``at``: the local day of the row (``tz``; default this machine's zone, like jobs_runner).
- ``how``: ``"telegram"`` only when the transport returned 0 (a real delivery; jobs_runner.DELIVERED is the
  same word). Every other value ("log", "folded (brief line)", "held (sleep mode)", "log (duplicate)",
  "log (daily cap)", "log (dropped)", "log (quiet: ...)", "log (telegram rc=N)") is not a delivery.
- ``title``: the wake brief is the row titled jobs.WAKE_BRIEF.send_title (the title bin/limitless-brief and
  limitless-jobs send it under).
- ``body``: for a delivery, the text as it went out (after message_shape.fit), cut to LOG_BODY_CHARS.

Not in the row, so never used: the send gate's decision word itself (only ``how``), the ``--once`` event key
(kept in sent.json, not in the log) and the wake event the brief was for.

A day of the window with no row at all is unknown (None), never zero: the log may not cover it. Bad lines
and rows (not JSON, not an object, no numeric ``at``, no string ``how``) are skipped and counted.
Pure: no clock, no file except read_log, no send. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Iterable, Optional

from . import jobs

DELIVERED = "telegram"           # bin/kevin-push's ``how`` for a real delivery (rc 0); jobs_runner.DELIVERED
WAKE_TITLE = jobs.WAKE_BRIEF.send_title
DAYS = 7
MODALITY = "measured"            # the push log is kevin-push's own record of what it did
UNKNOWN_ROWS = "unknown: no push rows this week"


def _at(v) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def valid(r) -> bool:
    """A row the audit can read: an object with a numeric ``at`` and a string ``how``."""
    return isinstance(r, dict) and _at(r.get("at")) is not None and isinstance(r.get("how"), str)


def parse_lines(text: str) -> tuple:
    """(rows, skipped): the valid rows of log.jsonl ``text`` in file order and the number of non-blank lines
    that were not (broken JSON, a cut line, a row without ``at`` or ``how``)."""
    rows, skipped = [], 0
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError:
            skipped += 1
            continue
        if valid(r):
            rows.append(r)
        else:
            skipped += 1
    return rows, skipped


def read_log(path) -> Optional[tuple]:
    """(rows, skipped) of the log at ``path``; None when it is missing or cannot be read. Opens it read-only."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except (OSError, TypeError, ValueError):
        return None
    return parse_lines(text)


def delivered(r: dict) -> bool:
    """True only for a real Telegram delivery as kevin-push logged it."""
    return r.get("how") == DELIVERED


def _day(r: dict, tz: Optional[tzinfo]) -> date:
    return datetime.fromtimestamp(_at(r["at"]), tz).date()


def audit(rows: Iterable, days: int = DAYS, wake_days: Optional[Iterable] = None, *, today: Optional[date] = None,
          tz: Optional[tzinfo] = None, cap: Optional[int] = None, skipped: int = 0) -> dict:
    """The delivery audit of ``rows`` over the ``days`` local days ending ``today`` (default: the newest row's
    day). T0 counts per day and in total, and one T1 ``label`` in words. See the module doc."""
    good, bad = [], int(skipped or 0)
    for r in rows or ():
        if valid(r):
            good.append(r)
        else:
            bad += 1
    if today is None:
        today = max((_day(r, tz) for r in good), default=None)
    out = {"days": [], "delivered": 0, "known_days": 0, "skipped": bad}
    if today is None:
        out["label"] = {"label": UNKNOWN_ROWS, "tier": "T1", "modality": MODALITY}
        return out
    window = [today - timedelta(days=n) for n in range(max(int(days), 1) - 1, -1, -1)]
    by_day = {d: [] for d in window}
    for r in good:
        d = _day(r, tz)
        if d in by_day:
            by_day[d].append(r)
    for d in window:
        got = by_day[d]
        known = bool(got)
        n = sum(1 for r in got if delivered(r)) if known else None
        out["days"].append({"day": d.isoformat(), "rows": len(got), "delivered": n, "over_cap": None})
        if known:
            out["known_days"] += 1
            out["delivered"] += n
    out["label"] = {"label": UNKNOWN_ROWS if not out["known_days"] else "known",
                    "tier": "T1", "modality": MODALITY}
    return out
