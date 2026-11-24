"""Missed wake brief: a wake brief that never reached the phone can be read in any Hermes chat.

    found = find(cfg, state_dir, now, env)   # {"missed", "text", "at", "why", "reason", "until"}
    line(found)                              # CARD_LINE while a brief is missed, else None
    key(state_dir)                           # the stat-only cache-key part of the wake events (no file opened)
    tool(reader, now, raw, env)              # limitless_missed_brief: the envelope, through tier_audit.gate

When phone pushes fail (the sender profile is missing, Sleep mode was left on, the daily cap) the wake brief is
built and logged but never delivered. kevin-push's log (config ``push_log``, delivery_audit.log_path) keeps
every attempt with its ``body``: the brief text as it was handed over (as it went out, shaped, for a failed
transport attempt). That row is the brief this module offers. ``brief-latest.md`` is written by the private
loader outside this repo and is not read: its shape is not defined here.

Missed, all of:

- today (``now``'s local date, ``tz``; this machine's zone by default) is a wake day
  (jobs_runner.delivery_wake_days: the wake events the plugin already merges), or no wake is known today but
  today's rows hold a wake-brief row with a text: the older sender logs its brief even on a morning no wake
  proxy fired, and that row shows the morning ran. It makes today a wake day for this offer only; the delivery
  audit's own wake days are left as they are;
- delivery_audit.brief_misses over today's rows says today had no delivered wake brief and had a brief row (the
  delivery audit's own rule: rows titled delivery_audit.WAKE_TITLE, ``how`` ``telegram`` is a delivery);
- the newest undelivered brief row of today with a text is no older than jobs.WAKE_BRIEF.stale_after_s.

A brief from a previous day is never offered, nor one older than the wake job's stale_after_s: hours later it
is noise. Unknown (no push log set, unreadable, no wake and no brief row today) is not missed and says why in words.

The state card adds CARD_LINE, digit-free, after the push-reach line (outside card.MAX_LINES, like it). The tool
returns the text with every digit masked unless the raw opt-in is set, through tier_audit.gate (hook HOOK; the
gate's content-free audit row is the only write). Nothing marks the brief sent: the phone still did not get it.
Never runs hermes, never sends. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import re
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Mapping, Optional

from . import delivery_audit as _delivery, jobs, jobs_runner, tier_audit
from .envelope import envelope
from .state_reader import StateReader, config

CARD_LINE = "Today's wake brief did not reach your phone; ask me for it."
HOOK = "tool:limitless_missed_brief"
MODALITY = _delivery.MODALITY      # kevin-push's own log: measured
STALE_S = jobs.WAKE_BRIEF.stale_after_s
LABEL = "today's wake brief did not reach your phone"
CUT_NOTE = "the push log keeps only the start of a long brief, so its end may be missing"
EVENT_FILES = ("events.jsonl", "screen-events.jsonl")   # wake sources not already in the card's key
# Why nothing is offered: words only, no digit, no path.
NO_LOG = "no push log set (config push_log), so a missed brief cannot be told"
UNREADABLE = "the push log could not be read"
NO_WAKE = "no wake today is known"
NO_BRIEF = "no wake brief was logged today"
DELIVERED = "today's wake brief reached your phone"
STALE = "today's wake brief is too old to offer"
BLOCKED = "the brief held a digit without the raw opt-in, so it was left out"


def _not(reason: str) -> dict:
    return {"missed": False, "text": None, "at": None, "why": None, "reason": reason, "until": None}


def _brief(r: Mapping) -> bool:
    """A wake-brief row (title delivery_audit.WAKE_TITLE) with a non-empty text."""
    return r.get("title") == _delivery.WAKE_TITLE and isinstance(r.get("body"), str) and bool(r["body"].strip())


def find(cfg: Optional[Mapping], state_dir, now: float, env: Optional[Mapping[str, str]] = None,
         home: Optional[Path] = None, tz: Optional[tzinfo] = None) -> dict:
    """Today's missed wake brief (see the module doc). ``until`` is when the offer goes stale (None when nothing
    is missed). Read-only; never raises: a broken input is not missed, with a reason in words."""
    try:
        path = _delivery.log_path(cfg, state_dir)
        if path is None:
            return _not(NO_LOG)
        got = _delivery.read_log(path)
        if got is None:
            return _not(UNREADABLE)
        today = datetime.fromtimestamp(now, tz).date()
        rows = [r for r in got[0] if float(r["at"]) <= now and _delivery._day(r, tz) == today]
        wakes = jobs_runner.delivery_wake_days(state_dir, now, env, home, tz) or []
        if today not in wakes:
            if not any(_brief(r) for r in rows):
                return _not(NO_WAKE)
            wakes = [today]   # today's own brief row shows the morning ran: a wake day for this offer only
        m = _delivery.brief_misses(rows, [today], tz, days=[today],
                                   sleep=_delivery.sleep_rows(state_dir, env))
        why = m["days"].get(today.isoformat())
        if why is None:
            return _not(DELIVERED if m["known"] else NO_BRIEF)
        briefs = [r for r in rows if _brief(r) and not _delivery.delivered(r)]
        if why == _delivery.MISS_NONE or not briefs:
            return _not(NO_BRIEF)
        newest = max(briefs, key=lambda r: float(r["at"]))
        at = float(newest["at"])
        if now - at > STALE_S:
            return _not(STALE)
        return {"missed": True, "text": newest["body"], "at": at, "why": why, "reason": None,
                "until": at + STALE_S}
    except Exception:  # noqa: BLE001 - a broken input must not break the card or the tool
        return _not(UNREADABLE)


def line(found: Optional[Mapping]) -> Optional[str]:
    """CARD_LINE while a brief is missed (``find``), else None."""
    return CARD_LINE if isinstance(found, Mapping) and found.get("missed") is True else None


def key(state_dir) -> tuple:
    """The mtimes of the wake event files ``find`` reads that the card's key does not already hold (the push
    log is in push_reach.key, sleepmode.jsonl in card.CARD_FILES, the ActivityWatch DB in its own part)."""
    reader = StateReader(Path(state_dir))
    return tuple(reader.mtime(n) for n in EVENT_FILES)


def tool(reader: StateReader, now: float, raw: bool = False, env: Optional[Mapping[str, str]] = None,
         home: Optional[Path] = None, tz: Optional[tzinfo] = None) -> dict:
    """limitless_missed_brief: today's missed wake brief, read-only.

    ``value: {brief, why}``: the brief text as kevin-push logged it (every digit masked as ``#`` unless ``raw``,
    LIMITLESS_RAW_IN_PROMPT) and the delivery audit's miss reason in words; ``note`` when the log may have cut
    it. Modality measured, age_h the brief row's age, a digit-free T1 label beside it. The text goes through
    tier_audit.gate (hook HOOK, opt-in ``raw``): the content-free audit row is the only write. value None with a
    words-only reason when nothing is missed. Never marks the brief sent and never sends.
    """
    f = find(config(env, home), reader.path, now, env, home, tz)
    if not f["missed"]:
        return envelope(None, MODALITY, None, reason=f["reason"])
    text = f["text"] if raw else re.sub(r"\d+", "#", f["text"])
    if tier_audit.gate(HOOK, text, raw, env=env, home=home, now=now) is None:
        return envelope(None, MODALITY, None, reason=BLOCKED)
    value = {"brief": text, "why": f["why"]}
    if len(f["text"]) >= _delivery.LOG_BODY_CHARS:
        value["note"] = CUT_NOTE
    out = envelope(value, MODALITY, max(0.0, now - f["at"]) / 3600)
    out["label"] = {"label": LABEL, "tier": "T1", "modality": MODALITY}
    return out
