"""The unlock-to-feed reflex: how often a feed app was the first thing opened after unlocking the phone.

    got = reflex(unlocks, rows, feed_apps, gap_s=REFLEX_GAP_S, tz=None)
        -> {"days": [{"day", "unlocks", "feed_first"}], "unlocks": int | None, "feed_first": int | None,
            "newest": epoch_s | None, "why": str}

``unlocks`` are epoch seconds or aw_reader.person_rows rows (only ``KEYGUARD_HIDDEN`` rows are unlocks);
``rows`` are app-in-foreground rows in blocks.read_rows / source_rows shape (``start``, ``end``, ``names`` or
``app`` / ``package``, optional ``source``). Only phone rows count: a row whose ``source`` is set and is not
"phone" (the desktop's) is never the first app after an unlock. The first app after an unlock is the first
phone row starting at or after it and before the next unlock; the unlock counts as a reflex when that row
starts within ``gap_s`` of the unlock and its app is in ``feed_apps`` (feeds_evidence.feed_apps: names trimmed
and case-folded). A non-feed app first, then a feed, does not count; an app opened after the gap does not
count. An unlock whose gap the phone data has not covered yet (the newest phone row ends inside it) is left
out, not counted as no feed.

Unknown is never zero: no feed apps set, no unlock, or no phone app row is ``unlocks`` None with a plain,
digit-free ``why``. The gap is a duration (config ``feed_reflex_gap_s``, default REFLEX_GAP_S seconds), never
a clock time; days are local calendar days in ``tz`` only to group the counts.

``label(got, th)`` is the T1 words (digit-free): a feed was often / sometimes / rarely the first thing opened
after unlocking, or "unknown: <why>". The thresholds are shares of the person's own unlocks (config
``feed_reflex_often_share``, ``feed_reflex_rarely_share``, ``feed_reflex_min_unlocks``) and change the wording
only. The counts are T0. It only observes and suggests: nothing here blocks, closes or delays an app, writes,
or sends. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping, Optional

from . import apps_reply, aw_reader, blocks, feeds_evidence
from .state_reader import config

REFLEX_GAP_S, GAP_CONFIG = 30.0, "feed_reflex_gap_s"         # the first app within this long of the unlock
OFTEN_SHARE, OFTEN_CONFIG = 0.5, "feed_reflex_often_share"     # at least this share of unlocks: often
RARELY_SHARE, RARELY_CONFIG = 0.2, "feed_reflex_rarely_share"  # under this share of unlocks: rarely
MIN_UNLOCKS, MIN_CONFIG = 5, "feed_reflex_min_unlocks"         # fewer unlocks than this: too few to say
LOOKBACK_DAYS = 7
MODALITY = "proxy"   # an app opened first is not a feed read: a proxy, never an answer
UNLOCK = "KEYGUARD_HIDDEN"
PHONE = blocks.PHONE

NO_FEEDS = "no feed apps set (config feed_apps)"
NO_UNLOCKS = "no unlock in the phone data"
NO_ROWS = "no phone app rows"
NO_COVER = "the phone data stops before the unlocks can be read"
TOO_FEW = "too few unlocks to say"

OFTEN = "a feed was often the first thing opened after unlocking"
SOMETIMES = "a feed was sometimes the first thing opened after unlocking"
RARELY = "a feed was rarely the first thing opened after unlocking"
WORDS = (OFTEN, SOMETIMES, RARELY)
UNKNOWN_PREFIX = "unknown: "
REASONS = (NO_FEEDS, NO_UNLOCKS, NO_ROWS, NO_COVER, TOO_FEW, blocks.NO_DB)


def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _unlock_times(unlocks) -> list:
    out = set()
    for u in unlocks or ():
        if isinstance(u, Mapping):
            if u.get("type", UNLOCK) != UNLOCK:
                continue
            u = u.get("ts")
        t = _num(u)
        if t is not None:
            out.add(t)
    return sorted(out)


def _phone_rows(rows) -> list:
    out = []
    for r in rows or ():
        if not isinstance(r, Mapping) or r.get("source", PHONE) != PHONE:
            continue
        s = _num(r.get("start", r.get("ts")))
        e = _num(r.get("end", s))
        if s is None or e is None or e < s:
            continue
        raw = r.get("names") if isinstance(r.get("names"), (list, tuple, set)) else (r.get("app"), r.get("package"))
        names = {v.strip().casefold() for v in raw if isinstance(v, str)} - {""}
        out.append((s, e, names))
    out.sort(key=lambda x: (x[0], x[1]))
    return out


def _unknown(why: str) -> dict:
    return {"days": [], "unlocks": None, "feed_first": None, "newest": None, "why": why}


def reflex(unlocks, rows, feed_apps: Optional[Iterable], gap_s: float = REFLEX_GAP_S, tz=None) -> dict:
    """Per-day and total counts of unlocks and of unlocks whose first phone app within ``gap_s`` is a feed
    app. Unknown (``unlocks`` None, ``why`` set) with no feed apps, no unlock or no phone row. Pure."""
    feeds = {w.casefold() for w in feeds_evidence._clean(feed_apps or ())}
    if not feeds:
        return _unknown(NO_FEEDS)
    times = _unlock_times(unlocks)
    if not times:
        return _unknown(NO_UNLOCKS)
    phone = _phone_rows(rows)
    if not phone:
        return _unknown(NO_ROWS)
    gap = _num(gap_s)
    gap = gap if gap is not None and gap > 0 else REFLEX_GAP_S
    newest = max(e for _, e, _ in phone)
    days, i = {}, 0
    for k, u in enumerate(times):
        nxt = times[k + 1] if k + 1 < len(times) else float("inf")
        while i < len(phone) and phone[i][0] < u:
            i += 1
        first = phone[i] if i < len(phone) and phone[i][0] < nxt else None
        if first is not None and first[0] - u <= gap:
            hit = bool(first[2] & feeds)
        elif first is not None or newest >= u + gap:
            hit = False
        else:
            continue   # the data has not covered this unlock's gap yet: left out, not "no feed"
        day = datetime.fromtimestamp(u, tz).date().isoformat()
        d = days.setdefault(day, {"day": day, "unlocks": 0, "feed_first": 0})
        d["unlocks"] += 1
        d["feed_first"] += int(hit)
    if not days:
        return _unknown(NO_COVER)
    per = [days[k] for k in sorted(days)]
    return {"days": per, "unlocks": sum(d["unlocks"] for d in per),
            "feed_first": sum(d["feed_first"] for d in per), "newest": max(newest, times[-1]), "why": ""}


def _cfg_num(cfg: Mapping, key: str, default, ok) -> float:
    v = _num(cfg.get(key))
    return v if v is not None and ok(v) else default


def _gap_of(cfg: Mapping) -> float:
    return float(_cfg_num(cfg, GAP_CONFIG, REFLEX_GAP_S, lambda v: v > 0))


def _thresholds_of(cfg: Mapping) -> dict:
    often = _cfg_num(cfg, OFTEN_CONFIG, OFTEN_SHARE, lambda v: 0 < v <= 1)
    rarely = _cfg_num(cfg, RARELY_CONFIG, RARELY_SHARE, lambda v: 0 < v <= 1)
    if rarely > often:
        often, rarely = OFTEN_SHARE, RARELY_SHARE
    least = _cfg_num(cfg, MIN_CONFIG, MIN_UNLOCKS, lambda v: v >= 1 and float(v).is_integer())
    return {"often": often, "rarely": rarely, "min_unlocks": int(least)}


def gap_s(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> float:
    """Config ``feed_reflex_gap_s`` (a positive number of seconds, a duration; default REFLEX_GAP_S)."""
    return _gap_of(config(env, home))


def thresholds(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> dict:
    """``{often, rarely, min_unlocks}`` from config (shares in (0, 1], a whole count of at least one); a bad
    value, or rarely above often, falls back to the defaults. Wording only."""
    return _thresholds_of(config(env, home))


_DEFAULT_TH = {"often": OFTEN_SHARE, "rarely": RARELY_SHARE, "min_unlocks": MIN_UNLOCKS}


def _share(got, th) -> Optional[float]:
    if not isinstance(got, Mapping):
        return None
    n, k = got.get("unlocks"), got.get("feed_first")
    if not isinstance(n, int) or not isinstance(k, int) or n < max(1, th["min_unlocks"]):
        return None
    return k / n


def label(got: Optional[Mapping], th: Optional[Mapping] = None) -> str:
    """The T1 words for a reflex result: often, sometimes or rarely, or "unknown: <why>". Digit-free."""
    th = dict(_DEFAULT_TH, **(th or {}))
    if not isinstance(got, Mapping) or got.get("unlocks") is None:
        why = got.get("why") if isinstance(got, Mapping) else None
        return UNKNOWN_PREFIX + (why if isinstance(why, str) and why else NO_UNLOCKS)
    share = _share(got, th)
    if share is None:
        return UNKNOWN_PREFIX + TOO_FEW
    if share >= th["often"]:
        return OFTEN
    return RARELY if share < th["rarely"] else SOMETIMES


def is_often(got: Optional[Mapping], th: Optional[Mapping] = None) -> bool:
    """True only when the words are "often" (the habit catalogue's circuit-breaker hint)."""
    return label(got, th) == OFTEN


def review_line(word) -> str:
    """The week review's one optional line for a known word; "" for unknown. Digit-free."""
    return f"Phone: {word} this week." if word in WORDS else ""


def from_settings(cfg: Mapping, state_dir, lo: float, hi: float, env: Optional[Mapping[str, str]] = None,
                  tz=None) -> dict:
    """reflex over [lo, hi) from a config mapping ``cfg`` (the doctor's): the feed list (apps_reply.list_for:
    $LIMITLESS_FEED_APPS, else ``feed_apps``, else apps.json in ``state_dir``), the phone ActivityWatch DB
    ($LIMITLESS_AW_DB, else ``aw_db``; relative to ``state_dir``), ``feed_reflex_gap_s`` and the thresholds;
    plus ``gap_s``, ``thresholds`` and ``label``. Unlocks come from aw_reader.person_rows and app rows from
    blocks.read_rows: the phone DB only, never the desktop's ActivityWatch. Read-only (the DB is opened
    mode=ro)."""
    env = os.environ if env is None else env
    cfg = cfg if isinstance(cfg, Mapping) else {}
    gap, th = _gap_of(cfg), _thresholds_of(cfg)
    feeds = apps_reply.list_for(apps_reply.FEED, cfg, state_dir, env)[0]
    db = env.get("LIMITLESS_AW_DB") or cfg.get("aw_db")
    db = Path(db).expanduser() if isinstance(db, str) and db else None
    if db is not None and not db.is_absolute():
        db = Path(state_dir) / db
    if not feeds:
        got = _unknown(NO_FEEDS)
    elif db is None:
        got = _unknown(blocks.NO_DB)
    else:
        rows = blocks.read_rows(db, lo, hi + gap)
        if rows is None:
            got = _unknown(blocks.NO_DB)
        else:
            unlocks = [r for r in aw_reader.person_rows(db, since_s=lo) if r.get("ts", hi) < hi]
            got = reflex(unlocks, [dict(r, source=PHONE) for r in rows], feeds, gap, tz)
    return dict(got, gap_s=gap, thresholds=th, label=label(got, th))


def read_for(reader, lo: float, hi: float, env: Optional[Mapping[str, str]] = None,
             home: Optional[Path] = None, tz=None) -> dict:
    """from_settings with the host config (state_reader.config) and the reader's state dir. Read-only."""
    return from_settings(config(env, home), reader.path, lo, hi, env, tz)
