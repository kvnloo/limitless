"""Tool bodies as plain functions of (reader, now, ...) returning evidence envelopes. Handlers live in plugin.py."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Mapping, Optional

from . import (asks as _asks, feeds_evidence, habit_start as _habit_start, jobs, jobs_runner, labeler as _labeler,
               owner_messages as _owner, passive_habit, prediction as _prediction, scorecard as _scorecard)
from .envelope import STALE_H, envelope, missing, with_label
from .state_reader import (OWNER_BEACONS_CONFIG, OWNER_BEACONS_ENV, OWNER_DBS_CONFIG, OWNER_DBS_ENV, StateReader,
                           parse_ts)
from .glide_provider import GlideProvider
from .window import MAX_AWAKE_H, wake_at
from .window import window as _window
from .window_chain import EventProvider, first_known


def _age_h(at, now: float):
    t = parse_ts(at)
    return None if t is None else max(0.0, now - t) / 3600


def asks_view(reader: StateReader, now: float, bands: Optional[Mapping] = None,
              env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> dict:
    """The asks queue (asks.queue_path) planned against the window chain (Glide, then Sleep mode and unlocks):
    ``{deliver, hold, fold}`` counts and a digit-free T1 label. Peak asks delivered since the wake event
    count against the one decision per peak window. Read-only; nothing sends."""
    rows = _asks.read(_asks.queue_path(env, home))
    events = EventProvider.from_reader(reader, now, bands)
    state = {"value": "asleep"} if events.asleep else first_known(GlideProvider.from_config(env, home, now=now),
                                                                 events)
    sent = _asks.delivered_since(rows, wake_at(reader.sleepmode()))
    todo = _asks.pending(rows)
    return _asks.summary(todo, _asks.plan(todo, state, sent))


def window(reader: StateReader, now: float, bands: Optional[Mapping] = None,
           env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> dict:
    """limitless_window: the window.py envelope plus ``asks`` (asks_view)."""
    out = _window(reader, now, bands)
    out["asks"] = asks_view(reader, now, bands, env, home)
    return out


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
    """_habit_week plus ``prediction`` when one is locked for habit.json's week (prediction_view)."""
    out = _habit_week(reader, now, today, env, home)
    try:
        start = date.fromisoformat(str((reader.habit() or {}).get("week_of")))
    except ValueError:
        return out
    view = prediction_view(reader.path, start)
    if view is not None:
        out["prediction"] = view
    return out


def prediction_view(state_dir, week_of: date) -> Optional[dict]:
    """The prediction locked for ``week_of`` and its receipt (or None), with a digit-free T1 label:
    prediction locked, or receipt: supports | contradicts | inconclusive. None when nothing is locked."""
    p = _prediction.locked(state_dir, week_of.isoformat())
    if p is None:
        return None
    r = _prediction.receipt_for(state_dir, week_of.isoformat())
    word = "prediction locked" if r is None else f"receipt: {r.get('verdict')}"
    view = {k: p.get(k) for k in ("week_of", "text", "metric", "direction", "locked_at")}
    view["receipt"] = None if r is None else {k: r.get(k) for k in ("verdict", "reason", "outcome", "at")}
    view["label"] = {"label": word, "tier": "T1", "modality": "self_report"}
    return view


def _habit_week(reader: StateReader, now: float, today: date, env: Optional[Mapping[str, str]] = None,
                home: Optional[Path] = None) -> dict:
    """This week's one habit and its check-ins, week_of through today, and the one number so far.

    A 1-tap answer (habit.json) beats the sync's verdict (habit1.jsonl); a day with neither is unlogged.
    ``logged`` is "N of M logged days": N Done, M Done + No. Skipped and unlogged days stay out of M.
    ``phone_hint`` (seen | not seen | unknown, evidence_tier "proxy") says what the phone saw in the
    first hour after the latest wake; it never changes a check-in. ``decision`` (Keep or Drop) and
    ``decided_at`` appear once the person answered the week review; an undecided week has neither.
    ``passive`` (passive_habit.summary: days_measured, days_met, modality proxy, a T1 label) is what the
    configured passive habit file measured for this week's days so far; it never changes a check-in,
    ``counts`` or ``logged``, and is absent when there is no such row (unknown, not zero).
    With no confirmed week, see _no_week.
    """
    h = reader.habit()
    if not h or not h.get("habit"):
        return _no_week(reader, now, today, missing("no habit.json with a habit: no habit set this week"), env, home)
    age_h = _age_h(h.get("at"), now)
    try:
        start = date.fromisoformat(str(h.get("week_of")))
    except ValueError:
        return _no_week(reader, now, today,
                        envelope(None, "self_report", age_h, reason="habit.json has no valid week_of date"), env, home)
    if not start <= today < start + timedelta(days=7):
        why = f"habit.json is for the week of {start}, not this week"
        return _no_week(reader, now, today, envelope(None, "self_report", age_h, reason=why), env, home)
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
    decision = jobs.habit_decision(h)
    if decision is not None:
        value.update(decision=decision, decided_at=h.get("decided_at"))
    passive = passive_habit.view(reader, start, today, env, home)
    if passive is not None:
        value["passive"] = passive   # beside the check-ins, never merged into them
    if any(d["from"] == "sync" for d in days):
        ages = [a for a in sync_ages + [age_h] if a is not None]
        out = envelope(value, "proxy", min(ages) if ages else None)
    else:
        out = envelope(value, "self_report", age_h)
    out["phone_hint"] = phone_hint(reader, now, env, home)
    return out


