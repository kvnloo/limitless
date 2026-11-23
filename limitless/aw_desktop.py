"""The desktop's app activity from its own ActivityWatch server (or a copied export), read-only.

    got = read_events(url, since, until, fetch=None)   # {"events": [(start_s, end_s, app)] | None, "state",
                                                       #  "why", "newest"}
    got = read_export(path, since, until)              # the same, from an aw-server export file
    got = for_config(env, home, lo, hi)                # from config desktop_aw_url, else desktop_aw_export
    rs = rows(got)                                     # blocks' row shape, labelled source "desktop"

The server is read through its public REST API: ``GET /api/0/buckets/`` (bucket id -> metadata with
``type`` and ``hostname``) and ``GET /api/0/buckets/<id>/events?start=&end=&limit=-1`` (events
``{"timestamp", "duration", "data"}``, timestamp ISO-8601, duration in seconds). Buckets are found by
``type``, never by name: ``currentwindow`` (data ``app``, ``title``) and ``afkstatus`` (data ``status``,
"afk" or "not-afk"). An export (``GET /api/0/export``, or the web UI's export) is
``{"buckets": {<id>: {..., "events": [...]}}}`` and reads the same way, for a host with no network path to
the desktop.

Window spans are cut to the not-afk spans of the afk bucket on the same host: a window left open while the
person is away is not activity. A host with a window bucket and no afk bucket is unknown, never "all
active". Only the ``app`` name is read from a window event; the window title is T0 and is dropped at read
time: it is in no return value, no row and no reason. Host names and bucket ids are not kept either.

Unset config is off: no network call, no file read. Every failure (no answer, a timeout, a body that is not
ActivityWatch data, a missing or broken export) is unknown (``events`` None) with a plain reason that has
no digit, no address and no path; nothing here raises. Unknown is never zero: a caller must not read a
missing desktop as "no work". The fetch timeout is short (TIMEOUT_S). Nothing here writes or sends.
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import math
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional
from urllib.parse import quote, urlencode, urlsplit

from .state_reader import config, state_dir

URL_CONFIG, EXPORT_CONFIG = "desktop_aw_url", "desktop_aw_export"
CURRENT_WINDOW, AFK = "currentwindow", "afkstatus"
SOURCE = "desktop"
TIMEOUT_S = 2.0                     # a desktop that is asleep or off reads as unreachable quickly
MAX_BYTES = 64 * 1024 * 1024        # a body larger than this is not read
HOLD_S = 300.0                      # after no answer, for_config does not ask the same server again this soon
_HOLD: dict = {}                    # server -> monotonic second until which it reads unreachable, unasked

OFF, LIVE, UNKNOWN, UNREACHABLE = "off", "live", "unknown", "unreachable"
OFF_WHY = "desktop ActivityWatch is not set (desktop_aw_url or desktop_aw_export)"
BAD_URL = "desktop_aw_url is not an http address"
BAD_SPAN = "no valid time span to read"
NO_ANSWER = "the desktop ActivityWatch server did not answer"
NOT_AW = "the desktop ActivityWatch server sent something that is not ActivityWatch data"
NO_WINDOW = "no window bucket on the desktop ActivityWatch server"
NO_AFK = "no afk bucket beside the desktop window bucket, so away time cannot be removed"
NO_EXPORT = "the desktop ActivityWatch export could not be read"

Fetch = Callable[[str, float], bytes]


def urllib_fetch(url: str, timeout: float) -> bytes:
    """GET ``url`` and return the body; raises OSError (or ValueError) on any failure."""
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:   # noqa: S310 - http(s) only, checked by caller
        body = resp.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("body too large")
    return body


def _result(events, state: str, why: str = "") -> dict:
    newest = max((e for _, e, _ in events), default=None) if events is not None else None
    return {"events": events, "state": state, "why": why, "newest": newest}


def _unknown(why: str, state: str = UNKNOWN) -> dict:
    return _result(None, state, why)


def _num(v) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    v = float(v)
    return v if math.isfinite(v) else None


_ISO = re.compile(r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:?\d{2})?$")


def _ts(v) -> Optional[float]:
    """Epoch seconds from an aw-server timestamp (ISO-8601, Z or offset, any fraction; naive = UTC)."""
    m = _ISO.match(v.strip()) if isinstance(v, str) else None
    if m is None:
        return None
    try:
        t = datetime.fromisoformat(m.group(1).replace(" ", "T")).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    frac, off = m.group(2), m.group(3)
    if off and off != "Z":
        sign = 1 if off[0] == "+" else -1
        hh, mm = int(off[1:3]), int(off[-2:])
        t -= sign * timedelta(hours=hh, minutes=mm)
    return t.timestamp() + (float("0." + frac) if frac else 0.0)


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def _merge(spans) -> list:
    out = []
    for s, e in sorted(x for x in spans if x[1] > x[0]):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def _spans(events, lo: float, hi: float):
    """(start, end, data) for each valid event, cut to [lo, hi)."""
    for ev in events if isinstance(events, list) else ():
        if not isinstance(ev, dict) or not isinstance(ev.get("data"), dict):
            continue
        s, d = _ts(ev.get("timestamp")), _num(ev.get("duration"))
        if s is None or d is None or d <= 0:
            continue
        s, e = max(s, lo), min(s + d, hi)
        if e > s:
            yield s, e, ev["data"]


def _events(buckets, events_of: Callable[[str], list], lo: float, hi: float) -> dict:
    """The shared read: ``buckets`` id -> metadata; ``events_of(id)`` the bucket's events."""
    if not isinstance(buckets, dict):
        return _unknown(NOT_AW)
    meta = [(bid, b) for bid, b in buckets.items() if isinstance(bid, str) and isinstance(b, dict)]

    def host(b) -> str:
        return b["hostname"] if isinstance(b.get("hostname"), str) else ""

    windows = [(bid, host(b)) for bid, b in meta if b.get("type") == CURRENT_WINDOW]
    afks = [(bid, host(b)) for bid, b in meta if b.get("type") == AFK]
    if not windows:
        return _unknown(NO_WINDOW)
    hosts = {h for _, h in afks}
    windows = [(bid, h) for bid, h in windows if h in hosts]
    if not windows:
        return _unknown(NO_AFK)
    here = {}
    for bid, h in afks:
        if h in {wh for _, wh in windows}:
            here.setdefault(h, []).extend((s, e) for s, e, d in _spans(events_of(bid), lo, hi)
                                          if d.get("status") == "not-afk")
    here = {h: _merge(v) for h, v in here.items()}
    out = []
    for bid, h in windows:
        for s, e, d in _spans(events_of(bid), lo, hi):
            app = d.get("app").strip() if isinstance(d.get("app"), str) else ""   # the title is never read
            if not app:
                continue
            for a, b in here.get(h, ()):
                cs, ce = max(s, a), min(e, b)
                if ce > cs:
                    out.append((cs, ce, app))
    return _result(sorted(out), LIVE)


