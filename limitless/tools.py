"""Tool bodies as plain functions of (reader, now, ...) returning evidence envelopes. Handlers live in plugin.py."""
from __future__ import annotations

from datetime import date, timedelta

from . import jobs
from .envelope import STALE_H, envelope, missing
from .state_reader import StateReader, parse_ts


def _age_h(at, now: float):
    t = parse_ts(at)
    return None if t is None else max(0.0, now - t) / 3600


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


def habit(reader: StateReader, now: float, today: date) -> dict:
    """This week's one habit and its check-ins, week_of through today, and the one number so far.

    A 1-tap answer (habit.json) beats the sync's verdict (habit1.jsonl); a day with neither is unlogged.
    ``logged`` is "N of M logged days": N Done, M Done + No. Skipped and unlogged days stay out of M.
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
        return envelope(value, "proxy", min(ages) if ages else None)
    return envelope(value, "self_report", age_h)
