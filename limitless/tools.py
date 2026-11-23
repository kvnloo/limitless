"""Tool bodies as plain functions of (reader, now, ...) returning evidence envelopes. Handlers live in plugin.py."""
from __future__ import annotations

from datetime import date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Mapping, Optional

from . import (anki as _anki, app_candidates as _app_candidates, asks as _asks, blocks as _blocks, body_calibration as _body_calibration,
               delivery_audit as _delivery,
               explain_back as _explain_back,
               feed_reflex as _feed_reflex, feeds_evidence,
               habit_catalogue as _habit_catalogue, idea_ledger as _idea_ledger,
               flow_ledger as _flow_ledger, flow_metrics as _flow_metrics, habit_start as _habit_start, jobs, jobs_runner, labeler as _labeler, modes as _modes,
               naps as _naps, presleep_hr as _presleep_hr,
               overnight as _overnight, owner_messages as _owner, palace as _palace, passive_habit, peak as _peak,
               phase as _phase,
               prediction as _prediction, propose as _propose,
               quiet as _quiet, regularity as _regularity, rides as _rides, schedule_cards as _schedule_cards,
               scorecard as _scorecard, skill_tree as _skill_tree, sleep as _sleep, sleep_debt as _sleep_debt,
               stop_rule as _stop_rule,
               strength as _strength, tier_audit as _tier_audit,
               weekly_target as _weekly_target, wind_down)
