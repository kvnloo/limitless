"""Wearable sleep from a self-hosted Open Wearables server, for the same sleep_file noop_export writes.

    got = fetch_sleep(base_url, api_key, since, user=user_id, http=None, until=None, tz=None)
    # {"sleep": [{"night", "asleep_s", "source": "open_wearables", "start", "end"}, ...],
    #  "reason": str | None, "skipped": {"nap", "not_wearable", "no_asleep_time", "not_a_night"}}

Open Wearables (github.com/the-momentum/open-wearables, MIT) is an open-source, self-hosted wearable data
platform. Its documented REST API (docs/api-reference/introduction.mdx, docs/openapi.json; route
backend/app/api/routes/v1/events.py ``list_sleep_sessions``) lists a user's sleep sessions at
``GET {base}/api/v1/users/{user_id}/events/sleep?start_date=...&end_date=...[&cursor=...]`` with the API key in the
``X-Open-Wearables-API-Key`` header (not a Bearer token). The answer is ``{"data": [SleepSession, ...],
"pagination": {"next_cursor", "has_more", ...}, "metadata": {...}}``; a SleepSession has ``start_time``,
``end_time`` (ISO-8601), ``sleep_duration_seconds`` (time asleep, awake excluded), ``stages`` (minutes per stage),
``is_nap`` and ``source.device_type``.

The rows are noop_export's sleep rows (``noop_export.sleep_row``'s keys, its night rule and its limits), so every
reader of sleep_file works unchanged. Time asleep is ``sleep_duration_seconds``, else light + deep + REM minutes;
time in bed is never taken as sleep. Naps and sessions from a phone, tablet, scale or smart display are skipped.
Per night the session with the most sleep wins, the earlier onset on a tie.

Never raises and never writes. Every failure is one plain reason in words (REASONS) with no rows; no reason, row or
exception text carries the API key, the URL or the user id. The http callable is injected so tests never touch
the network: ``http(url, headers, timeout) -> (status, body bytes)``, raising OSError (or TimeoutError) when the
server cannot be reached.
"""
from __future__ import annotations

import json
import math
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, Mapping, Optional
from urllib.parse import quote, urlencode, urlsplit

from .noop_export import merge, night_of, nights_words, sleep_row, words, write_atomic
from .state_reader import MAX_ASLEEP_S, StateReader, config, parse_ts, state_dir

SOURCE = "open_wearables"     # the one source name these sleep rows carry: never a provider, device or id
API = "/api/v1"
HEADER = "X-Open-Wearables-API-Key"
TIMEOUT_S = 20
PAGE_LIMIT = 100              # sessions per page (the API allows 1..1000)
MAX_PAGES = 50                # a server that keeps saying "more" is read this far and no further
ASLEEP_STAGES = ("light_minutes", "deep_minutes", "rem_minutes")
NOT_WEARABLE = ("phone", "tablet", "scale", "smart_display")   # SourceMetadata.device_type values that are not worn

NO_URL = 'no Open Wearables server configured (set "open_wearables_url" in config.json)'
BAD_URL = "the Open Wearables server address is not an http or https address"
NO_USER = 'no Open Wearables user configured (set "open_wearables_user" in config.json)'
NO_KEY = "no Open Wearables API key (set the environment variable LIMITLESS_OW_KEY)"
REFUSED = "the Open Wearables server refused the API key"
NOT_FOUND = "the Open Wearables server does not know that user or address"
HTTP_ERROR = "the Open Wearables server answered with an error"
TIMEOUT = "the Open Wearables server did not answer in time"
UNREACHABLE = "the Open Wearables server could not be reached"
BAD_JSON = "the Open Wearables server's answer is not the sleep list this reader knows"
REASONS = (NO_URL, BAD_URL, NO_USER, NO_KEY, REFUSED, NOT_FOUND, HTTP_ERROR, TIMEOUT, UNREACHABLE, BAD_JSON)

Http = Callable[[str, dict, float], tuple]


class _Fail(Exception):
    """A failure with one of REASONS; carries nothing else."""


