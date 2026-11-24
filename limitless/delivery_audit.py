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

Complaints (``signals``: ``{"replies": [(epoch, text)] | None, "quiet": quiet.json dict | None, "why"}``, as
``signals()`` reads them): only explicit signals the person sent, on a local day of the window. A quiet,
quiet tonight or snooze command (quiet.command: the whole message) in the replies, or the one quiet.json
records (mode off, quiet_tonight or snoozed, ``since`` in the window), counted once per second; and a reply
whose first words are ``stop`` or ``too much`` (stop_request) sent within REPLY_GAP_S after a delivered push.
Nothing else is read into it: no model, no sentiment. ``replies`` None (no Hermes DB set, or it cannot be
read) or a week with no row is unknown with a reason, never "no complaints". ``complaints`` keeps only the
counts (T0); the text is never stored. Label: "no complaints this week" / "some pushes drew a quiet or stop
request" / "complaints: unknown, <why>".
Pure: no clock, no file except read_log and signals, no send. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import math
import sqlite3
import unicodedata
from datetime import date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Iterable, Mapping, Optional

from . import jobs, message_shape, quiet, send_gate

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
COMPLAINTS_NONE, COMPLAINTS_SOME = "no complaints this week", "some pushes drew a quiet or stop request"
COMPLAINTS_UNKNOWN = "complaints: unknown, "
NO_DB_COMPLAINTS = "no Hermes DB set (config hermes_db), so replies cannot be read"
DB_UNREADABLE = "the Hermes DB could not be read"
QUIET_UNREADABLE = "the quiet file could not be read"
NO_WEEK_COMPLAINTS = "no push rows this week"
REPLY_GAP_S = 3600              # a stop or too much reply counts within an hour after a delivered push
STOP_WORDS = (("stop",), ("too", "much"))


