"""Tool bodies as plain functions of (reader, now, ...) returning evidence envelopes. Handlers live in plugin.py."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Mapping, Optional

from . import (feeds_evidence, habit_start as _habit_start, jobs, jobs_runner, labeler as _labeler,
               owner_messages as _owner, scorecard as _scorecard)
from .envelope import STALE_H, envelope, missing, with_label
from .state_reader import OWNER_DBS_CONFIG, OWNER_DBS_ENV, StateReader, parse_ts
from .window import MAX_AWAKE_H


def _age_h(at, now: float):
    t = parse_ts(at)
    return None if t is None else max(0.0, now - t) / 3600


def labeled(env: dict) -> dict:
    """env with the T1 age label (fresh | stale | missing | unknown) next to its value, where allowed."""
    if not isinstance(env, dict):
        return env
    return with_label(env, _labeler.label("age_h", env.get("age_h"), env.get("modality")))


def status(reader: StateReader, now: float) -> dict:
    """Each input's current age, which inputs are not recording (> STALE_H old or down), the last run."""
    inp = reader.inputs()
    if not inp or not isinstance(inp.get("ageHours"), dict):
        return missing("no inputs.json (with ageHours) in the state dir")
    snap_h = _age_h(inp.get("at"), now)
    inputs, not_recording, unknown = {}, [], []
    for name, age in sorted(inp["ageHours"].items()):
        if age == "down":
            inputs[name] = {"age_h": None, "state": "down"}
            not_recording.append(name)
        elif isinstance(age, (int, float)) and not isinstance(age, bool) and snap_h is not None:
            cur = round(age + snap_h, 1)
            state = "not recording" if cur > STALE_H else "recording"
            inputs[name] = {"age_h": cur, "state": state}
            if state == "not recording":
                not_recording.append(name)
        else:
            inputs[name] = {"age_h": None, "state": "unknown"}
            unknown.append(name)
    run = reader.last_run()
    run_h = _age_h((run or {}).get("at"), now)
    if run is None or run_h is None:
        last_run = missing("no timestamped row in runs.jsonl")
    else:
        last_run = envelope({"at": run["at"], "ok": run.get("ok")}, "measured", run_h)
    value = {"inputs": inputs, "not_recording": not_recording, "unknown": unknown, "last_run": last_run}
    return envelope(value, "measured", snap_h)


CHECKINS = ("Done", "No", "Skipped")


def _checkin(v) -> str:
    """Done | No | Skipped; anything else (absent, blank, unknown words) is unlogged, never No."""
    if isinstance(v, str):
        for c in CHECKINS:
            if v.strip().lower() == c.lower():
                return c
    return "unlogged"


def phone_hint(reader: StateReader, now: float, env: Optional[Mapping[str, str]] = None,
               home: Optional[Path] = None) -> dict:
    """``{"value": seen | not seen | unknown, "evidence_tier": "proxy"}``: did the phone see a feed app in
    the first hour after the latest wake (feeds_evidence)? Unknown while that hour is still open, with no
    wake within MAX_AWAKE_H, no feed list or too little phone data. A hint only; never a check-in."""
    try:
        wakes = jobs.wake_times(jobs_runner.events(reader, env, home), now)
    except Exception:  # noqa: BLE001 - unreadable state is unknown, never a traceback
        wakes = []
    wake = wakes[-1] if wakes else None
    if wake is None or now - wake > MAX_AWAKE_H * 3600 or now < wake + jobs.HABIT_CUE_AFTER_S:
        result = None
    else:
        result = feeds_evidence.phone_hint(reader, wake, env, home)
    return {"value": feeds_evidence.hint(result), "evidence_tier": feeds_evidence.EVIDENCE_TIER}