def urllib_get(url: str, headers: dict, timeout: float) -> tuple:
    """The default http callable: GET with urllib; an HTTP error status is returned, not raised."""
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:   # noqa: S310 - http(s) only, checked by caller
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, b""


def _empty(reason: Optional[str]) -> dict:
    return {"sleep": [], "reason": reason, "skipped": {}}


def endpoint(base_url: str, user: str) -> str:
    """``{base}/api/v1/users/{user}/events/sleep``; a base that already ends in /api/v1 is not doubled."""
    base = base_url.strip().rstrip("/")
    if base.endswith(API):
        base = base[: -len(API)]
    return f"{base}{API}/users/{quote(user.strip(), safe='')}/events/sleep"


def _day(v) -> str:
    return v.isoformat() if isinstance(v, (date, datetime)) else str(v)


def _get(http: Http, url: str, key: str, timeout: float) -> dict:
    try:
        status, raw = http(url, {HEADER: key, "Accept": "application/json"}, timeout)
    except (socket.timeout, TimeoutError):
        raise _Fail(TIMEOUT) from None
    except urllib.error.URLError as e:
        raise _Fail(TIMEOUT if isinstance(e.reason, (socket.timeout, TimeoutError)) else UNREACHABLE) from None
    except Exception:  # noqa: BLE001 - any other failure (a bad header value, a refused socket) is unreachable
        raise _Fail(UNREACHABLE) from None
    if status in (401, 403):
        raise _Fail(REFUSED)
    if status == 404:
        raise _Fail(NOT_FOUND)
    if status != 200:
        raise _Fail(HTTP_ERROR)
    try:
        got = json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)
    except (ValueError, TypeError, AttributeError):
        raise _Fail(BAD_JSON) from None
    if not isinstance(got, dict) or not isinstance(got.get("data"), list):
        raise _Fail(BAD_JSON)
    return got


def sessions(base_url: str, key: str, user: str, since, until, http: Http, timeout: float) -> list:
    """Every sleep session in [since, until], following ``pagination.next_cursor`` up to MAX_PAGES pages."""
    out, cursor = [], None
    for _ in range(MAX_PAGES):
        q = {"start_date": _day(since), "end_date": _day(until), "limit": PAGE_LIMIT}
        if cursor:
            q["cursor"] = cursor
        got = _get(http, endpoint(base_url, user) + "?" + urlencode(q), key, timeout)
        out += got["data"]
        pag = got.get("pagination") if isinstance(got.get("pagination"), dict) else {}
        cursor = pag.get("next_cursor")
        if pag.get("has_more") is not True or not isinstance(cursor, str) or not cursor:
            break
    return out


def _int(v) -> Optional[int]:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return int(v)


def asleep_seconds(s: dict) -> Optional[int]:
    """``sleep_duration_seconds``, else light + deep + REM minutes; None when neither is there."""
    secs = _int(s.get("sleep_duration_seconds"))
    if secs is not None:
        return secs
    st = s.get("stages")
    if not isinstance(st, dict):
        return None
    mins = [_int(st.get(k)) for k in ASLEEP_STAGES]
    mins = [m for m in mins if m is not None]
    return sum(mins) * 60 if mins else None


def sleep_nights(items: list, tz=None) -> tuple:
    """(night -> {"night", "onset", "end", "asleep_s"}, skipped counts) over Open Wearables SleepSession dicts."""
    best, skipped = {}, {"nap": 0, "not_wearable": 0, "no_asleep_time": 0, "not_a_night": 0}
    for s in items:
        if not isinstance(s, dict):
            skipped["not_a_night"] += 1
            continue
        if s.get("is_nap") is True:
            skipped["nap"] += 1
            continue
        src = s.get("source") if isinstance(s.get("source"), dict) else {}
        if src.get("device_type") in NOT_WEARABLE:
            skipped["not_wearable"] += 1
            continue
        a, b = parse_ts(s.get("start_time")), parse_ts(s.get("end_time"))
        if a is None or b is None or not (math.isfinite(a) and math.isfinite(b)) or not 0 < b - a <= MAX_ASLEEP_S:
            skipped["not_a_night"] += 1
            continue
        onset, end = int(a), int(b)
        asleep = asleep_seconds(s)
        if asleep is None:
            skipped["no_asleep_time"] += 1
            continue
        night = night_of(onset, tz)
        if night is None or not 0 < asleep <= MAX_ASLEEP_S:
            skipped["not_a_night"] += 1
            continue
        row = {"night": night, "onset": onset, "end": end, "asleep_s": asleep}
        old = best.get(night)
        if old is None or (asleep, -onset) > (old["asleep_s"], -old["onset"]):
            best[night] = row
    return {n: best[n] for n in sorted(best)}, skipped