def _span_ok(since, until) -> bool:
    return _num(since) is not None and _num(until) is not None and float(until) > float(since)


def _base(url) -> Optional[str]:
    if not isinstance(url, str):
        return None
    url = url.strip().rstrip("/")
    parts = urlsplit(url)
    return url if parts.scheme in ("http", "https") and parts.netloc else None


def read_events(url, since, until, fetch: Optional[Fetch] = None, timeout: float = TIMEOUT_S) -> dict:
    """The desktop's active app spans in [since, until) from the aw-server at ``url``. Never raises."""
    base = _base(url)
    if base is None:
        return _unknown(BAD_URL)
    if not _span_ok(since, until):
        return _unknown(BAD_SPAN)
    lo, hi = float(since), float(until)
    fetch = fetch or urllib_fetch
    q = urlencode({"start": _iso(lo), "end": _iso(hi), "limit": -1})

    class _NoAnswer(Exception):
        pass

    def get(path: str):
        try:
            body = fetch(base + path, timeout)
        except Exception:  # noqa: BLE001 - any failure to answer is unreachable, never a crash
            raise _NoAnswer from None
        try:
            return json.loads(body)
        except (TypeError, ValueError):
            return None

    try:
        buckets = get("/api/0/buckets/")

        def events_of(bid: str) -> list:
            got = get(f"/api/0/buckets/{quote(bid, safe='')}/events?{q}")
            return got if isinstance(got, list) else []

        return _events(buckets, events_of, lo, hi)
    except _NoAnswer:
        return _unknown(NO_ANSWER, UNREACHABLE)
    except Exception:  # noqa: BLE001 - odd data reads as unknown
        return _unknown(NOT_AW)


def read_export(path, since, until) -> dict:
    """The same read from an aw-server export file (``{"buckets": {id: {..., "events": [...]}}}``, or the
    bare bucket mapping). A missing or broken file is unknown; its path is never in the reason."""
    if not _span_ok(since, until):
        return _unknown(BAD_SPAN)
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return _unknown(NO_EXPORT)
    buckets = data.get("buckets", data) if isinstance(data, dict) else None
    if not isinstance(buckets, dict):
        return _unknown(NO_EXPORT)
    try:
        return _events(buckets, lambda bid: buckets[bid].get("events") or [], float(since), float(until))
    except Exception:  # noqa: BLE001
        return _unknown(NO_EXPORT)


def _setting(env: Optional[Mapping[str, str]], home: Optional[Path], key: str) -> Optional[str]:
    v = config(env, home).get(key)
    return v.strip() if isinstance(v, str) and v.strip() else None


def configured(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> bool:
    """True when config names a desktop source (desktop_aw_url or desktop_aw_export)."""
    return _setting(env, home, URL_CONFIG) is not None or _setting(env, home, EXPORT_CONFIG) is not None


def for_config(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None, lo: float = 0.0,
               hi: float = 0.0, fetch: Optional[Fetch] = None, timeout: float = TIMEOUT_S) -> dict:
    """read_events on config ``desktop_aw_url``, else read_export on ``desktop_aw_export`` (a relative path is
    in the state dir), else off: no fetch, no file read. A server that did not answer reads unreachable,
    unasked, for HOLD_S (a desktop that is asleep must not slow every card build)."""
    url = _setting(env, home, URL_CONFIG)
    if url is not None:
        base = _base(url) or url
        if _HOLD.get(base, -math.inf) > time.monotonic():
            return _unknown(NO_ANSWER, UNREACHABLE)
        got = read_events(url, lo, hi, fetch=fetch, timeout=timeout)
        if got["state"] == UNREACHABLE:
            _HOLD[base] = time.monotonic() + HOLD_S
        else:
            _HOLD.pop(base, None)
        return got
    exp = _setting(env, home, EXPORT_CONFIG)
    if exp is not None:
        p = Path(exp).expanduser()
        return read_export(p if p.is_absolute() else state_dir(env, home) / p, lo, hi)
    return _result(None, OFF, OFF_WHY)


def rows(got: Optional[dict]) -> Optional[list]:
    """The events as blocks' row shape ``{start, end, names, title: "", source: "desktop"}``; None when
    unknown or off."""
    evs = got.get("events") if isinstance(got, dict) else None
    if evs is None:
        return None
    return [{"start": s, "end": e, "names": [app.casefold()], "title": "", "source": SOURCE} for s, e, app in evs]
