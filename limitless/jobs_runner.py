"""One pass over the event-triggered jobs: a verdict per job, and a send only through ``push``.

    rows = run_once(state_dir, now, push=push, dry_run=False)

Events are the phone's Sleep-mode changes (``sleepmode.jsonl``), screen-event wakes from
``screen-events.jsonl`` and the optional ActivityWatch DB (``aw_reader``), plus any ``{"event", "at"}`` rows
in ``events.jsonl`` (any name in ``jobs.EVENTS``; others are ignored). The window is
``first_known(GlideProvider, EventProvider)``; asleep comes from the EventProvider. Each job's
verdict is ``jobs.should_fire`` against the sent log ``jobs-sent.jsonl`` in the state dir; a verdict
whose trigger is a screen-event wake (or its habit cue) says the wake is a proxy.

Only a ``deliver`` verdict calls ``push(title, body)``, with ``once=once_key(spec, trigger_at)`` when push
takes a ``once`` parameter (``event_key`` gives the same key to any other sender): the event key ``<job>:<trigger event time>`` that every sender for one event
passes to ``kevin-push --once``, so only the first message per event goes out. The MIQ key is one per
night instead, ``miq:<night date>`` (``night_date``), so one night has one MIQ prompt whoever sends. A push that reports
``send_gate.ONCE_DROP`` (another sender already sent for this event) drops the job. ``push`` returns what kevin-push reported
(``"telegram"`` or ``True`` for a real delivery). Only a real delivery appends ``jobs.sent_entry()``
to the sent log; a failed, log-only or held push is not a send, and the job holds until the next
run tries again. ``dry_run=True`` (the default) never calls ``push`` and never writes. Nothing here reads the
clock: ``now`` comes from the caller. Stdlib only, Python 3.9+.

Job owners: a job named in ``external_jobs`` (config key ``external_jobs``, env ``LIMITLESS_EXTERNAL_JOBS``)
has its own sender with the real content, so run_once still gives its verdict but never pushes it and
never logs it as sent. When the caller passes ``brief``, the wake brief is sent by calling it (the CLI runs
``limitless-brief send``, which builds the whole brief and passes the same event key) instead of pushing
the one-line placeholder; a failed ``brief`` sends nothing and the job holds.

Quiet: a push or brief that reports ``(quiet: ...)`` (kevin-push while quiet.json holds) drops the job; it is
not retried by the next run, and kevin-push has claimed its event key, so nothing is queued for later. A
``push`` that takes a ``why`` parameter gets the verdict's reason (trigger event and decision window), which
kevin-push turns into the message's one "Why now" line.

Break nudge: the ActivityWatch DB's focus blocks (blocks.read_for: config ``flow_work_apps``,
``break_after_min``, ``block_gap_min``) add one ``long_block`` event per block that ran that long. Its key is
``break:<block start>`` (break_key), so one block gets one nudge whoever polls; jobs.break_verdict drops it
once the block ended a while ago. Unknown blocks (no DB, no work apps) say so in the row; they are never "no
block".
"""
from __future__ import annotations

import inspect
import json
import os
from datetime import date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Callable, Iterable, Mapping, NamedTuple, Optional

from . import anki as _anki, aw_reader, blocks as _blocks, body as _body, feeds_evidence, flow_metrics as _flow_metrics, flow_week, \
    jobs, naps as _naps, overnight as _overnight, passive_habit, one_tap, quiet as _quiet, regularity as _regularity, \
    rides as _rides, send_gate, sleep as _sleep, stop_rule as _stop_rule, tier_audit, wake_proxy, weekly_target
from .glide_provider import GlideProvider
from .state_reader import StateReader, config, parse_ts
from .window import MAX_AWAKE_H
from .window_chain import EventProvider, first_known