def _at(v) -> Optional[float]:
    """Epoch seconds of a row's ``at``; None when it is not a number a date can be read from."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    try:
        datetime.fromtimestamp(v)
    except (OverflowError, OSError, ValueError):
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


NO_LOG_REASON = f"no push log set (config {LOG_CONFIG})"
UNREADABLE_REASON = "the push log could not be read"
NO_ROWS_REASON = "no push row in the last seven days"


def log_path(cfg: Optional[Mapping], state_dir) -> Optional[Path]:
    """The push log: config ``push_log`` (kevin-push writes it under its own state dir; a relative path is in
    the limitless state dir). None when it is not set: there is no default, so unset is unknown, not zero."""
    v = cfg.get(LOG_CONFIG) if isinstance(cfg, Mapping) else None
    if not isinstance(v, str) or not v.strip():
        return None
    p = Path(v.strip()).expanduser()
    return p if p.is_absolute() else Path(state_dir) / p


def _replies(db: Path, since: float) -> Optional[list]:
    """habit_replies' query of the person's Telegram messages after ``since``, read-only; None (not ``[]``) when
    the DB is missing, locked or not the session store, so an unreadable source is unknown, never none."""
    from . import habit_replies
    from urllib.parse import quote
    if not db.is_file():
        return None
    try:
        con = sqlite3.connect("file:" + quote(str(db.resolve())) + "?mode=ro", uri=True,
                              timeout=habit_replies.BUSY_TIMEOUT_S)
    except sqlite3.Error:
        return None
    try:
        rows = con.execute(habit_replies._QUERY, ("telegram", float(since))).fetchall()
    except (sqlite3.Error, ValueError, TypeError, OverflowError):
        return None
    finally:
        con.close()
    return [(float(t), c) for t, c in rows if _at(t) is not None and isinstance(c, str)]


def signals(state_dir, cfg: Optional[Mapping], now: float, env: Optional[Mapping[str, str]] = None,
            days: int = DAYS) -> dict:
    """The complaint sources for ``audit(signals=...)``: ``{"replies", "quiet", "why"}``. ``replies`` are the
    person's Telegram messages from the Hermes session DB (habit_replies.hermes_db_from: $LIMITLESS_HERMES_DB,
    else config ``hermes_db``, the DB the quiet ingest reads) over the last ``days`` and one more; ``quiet`` is
    quiet.json (None when there is none). ``why`` is set, and the complaints unknown, when no DB is set, it
    cannot be read, or quiet.json is there but cannot be read. Read-only; the texts are only passed on to
    ``audit``, which keeps counts."""
    from . import habit_replies
    try:
        db = habit_replies.hermes_db_from(state_dir, cfg if isinstance(cfg, Mapping) else {}, env)
    except (TypeError, ValueError):
        db = None
    if db is None:
        return {"replies": None, "quiet": None, "why": NO_DB_COMPLAINTS}
    replies = _replies(Path(db), float(now) - (max(int(days), 1) + 1) * 86400.0)
    if replies is None:
        return {"replies": None, "quiet": None, "why": DB_UNREADABLE}
    state = quiet.load(state_dir)
    if state is None and (Path(state_dir) / quiet.QUIET_FILE).exists():
        return {"replies": None, "quiet": None, "why": QUIET_UNREADABLE}
    return {"replies": replies, "quiet": state, "why": None}


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


def stop_request(text) -> bool:
    """True when a reply's first words, case-insensitive with trailing punctuation ignored, are ``stop`` or
    ``too much`` (STOP_WORDS). "stop" anywhere else in a sentence, or inside a word, is not one."""
    if not isinstance(text, str):
        return False
    words = []
    for w in text.lower().split()[:2]:
        while w and unicodedata.category(w[-1]).startswith("P"):
            w = w[:-1]
        words.append(w)
    return any(tuple(words[:len(s)]) == s for s in STOP_WORDS)


# Why a wake day had no delivered brief (brief_misses): the fixed list, in words, no digit.
MISS_SLEEP, MISS_QUIET = "held while Sleep mode was on", "held by the quiet setting"
MISS_REPEAT, MISS_GATE = "stopped as a repeat", "refused by the send gate"
MISS_LOGGED, MISS_NONE, MISS_UNKNOWN = "logged but not sent", "no brief attempt on that day", "unknown"
MISS_REASONS = (MISS_SLEEP, MISS_QUIET, MISS_REPEAT, MISS_GATE, MISS_LOGGED, MISS_NONE, MISS_UNKNOWN)
# Precedence when a day has several brief rows and none delivered: the first of these that any of them has.
# The cause that stopped the first attempt comes first: a Sleep hold or a quiet drop leaves the event for a
# retry that the gate then stops as a repeat, refuses (cap) or only logs, so those come after it. A day with
# no brief row at all is MISS_NONE; a brief row whose ``how`` is none of the known words is MISS_UNKNOWN.
MISS_ORDER = (MISS_SLEEP, MISS_QUIET, MISS_REPEAT, MISS_GATE, MISS_LOGGED, MISS_UNKNOWN)
MISSES_PREFIX, MISSES_NONE = "missed wake briefs: ", "no wake brief was missed"
MISSES_UNKNOWN = MISSES_PREFIX + "unknown"
MISS_CLAUSE = "most common miss: {}"
_MISS_EXACT = {"held (sleep mode)": MISS_SLEEP, "log (duplicate)": MISS_REPEAT,
               f"log ({send_gate.ONCE_DROP})": MISS_REPEAT, "log (daily cap)": MISS_GATE,
               "log (dropped)": MISS_GATE, "log": MISS_LOGGED, "folded (brief line)": MISS_LOGGED}


def miss_reason(how) -> str:
    """The MISS_REASONS word for one undelivered brief row's ``how`` (bin/kevin-push's HOW, the quiet drop
    ``log (quiet: ...)`` and a failed transport ``log (telegram rc=N)``); MISS_UNKNOWN for anything else."""
    if not isinstance(how, str):
        return MISS_UNKNOWN
    if how in _MISS_EXACT:
        return _MISS_EXACT[how]
    if how.startswith("log (quiet:"):
        return MISS_QUIET
    if how.startswith("log (telegram rc="):
        return MISS_LOGGED
    return MISS_UNKNOWN


def brief_misses(rows: Optional[Iterable], wake_days: Optional[Iterable], tz: Optional[tzinfo] = None, *,
                 days: Optional[Iterable] = None) -> dict:
    """Why the wake brief did not reach the person on each known wake day without a delivered one.

    A wake day (``wake_days``, as audit takes them) is judged only when the log has rows that day, like audit;
    ``days`` (optional) limits the judged days (audit passes its window). One reason a missed day, decided only
    from that day's rows titled WAKE_TITLE: a delivered one means no miss; else the first reason in MISS_ORDER
    any of them has (miss_reason); no such row at all is MISS_NONE. Other titles never lend their reason.
    T0: ``{"known", "missed", "reasons": {reason: count for every MISS_REASONS}, "days": {iso day: reason},
    "unknown_wake_days", "top", "label"}``; ``known`` is False (and nothing counted) when no wake day is known or
    the log has no row. ``top`` is the most common reason (ties by MISS_REASONS order), None with no miss.
    ``label`` is words only (``_miss_words``): each reason with a share word, most common first.
    """
    good = [r for r in rows or () if valid(r)]
    wakes = _wake_set(wake_days) or set()
    if days is not None:
        wakes &= _wake_set(days) or set()
    out = {"known": bool(good and wakes), "missed": 0, "reasons": {r: 0 for r in MISS_REASONS}, "days": {},
           "unknown_wake_days": 0, "top": None, "label": MISSES_UNKNOWN}
    if not out["known"]:
        return out
    by_day = {}
    for r in good:
        d = _day(r, tz)
        if d in wakes:
            by_day.setdefault(d, []).append(r)
    for d in sorted(wakes):
        got = by_day.get(d)
        if not got:
            out["unknown_wake_days"] += 1
            continue
        briefs = [r for r in got if r.get("title") == WAKE_TITLE]
        if any(delivered(r) for r in briefs):
            continue
        seen = {miss_reason(r.get("how")) for r in briefs}
        reason = next((m for m in MISS_ORDER if m in seen), MISS_NONE)
        out["days"][d.isoformat()] = reason
        out["reasons"][reason] += 1
        out["missed"] += 1
    if out["missed"]:
        out["top"] = max(MISS_REASONS, key=lambda m: (out["reasons"][m], -MISS_REASONS.index(m)))
    out["label"] = _miss_words(out)
    return out


def _miss_words(m: dict) -> str:
    """"missed wake briefs: <reason> (all|most|some), ..." most common first, ties in MISS_REASONS order; "all"
    when one reason covers every miss, "most" for more than half, else "some". No digit, date or clock time."""
    n = m["missed"]
    if not n:
        return MISSES_NONE
    used = sorted((r for r in MISS_REASONS if m["reasons"][r]), key=lambda r: (-m["reasons"][r],
                                                                             MISS_REASONS.index(r)))
    share = lambda c: "all" if c == n else "most" if c * 2 > n else "some"   # noqa: E731
    return MISSES_PREFIX + ", ".join(f"{r} ({share(m['reasons'][r])})" for r in used)


def miss_clause(a: Optional[dict]) -> str:
    """"most common miss: <reason>" for an audit (``audit``'s dict) whose goal is not met and that has a missed
    wake brief; "" otherwise (met, unknown, or not met for another reason). Words only."""
    if not isinstance(a, dict) or goal(a) != GOAL_NOT_MET:
        return ""
    top = (a.get("misses") or {}).get("top")
    return MISS_CLAUSE.format(top) if top else ""


MUTING = (quiet.OFF, quiet.TONIGHT, quiet.SNOOZED)


def _complaints(signals: Optional[Mapping], good: list, days: set, tz: Optional[tzinfo]) -> dict:
    """The T0 complaint counts over the window ``days`` (see the module doc); never the text."""
    sig = signals if isinstance(signals, Mapping) else {}
    replies = sig.get("replies")
    why = sig.get("why") or (NO_DB_COMPLAINTS if not isinstance(replies, (list, tuple)) else None)
    if not days:
        why = NO_WEEK_COMPLAINTS
    if why:
        return {"known": False, "quiet": None, "stop": None, "total": None, "why": str(why)}

    def in_window(t) -> bool:
        return _at(t) is not None and datetime.fromtimestamp(t, tz).date() in days

    sent = [float(r["at"]) for r in good if delivered(r)]
    muted, stops = set(), 0
    state = sig.get("quiet")
    since = quiet._since(state)
    if quiet.mode_of(state) in MUTING and since is not None and in_window(since):
        muted.add(int(since))
    for item in replies or ():
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            continue
        t, text = item
        if not in_window(t):
            continue
        if quiet.command(text) in MUTING:
            muted.add(int(t))
        elif stop_request(text) and any(p <= t <= p + REPLY_GAP_S for p in sent):
            stops += 1
    return {"known": True, "quiet": len(muted), "stop": stops, "total": len(muted) + stops, "why": None}


def audit(rows: Iterable, days: int = DAYS, wake_days: Optional[Iterable] = None, *, today: Optional[date] = None,
          tz: Optional[tzinfo] = None, cap: Optional[int] = None, skipped: int = 0,
          signals: Optional[Mapping] = None) -> dict:
    """The delivery audit of ``rows`` over the ``days`` local days ending ``today`` (default: the newest row's
    day). T0 counts per day and in total, and one T1 ``label`` in words. ``signals`` (``signals()``) are the
    complaint sources; None is complaints unknown. See the module doc."""
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
    out["misses"] = brief_misses(good, wake_days, tz, days=window)
    out["complaints"] = _complaints(signals, good, set(window) if out["known_days"] else set(), tz)
    out["labels"] = {"push": _push_words(out, len(window)), "brief": _brief_words(wake),
                     "action": _action_words(out), "complaints": _complaint_words(out["complaints"])}
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


def _complaint_words(c: dict) -> str:
    if not c["known"]:
        return COMPLAINTS_UNKNOWN + c["why"]
    return COMPLAINTS_SOME if c["total"] else COMPLAINTS_NONE


GOAL_MET, GOAL_NOT_MET, GOAL_UNKNOWN = "met", "not met", "unknown"


def goal(a: Optional[dict]) -> str:
    """Whether an audit (``audit``'s dict, None for no log) meets north-star row two, judged from its own counts.

    "not met" when a logged day went over the cap, a wake day with rows had no delivered brief, a delivered
    push had no reply line, or a complaint is known (a quiet or stop request). "met" only when every day of
    the window has rows, at least one wake day is known, no wake day is unknown, every delivered body is known
    to carry a reply line, and complaints are known to be none. Anything else ("unknown") includes no log, a
    quiet week, unknown wake days and unknown complaints: unknown is never met.
    """
    if not isinstance(a, dict) or not a.get("known_days"):
        return GOAL_UNKNOWN
    wake = a["wake"]
    c = a.get("complaints") or {}
    if a["over_cap_days"] or a["no_action"] or wake["brief_delivered"] < wake["wake_days"] or \
            (c.get("known") and c.get("total")):
        return GOAL_NOT_MET
    complete = a["known_days"] == len(a["days"]) and not a["action_unknown"] and c.get("known") is True
    return GOAL_MET if complete and wake["wake_days"] and not wake["unknown_wake_days"] else GOAL_UNKNOWN