def _no_week(reader: StateReader, now: float, today: date, out: dict, env: Optional[Mapping[str, str]] = None,
             home: Optional[Path] = None) -> dict:
    """``out`` (no confirmed habit week) as it is, unless the passive habit file has rows for today and the
    six days before. Then a proxy envelope whose value is ``{habit: None, week_of: None, started: False,
    reason, passive}`` with the T1 label "habit not started; <what phone data shows>". Measured evidence
    only: nothing is written, no day is Done and no week starts (habit_start is the one place that does)."""
    first = today - timedelta(days=passive_habit.WINDOW_DAYS - 1)
    passive = passive_habit.view(reader, first, today, env, home)
    if passive is None:
        return out
    value = {"habit": None, "week_of": None, "started": False, "reason": out.get("reason"), "passive": passive}
    res = envelope(value, passive_habit.MODALITY, _passive_age_h(reader, now, env, home))
    res["label"] = passive_habit.not_started_label(passive)
    return res


def _passive_age_h(reader: StateReader, now: float, env: Optional[Mapping[str, str]] = None,
                   home: Optional[Path] = None) -> Optional[float]:
    p = reader.passive_habit_file(env, home)
    try:
        return None if p is None else max(0.0, now - p.stat().st_mtime) / 3600
    except OSError:
        return None


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


def _labeled_row(r: dict, word: str) -> dict:
    out = envelope(r, "self_report", 0.0)
    out["label"] = {"label": word, "tier": "T1", "modality": "self_report"}
    return out


def _predict_week(state_dir, today: date) -> date:
    """habit.json's week while it is running or set to start later, else today (the next start's week)."""
    try:
        start = date.fromisoformat(str((StateReader(Path(state_dir)).habit() or {}).get("week_of")))
    except ValueError:
        return today
    return start if today < start + timedelta(days=_prediction.WEEK_DAYS) else today


def habit_predict(state_dir, text, metric, direction, today: date, now: float, confirm: bool = False) -> dict:
    """Lock a prediction for the habit week (prediction.lock), writing only when ``confirm`` is True.

    The week is habit.json's while it runs or is set to start later, else today. An envelope whose value is
    ``{action, reason, prediction}``, with a digit-free T1 label: would lock this prediction, locked this
    prediction or refused: <why>. Without confirm it writes nothing and says what it would do.
    """
    week = _predict_week(state_dir, today)
    r = _prediction.lock(state_dir, week.isoformat(), text, metric, direction, write=confirm is True,
                         today=today, now=now)
    return _labeled_row(r, _prediction.label(r))


def _receipt_week(state_dir, today: date) -> Optional[str]:
    """The newest locked prediction whose week is over and has no receipt, else the newest locked one."""
    weeks = [r.get("week_of") for r in _prediction.rows(state_dir) if r.get("kind") == "prediction"]
    weeks = [w for w in weeks if isinstance(w, str)]
    for w in reversed(weeks):
        try:
            over = today >= date.fromisoformat(w) + timedelta(days=_prediction.WEEK_DAYS)
        except ValueError:
            continue
        if over and _prediction.receipt_for(state_dir, w) is None:
            return w
    return weeks[-1] if weeks else None


def habit_receipt(state_dir, today: date, now: float, confirm: bool = False) -> dict:
    """Write the outcome receipt for the newest finished prediction (prediction.receipt), only with confirm.

    An envelope whose value is ``{action, reason, receipt}``, with a digit-free T1 label: would write this
    receipt: <verdict>, wrote this receipt: <verdict> or refused: <why>.
    """
    week = _receipt_week(state_dir, today)
    if week is None:
        r = {"action": _prediction.REFUSED, "reason": "no prediction is locked for that week: no receipt",
             "receipt": None}
    else:
        r = _prediction.receipt(state_dir, week, write=confirm is True, today=today, now=now)
    return _labeled_row(r, _prediction.receipt_label(r))


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
    """When the person last wrote to any agent, across every configured Hermes session store and owner beacon:
    an envelope
    ``{value: ISO time, modality: "messages", age_h, evidence_tier}`` plus ``sources: {read, failed}`` and a
    digit-free T1 label (wrote recently | quiet for a while | no data). No store configured is missing, not
    zero. Never carries message content; reasons never echo a path."""
    paths, beacons = reader.owner_db_paths(env, home), reader.owner_beacon_paths(env, home)
    if paths is None and beacons is None:
        return missing(f"no owner session DBs or beacons: set {OWNER_DBS_ENV} or {OWNER_BEACONS_ENV} "
                       f"(config \"{OWNER_DBS_CONFIG}\" or \"{OWNER_BEACONS_CONFIG}\")")
    got = _owner.newest_user_message(paths, now, beacons=beacons)
    sources = {"read": got["sources_read"], "failed": got["sources_failed"]}
    if got["at"] is None:
        why = ("no message from the person in the owner session DBs or beacons" if sources["read"]
               else "the owner session DBs or beacons could not be read")
        out = envelope(None, "messages", None, reason=why)
    else:
        out = envelope(got["at"], "messages", got["age_h"])
    out["sources"] = sources
    out["label"] = _labeler.label(OWNER_KIND, got["age_h"], "messages")
    return out