SENT_LOG = "jobs-sent.jsonl"
EXTERNAL_ENV = "LIMITLESS_EXTERNAL_JOBS"
EXTERNAL_CONFIG = "external_jobs"
OWN_SENDER = "sent by its own sender, not by limitless-jobs"
NIGHT_JOBS = (jobs.MIQ.name,)    # one message per night, keyed by the night's date, not by its event
DELIVERED = "telegram"
QUIET_DROP = f"({_quiet.PREFIX}"   # how kevin-push reports a push quiet dropped: "log (quiet: ...)"
_BODY = {
    jobs.WAKE_BRIEF.name: "You are up. Your brief comes next.",
    jobs.NAP.name: "Welcome back from your nap. Anything held while you slept is in your brief.",
    jobs.MIQ.name: "Your wind-down has started. Do you know the one thing that matters most tomorrow?",
}
# L14: an ask is one tap or one spoken word. The MIQ asks Yes / No / Later instead of a typed answer.
MIQ_ANSWERS = one_tap.YES_NO_LATER
# One soft line: no duration, no number, no advice beyond a short break. The Why-now line follows it.
BREAK_BODY = "Long focus block; a short break now keeps the next one good"
_BODY[jobs.BREAK_NUDGE.name] = BREAK_BODY


def body(spec: jobs.JobSpec, habit: Optional[dict] = None, phone: Optional[dict] = None,
         synced: Optional[dict] = None, flow: str = "", passive: str = "", body_line: str = "",
         overnight: str = "", rides_line: str = "", sleep_line: str = "", fragment: str = "",
         anki_line: str = "", target_days: Optional[int] = None, naps_line: str = "", rule_line: str = "") -> str:
    """The plain-words message for one job. The habit check-in names this week's habit; every body that asks
    (habit check-in, week review, MIQ) ends in its one_tap.choices_line, so one_tap.is_one_tap holds.

    ``phone`` (feeds_evidence.feeds_in_first_hour) adds one plain line to the check-in when it is known:
    a hint, no counts, times or app names; the answer stays the person's tap. The week review is
    jobs.week_review_text: the habit and "N of M logged days" (``synced``: StateReader.habit_days()), then the
    weekly target in words (weekly_target.review_line: "habit: target reached this week" or "habit: on the way";
    nothing with no Done day), then ``passive`` (week_passive: what the phone measured, a proxy) and ``flow``
    (flow_week.review_line), then ``fragment`` (week_flow_metrics: how broken up the work was, in words), then
    ``body_line`` (week_body: the body fat trend in words), then ``rides_line``
    (week_rides: this week's rides in words), then ``sleep_line`` (week_sleep: the wearable beside the phone
    proxy, in words), then ``naps_line`` (week_naps: this week's naps from phone Sleep mode, in words), then
    ``anki_line`` (week_anki: this week's Anki reviews in words), then ``rule_line`` (week_rule: what the stop
    rule picked at the week's start says, "Your rule says: keep it"), each as one more line
    when given, then ``Reply: Keep / Drop``: the rule only suggests, the reply decides. The first line's number
    stays the tapped one. The MIQ (wind-down) body is its question, then ``overnight`` (overnight.plan_for:
    what runs tonight, count words only) when given, then ``Reply: Yes / No / Later``.
    Once this week's Done days reach the weekly target (weekly_target, ``target_days``: config
    ``habit_target_days``, wording only) the check-in says so on one line after its question; nothing is
    said before that, and No, Skip or no answer never shows.
    """
    target = weekly_target.for_habit(habit, synced, target_days or weekly_target.DEFAULT_TARGET_DAYS)
    if spec.name == jobs.MIQ.name:
        return "\n".join(x for x in (_BODY[spec.name], overnight, one_tap.choices_line(MIQ_ANSWERS)) if x)
    if spec.name == jobs.WEEK_REVIEW.name:
        return "\n".join(x for x in (jobs.week_review_text(habit, synced), weekly_target.review_line(target),
                                      passive, flow, fragment, body_line,
                                      rides_line, sleep_line, naps_line, anki_line, rule_line,
                                      one_tap.choices_line(spec.answers))
                         if x)
    if spec.name == jobs.HABIT_CHECKIN.name:
        name = (habit or {}).get("habit") if isinstance(habit, dict) else None
        what = f"Did you do it today: {name}?" if isinstance(name, str) and name.strip() else "Did you do your habit today?"
        return "\n".join(x for x in (what, weekly_target.checkin_line(target), feeds_evidence.line(phone),
                                      one_tap.choices_line(spec.answers)) if x)
    return _BODY.get(spec.name, spec.send_title)


