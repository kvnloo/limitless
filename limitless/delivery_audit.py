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

Per day: ``delivered`` (rows with how "telegram"), ``over_cap`` (delivered above ``cap``: config ``push_cap``
via push_cap(), default send_gate.DAILY_CAP), ``brief`` (a delivered wake brief that day), ``wake_day`` (the
day is in ``wake_days``: local dates of the wake events the plugin already merges, jobs_runner.events and
jobs.wake_times; None = not known) and ``no_action`` (deliveries whose body has no reply line: has_action,
message_shape's own reply-line rule). A wake day is judged only when the log has rows that day.
Labels (T1, words, no digit): push "within the push limit every day this week" / "... on every logged day" /
"over the push limit on some days"; brief "every" / "most" (more than half) / "some" / "did not reach you on
any wake day" / unknown; action "every push had a reply line" / "some pushes had no reply line".

A day of the window with no row at all is unknown (None), never zero: the log may not cover it. Bad lines
and rows (not JSON, not an object, no numeric ``at``, no string ``how``) are skipped and counted.
Pure: no clock, no file except read_log, no send. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Iterable, Mapping, Optional

from . import jobs, message_shape, send_gate

DELIVERED = "telegram"           # bin/kevin-push's ``how`` for a real delivery (rc 0); jobs_runner.DELIVERED
WAKE_TITLE = jobs.WAKE_BRIEF.send_title
DAYS = 7
MODALITY = "measured"            # the push log is kevin-push's own record of what it did
UNKNOWN_ROWS = "unknown: no push rows this week"
NO_LOG = "unknown: no push log set"
LOG_BODY_CHARS = 2000            # bin/kevin-push logs ``shown[:2000]``: a body this long may have lost its end
CAP_CONFIG, LOG_CONFIG = "push_cap", "push_log"
# T1 words; the counts behind them stay T0 in the dict.
WITHIN_ALL, WITHIN_LOGGED = "within the push limit every day this week", "within the push limit on every logged day"
OVER = "over the push limit on some days"
BRIEF_ALL, BRIEF_MOST = "brief reached you on every wake day", "brief reached you on most wake days"
BRIEF_SOME, BRIEF_NONE = "brief reached you on some wake days", "brief did not reach you on any wake day"
BRIEF_UNKNOWN = "brief: unknown, no wake days known"
ACTION_ALL, ACTION_SOME = "every push had a reply line", "some pushes had no reply line"
ACTION_KNOWN = "every push with a known body had a reply line"


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


def push_cap(cfg: Optional[Mapping] = None) -> int:
    """Config ``push_cap`` (a whole number, at least one); anything else is the send gate's own DAILY_CAP."""
    v = cfg.get(CAP_CONFIG) if isinstance(cfg, Mapping) else None
    ok = isinstance(v, int) and not isinstance(v, bool) and v >= 1
    return v if ok else send_gate.DAILY_CAP


def has_action(body) -> Optional[bool]:
    """Whether a delivered body closes with message_shape's reply line (the line ``fit`` always keeps: a
    ``Reply: A / B`` choices line or a line with the word reply, the last line before any why-now line,
    never the first line). None when it cannot be told: no text, or a body the log may have cut."""
    if not isinstance(body, str) or len(body) >= LOG_BODY_CHARS:
        return None
    rest = [ln for ln in body.splitlines() if ln.strip()][1:]
    if rest and message_shape._is_why(rest[-1]):
        rest.pop()
    return bool(rest) and message_shape._asks_reply(rest[-1])


def _wake_set(wake_days) -> Optional[set]:
    if wake_days is None:
        return None
    out = set()
    for d in wake_days:
        if isinstance(d, datetime):
            d = d.date()
        if isinstance(d, str):
            try:
                d = date.fromisoformat(d)
            except ValueError:
                continue
        if isinstance(d, date):
            out.add(d)
    return out


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
    cap = cap if isinstance(cap, int) and not isinstance(cap, bool) and cap >= 1 else send_gate.DAILY_CAP
    wakes = _wake_set(wake_days)
    window = [] if today is None else [today - timedelta(days=n) for n in range(max(int(days), 1) - 1, -1, -1)]
    by_day = {d: [] for d in window}
    for r in good:
        d = _day(r, tz)
        if d in by_day:
            by_day[d].append(r)
    out.update(cap=cap, over_cap_days=[], no_action=0, action_unknown=0)
    wake = {"wake_days": 0, "brief_delivered": 0, "unknown_wake_days": 0, "brief_share": None}
    for d in window:
        got = by_day[d]
        known = bool(got)
        sent = [r for r in got if delivered(r)]
        acts = [has_action(r.get("body")) for r in sent]
        is_wake = None if wakes is None else d in wakes
        brief = any(r.get("title") == WAKE_TITLE for r in sent) if known else None
        row = {"day": d.isoformat(), "rows": len(got), "delivered": len(sent) if known else None,
               "over_cap": len(sent) > cap if known else None, "wake_day": is_wake, "brief": brief,
               "no_action": acts.count(False), "action_unknown": acts.count(None)}
        out["days"].append(row)
        out["no_action"] += row["no_action"]
        out["action_unknown"] += row["action_unknown"]
        if known:
            out["known_days"] += 1
            out["delivered"] += len(sent)
            if row["over_cap"]:
                out["over_cap_days"].append(row["day"])
        if is_wake:
            if not known:
                wake["unknown_wake_days"] += 1
            else:
                wake["wake_days"] += 1
                wake["brief_delivered"] += int(brief)
    if wake["wake_days"]:
        wake["brief_share"] = wake["brief_delivered"] / wake["wake_days"]
    out["wake"] = wake
    out["labels"] = {"push": _push_words(out, len(window)), "brief": _brief_words(wake),
                     "action": _action_words(out)}
    words = "; ".join(w for w in out["labels"].values() if w)
    out["label"] = {"label": words, "tier": "T1", "modality": MODALITY}
    return out


def _push_words(out: dict, n_days: int) -> str:
    if not out["known_days"]:
        return UNKNOWN_ROWS
    if out["over_cap_days"]:
        return OVER
    return WITHIN_ALL if out["known_days"] == n_days else WITHIN_LOGGED


def _brief_words(wake: dict) -> str:
    n, got = wake["wake_days"], wake["brief_delivered"]
    if not n:
        return BRIEF_UNKNOWN
    if got == n:
        return BRIEF_ALL
    if got * 2 > n:
        return BRIEF_MOST
    return BRIEF_SOME if got else BRIEF_NONE


def _action_words(out: dict) -> str:
    if not out["delivered"]:
        return ""
    if out["no_action"]:
        return ACTION_SOME
    return ACTION_KNOWN if out["action_unknown"] else ACTION_ALL
