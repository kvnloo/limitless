"""Lock one prediction for a habit week before it starts; write one outcome receipt after day seven.

    r = lock(state_dir, "2030-01-15", "More done days", "logged", "at_least 4 of 7", today=today)  # dry run
    r = lock(state_dir, week_of, text, metric, direction, write=True, today=today)              # appends
    r = receipt(state_dir, week_of, today=today)                    # says what the verdict would be
    r = receipt(state_dir, week_of, write=True, today=today)        # appends the receipt

An N-of-1 experiment needs its prediction fixed before the exposure and its outcome judged against it.
Both rows go to ``predictions.jsonl`` in the existing state dir, append-only: a prediction row
``{kind: "prediction", week_of, text, metric, direction, falsifier, lag_days, locked_at}`` (``falsifier``: the
person's words for what would show it wrong, or None; ``lag_days``: 0, 7 or 14; a row from before these
fields reads as None and 0) and later a receipt row
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


LAG_DAYS = (0, 7, 14)         # the outcome is judged on the habit week, or a week or two weeks after it
# only a habit is an experiment here: a prediction about anything taken is refused (no dosing experiments)
_NOT_A_HABIT = re.compile(r"(?i)\b(dos(e|es|ed|ing|age)|microdos\w*|supplement\w*|drugs?|medication\w*|"
                          r"medicine\w*|pills?|tablets?|capsules?|milligrams?|mg)\b")


def falsifier_of(row: dict) -> Optional[str]:
    """The falsifier stated when the prediction was locked (the person's words), else None (old rows too)."""
    f = row.get("falsifier") if isinstance(row, dict) else None
    return f if isinstance(f, str) and f.strip() else None


def lag_of(row: dict) -> Optional[int]:
    """The prediction's lag in days (0 for an old row without one); None when it is not one of LAG_DAYS."""
    v = row.get("lag_days", 0) if isinstance(row, dict) else None
    return v if type(v) is int and v in LAG_DAYS else None


def lock(state_dir, week_of, text, metric, direction, write: bool = False, today: Optional[date] = None,
         now: Optional[float] = None, falsifier: Optional[str] = None, lag_days: int = 0) -> dict:
    """``{action, reason, prediction}``: action is would lock, locked or refused; prediction is the row.

    ``falsifier`` is the person's own words for what result would show the prediction is wrong (optional).
    ``lag_days`` (LAG_DAYS) moves the judged span that many days past the habit week's start, for effects that
    show late; a lag needs a state metric (logged days are the habit itself, judged on its own week).
    """
    today = date.today() if today is None else today
    words = text.strip() if isinstance(text, str) else ""
    if not words:
        return _result(REFUSED, "the prediction text is empty: nothing locked")
    if falsifier is not None and not isinstance(falsifier, str):
        return _result(REFUSED, "the falsifier must be plain words: nothing locked")
    stated = falsifier.strip() if isinstance(falsifier, str) and falsifier.strip() else None
    if type(lag_days) is not int or lag_days not in LAG_DAYS:
        return _result(REFUSED, "the lag must be none, one week or two weeks: nothing locked")
    if _NOT_A_HABIT.search(words) or (stated and _NOT_A_HABIT.search(stated)):
        return _result(REFUSED, "only a habit can be the experiment here, not anything taken: nothing locked")
    start = _day(week_of)
    if start is None:
        return _result(REFUSED, "week_of is not a date: nothing locked")
    d, why = _parse_direction(metric, direction)
    if why:
        return _result(REFUSED, why)
    if lag_days and metric == LOGGED:
        return _result(REFUSED, "a lagged outcome needs a state metric: logged days are judged on the habit week")
    if locked(state_dir, start.isoformat()) is not None:
        return _result(REFUSED, "a prediction for that week is already locked: it is never rewritten")
    if today >= start + timedelta(days=WEEK_DAYS):
        return _result(REFUSED, "that habit week is over: a prediction is locked before the week")
    if today > start and any(c != "unlogged" for _, c in week_days(state_dir, start, today)):
        return _result(REFUSED, "that week already started and has check-ins logged: lock before the week")
    row = {"kind": "prediction", "week_of": start.isoformat(), "text": words, "metric": metric,
           "direction": d, "falsifier": stated, "lag_days": lag_days, "locked_at": _now_iso(now)}
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
WOULD_WRITE, WROTE, PENDING = "would write", "wrote", "pending"
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


_SPAN_WORDS = {0: "the habit week", 7: "the week after the habit week", 14: "the second week after the habit week"}


def _state_verdict(state_dir, start: date, metric: str, direction: str, lag: int = 0):
    """The habit week needs three logged days (the exposure happened); the judged span is the seven days from
    ``lag`` days after the week's start, against the seven days before the habit week."""
    answers = [c for _, c in week_days(state_dir, start)]
    if answers.count("Done") + answers.count("No") < MIN_DAYS:
        return INCONCLUSIVE, "fewer than three logged days: too little to judge", None
    first = start + timedelta(days=lag)
    span = _SPAN_WORDS[lag]
    week = _values(state_dir, metric, first, first + timedelta(days=WEEK_DAYS - 1))
    before = _values(state_dir, metric, start - timedelta(days=WEEK_DAYS), start - timedelta(days=1))
    if len(week) < MIN_DAYS or len(before) < MIN_DAYS:
        return INCONCLUSIVE, f"fewer than three days with {metric} in {span} or the week before it began", None
    a, b = sum(week) / len(week), sum(before) / len(before)
    outcome = "higher" if a > b else "lower" if a < b else "unchanged"
    want = "higher" if direction == UP else "lower"
    if outcome == want:
        return SUPPORTS, f"{metric} was {outcome} in {span} than the week before", outcome
    return CONTRADICTS, f"{metric} was {outcome} in {span}, not {want}, against the week before", outcome


def due_day(p: dict) -> Optional[date]:
    """The first day a receipt may be written for prediction row ``p``: the day after its judged span (day
    eight for no lag; a lag that cannot be read counts as none). None when week_of is not a date."""
    start = _day(p.get("week_of")) if isinstance(p, dict) else None
    return None if start is None else start + timedelta(days=(lag_of(p) or 0) + WEEK_DAYS)


def receipt(state_dir, week_of, write: bool = False, today: Optional[date] = None,
            now: Optional[float] = None) -> dict:
    """``{action, reason, receipt}``: action is would write, wrote, pending or refused; receipt is the row.

    Only after day seven, only for a locked prediction and only once per prediction (append-only). With a lag
    (``lag_days`` on the prediction) the action and ``verdict`` are pending, with nothing written, until the
    lagged span is over; then the outcome is judged on that span (the reason names it in words; the lag stays
    on the prediction row the receipt points at, so the receipt row has no digit beyond its dates).
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
    lag = lag_of(p)
    if lag:
        if today < start + timedelta(days=lag + WEEK_DAYS):
            return {"action": PENDING, "verdict": PENDING, "receipt": None,
                    "reason": "the outcome is judged later, after " + _SPAN_WORDS[lag] + ": nothing written"}
    elif today < start + timedelta(days=WEEK_DAYS):
        return {"action": REFUSED, "reason": "the habit week is not over: a receipt comes after day seven",
                "receipt": None}
    if lag is None:
        verdict, why, outcome = INCONCLUSIVE, "the locked lag cannot be read", None
    elif p.get("metric") == LOGGED and not lag:
        verdict, why, outcome = _logged_verdict(state_dir, start, p.get("direction"))
    elif p.get("metric") in STATE_METRICS and p.get("direction") in (UP, DOWN):
        verdict, why, outcome = _state_verdict(state_dir, start, p["metric"], p["direction"], lag)
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
    if r["action"] == PENDING:
        return "outcome pending: judged later"
    return f"{r['action']} this receipt: {r['receipt']['verdict']}"
