"""Outage recap: one plain message, once, about the pushes a kevin-push outage swallowed.

    o = outage(rows)               # the most recent outage in kevin-push's log rows, or None
    r = recap(rows, now, tz)       # {"key", "title", "body", "first_at", "closed_at"} for a closed outage, or None

When kevin-push's sender breaks, every push in that span is only logged (``log (telegram rc=N)`` or ``log (no
sender profile)``: delivery_audit.send_failed). By the time delivery works again those messages are out of date,
so they are never re-sent; the person learns once, in words, what they missed.

An outage is a run of SEND_FAIL_RUN (delivery_audit.SEND_FAIL_RUN) or more transport failures in a row; rows that
never reached the transport (held, folded, a repeat, the daily cap, quiet) are skipped, exactly as
delivery_audit's ``send_failures`` skips them. It is closed by the first later delivered row (``how ==
"telegram"``). Only the most recent outage counts. An outage still open gives no recap (the state card already
says "Phone pushes are not reaching you"), and neither does no outage at all.

The body (FIRST_LINE, the missed line, NOT_RESENT, then the reply line):

    Phone pushes are reaching you again.
    Missed since yesterday: a few messages (wake brief, MIQ prompt, back from nap).
    They were not sent again: by now they are out of date.
    Reply: OK / More

The missed kinds are worded from the failed rows' titles (``kind``), deduped, in order of first miss, at most
MAX_KINDS of them then "and others"; how many is the number of distinct messages (title plus body without its
"Why now" line, so a runner's retries of one message count once) as a word (``count_word``); since when is the
local date of the first failed row against ``now``'s (``since_words``), never a clock time. No digit, no body
text, no profile name, no target and no path ever reach the text. ``More`` is a placeholder: nothing reads the
reply yet (one_tap allows one-word options only, so "Show more" is said as ``More``).

The once key (``once_key``) is derived from the outage's first failed row, ``outage_recap:<its epoch>``, so every
poll of one outage gets the same key and kevin-push --once lets at most one recap out.

Pure: no clock, no file, no send. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import re
from datetime import datetime, tzinfo
from typing import Iterable, Optional

from . import delivery_audit as _da, jobs, one_tap
from .send_gate import WHY_PREFIX

SEND_FAIL_RUN = _da.SEND_FAIL_RUN
OPEN, CLOSED = "open", "closed"
KEY_PREFIX = "outage_recap"
TITLE = "Pushes are back"
FIRST_LINE = "Phone pushes are reaching you again."
MISSED = "Missed {since}: {count} {noun} ({kinds})."
NOT_RESENT = "They were not sent again: by now they are out of date."
ANSWERS = ("OK", "More")          # More: a placeholder, nothing reads it yet
MAX_KINDS = 4
OTHER = "another push"
OTHERS = "others"
_KINDS = {jobs.WAKE_BRIEF.send_title: "wake brief", jobs.MIQ.send_title: "MIQ prompt",
          jobs.NAP.send_title: "back from nap", jobs.HABIT_CHECKIN.send_title: "habit check-in",
          jobs.WEEK_REVIEW.send_title: "week review", jobs.BREAK_NUDGE.send_title: "break nudge"}
_TITLE_OK = re.compile(r"[A-Za-z][A-Za-z' -]*")
_MAX_TITLE_WORDS = 5
_NUM = ("zero", "one", "two", "three", "four", "five", "six")


def _good(rows) -> list:
    """The valid rows (delivery_audit.valid) in time order; rows with the same time keep their file order."""
    return sorted((r for r in rows or () if _da.valid(r)), key=lambda r: float(r["at"]))


def outage(rows: Optional[Iterable]) -> Optional[dict]:
    """The most recent outage in kevin-push's log ``rows``, or None when there is none.

    ``{"state": OPEN | CLOSED, "first_at", "last_at", "closed_at", "failed"}``: the epoch seconds (int) of its
    first and last failed rows and of the delivery that closed it (None while open), and the failed rows in time
    order. Only transport attempts are walked (delivered or send_failed); a run shorter than SEND_FAIL_RUN is no
    outage."""
    runs, cur = [], []
    for r in _good(rows):
        if _da.send_failed(r):
            cur.append(r)
        elif _da.delivered(r):
            if len(cur) >= SEND_FAIL_RUN:
                runs.append((cur, r))
            cur = []
    if len(cur) >= SEND_FAIL_RUN:
        run, closer = cur, None
    elif runs:
        run, closer = runs[-1]
    else:
        return None
    return {"state": OPEN if closer is None else CLOSED, "first_at": int(run[0]["at"]), "last_at": int(run[-1]["at"]),
            "closed_at": None if closer is None else int(closer["at"]), "failed": list(run)}


def once_key(o: dict) -> str:
    """``outage_recap:<epoch of the outage's first failed row>``: the same for every poll of one outage."""
    return f"{KEY_PREFIX}:{int(o['first_at'])}"