def ow_row(s: dict) -> dict:
    """noop_export's sleep row for one night, with this source."""
    return dict(sleep_row(s), source=SOURCE)


def fetch_sleep(base_url, api_key, since, http: Optional[Http] = None, *, user=None, until=None, tz=None,
                timeout: float = TIMEOUT_S) -> dict:
    """The nightly sleep rows from the Open Wearables server at ``base_url`` for ``user``, sessions from ``since``
    through ``until`` (default: tomorrow, so last night is in). Never raises, never writes."""
    if not isinstance(base_url, str) or not base_url.strip():
        return _empty(NO_URL)
    if urlsplit(base_url.strip()).scheme not in ("http", "https") or not urlsplit(base_url.strip()).netloc:
        return _empty(BAD_URL)
    if not isinstance(user, str) or not user.strip():
        return _empty(NO_USER)
    if not isinstance(api_key, str) or not api_key.strip():
        return _empty(NO_KEY)
    until = date.today() + timedelta(days=1) if until is None else until
    try:
        items = sessions(base_url, api_key.strip(), user, since, until, http or urllib_get, timeout)
    except _Fail as e:
        return _empty(str(e))
    except Exception:  # noqa: BLE001 - never a traceback, never the exception's text
        return _empty(UNREACHABLE)
    nights, skipped = sleep_nights(items, tz)
    out = _empty(None)
    out.update(sleep=[ow_row(s) for s in nights.values()], skipped=skipped)
    return out


# --- the CLI: bin/limitless-ow-export -------------------------------------------------------------------------

EXPORT_CONFIG, URL_CONFIG, USER_CONFIG = "open_wearables_export", "open_wearables_url", "open_wearables_user"
KEY_ENV = "LIMITLESS_OW_KEY"   # the API key comes from this variable only: never config.json, never printed
OFF, DRY_RUN, WRITE = "off", "dry_run", "write"
MODES = (OFF, DRY_RUN, WRITE)
DAYS = 30                      # sessions from this many days before today are read on each run
MARK = "open-wearables.json"   # the last run: when, which mode, done or failed, and the line it said
DONE, FAILED = "done", "failed"
USAGE = "usage: limitless-ow-export [--write]"
IS_OFF = f"the Open Wearables export is off (config {EXPORT_CONFIG})"
SKIP_WORDS = (("nap", "nap", ""), ("not_wearable", "session", " not from a wearable"),
              ("no_asleep_time", "session", " with no asleep time"), ("not_a_night", "session", " not a night"))


def mode(cfg) -> str:
    """Config ``open_wearables_export``: off (the default, and any value not in MODES), dry_run or write."""
    v = cfg.get(EXPORT_CONFIG) if isinstance(cfg, Mapping) else None
    v = v.strip().lower() if isinstance(v, str) else v
    return v if v in MODES else OFF


def _skipped(skipped: dict) -> str:
    parts = [f"{words(skipped[k])} {noun}{'' if skipped[k] == 1 else 's'}{why}"
             for k, noun, why in SKIP_WORDS if skipped.get(k)]
    return ("; skipped " + ", ".join(parts)) if parts else ""


