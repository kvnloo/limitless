"""Flow, weekly: deep-work minutes and feed leak per block-hour from an ActivityWatch DB copy. No score.

    w = week(aw_db, week_of, tz, blocks=None, work_apps=(...), feed_apps=(...))
    # {deep_min, block_hours, feed_leak_min, leak_per_block_hour, days_with_data, modality, evidence}

The week is the seven local days from ``week_of`` in ``tz`` (a tzinfo; None = this machine's zone).
Active time is the app-in-foreground spans (bucket type ``currentwindow``), cut to the not-afk spans when
the DB has an ``afkstatus`` bucket for the week. Overlapping spans count once. The desktop's ActivityWatch
(aw_desktop, ``desktop`` below) adds its own spans, cut to its own not-afk time; titles are never read from
it, so a ``title:`` work entry matches phone rows only.

- Deep work: active time in an app the person names as work (``work_apps``: an ``app`` or ``package``
  name, trimmed and case-folded; ``title:<text>`` matches inside the window title). No list = unknown.
- Feed leak: active time in a feed app (feeds_evidence.feed_apps) inside a focus block. ``blocks`` are
  ``(start_s, end_s)`` pairs or Glide-style ``{"start", "end"}`` dicts; no block in the covered days =
  leak unknown. Leak per block-hour is feed minutes over block hours; a clean block is 0, not unknown.

Words: ``review_line(this, last)`` is the week review's one line with numbers (Telegram only, never a
prompt); ``t1_label(this, last)`` is the card's digit-free label (T1), e.g. "deep work up on last week
(measured)" or "not recording". ``for_week(reader, week_of, tz, env, home)`` reads every input from config.

Nothing here judges the numbers: no score, no target, no grade. The DB is opened read-only
(``mode=ro``); nothing here writes, creates or locks it. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, time, timedelta, tzinfo
from pathlib import Path
from typing import Iterable, Mapping, Optional
from urllib.parse import quote

from . import apps_reply, aw_desktop, feeds_evidence, glide_provider
from .aw_reader import BUSY_TIMEOUT_S, CURRENT_WINDOW, NS
from .state_reader import StateReader, config

AFK = "afkstatus"
MODALITY = "measured"
DAYS = 7
TITLE = "title:"

_SPANS = (
    "SELECT b.type, e.starttime, e.endtime, e.data FROM events e JOIN buckets b ON b.id = e.bucketrow "
    "WHERE b.type IN (?, ?) AND typeof(e.starttime) = 'integer' AND typeof(e.endtime) = 'integer' "
    "AND e.starttime < ? AND e.endtime > ? ORDER BY e.starttime, e.id"
)


def _merge(spans: Iterable) -> list:
    out = []
    for s, e in sorted(x for x in spans if x[1] > x[0]):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def _cut(a: list, b: list) -> list:
    """The intersection of two merged span lists."""
    out, i, j = [], 0, 0
    while i < len(a) and j < len(b):
        s, e = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if e > s:
            out.append((s, e))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return out


def _total(spans: list) -> float:
    return sum(e - s for s, e in spans)


def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _matcher(names: Iterable):
    """A span -> bool test for a work or feed list, or None when the list names nothing."""
    exact, titles = set(), []
    for v in names or ():
        w = v.strip().casefold() if isinstance(v, str) else ""
        if w.startswith(TITLE):
            if w[len(TITLE):].strip():
                titles.append(w[len(TITLE):].strip())
        elif w:
            exact.add(w)

    def match(span) -> bool:
        return bool(span["names"] & exact) or any(t in span["title"] for t in titles)

    return match if exact or titles else None


def _day_start(d: date, tz: Optional[tzinfo]) -> float:
    if tz is None:
        return datetime.combine(d, time()).timestamp()
    return datetime.combine(d, time(), tzinfo=tz).timestamp()


def _pair(b):
    if isinstance(b, dict):
        return _num(b.get("start")), _num(b.get("end"))
    if isinstance(b, (tuple, list)) and len(b) >= 2:
        return _num(b[0]), _num(b[1])
    return None, None


def _blocks(blocks) -> list:
    out = []
    for b in blocks or ():
        s, e = _pair(b)
        if s is not None and e is not None:
            out.append((s, e))
    return _merge(out)


def _read(path: Path, lo: float, hi: float):
    """(window spans, afk spans) overlapping [lo, hi), cut to it. An afk row is None (away)."""
    uri = "file:" + quote(str(path.resolve())) + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=BUSY_TIMEOUT_S)
    try:
        rows = con.execute(_SPANS, (CURRENT_WINDOW, AFK, int(hi * NS), int(lo * NS))).fetchall()
    finally:
        con.close()
    windows, afk = [], []
    for btype, start, end, data in rows:
        try:
            d = json.loads(data) if data is not None else {}
        except (TypeError, ValueError):
            continue
        if not isinstance(d, dict):
            continue
        s, e = max(start / NS, lo), min(end / NS, hi)
        if e <= s:
            continue
        if btype == AFK:
            if d.get("status") == "not-afk":
                afk.append((s, e))
            elif d.get("status") == "afk":
                afk.append(None)
            continue
        names = {d[k].strip().casefold() for k in ("app", "package") if isinstance(d.get(k), str)} - {""}
        title = d["title"].casefold() if isinstance(d.get("title"), str) else ""
        windows.append({"s": s, "e": e, "names": names, "title": title})
    return windows, afk


def unknown(reason: str) -> dict:
    """Every field unknown (None), with the reason: no DB, an unreadable DB or no valid week."""
    return {"deep_min": None, "block_hours": None, "feed_leak_min": None, "leak_per_block_hour": None,
            "days_with_data": None, "modality": MODALITY,
            "evidence": {"source": "activitywatch", "reason": reason}}


def _week_start(week_of) -> Optional[date]:
    if isinstance(week_of, datetime):
        return week_of.date()
    if isinstance(week_of, date):
        return week_of
    try:
        return date.fromisoformat(week_of) if isinstance(week_of, str) else None
    except ValueError:
        return None


NO_DB = "no ActivityWatch DB at the configured path"


def week(aw_db, week_of, tz: Optional[tzinfo], blocks=None, *, work_apps: Iterable = (),
         feed_apps: Iterable = (), desktop=None) -> dict:
    """The week's flow numbers; every unknown is None with its reason in ``evidence``. Never raises on
    missing or bad input: no DB, an unreadable DB or a bad ``week_of`` gives ``unknown(reason)``.

    ``desktop`` (optional) is ``(lo, hi) -> aw_desktop result`` for the desktop's ActivityWatch: its spans
    (already cut to its own not-afk time, app names only) join the phone's. Off is the phone alone, exactly as
    without it; set and unreadable is ``unknown(reason)``, never zero work. With a desktop on, ``aw_db`` may
    be None (no phone DB set)."""
    start = _week_start(week_of)
    if start is None:
        return unknown("no valid week_of date")
    if aw_db and not Path(aw_db).is_file() or not aw_db and desktop is None:
        return unknown(NO_DB)
    try:
        bounds = [_day_start(start + timedelta(days=i), tz) for i in range(DAYS + 1)]
        lo, hi = bounds[0], bounds[-1]
        windows, afk_rows = _read(Path(aw_db), lo, hi) if aw_db else ([], [])
    except (sqlite3.Error, OSError, ValueError, OverflowError, TypeError):
        return unknown("the ActivityWatch DB could not be read (locked, broken or not an AW DB)")
    desk = desktop(lo, hi) if desktop is not None else None
    sources = None
    if desk is not None and desk.get("state") != aw_desktop.OFF:
        if desk.get("events") is None:
            return unknown(desk.get("why") or aw_desktop.NO_ANSWER)
        sources = (["phone"] if aw_db else []) + [aw_desktop.SOURCE]
        windows = windows + [{"s": s, "e": e, "names": {app.casefold()}, "title": "", "desk": True}
                             for s, e, app in desk["events"]]
    elif not aw_db:
        return unknown(NO_DB)
    seen = [i for i in range(DAYS) if any(w["s"] < bounds[i + 1] and w["e"] > bounds[i] for w in windows)]
    covered = _merge((bounds[i], bounds[i + 1]) for i in seen)
    days = [(start + timedelta(days=i)).isoformat() for i in seen]
    afk = _merge(x for x in afk_rows if x is not None)

    def active(ws) -> list:
        ws = list(ws)
        phone = _merge((w["s"], w["e"]) for w in ws if not w.get("desk"))
        phone = _cut(phone, afk) if afk_rows else phone
        desk_spans = [(w["s"], w["e"]) for w in ws if w.get("desk")]
        return _merge(phone + desk_spans) if desk_spans else phone   # the desktop's spans are cut already

    evidence = {"source": "activitywatch", "days": days, "afk_cut": bool(afk_rows)}
    if sources is not None:
        evidence["sources"] = sources
    out = {"deep_min": None, "block_hours": None, "feed_leak_min": None, "leak_per_block_hour": None,
           "days_with_data": len(days), "modality": MODALITY, "evidence": evidence}
    if not days:
        evidence["reason"] = "no ActivityWatch events this week: unknown, not zero"
        return out

    work = _matcher(work_apps)
    if work is None:
        evidence["deep"] = "unknown: no work apps set (flow_work_apps)"
    else:
        out["deep_min"] = round(_total(active(w for w in windows if work(w))) / 60, 1)
        evidence["deep"] = "active time in the configured work apps"

    data_end = max((w["e"] for w in windows), default=lo)
    block = _cut(_cut(_blocks(blocks), covered), [(lo, data_end)])
    if not block:
        evidence["leak"] = "unknown: no focus blocks on days with data"
        return out
    block_h = _total(block) / 3600
    out["block_hours"] = round(block_h, 2)
    feed = _matcher(feed_apps)
    if feed is None:
        evidence["leak"] = "unknown: no feed apps set (feed_apps)"
        return out
    leak_min = _total(_cut(active(w for w in windows if feed(w)), block)) / 60
    out["feed_leak_min"] = round(leak_min, 1)
    out["leak_per_block_hour"] = round(leak_min / block_h, 1)
    evidence["leak"] = "feed-app active time inside focus blocks"
    return out


# --- words: the Telegram review line (digits allowed) and the card's T1 label (digit-free) ---------------

NO_WORK, NO_BLOCKS, NO_FEEDS = "no work apps set", "no focus blocks", "no feed apps set"
NOT_RECORDING = "not recording"
# Wording only: a change within this fraction of last week reads "about the same". Not a target.
SAME_BAND = 0.1


def _known(r) -> bool:
    return isinstance(r, dict) and isinstance(r.get("days_with_data"), int) and r["days_with_data"] > 0


def _why(r: dict, part: str) -> str:
    text = (r.get("evidence") or {}).get(part, "") if isinstance(r.get("evidence"), dict) else ""
    for words in (NO_WORK, NO_BLOCKS, NO_FEEDS):
        if words in text:
            return words
    return "no data"


def _g(v) -> str:
    return f"{v:g}"


def review_line(this: Optional[dict], last: Optional[dict] = None) -> str:
    """The week review's one flow line, in plain words with the numbers (Telegram only; never a prompt).
    Last week's number sits beside this week's when known; nothing says whether either is enough."""
    if not _known(this):
        return f"Flow: {NOT_RECORDING} this week (no ActivityWatch data)."
    prev = last if _known(last) else {}
    if this["deep_min"] is None:
        deep = f"deep work unknown ({_why(this, 'deep')})"
    else:
        deep = f"deep work {round(this['deep_min'])} min"
        if prev.get("deep_min") is not None:
            deep += f" (last week {round(prev['deep_min'])})"
    if this["leak_per_block_hour"] is None:
        leak = f"feed leak unknown ({_why(this, 'leak')})"
    else:
        leak = (f"feed leak {_g(this['leak_per_block_hour'])} min per block-hour over "
                f"{_g(this['block_hours'])} block-hours")
        if prev.get("leak_per_block_hour") is not None:
            leak += f" (last week {_g(prev['leak_per_block_hour'])})"
    return f"Flow ({MODALITY}, {this['days_with_data']} of {DAYS} days): {deep}; {leak}."


def _direction(now: float, before: float) -> str:
    if before <= 0:
        return "about the same" if now <= 0 else "up"
    ratio = now / before
    return "up" if ratio > 1 + SAME_BAND else "down" if ratio < 1 - SAME_BAND else "about the same"


def t1_label(this: Optional[dict], last: Optional[dict] = None) -> str:
    """The card's digit-free label: deep work up, down or about the same on last week (minutes per day
    with data, so a short week is not a drop), plus the feed-leak direction when both weeks have one."""
    if not _known(this):
        return NOT_RECORDING
    if this["deep_min"] is None:
        return f"deep work unknown, {NO_WORK} ({MODALITY})"
    if not _known(last) or last.get("deep_min") is None:
        return f"deep work recorded, nothing last week to compare ({MODALITY})"
    word = _direction(this["deep_min"] / this["days_with_data"], last["deep_min"] / last["days_with_data"])
    out = f"deep work {word} on last week"
    if this.get("leak_per_block_hour") is not None and last.get("leak_per_block_hour") is not None:
        out += f"; feed leak {_direction(this['leak_per_block_hour'], last['leak_per_block_hour'])} on last week"
    return f"{out} ({MODALITY})"


# --- config: where each input comes from ---------------------------------------------------------------

WORK_ENV, WORK_CONFIG = apps_reply.ENV_KEYS[apps_reply.WORK], apps_reply.CONFIG_KEYS[apps_reply.WORK]


def work_apps(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> tuple:
    """The person's work apps: $LIMITLESS_FLOW_WORK_APPS (comma list), else config ``flow_work_apps``
    (a list or a comma string), else apps.json set from a reply (apps_reply.list_for); () when unset. The
    repo ships no list, so deep work starts unknown."""
    return apps_reply.host_list(apps_reply.WORK, env, home)


def glide_blocks(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> Optional[list]:
    """The focus block in Glide's attention.json (path as GlideProvider.from_config), as ``[{start, end}]``;
    [] when the file has none or cannot be read; None when Glide is not configured. Glide keeps only its
    current block (a stopped block is cleared), so this sees at most one block."""
    env = os.environ if env is None else env
    path = env.get(glide_provider.ENV_KEY) or config(env, home).get(glide_provider.CONFIG_KEY)
    if not isinstance(path, str) or not path:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    block = data.get("block") if isinstance(data, dict) else None
    s, e = _pair(block) if isinstance(block, dict) else (None, None)
    return [{"start": s, "end": e}] if s is not None and e is not None else []


def for_week(reader: StateReader, week_of, tz: Optional[tzinfo], env: Optional[Mapping[str, str]] = None,
             home: Optional[Path] = None) -> dict:
    """week() with every input from config: the AW DB (StateReader.aw_db_path), the desktop's ActivityWatch
    (aw_desktop.for_config: config desktop_aw_url or desktop_aw_export; off when unset), the work apps, the
    feed apps (feeds_evidence.feed_apps) and the Glide block. Read-only."""
    return week(reader.aw_db_path(env, home), week_of, tz, blocks=glide_blocks(env, home),
                work_apps=work_apps(env, home), feed_apps=feeds_evidence.feed_apps(env, home),
                desktop=lambda lo, hi: aw_desktop.for_config(env, home, lo, hi))