def kind(title) -> str:
    """The words for one missed message, from its title: a job's own name (``_KINDS``: wake brief, MIQ prompt,
    back from nap, ...), else the title itself when it is a few plain words (letters, spaces, hyphens and
    apostrophes, trailing punctuation dropped, the first letter lowered unless it starts an acronym), else OTHER.
    A title with a digit, a slash or anything else odd is never repeated."""
    if not isinstance(title, str):
        return OTHER
    if title in _KINDS:
        return _KINDS[title]
    t = title.strip().rstrip("?.!:")
    if not _TITLE_OK.fullmatch(t) or len(t.split()) > _MAX_TITLE_WORDS:
        return OTHER
    return t if t[1:2].isupper() else t[:1].lower() + t[1:]


def kinds(failed: Iterable[dict]) -> list:
    """The kinds of the failed rows, deduped, in order of first miss."""
    out = []
    for r in failed:
        k = kind(r.get("title"))
        if k not in out:
            out.append(k)
    return out


def _message(r: dict) -> tuple:
    body = r.get("body") if isinstance(r.get("body"), str) else ""
    lines = [ln.strip() for ln in body.splitlines() if ln.strip() and not ln.strip().startswith(WHY_PREFIX)]
    return r.get("title"), "\n".join(lines)


def count_word(n: int) -> str:
    """How many messages, as a word: one, a few (two to four) or many."""
    return "one" if n <= 1 else "a few" if n <= 4 else "many"


def since_words(first_at: float, now: float, tz: Optional[tzinfo] = None) -> str:
    """When the outage started, from local dates only: since earlier today, since yesterday, since two (... six)
    days ago, since over a week ago."""
    days = (datetime.fromtimestamp(now, tz).date() - datetime.fromtimestamp(first_at, tz).date()).days
    if days <= 0:
        return "since earlier today"
    if days == 1:
        return "since yesterday"
    return f"since {_NUM[days]} days ago" if days < len(_NUM) else "since over a week ago"


def _kinds_words(ks: list) -> str:
    if len(ks) > MAX_KINDS:
        return ", ".join(ks[:MAX_KINDS]) + f" and {OTHERS}"
    return ", ".join(ks)


def body_for(o: dict, now: float, tz: Optional[tzinfo] = None) -> str:
    """The recap's text for outage ``o`` (see the module doc)."""
    n = len({_message(r) for r in o["failed"]})
    missed = MISSED.format(since=since_words(o["first_at"], now, tz), count=count_word(n),
                           noun="message" if n == 1 else "messages", kinds=_kinds_words(kinds(o["failed"])))
    return "\n".join((FIRST_LINE, missed, NOT_RESENT, one_tap.choices_line(ANSWERS)))


def recap(rows: Optional[Iterable], now: float, tz: Optional[tzinfo] = None) -> Optional[dict]:
    """The recap for the most recent outage when it is closed: ``{"key", "title", "body", "first_at",
    "closed_at"}``; None when there is no outage or it is still open."""
    o = outage(rows)
    if o is None or o["state"] != CLOSED:
        return None
    return {"key": once_key(o), "title": TITLE, "body": body_for(o, now, tz), "first_at": o["first_at"],
            "closed_at": o["closed_at"]}
