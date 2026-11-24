"""Uptime audit: were the inputs fresh, day by day? Read-only, over the sync's own runs.jsonl (north-star row one).

    rows, skipped = parse_lines(text)          # runs.jsonl text -> dated rows, count of bad lines
    got = read_log(path)                       # (rows, skipped), or None when the file cannot be read
    audit(rows, inputs=(), days=28, ...)       # -> dict: T0 counts per input and per day

The log is the one the sync appends, one row per run (StateReader.last_run reads its last row); this module never
changes how it is written. The fields relied on:

- ``at``: an ISO-8601 UTC time ("...Z"); the row's local day is read in ``tz`` (default this machine's zone,
  like delivery_audit). A row with no readable ``at`` is skipped and counted.
- ``inputs``: on newer rows, the string ``"stale a,b,c"``: the input names that were stale on that run, comma
  separated (``"stale"`` with no name: none was). Older rows have no ``inputs`` key at all. A row without it, or
  with any other value, is unknown for that run: never fresh, never stale.

Per input and local day of the window (the ``days`` days ending ``today``): fresh when at least one run that day
has ``inputs`` and does not list the input; stale when every such run lists it; unknown when the day has no run
or only unknown rows. unknown is never fresh and never stale. The inputs judged are ``inputs`` (the names the
caller knows, e.g. inputs.json) plus every name a row in the window lists, minus ``ignore`` (config
``outage_ignore``, the same names the outage line leaves out). A day is "every input fresh" when it is known and
no judged input is stale that day.

Config: ``uptime_days`` (the window, a whole number of days, default DAYS) and ``uptime_target`` (the share of
window days that must be every-input-fresh, above zero and at most one, default TARGET). The share is over the
whole window, so an unknown day counts against the goal, never for it.
Pure: no clock, no file except read_log, no send. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Iterable, Mapping, Optional

from .state_reader import parse_ts

DAYS = 28
TARGET = 0.95
DAYS_CONFIG, TARGET_CONFIG = "uptime_days", "uptime_target"
LOG_NAME = "runs.jsonl"
STALE_WORD = "stale"
MODALITY = "measured"            # runs.jsonl is the sync's own record of each run
MIN_KNOWN_DAYS = 7               # fewer known days than this: the label is UNKNOWN
UNKNOWN = "unknown"
FRESH_ALL, FRESH_KNOWN, FRESH_MOST = "fresh every day", "fresh every known day", "fresh most days"
FRESH_HALF, STALE_MOST, STALE_KNOWN = "fresh about half the days", "stale most days", "stale every known day"
PHRASES = (FRESH_ALL, FRESH_KNOWN, FRESH_MOST, FRESH_HALF, STALE_MOST, STALE_KNOWN,
           "stale all week", "stale all month", "stale every day")       # the label's order, best first
NONE_NAMED = "no input was reported stale"
GOAL_MET, GOAL_NOT_MET, GOAL_UNKNOWN = "met", "not met", "unknown"
NO_LOG_REASON = "no sync run log in the state dir (runs.jsonl)"
NO_ROWS_REASON = "no sync run in the audit window"
FEW_KNOWN_REASON = "fewer than a week of sync runs name their stale inputs"
GOAL_WORDS = {GOAL_MET: "uptime goal met", GOAL_NOT_MET: "uptime goal not met",
              GOAL_UNKNOWN: "uptime goal unknown: too many days without input words"}


def _at(r) -> Optional[float]:
    """Epoch seconds of a row's ``at``; None when it is not a time a local date can be read from."""
    if not isinstance(r, dict):
        return None
    t = parse_ts(r.get("at"))
    if t is None or not math.isfinite(t):
        return None
    try:
        datetime.fromtimestamp(t)
    except (OverflowError, OSError, ValueError):
        return None
    return t


def valid(r) -> bool:
    """A row the audit can read: an object with a readable ``at``."""
    return _at(r) is not None


def stale_names(r) -> Optional[set]:
    """The input names a run lists as stale (a set, maybe empty); None when the run says nothing about its
    inputs (no ``inputs`` key, or a value that is not ``"stale ..."``)."""
    v = r.get("inputs") if isinstance(r, dict) else None
    if not isinstance(v, str):
        return None
    head, _, rest = v.strip().partition(" ")
    if head != STALE_WORD:
        return None
    return {n.strip() for n in rest.split(",") if n.strip()}


def parse_lines(text: str) -> tuple:
    """(rows, skipped): the dated rows of runs.jsonl ``text`` in file order and the number of non-blank lines
    that were not (broken JSON, a cut line, a row without a readable ``at``)."""
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


def window_days(cfg: Optional[Mapping] = None) -> int:
    """Config ``uptime_days`` (a whole number, at least one); anything else is DAYS."""
    v = cfg.get(DAYS_CONFIG) if isinstance(cfg, Mapping) else None
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 1 else DAYS