def delivered(result: object) -> bool:
    """True only for a real Telegram delivery as push reported it."""
    return result is True or result == DELIVERED


def once_key(spec: jobs.JobSpec, trigger_at: float) -> str:
    """The event key for one job's message: the job name and its trigger event time (whole seconds).

    Nothing else goes in it (no habit words, no window values), so it carries no health digits and
    no card ids, and every poll of one event (and any other sender for it) gets the same key.
    """
    return f"{spec.name}:{int(trigger_at)}"


def external_jobs(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> list:
    """Job names another sender owns: $LIMITLESS_EXTERNAL_JOBS (comma list), else config ``external_jobs``
    (a list of strings). Empty (the default) when neither is set: limitless-jobs sends every job."""
    env = os.environ if env is None else env
    if env.get(EXTERNAL_ENV):
        items = env[EXTERNAL_ENV].split(",")
    else:
        v = config(env, home).get(EXTERNAL_CONFIG)
        items = v if isinstance(v, list) else []
    return [s.strip() for s in items if isinstance(s, str) and s.strip()]


def _takes(push, name: str) -> bool:
    try:
        inspect.signature(push).bind("title", "body", **{name: "x"})
    except (TypeError, ValueError):
        return False
    return True


def _takes_once(push) -> bool:
    return _takes(push, "once")


def _push(push, title: str, text: str, once: Optional[str] = None, why: Optional[str] = None):
    """(delivered, how) for one push; an exception is a failed push, never a send."""
    kw = {}
    if once is not None and _takes(push, "once"):
        kw["once"] = once
    if why and _takes(push, "why"):
        kw["why"] = why
    try:
        result = push(title, text, **kw)
    except Exception as e:  # noqa: BLE001 - a broken push must not stop the other jobs
        return False, f"push failed ({type(e).__name__})"
    return delivered(result), (result if isinstance(result, str) and result else "no delivery reported")


def person_rows(reader: StateReader, env: Optional[Mapping[str, str]] = None,
                home: Optional[Path] = None) -> list:
    """Screen-event rows plus the ActivityWatch DB's unlocks and app-span starts (when configured),
    with rows of the same time (in seconds) and type kept once."""
    seen, out = set(), []
    for r in reader.screen_events() + aw_reader.person_rows(reader.aw_db_path(env, home)):
        t = wake_proxy._ts_s(r)
        key = (t, r.get("type")) if t is not None else None
        if key is not None and key in seen:
            continue
        if key is not None:
            seen.add(key)
        out.append(r)
    return out


def events(reader: StateReader, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> list:
    """Sleep-mode events, screen-event wakes (screen-events.jsonl and the ActivityWatch DB) Sleep mode
    does not cover (and their habit cues), plus the valid rows of events.jsonl, oldest first."""
    out = jobs.merged_events(jobs.events_from_sleepmode(reader.sleepmode()),
                             wake_proxy.events_from_screen(person_rows(reader, env, home)))
    for r in reader.events():
        at = parse_ts(r.get("at"))
        if at is not None and r.get("event") in jobs.EVENTS:
            out.append({"event": r["event"], "at": at})
    return sorted(out, key=lambda e: e["at"])


def _specs(reader: StateReader) -> list:
    habit = reader.habit()
    per_habit = {jobs.HABIT_CHECKIN.name: jobs.habit_checkin, jobs.WEEK_REVIEW.name: jobs.week_review}
    return [per_habit[name](habit) if name in per_habit else spec for name, spec in jobs.SPECS.items()]


class _Pass(NamedTuple):
    """Everything one pass reads from the state dir, read once so every caller sees the same inputs."""
    evs: list
    window: object
    sent: list
    habit: Optional[dict]
    specs: list
    synced: dict
    blocks: Optional[dict] = None      # blocks.read_for: today's focus blocks, or None with why (unknown)


def _read_pass(state_dir, now: float, env: Optional[Mapping[str, str]] = None,
               home: Optional[Path] = None) -> _Pass:
    reader = StateReader(Path(state_dir))
    ev_provider = EventProvider.from_reader(reader, now)
    state = first_known(GlideProvider.from_config(env=env, home=home, now=now), ev_provider)
    blk = _blocks.read_for(reader, now, env, home)
    evs = sorted(events(reader, env=env, home=home) + _blocks.long_block_events(blk["blocks"], blk["break_after_s"]),
                 key=lambda e: e["at"])
    return _Pass(evs=evs, blocks=blk,
                 window={"cls": "asleep"} if ev_provider.asleep else state,
                 sent=reader.jobs_sent(), habit=reader.habit(), specs=_specs(reader), synced=reader.habit_days())


def night_date(evs: list, at: float, tz: Optional[tzinfo] = None) -> str:
    """The local date of the night ``at`` belongs to: the date of the latest wake before it.

    An event after midnight and before the person's next wake keeps the previous date. A wake more
    than MAX_AWAKE_H before ``at`` is missing data, not a long day: with no wake, the date of ``at``.
    ``tz`` is the zone for the local date (default: this machine's local zone, as habit_replies).
    A key, never a trigger: nothing here decides when anything is sent.
    """
    wakes = [w for w in jobs.wake_times(evs, at) if at - w <= MAX_AWAKE_H * 3600]
    return datetime.fromtimestamp(wakes[-1] if wakes else at, tz).date().isoformat()


def reviewed_days(sent: list, tz: Optional[tzinfo] = None) -> list:
    """The local dates of the week reviews in the sent log, for jobs.week_review_gate."""
    return [datetime.fromtimestamp(s["t"], tz).date() for s in sent or ()
            if isinstance(s, dict) and s.get("job") == jobs.WEEK_REVIEW.name
            and isinstance(s.get("t"), (int, float)) and not isinstance(s.get("t"), bool)]


def week_review_verdict(v: jobs.Verdict, habit: Optional[dict], sent: list,
                        tz: Optional[tzinfo] = None) -> jobs.Verdict:
    """should_fire's verdict for the week review, narrowed by jobs.week_review_gate for its cue's date."""
    if v.trigger_at is None:
        return v
    gate = jobs.week_review_gate(habit, datetime.fromtimestamp(v.trigger_at, tz).date(), reviewed_days(sent, tz))
    return v if gate is None else gate._replace(trigger_at=v.trigger_at)


def week_key(habit: Optional[dict]) -> str:
    """The week review's event key: one per week, ``week_review:<week_of>``."""
    return f"{jobs.WEEK_REVIEW.name}:{(habit or {}).get('week_of')}"


def _key(spec: jobs.JobSpec, v: jobs.Verdict, evs: list, tz: Optional[tzinfo] = None,
         habit: Optional[dict] = None) -> Optional[str]:
    """The event key for one verdict: once_key of its trigger (for a night job, the trigger's night
    key; for the week review, the week's key), or None when nothing triggered it."""
    if v.trigger_at is None:
        return None
    if spec.name == jobs.WEEK_REVIEW.name:
        return week_key(habit)
    if spec.name in NIGHT_JOBS:
        return f"{spec.name}:{night_date(evs, v.trigger_at, tz)}"
    if spec.name == jobs.BREAK_NUDGE.name:
        return break_key(jobs.block_start(evs, v.trigger_at))
    return once_key(spec, v.trigger_at)


def break_key(block_start: float) -> str:
    """The break nudge's event key: one per focus block, ``break:<block start>`` (whole seconds)."""
    return f"break:{int(block_start)}"


def event_key(state_dir, now: float, job: str = jobs.WAKE_BRIEF.name, env: Optional[Mapping[str, str]] = None,
              home: Optional[Path] = None, tz: Optional[tzinfo] = None) -> Optional[str]:
    """The ``kevin-push --once`` key run_once uses for ``job`` right now, or None when it has no trigger.

    Same events, same trigger as run_once (both read through _read_pass and should_fire), so another
    sender for the same event (bin/limitless-brief) gets the same key. The key is the latest trigger's
    whatever the verdict: after run_once has sent (a drop), a later sender still gets that event's key and
    kevin-push drops it. For a night job (MIQ) it is the night key, and only for a trigger of tonight:
    last night's wind-down is no key now. Reads only; never sends or writes.
    """
    p = _read_pass(state_dir, now, env=env, home=home)
    spec = next((s for s in p.specs if s.name == job), None)
    if spec is None:
        raise ValueError(f"job must be one of {sorted(jobs.SPECS)}, got {job!r}")
    v = jobs.should_fire(spec, p.evs, p.window, p.sent, now)
    if spec.name == jobs.WEEK_REVIEW.name:
        v = week_review_verdict(v, p.habit, p.sent, tz)
        if v.action == jobs.NOT_TRIGGERED or v.reason == jobs.NO_WEEK:
            return None                          # no day-seven cue of a started week: no key
    k = _key(spec, v, p.evs, tz, p.habit)
    if k is not None and spec.name in NIGHT_JOBS and k != f"{spec.name}:{night_date(p.evs, now, tz)}":
        return None
    return k


def night_key(state_dir, now: float, job: str = jobs.MIQ.name, env: Optional[Mapping[str, str]] = None,
              home: Optional[Path] = None, tz: Optional[tzinfo] = None) -> str:
    """Tonight's key for a night job, ``<job>:<night date of now>``, with or without its trigger event.

    For a sender with its own cue (bin/limitless-once-key miq --night): it equals event_key whenever
    tonight has the trigger event, so the two senders share one key. State that cannot be read is no
    wake: the date of ``now``. Reads only; never sends or writes.
    """
    if job not in NIGHT_JOBS:
        raise ValueError(f"job must be one of {sorted(NIGHT_JOBS)}, got {job!r}")
    try:
        evs = events(StateReader(Path(state_dir)), env=env, home=home)
    except Exception:  # noqa: BLE001 - unreadable state is no wake, never a traceback
        evs = []
    return f"{job}:{night_date(evs, now, tz)}"


def _send_brief(brief):
    """(delivered, how) for the wake brief's own sender; an exception is a failed send, never a send."""
    try:
        result = brief()
    except Exception as e:  # noqa: BLE001 - a broken brief sender must not stop the other jobs
        return False, f"limitless-brief failed ({type(e).__name__})"
    return delivered(result), (result if isinstance(result, str) and result else "no delivery reported")


def first_hour_wake(evs: list, cue_at: float) -> Optional[float]:
    """The wake whose first hour a habit cue at ``cue_at`` closes: the latest wake at or before
    ``cue_at - jobs.HABIT_CUE_AFTER_S``; None when there is none (a cue from elsewhere with no wake)."""
    wakes = jobs.wake_times(evs, cue_at - jobs.HABIT_CUE_AFTER_S)
    return wakes[-1] if wakes else None


def _phone(spec: jobs.JobSpec, v: jobs.Verdict, p: "_Pass", state_dir, env, home) -> Optional[dict]:
    """The feed-app hint for a habit check-in cued by the first hour after a wake; else None."""
    if spec.name != jobs.HABIT_CHECKIN.name or spec.trigger_event != "habit_cue" or v.trigger_at is None:
        return None
    wake = first_hour_wake(p.evs, v.trigger_at)
    return feeds_evidence.phone_hint(StateReader(Path(state_dir)), wake, env, home) if wake is not None else None


def week_passive(state_dir, habit: Optional[dict], env: Optional[Mapping[str, str]] = None,
                 home: Optional[Path] = None) -> str:
    """The week review's passive line (passive_habit.review_line) for the habit week's seven days; "" with
    no started week or no passive row for those days (unknown is not zero). Digit-free; never a check-in."""
    day7 = jobs.review_day(habit)
    if day7 is None:
        return ""
    first = day7 - timedelta(days=jobs.HABIT_WEEK_DAYS - 1)
    return passive_habit.review_line(passive_habit.view(StateReader(Path(state_dir)), first, day7, env, home))


def week_flow(state_dir, habit: Optional[dict], env: Optional[Mapping[str, str]] = None,
              home: Optional[Path] = None, tz: Optional[tzinfo] = None) -> str:
    """The week review's flow line (flow_week.review_line) for the habit week and the week before it;
    "" when no ActivityWatch DB is configured or no week is named. Read-only."""
    reader = StateReader(Path(state_dir))
    start = jobs._week_start(habit)
    if start is None or reader.aw_db_path(env, home) is None:
        return ""
    this = flow_week.for_week(reader, start, tz, env, home)
    last = flow_week.for_week(reader, start - timedelta(days=jobs.HABIT_WEEK_DAYS), tz, env, home)
    return flow_week.review_line(this, last)


def week_flow_metrics(state_dir, habit: Optional[dict], env: Optional[Mapping[str, str]] = None,
                      home: Optional[Path] = None, tz: Optional[tzinfo] = None) -> str:
    """The week review's flow-metrics line (flow_metrics.review_line of the habit week's seven local days),
    digit-free; "" when no week is named or the words are unknown (no DB, no work apps, no work time).
    Read-only."""
    start = jobs._week_start(habit)
    if start is None:
        return ""
    try:
        lo = flow_week._day_start(start, tz)
        hi = flow_week._day_start(start + timedelta(days=jobs.HABIT_WEEK_DAYS), tz)
        got = _flow_metrics.read_for(StateReader(Path(state_dir)), lo, hi, env, home, tz)
        return _flow_metrics.review_line(_flow_metrics.label(got["pool"], th=got["thresholds"]))
    except Exception:  # noqa: BLE001 - broken activity data must not stop the review
        return ""


def week_body(state_dir, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None,
              today: Optional[date] = None) -> str:
    """The week review's body line (body.review_line of body.trend up to ``today``), digit-free; "" when no
    body file is configured or it has no valid row (unknown, not zero). Read-only."""
    reader = StateReader(Path(state_dir))
    try:
        rows = reader.body_rows(env, home, today=today)
        return _body.review_line(_body.trend(rows, today, flat=_body.flat_points(env, home))) if rows else ""
    except Exception:  # noqa: BLE001 - a broken body file must not stop the review
        return ""


def week_rides(state_dir, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None,
               today: Optional[date] = None) -> str:
    """The week review's rides line (rides.review_line of rides.week up to ``today``), digit-free; "" when no
    rides file is configured, it has no ride row or no ``today`` is given (unknown, not zero). Read-only."""
    if not isinstance(today, date):
        return ""
    reader = StateReader(Path(state_dir))
    try:
        rows = reader.ride_rows(today, env, home)
        return _rides.review_line(_rides.week(rows, today)) if rows else ""
    except Exception:  # noqa: BLE001 - a broken rides file must not stop the review
        return ""


def week_sleep(state_dir, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None,
               today: Optional[date] = None, tz: Optional[tzinfo] = None) -> str:
    """The week review's sleep line (sleep.review_line of the last seven nights before ``today``: the wearable
    beside the phone proxy, then the regularity clause of the last fourteen nights when it is known),
    digit-free; "" when there is no wearable row and no phone gap at all, or no ``today`` is given (unknown,
    not zero). Read-only."""
    if not isinstance(today, date):
        return ""
    reader = StateReader(Path(state_dir))
    try:
        wear = reader.sleep_rows(today, env, home)
        gaps = _sleep.screen_gaps(person_rows(reader, env, home))
        if not wear and not gaps:
            return ""
        reg = _regularity.regularity(_sleep.timed_nights(wear, gaps, today, tz=tz),
                                     _regularity.min_nights(config(env, home)), tz)
        return _sleep.review_line(_sleep.label(_sleep.nights(wear, gaps, today, tz=tz)), reg)
    except Exception:  # noqa: BLE001 - broken sleep data must not stop the review
        return ""


RAW_ENV = "LIMITLESS_RAW_IN_PROMPT"     # card.raw_in_prompt's opt-in (card is not imported: it imports this module)


def _gated(hook: str, text: str, env: Optional[Mapping[str, str]], home: Optional[Path]) -> str:
    """``text`` after tier_audit.gate (recorded, content-free); "" when it is empty or blocked."""
    if not text:
        return ""
    env_ = os.environ if env is None else env
    return tier_audit.gate(hook, text, env_.get(RAW_ENV) == "1", env, home) or ""


def _nap_events(state_dir, env, home):
    reader = StateReader(Path(state_dir))
    cfg = config(env, home)
    return jobs.events_from_sleepmode(reader.sleepmode()), _naps.nap_max_h(cfg), _naps.near_night_h(cfg)


def brief_naps(state_dir, now: float, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None,
               tz: Optional[tzinfo] = None) -> str:
    """The wake brief's naps line for yesterday (the local day before ``now``): naps.day's words, capitalized,
    with the source named ("Naps yesterday: one short nap (phone Sleep mode)"), through tier_audit.gate (hook
    ``brief:naps``); "" when unknown (no Sleep-mode change yesterday) or unreadable. Read-only."""
    try:
        evs, nap_max, near = _nap_events(state_dir, env, home)
        got = _naps.day(evs, datetime.fromtimestamp(now, tz).date() - timedelta(days=1), nap_max, near, tz)
        if got["naps"] is None:
            return ""
        word = got["label"]["label"]
        return _gated("brief:naps", f"{word[0].upper()}{word[1:]}{_naps.SOURCE}", env, home)
    except Exception:  # noqa: BLE001 - broken Sleep-mode rows must not stop the brief
        return ""


def week_naps(state_dir, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None,
              today: Optional[date] = None, tz: Optional[tzinfo] = None) -> str:
    """The week review's naps line (naps.week_line over the seven local days before ``today``), digit-free, through
    tier_audit.gate (hook ``week_review:naps``); "" when no ``today`` is given or no Sleep-mode change falls in those
    days (unknown, not none). Read-only."""
    if not isinstance(today, date):
        return ""
    try:
        evs, nap_max, near = _nap_events(state_dir, env, home)
        line = _naps.week_line(_naps.week(evs, today - timedelta(days=7), today - timedelta(days=1), nap_max, near, tz))
        return _gated("week_review:naps", f"{line}." if line else "", env, home)
    except Exception:  # noqa: BLE001 - broken Sleep-mode rows must not stop the review
        return ""


def week_anki(state_dir, habit: Optional[dict], env: Optional[Mapping[str, str]] = None,
              home: Optional[Path] = None, tz: Optional[tzinfo] = None, today: Optional[date] = None) -> str:
    """The week review's Anki line (anki.review_line of anki.for_week over the habit week up to ``today``),
    words only; "" when no week is named, no ``today`` is given, or the reviews are unknown (no collection
    set, unreadable). The collection is opened read-only."""
    start = jobs._week_start(habit)
    if start is None or not isinstance(today, date):
        return ""
    try:
        return _anki.review_line(_anki.for_week(start, today, tz, env, home))
    except Exception:  # noqa: BLE001 - a broken collection must not stop the review
        return ""


def week_rule(habit: Optional[dict], synced: Optional[dict] = None, env: Optional[Mapping[str, str]] = None,
              home: Optional[Path] = None) -> str:
    """The week review's stop-rule line (stop_rule.review_line of stop_rule.verdict for habit.json's rule),
    digit-free, through tier_audit.gate (hook ``week_review:stop_rule``); "" when the verdict is unknown (no
    rule set, no Done or No day). It suggests only: nothing is written; the person's Keep or Drop decides."""
    try:
        v = _stop_rule.verdict(habit, _stop_rule.rule_of(habit), synced)
        return _gated("week_review:stop_rule", _stop_rule.review_line(v), env, home)
    except Exception:  # noqa: BLE001 - a broken habit.json must not stop the review
        return ""


def _break(v: jobs.Verdict, p: _Pass, now: float) -> jobs.Verdict:
    """The break nudge's verdict: narrowed by its block (jobs.break_verdict); with no trigger and unknown
    blocks, the reason says why they are unknown (no DB, no work apps), never that there was no block."""
    blk = p.blocks or {}
    if v.action == jobs.NOT_TRIGGERED and blk.get("blocks") is None and blk.get("why"):
        return v._replace(reason=f"focus blocks unknown: {blk['why']}")
    return jobs.break_verdict(v, p.evs, now, blk.get("gap_s", _blocks.GAP_S))


def run_once(state_dir, now: float, push: Optional[Callable[[str, str], object]] = None, dry_run: bool = True,
             env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None,
             tz: Optional[tzinfo] = None, today: Optional[date] = None,
             external: Optional[Iterable[str]] = None, brief: Optional[Callable[[], object]] = None) -> list:
    """One ``{job, action, reason}`` row per job spec, in plain words. Sends only when not ``dry_run``.

    A triggered habit check-in drops outside a started habit week (jobs.habit_week_gate); ``today``
    is the date of ``now`` in ``tz`` (default: local zone) unless the caller passes one.
    ``external`` (default: external_jobs(env, home)) names jobs another sender owns: verdict only, no
    push, no sent log. ``brief``, when given, sends the wake brief in place of ``push`` (no placeholder).
    """
    external = set(external_jobs(env, home) if external is None else external)
    p = _read_pass(state_dir, now, env=env, home=home)
    today = datetime.fromtimestamp(now, tz).date() if today is None else today
    sent = p.sent
    proxy_at = {e["at"] for e in p.evs if e.get("source") == "screen"}   # screen wakes and their habit cues
    rows = []
    for spec in p.specs:
        v = jobs.should_fire(spec, p.evs, p.window, sent, now)
        gate = jobs.habit_week_gate(p.habit, today) if spec.name == jobs.HABIT_CHECKIN.name else None
        if gate is not None and v.action != jobs.NOT_TRIGGERED:
            v = gate._replace(trigger_at=v.trigger_at)      # a cue came, but no started week: drop, never send
        if spec.name == jobs.WEEK_REVIEW.name and v.action != jobs.NOT_TRIGGERED:
            v = week_review_verdict(v, p.habit, sent, tz)   # only a cue from day seven on, once per week
        if spec.name == jobs.BREAK_NUDGE.name:
            v = _break(v, p, now)
        action, reason = v.action, v.reason
        if v.trigger_at is not None and v.trigger_at in proxy_at:
            reason = f"{reason}; the wake is a phone-quiet gap (proxy), not a sleep measure"
        own = spec.name == jobs.WAKE_BRIEF.name and brief is not None
        if spec.name in external:
            reason = f"{reason}; {OWN_SENDER}"
        elif action == jobs.DELIVER and not dry_run and (push is not None or own):
            if own:
                ok, how = _send_brief(brief)       # the whole brief, same event key; never the placeholder
            else:
                flow = week_flow(state_dir, p.habit, env, home, tz) if spec.name == jobs.WEEK_REVIEW.name else ""
                review = spec.name == jobs.WEEK_REVIEW.name
                passive = week_passive(state_dir, p.habit, env, home) if review else ""
                body_line = week_body(state_dir, env, home, today) if review else ""
                plan = _overnight.plan_for(state_dir, now, env, home) if spec.name == jobs.MIQ.name else ""
                rides_line = week_rides(state_dir, env, home, today) if review else ""
                sleep_line = week_sleep(state_dir, env, home, today, tz) if review else ""
                fragment = week_flow_metrics(state_dir, p.habit, env, home, tz) if review else ""
                anki_line = week_anki(state_dir, p.habit, env, home, tz, today) if review else ""
                naps_line = week_naps(state_dir, env, home, today, tz) if review else ""
                rule_line = week_rule(p.habit, p.synced, env, home) if review else ""
                text = body(spec, p.habit, _phone(spec, v, p, state_dir, env, home), p.synced, flow, passive,
                            body_line, plan, rides_line, sleep_line, fragment, anki_line,
                            target_days=weekly_target.target_days(env, home), naps_line=naps_line,
                            rule_line=rule_line)
                ok, how = _push(push, spec.send_title, text, _key(spec, v, p.evs, tz, p.habit), why=v.reason)
            if ok:
                entry = jobs.sent_entry(spec, v.trigger_at, now)
                with open(Path(state_dir) / SENT_LOG, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")
                sent.append(entry)               # later jobs in this run see it (daily cap)
                reason = f"{reason}; sent"
            elif send_gate.ONCE_DROP in how:
                action, reason = jobs.DROP, f"{reason}; not sent: {send_gate.ONCE_DROP} by another sender"
            elif QUIET_DROP in how:
                said = how[how.index(QUIET_DROP) + 1:].split(")")[0]
                action, reason = jobs.DROP, f"{reason}; not sent: {said}"
            else:
                action, reason = jobs.HOLD, f"{reason}; not delivered: {how}; the next run tries again"
        rows.append({"job": spec.send_title, "action": action, "reason": reason})
    return rows