from . import mock_guard as _mock_guard
from .envelope import STALE_H, _tier as _envelope_tier, envelope, missing, with_label
from .state_reader import (BODY_CONFIG, OWNER_BEACONS_CONFIG, OWNER_BEACONS_ENV, OWNER_DBS_CONFIG, OWNER_DBS_ENV,
                           PRESLEEP_HR_CONFIG, RIDES_CONFIG, SLEEP_CONFIG, WORK_QUEUE_CONFIG, StateReader, config, parse_ts)
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
    count against the one decision per peak window; focused mode (modes.py) holds them like a focus block.
    Read-only; nothing sends."""
    rows = _asks.read(_asks.queue_path(env, home))
    events = EventProvider.from_reader(reader, now, bands)
    state = {"value": "asleep"} if events.asleep else first_known(GlideProvider.from_config(env, home, now=now),
                                                                 events)
    state = _modes.apply(state, _modes.load(reader.path))   # focused holds non-urgent asks like a focus block
    sent = _asks.delivered_since(rows, wake_at(reader.sleepmode()))
    todo = _asks.pending(rows)
    return _asks.summary(todo, _asks.plan(todo, state, sent))


def post_wake_peak(reader: StateReader, now: float, env: Optional[Mapping[str, str]] = None,
                   home: Optional[Path] = None) -> dict:
    """``{open, in_use, why, label}`` (peak.read_for) with a digit-free T1 label, a proxy: post-wake peak: open,
    post-wake peak: in use, post-wake peak: closed, or unknown (no wake seen, or too old)."""
    p = _peak.read_for(reader, now, env, home)
    word = p["label"] or (_peak.CLOSED if p["why"].startswith("closed") else _labeler.UNKNOWN)
    return {"open": p["open"], "in_use": p["in_use"], "why": p["why"],
            "label": {"label": word, "tier": "T1", "modality": "proxy"}}


def window(reader: StateReader, now: float, bands: Optional[Mapping] = None,
           env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> dict:
    """limitless_window: the window.py envelope plus ``asks`` (asks_view) and ``post_wake_peak``."""
    out = _window(reader, now, bands)
    out["asks"] = asks_view(reader, now, bands, env, home)
    out["post_wake_peak"] = post_wake_peak(reader, now, env, home)
    return out


def labeled(env: dict) -> dict:
    """env with the T1 age label (fresh | stale | missing | unknown) next to its value, where allowed."""
    if not isinstance(env, dict):
        return env
    return with_label(env, _labeler.label("age_h", env.get("age_h"), env.get("modality")))


def status(reader: StateReader, now: float, cfg: Optional[Mapping] = None) -> dict:
    """Each input's current age, which inputs are not recording (> STALE_H old or down), the last run. An input
    named for a demo or sample device (mock_guard, with ``cfg``'s mock_device_patterns) is state "demo": no age,
    listed as unknown, never recording."""
    inp = reader.inputs()
    if not inp or not isinstance(inp.get("ageHours"), dict):
        return missing("no inputs.json (with ageHours) in the state dir")
    snap_h = _age_h(inp.get("at"), now)
    inputs, not_recording, unknown = {}, [], []
    for name, age in sorted(inp["ageHours"].items()):
        if _mock_guard.is_mock(name, cfg):
            inputs[name] = {"age_h": None, "state": "demo"}
            unknown.append(name)
        elif age == "down":
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
    ``target`` (weekly_target.progress: done, logged, target, reached and a digit-free T1 label) is the
    week so far against config ``habit_target_days`` (default four of seven; wording, not a rule): No,
    Skipped and unlogged days never reduce it, there is no streak and nothing resets. The label is a proxy
    when the sync filled a day.
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
    value["target"] = _weekly_target.progress(
        {d["date"]: d["checkin"] for d in days}, start, today, _weekly_target.target_days(env, home),
        "proxy" if any(d["from"] == "sync" for d in days) else "self_report")
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


def habit_start(state_dir, habit, today: date, now: float, confirm: bool = False, stop_rule=None) -> dict:
    """Start this week's one habit (habit_start.start_week), writing only when ``confirm`` is True.

    An envelope whose value is the start row ``{action, reason, habit, week_of, kept}``, self-reported and
    of age zero, with a digit-free T1 label: would start this habit week, started this habit week or
    refused: <why>. Without confirm it writes nothing and says what it would do. ``stop_rule`` is the
    week's stop rule id (stop_rule.RULES), stored with the week; None for no rule.
    """
    r = _habit_start.start_week(state_dir, habit, today, confirm is True, now=now, stop_rule=stop_rule)
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


def habit_predict(state_dir, text, metric, direction, today: date, now: float, confirm: bool = False,
                  falsifier=None, lag_days=0) -> dict:
    """Lock a prediction for the habit week (prediction.lock), writing only when ``confirm`` is True.

    The week is habit.json's while it runs or is set to start later, else today. An envelope whose value is
    ``{action, reason, prediction}``, with a digit-free T1 label: would lock this prediction, locked this
    prediction or refused: <why>. Without confirm it writes nothing and says what it would do. ``falsifier``
    (the person's words) and ``lag_days`` (prediction.LAG_DAYS) go on the prediction row.
    """
    week = _predict_week(state_dir, today)
    r = _prediction.lock(state_dir, week.isoformat(), text, metric, direction, write=confirm is True,
                         today=today, now=now, falsifier=falsifier, lag_days=lag_days)
    return _labeled_row(r, _prediction.label(r))


def _receipt_week(state_dir, today: date) -> Optional[str]:
    """The newest locked prediction that is due (its judged span is over: prediction.due_day) and has no
    receipt, else the newest locked one."""
    preds = [r for r in _prediction.rows(state_dir) if r.get("kind") == "prediction" and isinstance(r.get("week_of"), str)]
    for p in reversed(preds):
        due = _prediction.due_day(p)
        if due is not None and today >= due and _prediction.receipt_for(state_dir, p["week_of"]) is None:
            return p["week_of"]
    return preds[-1]["week_of"] if preds else None


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


EXPERIMENT_MODALITY = "derived"
EXPERIMENT_PAST = 8               # the past experiments the tool lists, newest first
EXPERIMENT_NOTE = ("read-only and a suggestion only: a prediction is locked only through limitless_habit predict "
                   "after the person said yes in this turn; a receipt only through limitless_habit receipt")
_LAG_WORDS = {7: "outcome judged on the week after the habit week",
              14: "outcome judged on the second week after the habit week"}


def _experiment_open(p: dict, today: date) -> str:
    """The words for an unjudged prediction: running (its habit week is on or ahead), waiting (a lag not yet
    passed) or ready to judge."""
    start, due = _prediction._day(p.get("week_of")), _prediction.due_day(p)
    if start is None or due is None:
        return "one experiment not dated"
    if today < start + timedelta(days=_prediction.WEEK_DAYS):
        return "one experiment running, outcome pending"
    if today < due:
        return "one experiment waiting, outcome pending (judged later)"
    return "one experiment ready to judge"


def _experiment_past(p: dict, r: Optional[dict], today: date, raw: bool) -> dict:
    if r is not None:
        verdict = r.get("verdict") if isinstance(r.get("verdict"), str) else _prediction.INCONCLUSIVE
    else:
        due = _prediction.due_day(p)
        verdict = _prediction.PENDING if due is not None and today < due else "not judged"
    out = {"week_of": p.get("week_of"), "verdict": verdict, "falsifier_stated": _prediction.falsifier_of(p) is not None}
    if raw:
        out.update(text=p.get("text"), falsifier=_prediction.falsifier_of(p))
    return out


def experiment(state_dir, now: float, today: date, raw: bool = False) -> dict:
    """limitless_experiment: one read-only view over the prediction ledger (predictions.jsonl).

    ``value: {current, past}``: ``current`` is plain words for the newest prediction with no receipt (running,
    waiting on its lag, ready to judge; whether a falsifier was stated; the lagged span in words), or "no
    experiment locked" / "no experiment running"; ``past`` is every other prediction, newest first (at most
    EXPERIMENT_PAST), as ``{week_of, verdict (the receipt's, else pending or not judged), falsifier_stated}``.
    Modality derived; ``age_h`` is the age of the newest prediction or receipt row; evidence_tier as a
    self-report of that age (none before anything is locked). The T1 label is the current words' first part,
    digit-free. The prediction and falsifier text are the person's own words (T0): only with ``raw``
    (LIMITLESS_RAW_IN_PROMPT). ``strength`` (beside the envelope, once anything is locked) is the newest
    prediction's habit on the evidence ladder (strength.py), in words. No score, no streak; nothing is written,
    sent or locked.
    """
    if not Path(state_dir).is_dir():
        return missing("the state dir does not exist")
    rows = _prediction.rows(state_dir)
    preds = [r for r in rows if r.get("kind") == "prediction" and isinstance(r.get("week_of"), str)]
    seen, firsts = set(), []
    for p in preds:                          # the first prediction of a week is the locked one
        if p["week_of"] not in seen:
            seen.add(p["week_of"])
            firsts.append(p)
    receipts = {p["week_of"]: _prediction.receipt_for(state_dir, p["week_of"]) for p in firsts}
    open_ = next((p for p in reversed(firsts) if receipts[p["week_of"]] is None), None)
    if not firsts:
        word, current = "no experiment locked", "no experiment locked"
    elif open_ is None:
        word, current = "no experiment running", "no experiment running"
    else:
        word = _experiment_open(open_, today)
        bits = [word, "falsifier stated" if _prediction.falsifier_of(open_) else "no falsifier stated"]
        lag_words = _LAG_WORDS.get(_prediction.lag_of(open_) or 0)
        if lag_words:
            bits.append(lag_words)
        current = "; ".join(bits)
    past = [_experiment_past(p, receipts[p["week_of"]], today, raw)
            for p in reversed(firsts) if p is not open_][:EXPERIMENT_PAST]
    value = {"current": current, "past": past}
    if raw and open_ is not None:
        value["prediction"] = {"text": open_.get("text"), "falsifier": _prediction.falsifier_of(open_)}
    ages = [a for a in (_age_h(r.get("at") if r.get("kind") == "receipt" else r.get("locked_at"), now)
                        for r in rows if r.get("kind") in ("prediction", "receipt")) if a is not None]
    age = round(min(ages), 1) if ages else None
    tier = "none" if not firsts else _envelope_tier("self_report", age)
    out = {"value": value, "modality": EXPERIMENT_MODALITY, "age_h": age, "evidence_tier": tier,
           "label": _t1(word, EXPERIMENT_MODALITY), "note": EXPERIMENT_NOTE}
    if firsts:                               # the newest prediction's habit, on the evidence ladder
        out["strength"] = _habit_strength(state_dir, firsts[-1]["week_of"])
    return out


def _habit_strength(state_dir, week_of: str, habit=None) -> dict:
    """strength.habit_strength for the habit of ``week_of`` (its kept habit file, else ``habit``, the loop
    row's name); with no name, that week alone. Words only, beside the envelope, never in it."""
    start = _prediction._day(week_of)
    h = _prediction.week_habit(state_dir, start) if start is not None else None
    name = h.get("habit") if isinstance(h, dict) and isinstance(h.get("habit"), str) and h["habit"].strip() else habit
    return _strength.habit_strength(state_dir, name if isinstance(name, str) else None, week_of)


LOOP_WEEKS = 4                    # "the last few" weekly loop rows the tool shows
_NUMBER_WORDS = ("two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")
_RULE_SAID = {"keep": "your rule said keep it", "drop": "your rule said drop it",
              "your call": "your rule said your call"}
_DECIDED = {"Keep": "kept", "Drop": "dropped"}


def _week_words(week_of, today: date) -> str:
    """this week, last week, two weeks ago ... ten weeks ago, else earlier (or a week not dated)."""
    try:
        back = (today - date.fromisoformat(str(week_of))).days // 7
    except ValueError:
        return "a week not dated"
    if back <= 0:
        return "this week"
    if back == 1:
        return "last week"
    return f"{_NUMBER_WORDS[back - 2]} weeks ago" if back - 2 < len(_NUMBER_WORDS) else "earlier"


def _t1(word: str, modality: str) -> dict:
    return {"label": word, "tier": "T1", "modality": modality}


def _loop_week(r: dict, now: float, today: date) -> dict:
    decided = _DECIDED.get(r.get("decision"), "not decided")
    decision = envelope(decided, "self_report", _age_h(r.get("decided_at"), now))
    decision["label"] = _t1(decided, "self_report")
    outcome = r.get("outcome")
    if outcome in (_prediction.SUPPORTS, _prediction.CONTRADICTS, _prediction.INCONCLUSIVE):
        modality = r.get("outcome_modality") or "proxy"   # a state metric whose rows name none: the weakest claim
        out = envelope(outcome, modality, _age_h(r.get("outcome_at"), now))
        out["label"] = _t1(outcome, modality)
    elif r.get("prediction") == _stop_rule.LOCKED_LABEL:
        out = missing("no receipt for that week's prediction when the person decided")
    else:
        out = missing("no prediction was locked for that week")
    rule = "no rule set" if r.get("rule") is None else _RULE_SAID.get(r.get("verdict"), "your rule could not tell")
    return {"week": _week_words(r.get("week_of"), today), "habit": r.get("habit"),
            "prediction": "prediction locked" if r.get("prediction") == _stop_rule.LOCKED_LABEL else "no prediction",
            "rule": rule, "outcome": out, "decision": decision}


def loop(state_dir, now: float, today: date) -> dict:
    """The last LOOP_WEEKS weekly loop rows (stop_rule.loop_rows), newest first, in T1 words: the week, the
    habit, whether a prediction was locked, what the stop rule said, the outcome (the receipt's verdict, with
    the receipt's own modality) and the decision (self_report: the person's Keep or Drop). ``strength`` (beside
the envelope) is the newest week's habit on the evidence ladder (strength.py), in words. Read-only."""
    rows = _stop_rule.loop_rows(state_dir)[-LOOP_WEEKS:][::-1]
    if not rows:
        return missing("no week decided yet: no loop row")
    weeks = [_loop_week(r, now, today) for r in rows]
    out = envelope({"weeks": weeks}, "self_report", _age_h(rows[0].get("decided_at"), now))
    out["label"] = _t1(f"latest week: {weeks[0]['decision']['value']}", "self_report")
    out["strength"] = _habit_strength(state_dir, str(rows[0].get("week_of")), rows[0].get("habit"))
    return out


HABIT_NEXT_MODALITY = "derived"
HABIT_NEXT_NOTE = ("a suggestion only: nothing was started; the person starts it by saying start habit, and then "
                   "limitless_habit start runs with their yes")


def habit_next(state_dir, now: float, today: date, env: Optional[Mapping[str, str]] = None,
               home: Optional[Path] = None, tz=None) -> dict:
    """limitless_habit_next: habit_catalogue.next_habit over the weekly loop rows (stop_rule.loop_rows) and the
    running week (habit.json, while jobs.habit_week_gate is None), as a derived envelope: value ``{id, name,
    cue, start}``, ``age_h`` None, the evidence_tier of the newest decision used (self-reported; ``none`` before
    any week was decided) and the digit-free T1 label "next habit: <name>". Null with a plain reason when the
    list is exhausted. When the last seven days' feed reflex (feed_reflex) is "often", the circuit breaker may
    come first (habit_catalogue.next_habit ``reflex_often``). It only suggests: read-only, nothing is written,
    sent or started."""
    reader = StateReader(Path(state_dir))
    h = reader.habit()
    running = isinstance(h, dict) and jobs.habit_week_gate(h, today) is None
    rows = _stop_rule.loop_rows(state_dir)
    try:
        got = _feed_reflex.read_for(reader, now - _feed_reflex.LOOKBACK_DAYS * 86400.0, now, env, home, tz)
        often = got["label"] == _feed_reflex.OFTEN
    except Exception:  # noqa: BLE001 - broken activity data reads as not often, never as a failure
        often = False
    n = _habit_catalogue.next_habit(rows, current=h if running else None, reflex_often=often)
    if n.habit is None:
        out = missing(n.reason)
    else:
        ages = [a for a in (_age_h(r.get("decided_at"), now) for r in rows) if a is not None]
        tier = "none" if not rows else _envelope_tier("self_report", min(ages) if ages else None)
        out = {"value": {k: n.habit[k] for k in ("id", "name", "cue", "start")}, "modality": HABIT_NEXT_MODALITY,
               "age_h": None, "evidence_tier": tier, "because": n.reason,
               "label": _t1(f"next habit: {n.habit['name']}", HABIT_NEXT_MODALITY)}
    out["habit_week"] = "running" if running else "not running"
    out["note"] = HABIT_NEXT_NOTE
    return out


SKILL_TREE_MODALITY = "derived"
SKILL_TREE_NOTE = ("read-only and a suggestion only: it never starts a habit; a week with no Keep or Drop is "
                   "unlogged, never a drop")


def skill_tree_parts(state_dir, now: float, today: date):
    """(tree, evidence_tier) for the skill tree: habit_catalogue.CATALOGUE through skill_tree.tree, with the
    weekly loop rows (stop_rule.loop_rows) as the decisions and habit.json's habit as this week's (only while
    jobs.habit_week_gate is None). The tier is the newest self-reported decision's; none before any."""
    h = StateReader(Path(state_dir)).habit()
    running = isinstance(h, dict) and jobs.habit_week_gate(h, today) is None
    rows = _stop_rule.loop_rows(state_dir)
    t = _skill_tree.tree(_habit_catalogue.CATALOGUE, rows, current=h if running else None)
    ages = [a for a in (_age_h(r.get("decided_at"), now) for r in rows) if a is not None]
    tier = "none" if not rows else _envelope_tier("self_report", min(ages) if ages else None)
    return t, tier


def skill_tree(state_dir, now: float, today: date) -> dict:
    """limitless_skill_tree: the four layers (Foundation, Learning, Flow, Enhancement), whether each is open,
    and one state word per habit (kept, dropped, trying, not tried), as a derived envelope with ``age_h``
    None and the digit-free T1 label "Foundation open, one habit kept". No score, level or streak. Read-only:
    nothing is written, sent or started."""
    t, tier = skill_tree_parts(state_dir, now, today)
    return {"value": {"layers": t}, "modality": SKILL_TREE_MODALITY, "age_h": None, "evidence_tier": tier,
            "label": _t1(_skill_tree.label(t), SKILL_TREE_MODALITY), "note": SKILL_TREE_NOTE}


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
    """limitless_body: the body-fat trend (body_calibration.trend, over body.trend) for ``today``, read-only.

    An envelope whose value is ``{recent_rows, prior_rows, label}`` (counts and the T1 words) with the T1
    label beside it; modality measured when every row in both windows is calibrated, else proxy; aged by the
    body file's mtime. With reference scans in the file (body_calibration) the trend reads the calibrated
    rows and ``calibration`` holds the fit's T1 words; the fit's numbers never appear, raw or not.
    Raw numbers (``recent_median``, ``prior_median``, ``change``) are T0 and appear only
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
    t = _body_calibration.trend(rows, today, env, home)
    value = {"recent_rows": t["recent"]["rows"], "prior_rows": t["prior"]["rows"], "label": t["label"]["label"]}
    if "calibration" in t:
        value["calibration"] = t["calibration"]["label"]
    if raw:
        for k, v in (("recent_median", t["recent"]["median"]), ("prior_median", t["prior"]["median"]),
                     ("change", t["change"])):
            value[k] = None if v is None else round(v, 2)
    out = envelope(value, t["modality"], age_h)
    out["label"] = t["label"]
    if "calibration" in t:
        out["calibration"] = t["calibration"]
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


def anki(reader: StateReader, now: float, today: date, raw: bool = False, env: Optional[Mapping[str, str]] = None,
         home: Optional[Path] = None, tz=None) -> dict:
    """limitless_anki: this week's Anki reviews (anki.for_week), measured from Anki's own review log.

    "This week" is the running habit week when today is one of its days, else the seven days ending today
    (anki.week_first). An envelope whose value is ``{label}`` (the T1 words) with the T1 label beside it;
    modality measured, age_h from the newest review (stale when it is over a day old or there is none). The
    raw count and the day counts (``count``, ``days_with_review``, ``days_so_far``) are T0 and appear only
    with ``raw`` (LIMITLESS_RAW_IN_PROMPT). No collection set or an unreadable one is value None with a
    path-free reason (unknown, not zero). The collection is opened read-only and never written.
    """
    w = _anki.for_week(_anki.week_first(reader.habit(), today), today, tz, env, home)
    if w["count"] is None:
        return missing(w["reason"] or _anki.NO_COLLECTION)
    age_h = None if w["newest_s"] is None else max(0.0, now - w["newest_s"]) / 3600
    value = {"label": w["label"]["label"]}
    if raw:
        value.update(count=w["count"], days_with_review=w["days_with_review"], days_so_far=w["days_so_far"])
    out = envelope(value, _anki.MODALITY, age_h)
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


RAW_DEBT_MIN = (("baseline_median_min", "baseline_median_s"), ("recent_mean_min", "recent_mean_s"),
                ("short_min", "short_s"))
RAW_DEBT = ("short_share", "recent_nights", "unknown_nights", "baseline_nights", "proxy_nights")


def sleep_debt(reader: StateReader, now: float, today: date, raw: bool = False,
               env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None, tz=None) -> dict:
    """limitless_sleep_debt: the last few nights against the person's own usual night, in words (sleep_debt.debt).

    Reads exactly what limitless_sleep reads (StateReader.sleep_rows and sleep.screen_gaps over
    jobs_runner.person_rows) through one sleep.nights call over the RECENT_NIGHTS + BASELINE_NIGHTS nights before
    ``today``: the newest RECENT_NIGHTS are the recent nights, the rest the baseline. An envelope whose value is
    ``{label}`` (little / some / a lot of sleep debt, with " (phone estimate)" when a proxy night was used) with
    the T1 label beside it; modality from sleep_debt (proxy when any night used is a proxy night); age_h as
    limitless_sleep's. Minutes, the shortfall share and the night counts are T0 and appear only with ``raw``
    (LIMITLESS_RAW_IN_PROMPT). Too few nights is value None with the reason "unknown: too few nights"; no data at
    all is limitless_sleep's missing reason. No target, no advice, no score. Read-only.
    """
    wear = reader.sleep_rows(today, env, home)
    gaps = _sleep.screen_gaps(jobs_runner.person_rows(reader, env, home))
    if not wear and not gaps:
        if reader.sleep_file(env, home) is None:
            return missing(f"no sleep data: no wearable file (set \"{SLEEP_CONFIG}\" in config.json) and no phone "
                           "screen events")
        return missing("no sleep data: no night in the configured wearable sleep file and no phone screen events")
    ns = _sleep.nights(wear, gaps, today, days=_sleep_debt.RECENT_NIGHTS + _sleep_debt.BASELINE_NIGHTS, tz=tz)
    got = _sleep_debt.debt(ns[-_sleep_debt.RECENT_NIGHTS:], ns[:-_sleep_debt.RECENT_NIGHTS])
    newest = _sleep.newest_at([r for r in wear if r["night"] < today.isoformat()],
                              [g for g in gaps if g[1] <= now], tz)
    age_h = None if newest is None else max(0.0, now - newest) / 3600
    if got["word"] is None:
        return envelope(None, got["modality"], age_h, reason=got["label"]["label"])
    value = {"label": got["label"]["label"]}
    if raw:
        value.update({k: _minutes(got[s]) for k, s in RAW_DEBT_MIN})
        value.update({k: got[k] for k in RAW_DEBT})
    out = envelope(value, got["modality"], age_h)
    out["label"] = got["label"]
    return out


def presleep_hr(reader: StateReader, now: float, raw: bool = False, env: Optional[Mapping[str, str]] = None,
                home: Optional[Path] = None, tz=None) -> dict:
    """limitless_presleep_hr: the newest wearable night's pre-sleep heart rate against the usual (presleep_hr.latest).

    An envelope whose value is ``{label}`` (the T1 words: lower than usual, about usual or higher than usual,
    with the wearable named) with the T1 label beside it; modality measured (only the wearable's rows are read);
    age_h from the local midnight after the newest wearable night. ``bpm``, ``baseline_bpm``, ``baseline_nights``
    and ``night`` are T0 and appear only with ``raw`` (LIMITLESS_RAW_IN_PROMPT). No file configured is missing
    with a reason that never echoes the path; no wearable row, only phone rows, too few earlier nights or a
    stale newest night is value None with presleep_hr's plain reason: unknown, never zero, never a phone
    guess. No advice, no target, no score. Read-only.
    """
    if reader.presleep_hr_file(env, home) is None:
        return missing(f"no pre-sleep heart-rate file: set \"{PRESLEEP_HR_CONFIG}\" in config.json")
    got = _presleep_hr.latest(reader.presleep_hr_rows(env, home), now, tz)
    if got["word"] is None:
        return envelope(None, got["modality"], got["age_h"], reason=got["reason"])
    value = {"label": got["label"]["label"]}
    if raw:
        value.update(bpm=got["bpm"], baseline_bpm=got["baseline_bpm"], baseline_nights=got["baseline_nights"],
                     night=got["night"])
    out = envelope(value, got["modality"], got["age_h"])
    out["label"] = got["label"]
    return out


BREATHING_MODALITY = "derived"     # from config and inputs.json's wearable age, not a measure of breathing
BREATHING_HIDDEN = "a link is set"
BREATHING_NOT_USED = ("a link is configured but not used: it must be one link with a scheme such as example://, "
                      "no space and no digit")
BREATHING_NOTE = ("a suggestion only: the wind-down line offers the person's own app by its link; nothing here "
                  "opens it, counts breaths, sets a pace or sends")


def breathing(reader: StateReader, now: float, raw: bool = False, env: Optional[Mapping[str, str]] = None,
              home: Optional[Path] = None) -> dict:
    """limitless_breathing: whether the wind-down line offers slow breathing in the person's own app (config
    ``wind_down_breathing_link``, wind_down.breathing_link) and whether live heart data backs it.

    ``value: {link_set, heart_data}``: ``heart_data`` is "with live heart data" only when inputs.json says the
    wearable is recording now (wind_down.wearable_live, the rule limitless_status uses), else "without heart
    data". With a link set, ``link`` is the link itself only with ``raw`` (LIMITLESS_RAW_IN_PROMPT), otherwise
    "a link is set"; a configured value that cannot ride in the line gets a ``note`` and is never echoed.
    Modality derived; ``age_h`` the wearable input's age (None when down or unknown); evidence_tier that of a
    measured input of that age. A digit-free T1 label. No breath count, pace, heart rate or heart rate
    variability value. Read-only; nothing is written or sent.
    """
    cfg = config(env, home)
    link = wind_down.breathing_link(cfg)
    inputs = reader.inputs()
    names = wind_down.wearable_inputs(cfg)
    age = wind_down.wearable_age_h(inputs, now, names)
    words = wind_down.breathing_words(wind_down.wearable_live(inputs, now, names))
    value = {"link_set": link is not None, "heart_data": words}
    if link is not None:
        value["link"] = link if raw else BREATHING_HIDDEN
    else:
        v = cfg.get(wind_down.BREATHING_KEY)
        if v is not None and not (isinstance(v, str) and not v.strip()):
            value["note"] = BREATHING_NOT_USED
    label = f"breathing link set, {words}" if link is not None else "breathing link off"
    return {"value": value, "modality": BREATHING_MODALITY, "age_h": age,
            "evidence_tier": _envelope_tier("measured", age), "label": _t1(label, BREATHING_MODALITY),
            "note": BREATHING_NOTE}


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


def flow_ledger(reader: StateReader, now: float, raw: bool = False, env: Optional[Mapping[str, str]] = None,
                home: Optional[Path] = None, tz=None) -> dict:
    """limitless_flow_ledger: yesterday's (the local day before ``now`` in ``tz``) focus blocks, whether a feed
    app leaked into each, and how many work-queue items landed (flow_ledger.read_for), read-only.

    An envelope whose value is ``{label}`` (the T1 words: "two long blocks, one with a feed leak; three items
    landed", "no long blocks") with the T1 label beside it; modality observed (app activity as observed),
    evidence_tier observed-activity (stale when the newest activity row of the day is over a day old), aged by
    that row. The day, the counts and each block's start and end seconds and app names are T0 and appear only
    with ``raw`` (LIMITLESS_RAW_IN_PROMPT); work-queue file names never appear. No DB, no work apps, no
    activity that day is value None with the label "unknown: <why>". No score, no ranking, no target, no
    advice. Nothing is written or sent.
    """
    from datetime import datetime
    day = datetime.fromtimestamp(now, tz).date() - timedelta(days=1)
    got = _flow_ledger.read_for(reader, day, now, env, home, tz)
    label = _flow_ledger.t1(got)
    if got["blocks"] is None or got["rows_end"] is None:
        out = envelope(None, "proxy", None, reason=f"flow ledger unknown: {got['why'] or _flow_ledger.NO_ACTIVITY}")
        out["modality"], out["label"] = _flow_ledger.MODALITY, label
        return out
    value = {"label": label["label"]}
    if raw:
        value.update(day=got["day"], long_blocks=got["long_blocks"], leaks=got["leaks"], landed=got["landed"],
                     blocks=[dict(b) for b in got["blocks"]])
    out = envelope(value, "proxy", max(0.0, now - got["rows_end"]) / 3600)
    out["modality"] = _flow_ledger.MODALITY
    if out["evidence_tier"] != "stale":
        out["evidence_tier"] = _flow_metrics.EVIDENCE_TIER
    out["label"] = label
    return out


NAPS_UNKNOWN = "naps unknown: no phone Sleep-mode change yesterday"


def naps(reader: StateReader, now: float, today: date, raw: bool = False, env: Optional[Mapping[str, str]] = None,
         home: Optional[Path] = None, tz=None) -> dict:
    """limitless_naps: yesterday's naps from phone Sleep mode (naps.day over sleepmode.jsonl), read-only.

    An envelope whose value is ``{label}`` (the T1 words: naps yesterday: none, one short nap or a few short naps,
    with ", close to the night" when one ended within config nap_near_night_h of the night's start) with the T1
    label beside it; modality proxy (Sleep mode is a phone switch, not a sensor), aged by the newest Sleep-mode
    change. The start and end seconds (``naps``) and the close count (``close``) are T0 and appear only with
    ``raw`` (LIMITLESS_RAW_IN_PROMPT). No Sleep-mode change yesterday is value None with a reason and the label
    "naps yesterday: unknown", never none. No target, no advice. Nothing is written or sent.
    """
    cfg = config(env, home)
    evs = jobs.events_from_sleepmode(reader.sleepmode())
    got = _naps.day(evs, today - timedelta(days=1), _naps.nap_max_h(cfg), _naps.near_night_h(cfg), tz)
    if got["naps"] is None:
        out = envelope(None, _naps.MODALITY, None, reason=NAPS_UNKNOWN)
        out["label"] = got["label"]
        return out
    newest = _naps.newest_at(evs, now)
    value = {"label": got["label"]["label"]}
    if raw:
        value.update(naps=got["naps"], close=got["close"])
    out = envelope(value, _naps.MODALITY, None if newest is None else max(0.0, now - newest) / 3600)
    out["label"] = got["label"]
    return out


def feed_reflex(reader: StateReader, now: float, raw: bool = False, env: Optional[Mapping[str, str]] = None,
                home: Optional[Path] = None, tz=None) -> dict:
    """limitless_feed_reflex: over the last feed_reflex.LOOKBACK_DAYS days, how often a feed app was the first
    thing opened after unlocking the phone (feed_reflex.read_for), read-only.

    An envelope whose value is ``{label}`` (the T1 words: a feed was often, sometimes or rarely the first thing
    opened after unlocking) with the T1 label beside it; modality proxy (an app opened first is not a feed
    read), aged by the newest phone row or unlock. The counts (``unlocks``, ``feed_first``, ``days``) and
    ``gap_s`` are T0 and appear only with ``raw`` (LIMITLESS_RAW_IN_PROMPT). No feed apps, no DB, no unlock
    or too few unlocks is value None with the reason and the label "unknown: <why>", never zero. It never
    blocks, closes or delays an app; no score, no streak, no target. Nothing is written or sent.
    """
    got = _feed_reflex.read_for(reader, now - _feed_reflex.LOOKBACK_DAYS * 86400.0, now, env, home, tz)
    word = got["label"]
    label = {"tier": "T1", "modality": _feed_reflex.MODALITY, "label": word}
    if word not in _feed_reflex.WORDS:
        out = envelope(None, _feed_reflex.MODALITY, None, reason=f"feed reflex {word}")
        out["label"] = label
        return out
    value = {"label": word}
    if raw:
        value.update(unlocks=got["unlocks"], feed_first=got["feed_first"], gap_s=got["gap_s"],
                     days=[dict(d) for d in got["days"]])
    out = envelope(value, _feed_reflex.MODALITY, max(0.0, now - got["newest"]) / 3600)
    out["label"] = label
    return out


_COUNT = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")


def _apps_words(entries) -> str:
    n, kept = len(entries), sum(1 for e in entries if e.get("kept"))
    words = (_COUNT[n] if n < len(_COUNT) else "more than ten") + (" app" if n == 1 else " apps")
    if kept:
        words += ", " + (_COUNT[kept] if kept < len(_COUNT) else "more than ten") + " kept"
    return words


def app_candidates(reader: StateReader, now: float, raw: bool = False, env: Optional[Mapping[str, str]] = None,
                   home: Optional[Path] = None) -> dict:
    """limitless_app_candidates: the work-app and feed-app lists proposed from the last
    app_candidates.LOOKBACK_DAYS days of observed app time (app_candidates.read_for), read-only.

    An envelope whose value is ``{label, work, feed}`` in words (which lists are proposed; how many apps each
    holds and how many are already kept), with the T1 label beside it; modality proxy, aged by the newest
    row. App names are the person's own data: the ready-to-send ``reply`` and the lists (``work``, ``feed``,
    ``other`` with names, seconds and kept) appear only with ``raw`` (LIMITLESS_RAW_IN_PROMPT). No source,
    no rows, too little activity or no work or feed app is value None with the reason, never empty lists.
    It only suggests: it never writes config or any file and never sends.
    """
    got = _app_candidates.read_for(reader, now, env, home)
    word = got["label"]
    label = {"tier": "T1", "modality": _app_candidates.MODALITY, "label": word}
    if word not in _app_candidates.WORDS:
        out = envelope(None, _app_candidates.MODALITY, None, reason=f"app candidates {word}")
        out["label"] = label
        return out
    value = {"label": word, "work": _apps_words(got["work"]), "feed": _apps_words(got["feed"])}
    if raw:
        lists = {k: [{"name": e["name"], "seconds": e["seconds"], "kept": e["kept"]} for e in got[k]]
                 for k in ("work", "feed", "other")}
        value.update(lists, reply=_app_candidates.reply_line(got), sources=list(got["sources"]),
                     total_s=got["total_s"], max_n=got["max_n"])
    out = envelope(value, _app_candidates.MODALITY, max(0.0, now - got["newest"]) / 3600)
    out["label"] = label
    return out


_PEAK_WORDS = {_peak.OPEN: "open", _peak.IN_USE: "in use", _peak.CLOSED: "closed"}
_HELD_QUIET = {_quiet.OFF: "off", _quiet.TONIGHT: "quiet tonight", _quiet.SNOOZED: "snoozed"}


def peak_ask_label(rows: Optional[list], wake: Optional[float]) -> Optional[str]:
    """``waiting`` (a pending, non-urgent peak ask and none delivered since the wake), ``spent`` (one was
    delivered since the wake: one decision per peak window), ``none`` (no pending peak ask), or None
    (unknown) when there is no queue configured (``rows`` None)."""
    if rows is None:
        return None
    todo = [r for r in _asks.pending(rows) if r.get("urgent") is not True and _asks.classify(r) == _asks.PEAK]
    if not todo:
        return "none"
    return "spent" if _asks.delivered_since(rows, wake) else "waiting"


def _guard(fn, default):
    try:
        return fn()
    except Exception:  # noqa: BLE001 - one unreadable source is unknown, never a traceback
        return default


def propose_state(reader: StateReader, now: float, today: date, bands: Optional[Mapping] = None,
                  env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None):
    """``(state, tiers)`` for propose.propose: each of propose.STATE_KEYS as a known value or None (unknown),
    built read-only from the labels the other tools already compute, and the evidence_tier of each.
    Nothing is written or sent."""
    state = {k: None for k in _propose.STATE_KEYS}
    tiers = {k: "none" for k in _propose.STATE_KEYS}
    if not Path(reader.path).is_dir():
        return state, tiers   # no state dir: every label unknown

    def put(key, value, tier):
        if value is not None and value in _propose.STATE_KEYS[key]:
            state[key], tiers[key] = value, tier

    # the window chain, as asks_view reads it: asleep from events; Glide first, then the event classifier
    events = _guard(lambda: EventProvider.from_reader(reader, now, bands), None)
    if events is not None:
        cls = events.classification
        ev_tier = cls.get("evidence_tier", "none")
        if cls.get("value") == "asleep":
            put("asleep", True, ev_tier)
        elif cls.get("value") in ("peak", "trough", "anytime", "wind_down"):
            put("asleep", False, ev_tier)
        if not events.asleep:
            glide = _guard(lambda: GlideProvider.from_config(env, home, now=now), None)
            win = first_known(glide, events)
            put("window", win.cls, ev_tier if win.source == "events" else "indirect")
            if win.hold_asks:
                put("focus_block", "in a block", "indirect")
    if state["focus_block"] is None:
        b = _guard(lambda: blocks(reader, now, env, home), {})
        v = b.get("value") if isinstance(b, dict) else None
        if isinstance(v, dict) and isinstance(v.get("in_block"), bool):
            put("focus_block", "in a block" if v["in_block"] else "between blocks", b.get("evidence_tier"))
    put("mode", _guard(lambda: _modes.load(reader.path), None), "direct")
    q = _guard(lambda: quiet(reader.path, now, env, home), {})
    qv = q.get("value") if isinstance(q, dict) else None
    if isinstance(qv, dict):
        put("quiet", _HELD_QUIET.get(qv.get("mode"), "on") if qv.get("held") is True else "on",
            q.get("evidence_tier"))
    pk = _guard(lambda: post_wake_peak(reader, now, env, home), {})
    put("post_wake_peak", _PEAK_WORDS.get(((pk or {}).get("label") or {}).get("label")), "indirect")
    qp = _guard(lambda: _asks.queue_path(env, home), None)
    rows = None if qp is None else _guard(lambda: _asks.read(qp), None)
    put("peak_ask", peak_ask_label(rows, _guard(lambda: wake_at(reader.sleepmode()), None)), "direct")
    put("anki", "set" if _guard(lambda: _anki.collection_path(env, home), None) is not None else "not set",
        "direct")
    put("palace", "set" if _guard(lambda: _palace.link(config(env, home)), None) is not None else "not set",
        "direct")
    h = _guard(lambda: _habit_week(reader, now, today, env, home), {})
    hv = h.get("value") if isinstance(h, dict) else None
    if isinstance(hv, dict) and hv.get("habit"):
        put("habit_week", "running", h.get("evidence_tier"))
        put("habit_today", hv.get("today"), h.get("evidence_tier"))
    elif isinstance(h, dict) and (h.get("reason") or isinstance(hv, dict)):
        put("habit_week", "not running", h.get("evidence_tier") if hv else "direct")
    return state, tiers


def propose(reader: StateReader, now: float, today: date, bands: Optional[Mapping] = None,
            env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> dict:
    """limitless_propose: propose.propose over propose_state, as propose.derived's envelope. Read-only: it
    only suggests; nothing is written, sent, scheduled or started."""
    state, tiers = propose_state(reader, now, today, bands, env, home)
    return _propose.derived(_propose.propose(state), tiers)


def ideas(reader: StateReader, now: float, raw: bool = False, env: Optional[Mapping[str, str]] = None,
          home: Optional[Path] = None) -> dict:
    """limitless_ideas: the idea ledger's last seven days (idea_ledger.week), read-only.

    An envelope whose value is ``{label}`` (the T1 words: "a few new ideas this week, none triaged") with the T1
    label beside it; modality self_report (the person's own captures), aged by the newest idea row. The counts
    and each idea's id, time, text, source and status are T0 and appear only with ``raw``
    (LIMITLESS_RAW_IN_PROMPT). No ledger set is value None with the reason "no idea ledger set". No triage, no
    ranking, no advice: the person triages in a review. Nothing is written or sent.
    """
    if reader.idea_ledger_path(env, home) is None:
        return envelope(None, _idea_ledger.MODALITY, None, reason=_idea_ledger.NO_LEDGER)
    w = _idea_ledger.week(reader.idea_ledger_rows(env, home), now)
    lab = _idea_ledger.t1(w)
    value = {"label": lab["label"]}
    if raw:
        value.update(recorded=w["recorded"], triaged=w["triaged"], ideas=[dict(x) for x in w["ideas"]])
    out = envelope(value, _idea_ledger.MODALITY, None if w["newest_at"] is None else (now - w["newest_at"]) / 3600)
    out["label"] = lab
    return out


def explain_back(reader: StateReader, now: float, raw: bool = False, env: Optional[Mapping[str, str]] = None,
                 home: Optional[Path] = None) -> dict:
    """limitless_explain_back: whether the explain-back offer was made for the latest wake event and how many
    answers the last seven days hold, in words (explain_back.offered_for, explain_back.answers), read-only.

    ``value: {offered, answered_this_week}`` (a bool and digit-free words such as "two this week"), modality
    self_report, aged by the newest of the offer and the answers, with a digit-free T1 label beside it. The
    answers' time, text and unknowns are T0 and appear only with ``raw`` (LIMITLESS_RAW_IN_PROMPT). No grade,
    score or streak; a skipped offer is not logged. Nothing is written or sent.
    """
    if not reader.exists():
        return missing("the state dir does not exist")
    offered, offered_at = _explain_back.offered_for(reader, now, env, home)
    got = _explain_back.answers(reader.captures(), now)
    value = {"offered": offered, "answered_this_week": _explain_back.answered_words(len(got))}
    if raw:
        value["answers"] = [{"at": r["at"], "text": r["text"], "unknowns": list(r.get("unknowns") or [])}
                            for _, r in got]
    times = [t for t, _ in got] + ([offered_at] if offered_at is not None and offered_at <= now else [])
    out = envelope(value, _explain_back.MODALITY, (now - max(times)) / 3600 if times else None)
    out["label"] = {"label": _explain_back.label(offered, len(got)), "tier": _explain_back.TIER,
                    "modality": _explain_back.MODALITY}
    return out


def palace(result) -> dict:
    """limitless_palace: whether the one memory palace offer fits now (palace.for_turn's result, which the plugin
    builds from the window the state card sees), read-only.

    ``value: {label}`` with the label "off" (and ``why``: "no memory palace link set"), "fits now" (and ``line``,
    the offer with the person's link) or "not now: <reason in words>". Modality derived, age_h None,
    evidence_tier direct when off (the config alone decides it), else indirect (the window is inferred). Words
    only: no time, no count of walks, no score; a result with a digit anywhere is not now. Nothing is written,
    marked or sent: only the state card's hook marks the wake day.
    """
    r = result if isinstance(result, Mapping) else {}
    word, words, line = r.get("word"), r.get("words"), r.get("line")
    ok = isinstance(words, str) and words and not any(c.isdigit() for c in words)
    if ok and line is not None:
        ok = word == _palace.FITS and isinstance(line, str) and not any(c.isdigit() for c in line)
    if not ok:
        word, words, line = _palace.NOT_NOW, f"{_palace.NOT_NOW}: {_palace.BROKEN}", None
    value = {"label": words}
    if word == _palace.OFF:
        value["why"] = _palace.NO_LINK
    elif word == _palace.FITS and line:
        value["line"] = line
    tier = "direct" if word == _palace.OFF else "indirect"
    return {"value": value, "modality": _palace.MODALITY, "age_h": None, "evidence_tier": tier,
            "label": {"label": words, "tier": "T1", "modality": _palace.MODALITY}}


def schedule(reader: StateReader, now: float, env: Optional[Mapping[str, str]] = None,
             home: Optional[Path] = None) -> dict:
    """limitless_schedule: every job's schedule card (schedule_cards.cards), read-only.

    ``value: {cards}`` holds the raw cards (ids, event names, stale_after_s, budget). Outside it only plain
    words: ``lines`` (one card description each) and the T1 ``label``, both through tier_audit.gate (hook
    tool:limitless_schedule, never opted in); a digit there drops both and says why. The habit cards follow
    habit.json's cue; ``external_jobs`` marks jobs another sender owns; a configured idea ledger adds its card,
    config ``noop_export`` (dry_run or write) adds the NOOP export's and config ``apps_ingest`` the apps ingest's.
    Modality derived, age_h None.
    Nothing is written, sent, scheduled or registered.
    """
    cards = _schedule_cards.cards(external=jobs_runner.external_jobs(env, home), habit=reader.habit(),
                                  ledger=reader.idea_ledger_path(env, home) is not None,
                                  noop=jobs.noop_mode(config(env, home)) != jobs.NOOP_OFF,
                                  apps=jobs.apps_mode(config(env, home)) != jobs.APPS_OFF)
    lines = [c["description"] for c in cards]
    word = _schedule_cards.label(len(cards))
    out = {"value": {"cards": cards}, "modality": _schedule_cards.MODALITY, "age_h": None, "evidence_tier": "direct"}
    if _tier_audit.gate(_schedule_cards.HOOK, "\n".join([word, *lines]), False, env=env, home=home, now=now) is None:
        out["reason"] = "the plain words held a digit, so they were left out; the cards are in value"
        return out
    out["lines"] = lines
    out["label"] = {"label": word, "tier": "T1", "modality": _schedule_cards.MODALITY}
    return out


def phase(reader: StateReader, now: float, env: Optional[Mapping[str, str]] = None,
          home: Optional[Path] = None) -> dict:
    """limitless_phase: the part of the day (phase.read_for), read-only.

    ``value: {phase}`` with phase just_woke, day, evening, asleep or unknown. Modality derived when a fresh
    posture file decided it, else proxy (the wake event, Sleep mode). ``age_h`` is the age of the event that
    decided it (the posture, the wind-down, the wake or Sleep mode on); evidence_tier as envelope.py (a fresh
    derived phase is indirect, like a proxy), none for unknown, with ``reason``. ``label`` is the T1 words
    ("just woke: a good time for outdoor light"), digit-free, with no clock time; ``why`` says which event,
    ``posture_ignored`` why a posture file was not used. Nothing is written, sent or scheduled.
    """
    r = _phase.read_for(reader, now, env, home)
    modality = "derived" if r["source"] == "posture" else "proxy"
    at = r.get("at")
    age = None if at is None else round(max(0.0, now - at) / 3600, 1)
    if r["phase"] == "unknown":
        tier = "none"
    else:
        tier = _envelope_tier("proxy", age)
    out = {"value": {"phase": r["phase"]}, "modality": modality, "age_h": age, "evidence_tier": tier,
           "label": {"label": _phase.label(r), "tier": "T1", "modality": modality}, "why": r["why"]}
    if r["phase"] == "unknown":
        out["reason"] = r["why"]
    if r.get("posture_ignored"):
        out["posture_ignored"] = r["posture_ignored"]
    return out


def delivery(reader: StateReader, now: float, raw: bool = False, env: Optional[Mapping[str, str]] = None,
             home: Optional[Path] = None, tz: Optional[tzinfo] = None) -> dict:
    """limitless_delivery: the delivery audit (delivery_audit.audit) of kevin-push's own log over the seven local
    days up to ``now``, read-only.

    An envelope whose value is ``{label}`` (the T1 words: within or over the push limit, whether the wake brief
    reached the person on the wake days, whether every push had a reply line) with the T1 label beside it;
    modality measured (the log is kevin-push's own record), aged by the newest row in the window. The counts
    (per-day deliveries, days over the cap, wake days and briefs, pushes with no reply line, skipped lines) are
    T0 and appear only with ``raw`` (LIMITLESS_RAW_IN_PROMPT). Config ``push_log`` unset, an unreadable log or a
    week with no row is value None with a reason (unknown, not zero); reasons never echo the path. The cap is
    config ``push_cap``, else the send gate's own. Nothing is written or sent.
    """
    cfg = config(env, home)
    unknown = {"label": _delivery.UNKNOWN_ROWS, "tier": "T1", "modality": _delivery.MODALITY}
    path = _delivery.log_path(cfg, reader.path)
    if path is None:
        out = envelope(None, _delivery.MODALITY, None, reason=_delivery.NO_LOG_REASON)
        out["label"] = dict(unknown, label=_delivery.NO_LOG)
        return out
    got = _delivery.read_log(path)
    if got is None:
        out = envelope(None, _delivery.MODALITY, None, reason=_delivery.UNREADABLE_REASON)
        out["label"] = unknown
        return out
    rows, skipped = got
    a = _delivery.audit(rows, wake_days=jobs_runner.delivery_wake_days(reader.path, now, env, home, tz),
                        today=datetime.fromtimestamp(now, tz).date(), tz=tz, cap=_delivery.push_cap(cfg),
                        skipped=skipped)
    if not a["known_days"]:
        out = envelope(None, _delivery.MODALITY, None, reason=_delivery.NO_ROWS_REASON)
        out["label"] = unknown
        return out
    days = {d["day"] for d in a["days"]}
    ats = [float(r["at"]) for r in rows if datetime.fromtimestamp(float(r["at"]), tz).date().isoformat() in days
           and float(r["at"]) <= now]
    value = {"label": a["label"]["label"]}
    if raw:
        for k in ("days", "delivered", "known_days", "cap", "over_cap_days", "wake", "no_action",
                  "action_unknown", "skipped"):
            value[k] = a[k]
    out = envelope(value, _delivery.MODALITY, (now - max(ats)) / 3600 if ats else None)
    out["label"] = a["label"]
    return out
