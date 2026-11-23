"""Tool bodies as plain functions of (reader, now, ...) returning evidence envelopes. Handlers live in plugin.py."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Mapping, Optional

from . import (asks as _asks, blocks as _blocks, body as _body, feeds_evidence, flow_metrics as _flow_metrics,
               habit_start as _habit_start, jobs, jobs_runner, labeler as _labeler,
               overnight as _overnight, owner_messages as _owner, passive_habit, prediction as _prediction,
               quiet as _quiet, regularity as _regularity, rides as _rides, scorecard as _scorecard,
               sleep as _sleep)
from .envelope import STALE_H, envelope, missing, with_label
from .state_reader import (BODY_CONFIG, OWNER_BEACONS_CONFIG, OWNER_BEACONS_ENV, OWNER_DBS_CONFIG, OWNER_DBS_ENV,
                           RIDES_CONFIG, SLEEP_CONFIG, WORK_QUEUE_CONFIG, StateReader, config, parse_ts)
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


def body(reader: StateReader, now: float, today: date, raw: bool = False, env: Optional[Mapping[str, str]] = None,
         home: Optional[Path] = None) -> dict:
    """limitless_body: the body-fat trend (body.trend) for ``today``, read-only.

    An envelope whose value is ``{recent_rows, prior_rows, label}`` (counts and the T1 words) with the T1
    label beside it; modality measured when every row in both windows is calibrated, else proxy; aged by the
    body file's mtime. Raw numbers (``recent_median``, ``prior_median``, ``change``) are T0 and appear only
    with ``raw`` (the card's LIMITLESS_RAW_IN_PROMPT opt-in). No file configured, a missing file or no valid
    row is value None with a reason (unknown, not zero); reasons never echo the path.
    """
    path = reader.body_file(env, home)
    if path is None:
        return missing(f"no body file: set \"{BODY_CONFIG}\" in config.json")
    rows = reader.body_rows(env, home, today=today)
    if not rows:
        return missing("no valid body row in the configured body file")
    try:
        age_h = max(0.0, now - path.stat().st_mtime) / 3600
    except OSError:
        age_h = None
    t = _body.trend(rows, today, flat=_body.flat_points(env, home))
    value = {"recent_rows": t["recent"]["rows"], "prior_rows": t["prior"]["rows"], "label": t["label"]["label"]}
    if raw:
        for k, v in (("recent_median", t["recent"]["median"]), ("prior_median", t["prior"]["median"]),
                     ("change", t["change"])):
            value[k] = None if v is None else round(v, 2)
    out = envelope(value, t["modality"], age_h)
    out["label"] = t["label"]
    return out


def overnight(reader: StateReader, now: float, env: Optional[Mapping[str, str]] = None,
              home: Optional[Path] = None) -> dict:
    """limitless_overnight: the overnight work queue since the latest wind-down (overnight.since), read-only.

    An envelope whose value is ``{running, queued, done_since, failed_since}`` counts, modality measured,
    aged by the newest item's mtime (the dir's when it is empty), with the digit-free T1 label beside it.
    Item names never appear. No dir configured or not there is value None with a reason (unknown, not
    zero); reasons never echo the path.
    """
    d = reader.work_queue_dir(env, home)
    if d is None:
        return missing(f"no work queue: set \"{WORK_QUEUE_CONFIG}\" in config.json")
    items = _overnight.items_for(reader, env, home)
    if items is None:
        return missing("no work queue dir at the configured path")
    since = _overnight.since(jobs_runner.events(reader, env, home), now)
    try:
        newest = max([r["mtime"] for r in items] or [d.stat().st_mtime])
        age_h = max(0.0, now - newest) / 3600
    except OSError:
        age_h = None
    out = envelope(_overnight.counts(items, since), _overnight.MODALITY, age_h)
    out["label"] = _overnight.label(items, since)
    return out


def rides(reader: StateReader, now: float, today: date, raw: bool = False, env: Optional[Mapping[str, str]] = None,
          home: Optional[Path] = None) -> dict:
    """limitless_rides: rides in the last seven days against the seven before (rides.week), read-only.

    An envelope whose value is ``{this_week, last_week, label}`` (counts and the T1 words) with the T1 label
    beside it; modality measured, aged by the rides file's mtime. Total minutes (``minutes_this_week``,
    ``minutes_last_week``) are T0 and appear only with ``raw`` (the card's LIMITLESS_RAW_IN_PROMPT opt-in).
    No file configured, a missing file or no ride row is value None with a reason (unknown, not zero);
    reasons never echo the path. No target, no score, no streak.
    """
    path = reader.rides_file(env, home)
    if path is None:
        return missing(f"no rides file: set \"{RIDES_CONFIG}\" in config.json")
    rows = reader.ride_rows(today, env, home)
    if not rows:
        return missing("no ride in the configured rides file")
    try:
        age_h = max(0.0, now - path.stat().st_mtime) / 3600
    except OSError:
        age_h = None
    w = _rides.week(rows, today)
    value = {"this_week": w["this_week"], "last_week": w["last_week"], "label": w["label"]["label"]}
    if raw:
        value.update(minutes_this_week=w["minutes_this_week"], minutes_last_week=w["minutes_last_week"])
    out = envelope(value, _rides.MODALITY, age_h)
    out["label"] = w["label"]
    return out


def _minutes(s) -> Optional[int]:
    return None if s is None else int(round(s / 60))


RAW_REGULARITY = ("nights", "mid_spread_min", "wake_spread_min", "drift_min")


def sleep(reader: StateReader, now: float, today: date, raw: bool = False, env: Optional[Mapping[str, str]] = None,
          home: Optional[Path] = None, tz=None) -> dict:
    """limitless_sleep: the wearable summary and the phone proxy side by side for the last seven nights.

    An envelope whose value is ``{wearable_nights, proxy_only_nights, unknown_nights, label}`` (counts and the T1
    words of sleep.label) with the T1 label beside it. Per-night minutes (``nights``: ``{night, wearable_min,
    proxy_min}``, None where unknown) are T0 and appear only with ``raw`` (LIMITLESS_RAW_IN_PROMPT). modality is
    "measured" only when the wearable covers the newest night, else "proxy"; age_h is the newest datum's age
    (a gap's end, or the local midnight after a wearable night). The wearable comes from config sleep_file; the
    proxy from the screen-event rows the screen wakes use (jobs_runner.person_rows). No wearable row and no
    phone gap at all is value None with a reason that never echoes the path. No target, no advice. Read-only.

    ``regularity`` is regularity.label's T1 words over the last fourteen nights (sleep.timed_nights; config
    regularity_min_nights): how steady sleep times have been, the source named, never a clock time. It rides in
    this tool rather than a tool of its own because it reads the same two sources with the same envelope, so one
    call answers how sleep has been. The raw opt-in adds ``regularity_min``: per source, the nights read and the
    midpoint spread, wake spread and drift in minutes (None when unknown); no mean time is ever shown.
    """
    wear = reader.sleep_rows(today, env, home)
    gaps = _sleep.screen_gaps(jobs_runner.person_rows(reader, env, home))
    if not wear and not gaps:
        if reader.sleep_file(env, home) is None:
            return missing(f"no sleep data: no wearable file (set \"{SLEEP_CONFIG}\" in config.json) and no phone "
                           "screen events")
        return missing("no sleep data: no night in the configured wearable sleep file and no phone screen events")
    ns = _sleep.nights(wear, gaps, today, tz=tz)
    modality = "measured" if ns and ns[-1]["wearable"] is not None else "proxy"
    newest = _sleep.newest_at([r for r in wear if r["night"] < today.isoformat()],
                              [g for g in gaps if g[1] <= now], tz)
    age_h = None if newest is None else max(0.0, now - newest) / 3600
    lab = _sleep.label(ns, modality)
    reg = _regularity.regularity(_sleep.timed_nights(wear, gaps, today, tz=tz),
                                 _regularity.min_nights(config(env, home)), tz)
    value = dict(_sleep.counts(ns), label=lab["label"], regularity=_regularity.label(reg)["label"])
    if raw:
        value["nights"] = [{"night": n["night"], "wearable_min": _minutes(n["wearable"]),
                            "proxy_min": _minutes(n["proxy"])} for n in ns]
        value["regularity_min"] = {src: {k: reg[src][k] for k in RAW_REGULARITY} for src in _regularity.SOURCES}
    out = envelope(value, modality, age_h)
    out["label"] = lab
    return out


def quiet(state_dir, now: float, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> dict:
    """limitless_quiet: whether pushes are muted now (quiet.check), read-only.

    An envelope whose value is ``{mode, set, held, why}``: ``set`` is the mode quiet.json names (on with no
    file), ``mode`` the one in force now (on once its event ended it), ``held`` whether a push would be
    dropped and ``why`` the plain reason. Self-reported, aged by ``since``, with the digit-free T1 label
    (on, off, quiet tonight or snoozed). Nothing is written or sent.
    """
    state = _quiet.load(state_dir)
    held, why = _quiet.check(state_dir, now, env, home)
    set_mode = _quiet.mode_of(state)
    mode = set_mode if held else _quiet.ON
    since = _quiet._since(state)
    age_h = None if since is None else max(0.0, now - since) / 3600
    out = envelope({"mode": mode, "set": set_mode, "held": held, "why": why}, "self_report", age_h)
    out["label"] = {"label": _quiet.label(mode), "tier": "T1", "modality": "self_report"}
    return out


BLOCK_LABELS = ("in a long block", "between blocks", "unknown")


def blocks(reader: StateReader, now: float, env: Optional[Mapping[str, str]] = None,
           home: Optional[Path] = None) -> dict:
    """limitless_blocks: today's focus blocks from the ActivityWatch DB (blocks.read_for), read-only.

    An envelope whose value is ``{in_block, long, blocks, long_blocks}``: whether a block is going now, whether
    it has run past ``break_after_min``, and how many blocks (and long ones) the last day had. A proxy (app
    activity, not attention), aged by the newest activity row, with the T1 label "in a long block", "between
    blocks" or "unknown". No DB, no work apps (flow_work_apps) or no activity row in the last day is value
    None with a reason and the label unknown, never zero blocks. No score, no target. Nothing is written or sent.
    """
    label = {"tier": "T1", "modality": "proxy"}
    got = _blocks.read_for(reader, now, env, home)
    bs = got["blocks"]
    if bs is None or got["rows_end"] is None:
        why = got["why"] or "no activity rows in the last day"
        out = envelope(None, "proxy", None, reason=f"focus blocks unknown: {why}")
        out["label"] = dict(label, label=BLOCK_LABELS[2])
        return out
    after = got["break_after_s"]
    cur = _blocks.current_block(bs, now, got["gap_s"])
    long_now = cur is not None and cur[1] - cur[0] >= after
    value = {"in_block": cur is not None, "long": long_now, "blocks": len(bs),
             "long_blocks": sum(1 for s, e in bs if e - s >= after)}
    out = envelope(value, "proxy", max(0.0, now - got["rows_end"]) / 3600)
    out["label"] = dict(label, label=BLOCK_LABELS[0] if long_now else BLOCK_LABELS[1])
    return out


FLOW_DAYS = 7


def _flow_raw(m: dict) -> dict:
    back = m.get("median_return_s")
    return {"switches_per_work_h": None if m["switches_per_work_h"] is None else round(m["switches_per_work_h"], 2),
            "long_block_share": None if m["long_block_share"] is None else round(m["long_block_share"], 2),
            "median_return_min": None if back is None else round(back / 60, 1)}


def flow_metrics(reader: StateReader, now: float, raw: bool = False, env: Optional[Mapping[str, str]] = None,
                 home: Optional[Path] = None, tz=None) -> dict:
    """limitless_flow_metrics: how broken up the work was over the last FLOW_DAYS days (flow_metrics), read-only.

    An envelope whose value is ``{days, work_days, label}`` (counts and the T1 words: work stayed in long
    blocks, work was broken up, mixed) with the T1 label beside it; modality proxy, evidence_tier
    observed-activity (stale when the newest activity row is over a day old), aged by that row. The numbers
    (``switches_per_work_h``, ``long_block_share``, ``median_return_min`` and ``per_day``) are T0 and appear
    only with ``raw`` (LIMITLESS_RAW_IN_PROMPT). No DB, no work apps or no activity row is value None with
    the label "unknown: <why>", never zero. Observed app activity, not attention: no score, no target.
    """
    got = _flow_metrics.read_for(reader, now - FLOW_DAYS * 86400.0, now, env, home, tz,
                                 no_rows="no activity rows in the last seven days")
    th, pool = got["thresholds"], got["pool"]
    label = {"tier": "T1", "modality": "proxy"}
    if pool is None:
        out = envelope(None, "proxy", None, reason=f"flow metrics unknown: {got['why']}")
        out["label"] = dict(label, label=_flow_metrics.label(None, why=got["why"]))
        return out
    word = _flow_metrics.label(pool, th=th)
    value = {"days": pool["days"], "work_days": pool["work_days"], "label": word}
    if raw:
        value.update(_flow_raw(pool))
        value["per_day"] = [dict(day=d["day"], work_h=round(d["work_h"], 2), **_flow_raw(d),
                                 label=_flow_metrics.label(d, th=th)) for d in got["days"]]
    out = envelope(value, "proxy", max(0.0, now - got["rows_end"]) / 3600)
    if out["evidence_tier"] != "stale":
        out["evidence_tier"] = _flow_metrics.EVIDENCE_TIER
    out["label"] = dict(label, label=word)
    return out
