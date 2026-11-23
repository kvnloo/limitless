"""Lock one prediction for a habit week before it starts; write one outcome receipt after day seven.

    r = lock(state_dir, "2030-01-15", "More done days", "logged", "at_least 4 of 7", today=today)  # dry run
    r = lock(state_dir, week_of, text, metric, direction, write=True, today=today)              # appends
    r = receipt(state_dir, week_of, today=today)                    # says what the verdict would be
    r = receipt(state_dir, week_of, write=True, today=today)        # appends the receipt

An N-of-1 experiment needs its prediction fixed before the exposure and its outcome judged against it.
Both rows go to ``predictions.jsonl`` in the existing state dir, append-only: a prediction row
``{kind: "prediction", week_of, text, metric, direction, locked_at}`` and later a receipt row
``{kind: "receipt", week_of, locked_at, verdict, reason, outcome, at}``. A row is never rewritten.

``metric`` is ``logged`` (the habit's own "N of M logged days": N Done, M Done + No) with ``direction``
``at_least <k> of <m>`` (N of M at least k of m), or a named state metric from digests.jsonl
(``STATE_METRICS``) with ``direction`` ``up`` or ``down`` (the habit week against the seven days before).

``lock`` refuses, in plain words and writing nothing, when the text is empty, the week_of is not a date,
the metric or direction is not one of the above, a prediction for that week is already locked, the week
is over, or the week started before today and a check-in (Done, No or Skipped, a tap or the sync's) is
already logged. Reasons and labels have no digits. Nothing here sends. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from . import jobs
from .habit_replies import HABIT_FILE
from .state_reader import StateReader, normalize_digest, parse_ts

PREDICTIONS_FILE = "predictions.jsonl"
WEEK_DAYS = jobs.HABIT_WEEK_DAYS
LOGGED = "logged"
STATE_METRICS = ("sleep_h", "readiness")
UP, DOWN = "up", "down"
WOULD_LOCK, LOCKED, REFUSED = "would lock", "locked", "refused"
_AT_LEAST = re.compile(r"^at_least\s+(\d+)\s+of\s+(\d+)$")


def _result(action: str, reason: str, prediction=None) -> dict:
    return {"action": action, "reason": reason, "prediction": prediction}


def _day(v) -> Optional[date]:
    try:
        return date.fromisoformat(str(v))
    except ValueError:
        return None


def _now_iso(now: Optional[float]) -> str:
    return datetime.fromtimestamp(time.time() if now is None else now, timezone.utc).isoformat(timespec="seconds")


def rows(state_dir) -> list:
    """Every readable row of predictions.jsonl, oldest first; a torn or non-object line is skipped."""
    try:
        text = (Path(state_dir) / PREDICTIONS_FILE).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out = []
    for ln in text.splitlines():
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if isinstance(r, dict):
            out.append(r)
    return out


def locked(state_dir, week_of) -> Optional[dict]:
    """The prediction locked for ``week_of`` (the first one; later ones are never written), else None."""
    week = str(week_of)
    for r in rows(state_dir):
        if r.get("kind") == "prediction" and r.get("week_of") == week:
            return r
    return None


def _append(state_dir, row: dict) -> None:
    """Append one JSON line to predictions.jsonl (0600, created if absent); a torn last line is ended first."""
    path = Path(state_dir) / PREDICTIONS_FILE
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "r+b") as f:
        f.seek(0, os.SEEK_END)
        lead = b""
        if f.tell():
            f.seek(-1, os.SEEK_END)
            lead = b"" if f.read(1) == b"\n" else b"\n"
        f.write(lead + json.dumps(row, ensure_ascii=False).encode("utf-8") + b"\n")
        f.flush()
        os.fsync(f.fileno())


def _parse_direction(metric, direction):
    """(direction, None) when the pair is valid, else (None, why) in plain words."""
    if metric != LOGGED and metric not in STATE_METRICS:
        return None, "the metric must be logged days or a named state metric (sleep or readiness)"
    d = " ".join(direction.split()).lower() if isinstance(direction, str) else ""
    m = _AT_LEAST.match(d)
    if metric == LOGGED:
        if d in (UP, DOWN):
            return None, "logged days take at_least k of m, not up or down"
        if not m or not 1 <= int(m.group(1)) <= int(m.group(2)) <= WEEK_DAYS:
            return None, "the direction must be at_least k of m, with k from one to m and m at most seven"
        return f"at_least {int(m.group(1))} of {int(m.group(2))}", None
    if d not in (UP, DOWN):
        return None, "a state metric takes up or down as its direction"
    return d, None


def week_habit(state_dir, week_of: date) -> Optional[dict]:
    """habit.json when it is for ``week_of``, else the kept ``habit-<week_of>.json``; None when neither is."""
    state = Path(state_dir)
    for name in (HABIT_FILE, f"habit-{week_of.isoformat()}.json"):
        try:
            h = json.loads((state / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(h, dict) and _day(h.get("week_of")) == week_of:
            return h
    return None


def week_days(state_dir, week_of: date, through: Optional[date] = None) -> list:
    """[(day, Done | No | Skipped | unlogged)] for week_of through ``through`` (default: the whole week)."""
    h = week_habit(state_dir, week_of)
    synced = StateReader(Path(state_dir)).habit_days()
    last = week_of + timedelta(days=WEEK_DAYS - 1)
    if through is not None:
        last = min(last, through)
    out, d = [], week_of
    while d <= last:
        out.append((d.isoformat(), jobs.habit_day(h, d.isoformat(), synced)))
        d += timedelta(days=1)
    return out


def lock(state_dir, week_of, text, metric, direction, write: bool = False, today: Optional[date] = None,
         now: Optional[float] = None) -> dict:
    """``{action, reason, prediction}``: action is would lock, locked or refused; prediction is the row."""
    today = date.today() if today is None else today
    words = text.strip() if isinstance(text, str) else ""
    if not words:
        return _result(REFUSED, "the prediction text is empty: nothing locked")
    start = _day(week_of)
    if start is None:
        return _result(REFUSED, "week_of is not a date: nothing locked")
    d, why = _parse_direction(metric, direction)
    if why:
        return _result(REFUSED, why)
    if locked(state_dir, start.isoformat()) is not None:
        return _result(REFUSED, "a prediction for that week is already locked: it is never rewritten")
    if today >= start + timedelta(days=WEEK_DAYS):
        return _result(REFUSED, "that habit week is over: a prediction is locked before the week")
    if today > start and any(c != "unlogged" for _, c in week_days(state_dir, start, today)):
        return _result(REFUSED, "that week already started and has check-ins logged: lock before the week")
    row = {"kind": "prediction", "week_of": start.isoformat(), "text": words, "metric": metric,
           "direction": d, "locked_at": _now_iso(now)}
    if not write:
        return _result(WOULD_LOCK, "dry run: nothing written", row)
    _append(state_dir, row)
    return _result(LOCKED, "prediction locked: it is never rewritten", row)


def label(r: dict) -> str:
    """A digit-free label: would lock this prediction, locked this prediction, or refused: why."""
    if r["action"] == REFUSED:
        return f"refused: {r['reason']}"
    return f"{r['action']} this prediction"


# --- receipts --------------------------------------------------------------------------------------------

SUPPORTS, CONTRADICTS, INCONCLUSIVE = "supports", "contradicts", "inconclusive"
WOULD_WRITE, WROTE = "would write", "wrote"
MIN_DAYS = 3                  # fewer logged days (or state values) than this is inconclusive, never contradicts


def receipt_for(state_dir, week_of) -> Optional[dict]:
    """The receipt written for the prediction locked for ``week_of``, else None."""
    p = locked(state_dir, week_of)
    if p is None:
        return None
    for r in rows(state_dir):
        if r.get("kind") == "receipt" and r.get("week_of") == p["week_of"] and r.get("locked_at") == p.get("locked_at"):
            return r
    return None


def _logged_verdict(state_dir, start: date, direction: str):
    m = _AT_LEAST.match(direction or "")
    if not m:
        return INCONCLUSIVE, "the locked direction cannot be read", None
    k, of = int(m.group(1)), int(m.group(2))
    answers = [c for _, c in week_days(state_dir, start)]
    n, logged, unlogged = answers.count("Done"), answers.count("Done") + answers.count("No"), answers.count("unlogged")
    outcome = f"{n} of {logged} logged days"
    if logged < MIN_DAYS:
        return INCONCLUSIVE, "fewer than three logged days: too little to judge", outcome
    if n * of >= k * logged:
        return SUPPORTS, "the done share of logged days reached the predicted share", outcome
    if (n + unlogged) * of >= k * (logged + unlogged):
        return INCONCLUSIVE, "the done share fell short, but unlogged days could have reached it", outcome
    return CONTRADICTS, "the done share of logged days fell short of the predicted share", outcome


def _values(state_dir, metric: str, first: date, last: date) -> list:
    """The metric's value for each day first..last that has one (the day's latest digest row wins)."""
    by_day = {}
    for raw in StateReader(Path(state_dir)).digests():
        row = normalize_digest(raw)
        if not isinstance(row, dict) or not isinstance(row.get("metrics"), dict):
            continue
        d = _day(row.get("date"))
        if d is None:
            t = parse_ts(row.get("at"))
            d = None if t is None else datetime.fromtimestamp(t, timezone.utc).date()
        cell = row["metrics"].get(metric)
        v = cell.get("value") if isinstance(cell, dict) else None
        if d is None or not first <= d <= last or isinstance(v, bool) or not isinstance(v, (int, float)) \
                or v != v or v in (float("inf"), float("-inf")):
            continue
        by_day[d] = float(v)
    return list(by_day.values())


def _state_verdict(state_dir, start: date, metric: str, direction: str):
    answers = [c for _, c in week_days(state_dir, start)]
    if answers.count("Done") + answers.count("No") < MIN_DAYS:
        return INCONCLUSIVE, "fewer than three logged days: too little to judge", None
    week = _values(state_dir, metric, start, start + timedelta(days=WEEK_DAYS - 1))
    before = _values(state_dir, metric, start - timedelta(days=WEEK_DAYS), start - timedelta(days=1))
    if len(week) < MIN_DAYS or len(before) < MIN_DAYS:
        return INCONCLUSIVE, f"fewer than three days with {metric} in the week or the week before", None
    a, b = sum(week) / len(week), sum(before) / len(before)
    outcome = "higher" if a > b else "lower" if a < b else "unchanged"
    want = "higher" if direction == UP else "lower"
    if outcome == want:
        return SUPPORTS, f"{metric} was {outcome} in the habit week than the week before", outcome
    return CONTRADICTS, f"{metric} was {outcome} in the habit week, not {want}, against the week before", outcome


def receipt(state_dir, week_of, write: bool = False, today: Optional[date] = None,
            now: Optional[float] = None) -> dict:
    """``{action, reason, receipt}``: action is would write, wrote or refused; receipt is the row.

    Only after day seven, only for a locked prediction and only once per prediction (append-only).
    """
    today = date.today() if today is None else today
    start = _day(week_of)
    if start is None:
        return {"action": REFUSED, "reason": "week_of is not a date: no receipt", "receipt": None}
    p = locked(state_dir, start.isoformat())
    if p is None:
        return {"action": REFUSED, "reason": "no prediction is locked for that week: no receipt", "receipt": None}
    if receipt_for(state_dir, start.isoformat()) is not None:
        return {"action": REFUSED, "reason": "a receipt for that prediction is already written: one per prediction",
                "receipt": None}
    if today < start + timedelta(days=WEEK_DAYS):
        return {"action": REFUSED, "reason": "the habit week is not over: a receipt comes after day seven",
                "receipt": None}
    if p.get("metric") == LOGGED:
        verdict, why, outcome = _logged_verdict(state_dir, start, p.get("direction"))
    elif p.get("metric") in STATE_METRICS and p.get("direction") in (UP, DOWN):
        verdict, why, outcome = _state_verdict(state_dir, start, p["metric"], p["direction"])
    else:
        verdict, why, outcome = INCONCLUSIVE, "the locked metric or direction cannot be read", None
    row = {"kind": "receipt", "week_of": p["week_of"], "locked_at": p.get("locked_at"), "verdict": verdict,
           "reason": why, "outcome": outcome, "at": _now_iso(now)}
    if not write:
        return {"action": WOULD_WRITE, "reason": "dry run: nothing written", "receipt": row}
    _append(state_dir, row)
    return {"action": WROTE, "reason": "receipt written: it is never rewritten", "receipt": row}


def receipt_label(r: dict) -> str:
    """A digit-free label: would write this receipt: <verdict>, wrote this receipt: <verdict>, or refused: why."""
    if r["action"] == REFUSED:
        return f"refused: {r['reason']}"
    return f"{r['action']} this receipt: {r['receipt']['verdict']}"