def merge_sleep(existing: str, rows: list) -> tuple:
    """(new text, rows new or changed, nights kept from another source): ``rows`` (ours) merged into the sleep
    file text with noop_export.merge by night and source. A night that a row of another source already holds keeps
    only that row: our row for it is not added, and a row of ours left from an earlier run is dropped."""
    held, lines = set(), []
    parsed = []
    for ln in existing.splitlines():
        try:
            r = json.loads(ln)
        except ValueError:
            r = None
        ok = isinstance(r, dict) and isinstance(r.get("night"), str)
        parsed.append((ln, r if ok else None))
        if ok and r.get("source") != SOURCE:
            held.add(r["night"])
    for ln, r in parsed:
        if r is not None and r.get("source") == SOURCE and r["night"] in held:
            continue
        lines.append(ln + "\n")
    ours = [r for r in rows if r["night"] not in held]
    text, changed = merge("".join(lines), ours, ("night", "source"))
    return text, changed, len(rows) - len(ours)


def load_mark(state) -> dict:
    """open-wearables.json as ``{"ran_at", "mode", "outcome", "said"}``; {} when missing or malformed."""
    try:
        data = json.loads((Path(state) / MARK).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    at = data.get("ran_at")
    ok_at = isinstance(at, (int, float)) and not isinstance(at, bool) and math.isfinite(at)
    return {"ran_at": float(at) if ok_at else None,
            "mode": data.get("mode") if data.get("mode") in MODES else None,
            "outcome": data.get("outcome") if data.get("outcome") in (DONE, FAILED) else None,
            "said": data.get("said") if isinstance(data.get("said"), str) else None}


def _mark(state: Path, now: float, run_mode: str, outcome: str, said: str) -> None:
    try:
        write_atomic(state / MARK, json.dumps({"ran_at": now, "mode": run_mode, "outcome": outcome, "said": said},
                                              sort_keys=True) + "\n")
    except OSError:
        pass   # the mark is a note for the doctor; a run never fails on it


def main(argv, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None, tz=None, out=None, err=None,
         http: Optional[Http] = None, today: Optional[date] = None, now: Optional[float] = None) -> int:
    """The CLI: 0 when done or off, 1 when the server cannot be read or the sleep file cannot be written (one
    plain line why on stderr, nothing written), 2 for bad arguments. Prints counts in words; never a path, the
    URL, the user, the key or a reading."""
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    env = os.environ if env is None else env
    args = list(argv)
    if args not in ([], ["--write"]):
        print(USAGE, file=err)
        return 2
    cfg = config(env, home)
    run_mode = mode(cfg)
    if run_mode == OFF:
        print(IS_OFF, file=out)
        return 0
    state = state_dir(env, home)
    now = time.time() if now is None else now
    today = date.today() if today is None else today

    def fail(line: str) -> int:
        print(line, file=err)
        _mark(state, now, run_mode, FAILED, line)
        return 1

    got = fetch_sleep(cfg.get(URL_CONFIG), env.get(KEY_ENV), today - timedelta(days=DAYS), http,
                      user=cfg.get(USER_CONFIG), until=today + timedelta(days=1), tz=tz)
    if got["reason"] is not None:
        return fail(got["reason"])
    found = f"{nights_words(len(got['sleep']))} of wearable sleep from Open Wearables{_skipped(got['skipped'])}"
    if not args or run_mode == DRY_RUN:
        hint = "(run with --write to write them)" if run_mode == WRITE else \
            f'(config {EXPORT_CONFIG} "{WRITE}" writes them)'
        line = f"dry run: {found}; nothing written {hint}"
        print(line, file=out)
        _mark(state, now, run_mode, DONE, line)
        return 0
    print(f"found {found}", file=out)
    path = StateReader(state).sleep_file(env, home)
    if path is None:
        return fail('sleep file: not configured (set "sleep_file" in config.json), not written')
    try:
        old = path.read_text(encoding="utf-8") if path.is_file() else ""
        text, changed, kept = merge_sleep(old, got["sleep"])
        if text != old:
            write_atomic(path, text)
    except (OSError, ValueError) as e:
        return fail(f"sleep file: not written: {getattr(e, 'strerror', None) or type(e).__name__}")
    tail = f"; {nights_words(kept)} kept from another source" if kept else ""
    line = "sleep file: unchanged" + tail if text == old else \
        f"sleep file: written, {nights_words(changed)} new or changed{tail}"
    print(line, file=out)
    _mark(state, now, run_mode, DONE, line)
    return 0