def target(cfg: Optional[Mapping] = None) -> float:
    """Config ``uptime_target`` (a number above zero and at most one); anything else is TARGET."""
    v = cfg.get(TARGET_CONFIG) if isinstance(cfg, Mapping) else None
    ok = isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and 0 < v <= 1
    return float(v) if ok else TARGET


def _day(r: dict, tz: Optional[tzinfo]) -> date:
    return datetime.fromtimestamp(_at(r), tz).date()


def audit(rows: Iterable, inputs: Iterable = (), days: int = DAYS, *, today: Optional[date] = None,
          tz: Optional[tzinfo] = None, ignore: Iterable = (), target: float = TARGET, skipped: int = 0) -> dict:
    """The uptime audit of ``rows`` over the ``days`` local days ending ``today`` (default: the newest row's
    day). T0 counts per input (fresh, stale, unknown days) and per day. See the module doc."""
    good, bad = [], int(skipped or 0)
    for r in rows or ():
        if valid(r):
            good.append(r)
        else:
            bad += 1
    if today is None:
        today = max((_day(r, tz) for r in good), default=None)
    n = max(int(days), 1)
    window = [] if today is None else [today - timedelta(days=k) for k in range(n - 1, -1, -1)]
    by_day = {d: [] for d in window}
    for r in good:
        d = _day(r, tz)
        if d in by_day:
            by_day[d].append(r)
    skip = {x for x in ignore or () if isinstance(x, str)}
    said = {d: [s for s in (stale_names(r) for r in got) if s is not None] for d, got in by_day.items()}
    given = list(dict.fromkeys(x for x in inputs or () if isinstance(x, str) and x))
    seen = set()
    for runs in said.values():
        for s in runs:
            seen |= s
    names = [x for x in given + sorted(seen - set(given)) if x not in skip]   # the caller's order, then the rest
    per = {name: {"fresh": 0, "stale": 0, "unknown": 0} for name in names}
    out = {"days": [], "window_days": len(window), "known_days": 0, "all_fresh_days": 0, "skipped": bad}
    for d in window:
        runs = said[d]
        known = bool(runs)
        stale = sorted(x for x in names if all(x in s for s in runs)) if known else None
        for name in names:
            per[name]["unknown" if not known else "stale" if name in stale else "fresh"] += 1
        out["days"].append({"day": d.isoformat(), "runs": len(by_day[d]), "known_runs": len(runs),
                            "stale": stale, "all_fresh": (not stale) if known else None})
        if known:
            out["known_days"] += 1
            out["all_fresh_days"] += int(not stale)
    out["inputs"] = per
    out["target"] = target
    out["all_fresh_share"] = out["all_fresh_days"] / len(window) if window else None
    out["goal"] = _goal(out)
    out["label"] = {"label": _words(out), "tier": "T1", "modality": MODALITY}
    return out


# --- words (T1, no digit); the counts behind them stay T0 in the dict ----------------------------------------

def needed_days(n_days: int, share: float) -> int:
    """Whole days of ``n_days`` that are every-input-fresh at the ``share`` target (rounded up)."""
    return math.ceil(n_days * share - 1e-9)


def _goal(out: dict) -> str:
    """"met" when enough window days were every-input-fresh; "not met" when even every unknown day being fresh
    would not reach it; else "unknown". Fewer than MIN_KNOWN_DAYS known days is "unknown"."""
    n = out["window_days"]
    if not n or out["known_days"] < MIN_KNOWN_DAYS:
        return GOAL_UNKNOWN
    need = needed_days(n, out["target"])
    if out["all_fresh_days"] >= need:
        return GOAL_MET
    if out["all_fresh_days"] + (n - out["known_days"]) < need:
        return GOAL_NOT_MET
    return GOAL_UNKNOWN


def _span(n_days: int) -> str:
    return "all week" if n_days == 7 else "all month" if 28 <= n_days <= 31 else "every day"


def phrase(c: Mapping, n_days: int) -> str:
    """One input's days in words: fresh every day ... stale all month (see PHRASES)."""
    f, s = c["fresh"], c["stale"]
    k = f + s
    if f == k:
        return FRESH_ALL if k == n_days else FRESH_KNOWN
    if s == k:
        return "stale " + _span(n_days) if k == n_days else STALE_KNOWN
    if f * 2 > k:
        return FRESH_MOST
    return STALE_MOST if s * 2 > k else FRESH_HALF


def _and(parts: list) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _words(out: dict) -> str:
    if out["known_days"] < MIN_KNOWN_DAYS:
        return UNKNOWN
    from .outage import name_words   # lazily: outage reads tools, which reads this module
    n = out["window_days"]
    groups = {}
    for name, c in out["inputs"].items():
        groups.setdefault(phrase(c, n), []).append(name_words(name))
    order = PHRASES + tuple(p for p in groups if p not in PHRASES)
    parts = [f"{_and(groups[p])} {p}" for p in order if p in groups] or [NONE_NAMED]
    return "; ".join(parts + [GOAL_WORDS[out["goal"]]])