def habit(reader: StateReader, now: float, today: date, env: Optional[Mapping[str, str]] = None,
          home: Optional[Path] = None) -> dict:
    """This week's one habit and its check-ins, week_of through today, and the one number so far.

    A 1-tap answer (habit.json) beats the sync's verdict (habit1.jsonl); a day with neither is unlogged.
    ``logged`` is "N of M logged days": N Done, M Done + No. Skipped and unlogged days stay out of M.
    ``phone_hint`` (seen | not seen | unknown, evidence_tier "proxy") says what the phone saw in the
    first hour after the latest wake; it never changes a check-in.
    """
    h = reader.habit()
    if not h or not h.get("habit"):
        return missing("no habit.json with a habit: no habit set this week")
    age_h = _age_h(h.get("at"), now)
    try:
        start = date.fromisoformat(str(h.get("week_of")))
    except ValueError:
        return envelope(None, "self_report", age_h, reason="habit.json has no valid week_of date")
    if not start <= today < start + timedelta(days=7):
        return envelope(None, "self_report", age_h, reason=f"habit.json is for the week of {start}, not this week")
    synced = reader.habit_days()
    wakes = {r.get("day"): _age_h(r.get("wake"), now) for r in reader.habit1() if isinstance(r.get("day"), str)}
    tapped = {d for d in (h.get("checkins") or {}) if _checkin(h["checkins"][d]) != "unlogged"} \
        if isinstance(h.get("checkins"), dict) else set()
    days, sync_ages = [], []
    for i in range((today - start).days + 1):
        d = (start + timedelta(days=i)).isoformat()
        checkin = jobs.habit_day(h, d, synced)
        src = None if checkin == "unlogged" else ("tap" if d in tapped else "sync")
        if src == "sync" and wakes.get(d) is not None:
            sync_ages.append(wakes[d])
        days.append({"date": d, "checkin": checkin, "from": src})
    counts = {c: 0 for c in CHECKINS + ("unlogged",)}
    for d in days:
        counts[d["checkin"]] += 1
    n, m = counts["Done"], counts["Done"] + counts["No"]
    value = {"habit": h["habit"], "start": h.get("start"), "week_of": start.isoformat(), "days": days,
             "counts": counts, "today": days[-1]["checkin"], "day": len(days), "logged": f"{n} of {m} logged days"}
    if any(d["from"] == "sync" for d in days):
        ages = [a for a in sync_ages + [age_h] if a is not None]
        out = envelope(value, "proxy", min(ages) if ages else None)
    else:
        out = envelope(value, "self_report", age_h)
    out["phone_hint"] = phone_hint(reader, now, env, home)
    return out


def habit_start(state_dir, habit, today: date, now: float, confirm: bool = False) -> dict:
    """Start this week's one habit (habit_start.start_week), writing only when ``confirm`` is True.

    An envelope whose value is the start row ``{action, reason, habit, week_of, kept}``, self-reported and
    of age zero, with a digit-free T1 label: would start this habit week, started this habit week or
    refused: <why>. Without confirm it writes nothing and says what it would do.
    """
    r = _habit_start.start_week(state_dir, habit, today, confirm is True, now=now)
    out = envelope(r, "self_report", 0.0)
    out["label"] = {"label": _habit_start.label(r), "tier": "T1", "modality": "self_report"}
    return out


def scorecard(path: Optional[Path], now: float) -> dict:
    """The weekly review's scorecard block: at most 5 plain-word lines (counts, the stop rule, the criteria
    furthest from green). Self-reported, aged by the file's mtime. Reasons never echo the path."""
    if path is None:
        return missing(f"no scorecard path: set {_scorecard.ENV_KEY} or \"{_scorecard.CONFIG_KEY}\" in config.json")
    try:
        text = Path(path).read_text(errors="replace")
        mtime = Path(path).stat().st_mtime
    except OSError:
        return missing("no scorecard file at the configured path")
    age_h = max(0.0, now - mtime) / 3600
    lines = _scorecard.summary(_scorecard.parse(text))
    if not lines:
        return envelope(None, "self_report", age_h, reason="the scorecard file has no scorecard table rows")
    return envelope(lines, "self_report", age_h)


OWNER_KIND = "owner_message_age_h"


def owner_message(reader: StateReader, now: float, env: Optional[Mapping[str, str]] = None,
                  home: Optional[Path] = None) -> dict:
    """When the person last wrote to any agent, across every configured Hermes session store: an envelope
    ``{value: ISO time, modality: "messages", age_h, evidence_tier}`` plus ``sources: {read, failed}`` and a
    digit-free T1 label (wrote recently | quiet for a while | no data). No store configured is missing, not
    zero. Never carries message content; reasons never echo a path."""
    paths = reader.owner_db_paths(env, home)
    if paths is None:
        return missing(f"no owner session DBs: set {OWNER_DBS_ENV} or \"{OWNER_DBS_CONFIG}\" in config.json")
    got = _owner.newest_user_message(paths, now)
    sources = {"read": got["sources_read"], "failed": got["sources_failed"]}
    if got["at"] is None:
        why = ("no message from the person in the owner session DBs" if sources["read"]
               else "the owner session DBs could not be read")
        out = envelope(None, "messages", None, reason=why)
    else:
        out = envelope(got["at"], "messages", got["age_h"])
    out["sources"] = sources
    out["label"] = _labeler.label(OWNER_KIND, got["age_h"], "messages")
    return out
