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

NOOP export: with config ``noop_export`` dry_run or write, one more row (noop_export_row). When the newest runs.jsonl
row says the sync copied the NOOP database and the mark ``noop-export.json`` has not seen that row, a pass that is
not a dry run calls ``noop_export.main`` in-process and writes the mark; nothing is pushed or logged as sent, and
no process is started. Off (the default): no row, nothing read.

Apps ingest: with config ``apps_ingest`` dry_run or write, one more row (apps_ingest_row). Once per new sync row in
runs.jsonl, a pass that is not a dry run reads the person's replies from the Hermes session DB (config
``hermes_db``; none set: skipped) and runs apps_reply.ingest (write mode writes apps.json), then writes the mark
``apps-ingest.json`` in words only. A write adds the row's ``line`` (jobs.APPS_LINE) for a later brief; nothing is
pushed or logged as sent. Off (the default): no row, nothing read.

Ranked ingest: with config ``ranked_ingest`` dry_run or write, one more row (ranked_ingest_row), by the apps
ingest's rule: once per new sync row in runs.jsonl, a pass that is not a dry run reads the owner's
"drop: <id>[, <id>...]" replies from the Hermes session DB and runs ranked_ledger.ingest (write mode appends owner
drop rows to the ranked ledger and moves ranked-drops.json), then writes ``ranked-ingest.json`` in words only. No
ranked ledger or no Hermes DB set: skipped. Nothing is pushed or logged as sent. Off (the default): no row, nothing
read.

Sender ingest: with config ``sender_ingest`` dry_run or write, one more row right after the ranked ingest's
(sender_ingest_job.run), by the apps ingest's rule: once per new sync row, a pass that is not a dry run reads the
owner's whole "push via <profile>" reply from the Hermes session DB and runs sender_reply.ingest (write mode writes
push-sender.json, only for a profile push_sender.check says exists), then writes ``push-sender-ingest.json`` in
words only. No Hermes DB set: skipped. Nothing is pushed or logged as sent. Off (the default): no row, nothing read.

Outage recap: with config ``outage_recap`` dry_run or write, one more row, last (outage_recap_job.run). After a push
kevin-push delivered closed an outage in its log (config ``push_log``; outage_recap.outage), a pass that is not a
dry run pushes one plain recap of what the outage swallowed through ``push`` with ``once``
``outage_recap:<first failed push time>``, and writes ``outage-recap.json`` only on a real delivery. It is not
logged in the sent log. Off (the default): no row, nothing read.
"""
from __future__ import annotations

import inspect
import io
import json
import math
import os
import re
import tempfile
from datetime import date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Callable, Iterable, Mapping, NamedTuple, Optional

from . import feed_reflex as _feed_reflex
from . import delivery_audit as _delivery, habit_catalogue, idea_ledger as _idea_ledger, prediction as _prediction
from . import anki as _anki, aw_desktop, aw_reader, blocks as _blocks, body_calibration as _body_calibration, feeds_evidence, flow_ledger as _flow_ledger, \
    flow_metrics as _flow_metrics, flow_week, \
    jobs, naps as _naps, overnight as _overnight, passive_habit, one_tap, quiet as _quiet, regularity as _regularity, \
    presleep_hr as _presleep_hr, rides as _rides, send_gate, sleep as _sleep, stop_rule as _stop_rule, tier_audit, wake_proxy, weekly_target, \
    wind_down
from . import apps_reply as _apps_reply, glide_provider, habit_replies as _habit_replies, mock_guard, \
    noop_export as _noop_export, ranked_ledger as _ranked, scorecard as _scorecard
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
MIQ_QUESTION = "Do you know the one thing that matters most tomorrow?"   # the MIQ itself (voice_miq, call_brief)
_BODY = {
    jobs.WAKE_BRIEF.name: "You are up. Your brief comes next.",
    jobs.NAP.name: "Welcome back from your nap. Anything held while you slept is in your brief.",
    jobs.MIQ.name: "Your wind-down has started. " + MIQ_QUESTION,
}
# L14: an ask is one tap or one spoken word. The MIQ asks Yes / No / Later instead of a typed answer.
MIQ_ANSWERS = one_tap.YES_NO_LATER
# One soft line: no duration, no number, no advice beyond a short break. The Why-now line follows it.
BREAK_BODY = "Long focus block; a short break now keeps the next one good"
_BODY[jobs.BREAK_NUDGE.name] = BREAK_BODY


def body(spec: jobs.JobSpec, habit: Optional[dict] = None, phone: Optional[dict] = None,
         synced: Optional[dict] = None, flow: str = "", passive: str = "", body_line: str = "",
         overnight: str = "", rides_line: str = "", sleep_line: str = "", fragment: str = "",
         anki_line: str = "", target_days: Optional[int] = None, naps_line: str = "",
         wind_down_line: str = "", rule_line: str = "", presleep_line: str = "", ideas_line: str = "",
         experiment_line: str = "", delivery_line: str = "", reflex_line: str = "") -> str:
    """The plain-words message for one job. The habit check-in names this week's habit; every body that asks
    (habit check-in, week review, MIQ) ends in its one_tap.choices_line, so one_tap.is_one_tap holds.

    ``phone`` (feeds_evidence.feeds_in_first_hour) adds one plain line to the check-in when it is known:
    a hint, no counts, times or app names; the answer stays the person's tap. The week review is
    jobs.week_review_text: the habit and "N of M logged days" (``synced``: StateReader.habit_days()), then the
    weekly target in words (weekly_target.review_line: "habit: target reached this week" or "habit: on the way";
    nothing with no Done day), then ``passive`` (week_passive: what the phone measured, a proxy) and ``flow``
    (flow_week.review_line), then ``fragment`` (week_flow_metrics: how broken up the work was, in words), then
    ``reflex_line`` (week_feed_reflex: how often a feed was the first app after an unlock, in words), then
    ``body_line`` (week_body: the body fat trend in words), then ``rides_line``
    (week_rides: this week's rides in words), then ``sleep_line`` (week_sleep: the wearable beside the phone
    proxy, in words), then ``presleep_line`` (week_presleep_hr: the wearable's pre-sleep heart rate against the
    usual, in words, next to the night), then ``naps_line`` (week_naps: this week's naps from phone Sleep mode, in words), then
    ``anki_line`` (week_anki: this week's Anki reviews in words), then ``ideas_line`` (week_ideas: the idea
    ledger's week, "Ideas recorded this week: a few, none triaged."), then ``delivery_line`` (week_delivery:
    the push log's week in words, "Pushes: within the push limit every day this week; ..."), then
    ``experiment_line`` (week_experiment:
    "Experiment: outcome pending (judged later)" while a lagged outcome waits), then ``rule_line`` (week_rule: what the stop
    rule picked at the week's start says, "Your rule says: keep it"), each as one more line
    when given, then ``Reply: Keep / Drop``: the rule only suggests, the reply decides. The first line's number
    stays the tapped one. The MIQ (wind-down) body is its question, then ``overnight`` (overnight.plan_for:
    what runs tonight, count words only) when given, then ``wind_down_line`` (miq_wind_down: one gentle
    suggestion, digit-free) when given, then ``Reply: Yes / No / Later``.
    Once this week's Done days reach the weekly target (weekly_target, ``target_days``: config
    ``habit_target_days``, wording only) the check-in says so on one line after its question; nothing is
    said before that, and No, Skip or no answer never shows.
    """
    target = weekly_target.for_habit(habit, synced, target_days or weekly_target.DEFAULT_TARGET_DAYS)
    if spec.name == jobs.MIQ.name:
        return "\n".join(x for x in (_BODY[spec.name], overnight, wind_down_line,
                                      one_tap.choices_line(MIQ_ANSWERS)) if x)
    if spec.name == jobs.WEEK_REVIEW.name:
        return "\n".join(x for x in (jobs.week_review_text(habit, synced), weekly_target.review_line(target),
                                      passive, flow, fragment, reflex_line, body_line,
                                      rides_line, sleep_line, presleep_line, naps_line, anki_line, ideas_line,
                                      delivery_line, experiment_line, rule_line,
                                      one_tap.choices_line(spec.answers))
                         if x)
    if spec.name == jobs.HABIT_CHECKIN.name:
        name = (habit or {}).get("habit") if isinstance(habit, dict) else None
        what = f"Did you do it today: {name}?" if isinstance(name, str) and name.strip() else "Did you do your habit today?"
        return "\n".join(x for x in (what, weekly_target.checkin_line(target), feeds_evidence.line(phone),
                                      one_tap.choices_line(spec.answers)) if x)
    return _BODY.get(spec.name, spec.send_title)


def week_review_body(state_dir, habit: Optional[dict], synced: Optional[dict] = None,
                     env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None,
                     tz: Optional[tzinfo] = None, today: Optional[date] = None,
                     now: Optional[float] = None) -> str:
    """The week review's whole message (body for jobs.week_review(habit)) with every review line read from
    ``state_dir``: the one text run_once sends and limitless_card_view shows. ``now`` bounds the idea-ledger
    week; without it there is no ideas line. Read-only; never sends."""
    return body(jobs.week_review(habit), habit, None, synced, week_flow(state_dir, habit, env, home, tz),
                week_passive(state_dir, habit, env, home), week_body(state_dir, env, home, today),
                rides_line=week_rides(state_dir, env, home, today),
                sleep_line=week_sleep(state_dir, env, home, today, tz),
                fragment=week_flow_metrics(state_dir, habit, env, home, tz),
                reflex_line=week_feed_reflex(state_dir, habit, env, home, tz),
                anki_line=week_anki(state_dir, habit, env, home, tz, today),
                target_days=weekly_target.target_days(env, home),
                naps_line=week_naps(state_dir, env, home, today, tz), rule_line=week_rule(habit, synced, env, home),
                presleep_line=week_presleep_hr(state_dir, env, home, today),
                experiment_line=week_experiment(state_dir, habit, today, env, home),
                ideas_line=week_ideas(state_dir, now, env, home) if now is not None else "",
                delivery_line=week_delivery(state_dir, env, home, today, tz, now))


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
    "" when neither the ActivityWatch DB nor the desktop's ActivityWatch is configured, or no week is named.
    Read-only."""
    reader = StateReader(Path(state_dir))
    start = jobs._week_start(habit)
    if start is None or reader.aw_db_path(env, home) is None and not aw_desktop.configured(env, home):
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


def _week_reflex(state_dir, habit: Optional[dict], env: Optional[Mapping[str, str]] = None,
                 home: Optional[Path] = None, tz: Optional[tzinfo] = None) -> Optional[dict]:
    """feed_reflex.read_for over the habit week's seven local days; None with no week named. Read-only."""
    start = jobs._week_start(habit)
    if start is None:
        return None
    lo = flow_week._day_start(start, tz)
    hi = flow_week._day_start(start + timedelta(days=jobs.HABIT_WEEK_DAYS), tz)
    return _feed_reflex.read_for(StateReader(Path(state_dir)), lo, hi, env, home, tz)


def week_feed_reflex(state_dir, habit: Optional[dict], env: Optional[Mapping[str, str]] = None,
                     home: Optional[Path] = None, tz: Optional[tzinfo] = None) -> str:
    """The week review's one optional feed-reflex line (feed_reflex.review_line of the habit week: "Phone: a feed
    was often the first thing opened after unlocking this week."), through tier_audit.gate (hook
    ``week_review:feed_reflex``); "" with no week, no feed apps, no DB, too few unlocks or broken data (unknown
    is never a line). Read-only; it never blocks an app."""
    try:
        got = _week_reflex(state_dir, habit, env, home, tz)
        line = _feed_reflex.review_line(got["label"]) if got else ""
    except Exception:  # noqa: BLE001 - broken activity data must not stop the review
        return ""
    return _gated("week_review:feed_reflex", line, env, home)


def week_body(state_dir, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None,
              today: Optional[date] = None) -> str:
    """The week review's body line (body_calibration.review_line of its trend up to ``today``), digit-free; "" when no
    body file is configured or it has no valid row (unknown, not zero). Read-only."""
    reader = StateReader(Path(state_dir))
    try:
        rows = reader.body_rows(env, home, today=today)
        return _body_calibration.review_line(_body_calibration.trend(rows, today, env, home)) if rows else ""
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


def week_presleep_hr(state_dir, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None,
                     today: Optional[date] = None) -> str:
    """The week review's pre-sleep heart-rate line (presleep_hr.review_line of presleep_hr.week over the seven
    nights before ``today``: "Pre-sleep heart rate: about usual most nights (wearable)."), wearable rows only,
    digit-free, through tier_audit.gate (hook ``week_review:presleep_hr``); "" when no ``today`` is given, no
    file is configured, or the week is unknown (phone rows only, too few compared nights). It rides in the
    week review: never a push or a job of its own. Read-only."""
    if not isinstance(today, date):
        return ""
    try:
        rows = StateReader(Path(state_dir)).presleep_hr_rows(env, home)
        line = _presleep_hr.review_line(_presleep_hr.week(rows, today)) if rows else ""
        return _gated("week_review:presleep_hr", line, env, home)
    except Exception:  # noqa: BLE001 - a broken file must not stop the review
        return ""


RAW_ENV = "LIMITLESS_RAW_IN_PROMPT"     # card.raw_in_prompt's opt-in (card is not imported: it imports this module)


def _gated(hook: str, text: str, env: Optional[Mapping[str, str]], home: Optional[Path]) -> str:
    """``text`` after tier_audit.gate (recorded, content-free); "" when it is empty or blocked."""
    if not text:
        return ""
    env_ = os.environ if env is None else env
    return tier_audit.gate(hook, text, env_.get(RAW_ENV) == "1", env, home) or ""


def miq_wind_down(evs: list, trigger_at: Optional[float], env: Optional[Mapping[str, str]] = None,
                  home: Optional[Path] = None, tz: Optional[tzinfo] = None, state_dir=None,
                  now: Optional[float] = None) -> str:
    """The MIQ body's wind-down line (wind_down.line: config ``wind_down_line``, and nothing when Glide's
    attention file says Glide already nudged on this night), through tier_audit.gate (hook ``miq:wind_down``).
    With config ``wind_down_breathing_link`` set, the same line offers slow breathing in the person's own app,
    "with live heart data" only when ``state_dir``'s inputs.json says the wearable is recording at ``now``
    (wind_down.wearable_live, limitless_status's rule); without ``state_dir`` or ``now`` it is never live.
    "" when off, already nudged, blocked or unreadable. It rides in the one MIQ push: never a push of its own.
    Read-only."""
    try:
        night = night_date(evs, trigger_at, tz) if trigger_at is not None else None
        cfg = config(env, home)
        live = (state_dir is not None and now is not None
                and wind_down.wearable_live(StateReader(Path(state_dir)).inputs(), now,
                                            wind_down.wearable_inputs(cfg)))
        text = wind_down.line(cfg, glide_provider.attention(env, home), night, heart_live=live)
        return _gated("miq:wind_down", text, env, home)
    except Exception:  # noqa: BLE001 - a broken line must never stop the bedtime question
        return ""


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


BRIEF_WORK = "Yesterday's work: {}."


def brief_flow_ledger(state_dir, now: float, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None,
                      tz: Optional[tzinfo] = None) -> str:
    """The wake brief's one flow-ledger line for yesterday (the local day before ``now``): flow_ledger.label's
    words, "Yesterday's work: two long blocks, one with a feed leak; three items landed.", through
    tier_audit.gate (hook ``brief:flow_ledger``); "" when unknown (no DB, no work apps, no activity that day) or
    unreadable. It rides in the brief that is already going out: no push or job of its own. Read-only."""
    try:
        day = datetime.fromtimestamp(now, tz).date() - timedelta(days=1)
        got = _flow_ledger.read_for(StateReader(Path(state_dir)), day, now, env, home, tz)
        if got["blocks"] is None:
            return ""
        return _gated("brief:flow_ledger", BRIEF_WORK.format(_flow_ledger.label(got)), env, home)
    except Exception:  # noqa: BLE001 - broken activity data must not stop the brief
        return ""


def brief_outage(state_dir, now: float, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None,
                 write: bool = True) -> str:
    """The wake brief's one input-outage line (outage.line): "Not recording: wearable (since about two days ago).
    Open the app once to restart it." for each input that stopped recording and was not yet told, through
    tier_audit.gate (hook ``brief:outage``); "" when none, off (config ``input_outage``) or unreadable. With
    ``write`` (the default) this is a poll: it records each outage's start in outage.json and clears recovered
    ones silently; ``write=False`` previews and writes no mark. Nothing is marked told here: the sender calls
    brief_outage_told once the brief went out. It rides in the brief: no push or job of its own, and nothing is
    restarted."""
    from . import outage as _outage   # outage -> doctor -> card imports this module
    try:
        cfg = config(env, home)
        new = (_outage.poll(state_dir, now, cfg) if write else
               [o for o in _outage.current(state_dir, now, cfg)
                if o["name"] not in _outage.load_mark(state_dir)["told"]])
        return _gated("brief:outage", _outage.line(new, cfg, now), env, home)
    except Exception:  # noqa: BLE001 - unreadable inputs must not stop the brief
        return ""


def brief_outage_told(state_dir, now: float, env: Optional[Mapping[str, str]] = None,
                      home: Optional[Path] = None) -> bool:
    """Mark every current outage told (outage.tell), after a brief with the outage line went out, so it is said
    at most once until the input records again. False when off or unreadable; never raises."""
    from . import outage as _outage
    try:
        cfg = config(env, home)
        if not _outage.enabled(cfg):
            return False
        return _outage.tell(state_dir, [o["name"] for o in _outage.current(state_dir, now, cfg)], now)
    except Exception:  # noqa: BLE001 - a failed mark must not stop the sender
        return False


def brief_apps_ask(state_dir, now: float, env: Optional[Mapping[str, str]] = None,
                   home: Optional[Path] = None) -> str:
    """The wake brief's app-lists ask (apps_ask.ask_lines): "Reply with this to set your app lists (edit
    freely):" and the pre-filled "work apps: ... / feed apps: ..." reply, while both lists are unset and the ask
    was not delivered in the last seven days, through tier_audit.gate (hook ``brief:apps_ask``; a name with a
    digit blocks it, so it is left out). "" when off (config ``apps_ask``), a list is set, told recently, the
    candidates are unknown, or unreadable. Read-only: the sender calls brief_apps_ask_told once the brief went
    out. It rides in the brief: no push or job of its own. The app names are only in the returned text."""
    from . import apps_ask as _apps_ask
    try:
        cfg = config(env, home)
        return _gated("brief:apps_ask", "\n".join(_apps_ask.ask_lines(cfg, state_dir, now, env, home)), env, home)
    except Exception:  # noqa: BLE001 - unreadable activity must not stop the brief
        return ""


def brief_apps_ask_told(state_dir, now: float, env: Optional[Mapping[str, str]] = None,
                        home: Optional[Path] = None) -> bool:
    """Mark the app-lists ask told (apps_ask.tell: apps-ask.json, an epoch only), after a delivered brief that
    carried it, so it is asked at most once in seven days. False when off or a list is set; never raises."""
    from . import apps_ask as _apps_ask
    try:
        cfg = config(env, home)
        if not _apps_ask.enabled(cfg) or _apps_ask.lists_set(cfg, state_dir, env):
            return False
        return _apps_ask.tell(state_dir, now)
    except Exception:  # noqa: BLE001 - a failed mark must not stop the sender
        return False


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


def week_ideas(state_dir, now: float, env: Optional[Mapping[str, str]] = None,
               home: Optional[Path] = None) -> str:
    """The week review's idea-ledger line (idea_ledger.review_line of idea_ledger.week over the seven days up to
    ``now``), digit-free, through tier_audit.gate (hook ``week_review:ideas``); "" when no ledger is set, the
    line is blocked or the ledger cannot be read. Never the idea text; it never triages. Read-only."""
    try:
        reader = StateReader(Path(state_dir))
        if reader.idea_ledger_path(env, home) is None:
            return ""
        line = _idea_ledger.review_line(_idea_ledger.week(reader.idea_ledger_rows(env, home), now))
    except Exception:  # noqa: BLE001 - a broken ledger must not stop the review
        return ""
    return _gated("week_review:ideas", line, env, home)


def delivery_wake_days(state_dir, now: Optional[float] = None, env: Optional[Mapping[str, str]] = None,
                       home: Optional[Path] = None, tz: Optional[tzinfo] = None) -> Optional[list]:
    """The local dates of the wake events this module already merges (events, jobs.wake_times: Sleep mode,
    screen-event wakes, events.jsonl) up to ``now`` (no bound when None); None when there is none or the state
    cannot be read (unknown, never "no wake"). Dates only: no time of day is compared."""
    try:
        evs = events(StateReader(Path(state_dir)), env, home)
        wakes = jobs.wake_times(evs, math.inf if now is None else now)
    except Exception:  # noqa: BLE001 - unreadable state is unknown wake days, never a traceback
        return None
    return sorted({datetime.fromtimestamp(t, tz).date() for t in wakes}) or None


DELIVERY_LINE = "Pushes: {}."


def week_delivery(state_dir, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None,
                  today: Optional[date] = None, tz: Optional[tzinfo] = None, now: Optional[float] = None) -> str:
    """The week review's delivery line (delivery_audit.audit of kevin-push's log, config ``push_log``, over the
    seven local days up to ``today``): "Pushes: within the push limit every day this week; brief reached you on
    most wake days; every push had a reply line.", digit-free, through tier_audit.gate (hook
    ``week_review:delivery``); an unknown brief clause and the complaints clause (no complaint source is read
    here, so it is unknown) are left out. "" when no ``today`` is given, the log is
    unset or unreadable, or the week has no row (unknown, not zero). Read-only: the log is never written."""
    if not isinstance(today, date):
        return ""
    try:
        cfg = config(env, home)
        path = _delivery.log_path(cfg, state_dir)
        got = _delivery.read_log(path) if path is not None else None
        if got is None:
            return ""
        a = _delivery.audit(got[0], wake_days=delivery_wake_days(state_dir, now, env, home, tz), today=today,
                            tz=tz, cap=_delivery.push_cap(cfg), skipped=got[1])
        if not a["known_days"]:
            return ""
        words = [w for k, w in a["labels"].items() if w and not (k == "brief" and w == _delivery.BRIEF_UNKNOWN)
                 and not (k == "complaints" and w.startswith(_delivery.COMPLAINTS_UNKNOWN))]
        line = DELIVERY_LINE.format("; ".join(words))
    except Exception:  # noqa: BLE001 - a broken log must not stop the review
        return ""
    return _gated("week_review:delivery", line, env, home)


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


EXPERIMENT_PENDING_LINE = "Experiment: outcome pending (judged later)"


def week_experiment(state_dir, habit: Optional[dict], today: Optional[date] = None,
                    env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> str:
    """The week review's experiment line: EXPERIMENT_PENDING_LINE when habit.json's week has a locked
    prediction whose receipt is pending (a lag that has not passed: prediction.receipt says so, writing
    nothing), through tier_audit.gate (hook ``week_review:experiment``); "" otherwise (no week, nothing locked,
    no lag, a receipt already written or the state cannot be read). Read-only; never the prediction's text."""
    try:
        start = jobs._week_start(habit)
        if start is None:
            return ""
        r = _prediction.receipt(state_dir, start.isoformat(), write=False, today=today)
        if r.get("action") != _prediction.PENDING:
            return ""
    except Exception:  # noqa: BLE001 - a broken ledger must not stop the review
        return ""
    return _gated("week_review:experiment", EXPERIMENT_PENDING_LINE, env, home)


def week_next(state_dir, habit: Optional[dict], decision, env: Optional[Mapping[str, str]] = None,
              home: Optional[Path] = None, tz: Optional[tzinfo] = None) -> str:
    """After a Drop at the week review, the one words line habit_catalogue.review_line gives ("Next up, if you
    want it: <name>."), through tier_audit.gate (hook ``week_review:next``); "" after Keep, for an unknown
    decision, when the list is exhausted or the state cannot be read. It only suggests: no push, no job, and
    no habit starts (that is the person's yes and habit_start). When the habit week's feed reflex
    (feed_reflex) is "often", the line may name the circuit breaker instead (habit_catalogue.CIRCUIT_BREAKER).
    """
    if decision != "Drop":
        return ""
    try:
        got = _week_reflex(state_dir, habit, env, home, tz)
        often = got is not None and got["label"] == _feed_reflex.OFTEN
    except Exception:  # noqa: BLE001 - broken activity data never stops the line; it reads as not often
        often = False
    try:
        line = habit_catalogue.review_line(decision, _stop_rule.loop_rows(state_dir), habit, reflex_often=often)
    except Exception:  # noqa: BLE001 - a broken ledger must not stop the decision being logged
        return ""
    return _gated("week_review:next", line, env, home)


def _break(v: jobs.Verdict, p: _Pass, now: float) -> jobs.Verdict:
    """The break nudge's verdict: narrowed by its block (jobs.break_verdict); with no trigger and unknown
    blocks, the reason says why they are unknown (no DB, no work apps), never that there was no block."""
    blk = p.blocks or {}
    if v.action == jobs.NOT_TRIGGERED and blk.get("blocks") is None and blk.get("why"):
        return v._replace(reason=f"focus blocks unknown: {blk['why']}")
    return jobs.break_verdict(v, p.evs, now, blk.get("gap_s", _blocks.GAP_S))


NOOP_MARK = "noop-export.json"
NOOP_DONE, NOOP_NOTHING, NOOP_NOT_WRITTEN, NOOP_FAILED = "done", "nothing to export", "a file was not written", \
    "failed"
_NOOP_NOTHING = (_noop_export.NO_DB, _noop_export.NO_FILE, _noop_export.NOT_NOOP, mock_guard.ONLY_DEMO)
_DIGITS = re.compile(r"\d+(?:[.,:]\d+)*")
# the CLI's dry-run hint, said the way the job is switched to writing
_NOOP_CLI_HINT = "(run with --write to write them)"
_NOOP_JOB_HINT = f'(config {jobs.NOOP_CONFIG} "{jobs.NOOP_WRITE}" writes them)'


def _epoch(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def load_noop_mark(state_dir) -> dict:
    """noop-export.json as ``{"row_at", "ran_at", "mode", "outcome", "said"}``; {} when missing or malformed.
    ``row_at`` and ``ran_at`` are epoch seconds or None."""
    try:
        data = json.loads((Path(state_dir) / NOOP_MARK).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    said = data.get("said")
    return {"row_at": _epoch(data.get("row_at")), "ran_at": _epoch(data.get("ran_at")),
            "mode": data.get("mode") if data.get("mode") in jobs.NOOP_MODES else None,
            "outcome": data.get("outcome") if isinstance(data.get("outcome"), str) else None,
            "said": [s for s in said if isinstance(s, str)] if isinstance(said, list) else []}


def _write_noop_mark(state_dir, mark: dict) -> None:
    """noop-export.json, atomic (a temp file in the state dir, then a rename) and 0600."""
    _write_mark(state_dir, NOOP_MARK, mark)


def _noop_words(text: str) -> list:
    """noop_export.main's printed lines, digit-free (it prints counts in words and never a path, a device or a
    reading; a number from anywhere else becomes "a number")."""
    return [_DIGITS.sub("a number", ln.replace(_NOOP_CLI_HINT, _NOOP_JOB_HINT)).strip()
            for ln in text.splitlines() if ln.strip()]


def run_noop_export(state_dir, row_at: float, now: float, mode: str, env: Optional[Mapping[str, str]] = None,
                    home: Optional[Path] = None, tz: Optional[tzinfo] = None) -> dict:
    """Call noop_export.main in-process (``--write`` only in write mode) and record the run in noop-export.json:
    the epoch seconds of the runs.jsonl row it acted on (``row_at``) and of this run (``ran_at``), the mode, the
    outcome and what it said, in words only. A plain reason (no ``noop_db``, no file, not a NOOP DB) is the
    outcome "nothing to export", recorded like any run, so the same copy is never retried: never an error loop.
    Returns the mark. Starts, stops and sends nothing."""
    out, err = io.StringIO(), io.StringIO()
    try:
        code = _noop_export.main(["--write"] if mode == jobs.NOOP_WRITE else [], env=env, home=home, tz=tz,
                                 out=out, err=err)
    except Exception as e:  # noqa: BLE001 - a broken export must not stop the other jobs or loop
        code, said = None, [f"the export failed ({type(e).__name__})"]
    else:
        said = _noop_words(out.getvalue()) + _noop_words(err.getvalue())
    first = said[0] if said else ""
    outcome = (NOOP_FAILED if code is None else NOOP_NOT_WRITTEN if code != 0
               else NOOP_NOTHING if first in _NOOP_NOTHING or first.startswith(_noop_export.SCHEMA_PREFIX)
               else NOOP_DONE)
    mark = {"row_at": row_at, "ran_at": now, "mode": mode, "outcome": outcome, "said": said}
    _write_noop_mark(state_dir, mark)
    return mark


def noop_export_row(state_dir, now: float, dry_run: bool = True, env: Optional[Mapping[str, str]] = None,
                    home: Optional[Path] = None, tz: Optional[tzinfo] = None) -> Optional[dict]:
    """The NOOP export's ``{job, action, reason}`` row, or None when config ``noop_export`` is off (no row: the
    pass is as before). Due (jobs.noop_export_verdict) and not ``dry_run``: runs it (run_noop_export) and says
    what it found in words; ``dry_run``: the verdict only, nothing read, run or written."""
    mode = jobs.noop_mode(config(env, home))
    if mode == jobs.NOOP_OFF:
        return None
    v = jobs.noop_export_verdict(mode, StateReader(Path(state_dir)).last_run(),
                                 load_noop_mark(state_dir).get("row_at"), now)
    title = jobs.NOOP_EXPORT.send_title
    if v.action != jobs.RUN:
        return {"job": title, "action": v.action, "reason": v.reason}
    if dry_run:
        return {"job": title, "action": v.action, "reason": f"{v.reason}; dry run of limitless-jobs: not run"}
    try:
        mark = run_noop_export(state_dir, v.trigger_at, now, mode, env, home, tz)
    except OSError as e:
        return {"job": title, "action": jobs.HOLD,
                "reason": f"{v.reason}; the mark was not written ({type(e).__name__}); the next run tries again"}
    said = "; ".join(mark["said"]) or "nothing said"
    return {"job": title, "action": v.action, "reason": f"{v.reason}; ran ({mark['outcome']}): {said}"}


APPS_MARK = "apps-ingest.json"
APPS_ACTIONS = (_apps_reply.NOTHING, _apps_reply.WOULD_WRITE, _apps_reply.WRITE)


APPS_LIST_WORDS = ("work", "feed")     # apps-ingest.json's ``wrote``: which lists the last write set, in words
_APPS_LIST_OF = {"work apps": "work", "feed apps": "feed"}   # apps_reply row words -> APPS_LIST_WORDS


def load_apps_mark(state_dir) -> dict:
    """apps-ingest.json as ``{"row_at", "ran_at", "mode", "action", "wrote_at", "wrote"}``; {} when missing or
    malformed. ``row_at``, ``ran_at`` and ``wrote_at`` (the ``ran_at`` of the last run that wrote the app lists,
    kept by later runs) are epoch seconds or None; ``action`` is one of APPS_ACTIONS or None; ``wrote`` is the
    words of the lists that write set (APPS_LIST_WORDS order), () when unknown."""
    try:
        data = json.loads((Path(state_dir) / APPS_MARK).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    wrote = data.get("wrote") if isinstance(data.get("wrote"), list) else []
    return {"row_at": _epoch(data.get("row_at")), "ran_at": _epoch(data.get("ran_at")),
            "mode": data.get("mode") if data.get("mode") in jobs.APPS_MODES else None,
            "action": data.get("action") if data.get("action") in APPS_ACTIONS else None,
            "wrote_at": _epoch(data.get("wrote_at")),
            "wrote": tuple(w for w in APPS_LIST_WORDS if w in wrote)}


def _write_mark(state_dir, name: str, mark: dict) -> None:
    """A mark file in the state dir, atomic (a temp file there, then a rename) and 0600."""
    d = Path(state_dir)
    fd, tmp = tempfile.mkstemp(prefix="." + name + ".", suffix=".tmp", dir=str(d))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(mark, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, d / name)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def run_apps_ingest(state_dir, db, row_at: float, now: float, mode: str) -> dict:
    """Read the person's replies after apps.json's ``since`` from the Hermes session DB ``db`` (read-only), run
    apps_reply.ingest (writing apps.json only in write mode) and record the run in apps-ingest.json: the runs.jsonl
    row it acted on (``row_at``), this run (``ran_at``), the mode and the action word (nothing, would write,
    write). A write also records ``wrote_at`` (this run) and ``wrote``, the words of the lists it set ("work",
    "feed"); a later run that writes nothing keeps them, so a wake brief can still tell that write once
    (brief_apps_set). Never an app name or reply text. Returns the mark. Sends nothing."""
    replies = _habit_replies.replies_from_hermes_db(db, _apps_reply.read_after(state_dir, now))
    got = _apps_reply.ingest(state_dir, replies, now, dry_run=mode != jobs.APPS_WRITE)
    action = _apps_reply.NOTHING if got["apps"] is None else \
        _apps_reply.WRITE if mode == jobs.APPS_WRITE else _apps_reply.WOULD_WRITE
    mark = {"row_at": row_at, "ran_at": now, "mode": mode, "action": action}
    if action == _apps_reply.WRITE:
        said = {_APPS_LIST_OF.get(w) for r in got["rows"] if r.get("action") == _apps_reply.WRITE
                for w in r.get("lists", ())}
        mark.update(wrote_at=now, wrote=[w for w in APPS_LIST_WORDS if w in said])
    else:
        old = load_apps_mark(state_dir)
        if old.get("wrote_at") is not None:
            mark.update(wrote_at=old["wrote_at"], wrote=list(old["wrote"]))
    _write_mark(state_dir, APPS_MARK, mark)
    return mark


_APPS_SAID = {_apps_reply.NOTHING: "no new apps reply: the app lists stay as they are",
              _apps_reply.WOULD_WRITE: f'would write the app lists (config {jobs.APPS_CONFIG} "{jobs.APPS_WRITE}" '
                                       f'writes them)',
              _apps_reply.WRITE: "wrote the app lists"}


def apps_ingest_row(state_dir, now: float, dry_run: bool = True, env: Optional[Mapping[str, str]] = None,
                    home: Optional[Path] = None) -> Optional[dict]:
    """The apps ingest's ``{job, action, reason}`` row, or None when config ``apps_ingest`` is off (no row).
    Due (jobs.apps_ingest_verdict) and not ``dry_run``: runs it (run_apps_ingest) and says the action in words;
    a write adds ``line`` (jobs.APPS_LINE). ``dry_run``: the verdict only, nothing read, run or written."""
    mode = jobs.apps_mode(config(env, home))
    if mode == jobs.APPS_OFF:
        return None
    db = _habit_replies.hermes_db_path(state_dir, env, home)
    v = jobs.apps_ingest_verdict(mode, StateReader(Path(state_dir)).last_run(),
                                 load_apps_mark(state_dir).get("row_at"), now, db_set=db is not None)
    title = jobs.APPS_INGEST.send_title
    if v.action != jobs.RUN:
        return {"job": title, "action": v.action, "reason": v.reason}
    if dry_run:
        return {"job": title, "action": v.action, "reason": f"{v.reason}; dry run of limitless-jobs: not run"}
    try:
        mark = run_apps_ingest(state_dir, db, v.trigger_at, now, mode)
    except OSError as e:
        return {"job": title, "action": jobs.HOLD,
                "reason": f"{v.reason}; a file was not written ({type(e).__name__}); the next run tries again"}
    row = {"job": title, "action": v.action, "reason": f"{v.reason}; {_APPS_SAID[mark['action']]}"}
    if mark["action"] == _apps_reply.WRITE:
        row["line"] = jobs.APPS_LINE
    return row


def apps_ingest_line(state_dir) -> str:
    """jobs.APPS_LINE when the last apps ingest wrote the app lists (apps-ingest.json says ``write``), else "".
    Words only: a later brief may show it as a T1 line."""
    return jobs.APPS_LINE if load_apps_mark(state_dir).get("action") == _apps_reply.WRITE else ""


APPS_SET_MARK = "apps-set.json"   # {"told": the wrote_at last told in a brief, "told_at": when}, epochs only
APPS_SET_HOOK = "brief:apps_set"
_APPS_SET_WORDS = {("work", "feed"): "Work and feed app lists", ("work",): "Work app list",
                   ("feed",): "Feed app list"}


def load_apps_set_mark(state_dir) -> dict:
    """apps-set.json as ``{"told", "told_at"}`` (epoch seconds or None); {} when missing or malformed."""
    try:
        data = json.loads((Path(state_dir) / APPS_SET_MARK).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {"told": _epoch(data.get("told")), "told_at": _epoch(data.get("told_at"))}


def apps_set_untold(state_dir, now: float, cfg: Mapping) -> Optional[dict]:
    """The apps-ingest mark of the last write not yet told in a brief, or None: none, the ingest is not in write
    mode (config ``apps_ingest``: a dry run never tells), the write is after ``now``, or it was told already."""
    if jobs.apps_mode(cfg) != jobs.APPS_WRITE:
        return None
    mark = load_apps_mark(state_dir)
    at = mark.get("wrote_at")
    if at is None or at > now or load_apps_set_mark(state_dir).get("told") == at:
        return None
    return mark


def apps_set_line(wrote) -> str:
    """"Work and feed app lists set from your reply." (or the one list ``wrote`` names); words only, never a name
    or a count. jobs.APPS_LINE, capitalized, when the lists are unknown."""
    head = _APPS_SET_WORDS.get(tuple(w for w in APPS_LIST_WORDS if w in (wrote or ())))
    return f"{head} set from your reply." if head else f"{jobs.APPS_LINE[0].upper()}{jobs.APPS_LINE[1:]}."


def brief_apps_set(state_dir, now: float, env: Optional[Mapping[str, str]] = None,
                   home: Optional[Path] = None) -> str:
    """The wake brief's one apps-set line (apps_set_line): "Work and feed app lists set from your reply." once
    after each apps-ingest write not yet told, through tier_audit.gate (hook ``brief:apps_set``); "" when there is
    none, the ingest is not in write mode, it was told, or state is unreadable. Read-only, like brief_outage with
    ``write=False``: the sender calls brief_apps_set_told once the brief went out. It rides in the brief: no push
    or job of its own."""
    try:
        mark = apps_set_untold(state_dir, now, config(env, home))
        return _gated(APPS_SET_HOOK, apps_set_line(mark["wrote"]), env, home) if mark else ""
    except Exception:  # noqa: BLE001 - an unreadable mark must not stop the brief
        return ""


def brief_apps_set_told(state_dir, now: float, env: Optional[Mapping[str, str]] = None,
                        home: Optional[Path] = None) -> bool:
    """Mark the last apps-ingest write told (apps-set.json: ``{"told": its wrote_at, "told_at": now}``, epochs only,
    atomic, 0600), after a delivered brief that carried brief_apps_set's line, so one write is said once and a later
    write (a new reply) is said again. False when there is nothing untold (or not write mode) or state is
    unreadable; never raises."""
    try:
        mark = apps_set_untold(state_dir, now, config(env, home))
        if mark is None:
            return False
        _write_mark(state_dir, APPS_SET_MARK, {"told": mark["wrote_at"], "told_at": float(now)})
        return True
    except Exception:  # noqa: BLE001 - a failed mark must not stop the sender
        return False


def apps_set_told(state_dir) -> Optional[bool]:
    """For the doctor: None before any apps-ingest write, else whether the last write was told in a brief."""
    at = load_apps_mark(state_dir).get("wrote_at")
    return None if at is None else load_apps_set_mark(state_dir).get("told") == at


def apps_ingest_label(state_dir) -> Optional[dict]:
    """apps_ingest_line as a T1 label (``{"label", "tier": "T1", "modality": "derived"}``) a later wake brief may
    show; None unless the last apps ingest run wrote the app lists. Read-only; sends nothing."""
    line = apps_ingest_line(state_dir)
    return {"label": line, "tier": "T1", "modality": "derived"} if line else None


RANKED_MARK = "ranked-ingest.json"
RANKED_ACTIONS = (_ranked.NOTHING, _ranked.IGNORE, _ranked.WOULD_WRITE, _ranked.WRITE)


def load_ranked_mark(state_dir) -> dict:
    """ranked-ingest.json as ``{"row_at", "ran_at", "mode", "action"}``; {} when missing or malformed. ``row_at`` and
    ``ran_at`` are epoch seconds or None; ``mode`` is one of jobs.RANKED_MODES or None; ``action`` one of
    RANKED_ACTIONS or None."""
    try:
        data = json.loads((Path(state_dir) / RANKED_MARK).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {"row_at": _epoch(data.get("row_at")), "ran_at": _epoch(data.get("ran_at")),
            "mode": data.get("mode") if data.get("mode") in jobs.RANKED_MODES else None,
            "action": data.get("action") if data.get("action") in RANKED_ACTIONS else None}


def _ranked_action(got: dict, mode: str) -> str:
    """One word for a ranked_ledger.ingest result: nothing (no new owner message), ignore (no drop to append), would
    write (a dry run with drops) or write."""
    if got.get("mark") is None:
        return _ranked.NOTHING
    if not got.get("would_append"):
        return _ranked.IGNORE
    return _ranked.WRITE if mode == jobs.RANKED_WRITE else _ranked.WOULD_WRITE


def run_ranked_ingest(state_dir, db, ledger, row_at: float, now: float, mode: str) -> tuple:
    """Read the owner's messages after ranked-drops.json from the Hermes session DB ``db`` (read-only), run
    ranked_ledger.ingest (appending owner drop rows to ``ledger`` and moving ranked-drops.json only in write mode)
    and record the pass in ranked-ingest.json: the runs.jsonl row it acted on (``row_at``), this pass (``ran_at``),
    the mode and the action word. Never an id, evidence or message text, never a count. Returns (mark, the ingest
    result). Sends nothing."""
    replies = _habit_replies.replies_from_hermes_db(db, _ranked.read_after(state_dir, now))
    got = _ranked.ingest(state_dir, ledger, replies, now, write=mode == jobs.RANKED_WRITE)
    mark = {"row_at": row_at, "ran_at": now, "mode": mode, "action": _ranked_action(got, mode)}
    _write_mark(state_dir, RANKED_MARK, mark)
    return mark, got


def _ranked_said(action: str, n: int) -> str:
    """What one pass did, in words; ``n`` (the owner drop rows appended or that would be) as a word, never a digit."""
    rows = f"{_ranked.count_words(n)} owner drop row{'' if n == 1 else 's'}"
    return {_ranked.NOTHING: "no new owner message: the ranked ledger stays as it is",
            _ranked.IGNORE: "no owner drop to append: the ranked ledger stays as it is",
            _ranked.WOULD_WRITE: f'would append {rows} (config {jobs.RANKED_CONFIG} "{jobs.RANKED_WRITE}" appends '
                                 f'{"it" if n == 1 else "them"})',
            _ranked.WRITE: f"appended {rows}"}[action]


def ranked_ingest_row(state_dir, now: float, dry_run: bool = True, env: Optional[Mapping[str, str]] = None,
                      home: Optional[Path] = None) -> Optional[dict]:
    """The ranked ingest's ``{job, action, reason}`` row, or None when config ``ranked_ingest`` is off (no row,
    nothing read). Due (jobs.ranked_ingest_verdict) and not ``dry_run``: runs it (run_ranked_ingest) and says what it
    did in words; ``dry_run``: the verdict only, nothing read, run or written. Only the owner's drop replies ever
    reach the ledger here (ranked_ledger.ingest): an agent row is never made dropped."""
    cfg = config(env, home)
    mode = jobs.ranked_mode(cfg)
    if mode == jobs.RANKED_OFF:
        return None
    ledger = _scorecard.ledger_path(state_dir, cfg, os.environ if env is None else env)
    db = _habit_replies.hermes_db_path(state_dir, env, home)
    v = jobs.ranked_ingest_verdict(mode, StateReader(Path(state_dir)).last_run(),
                                   load_ranked_mark(state_dir).get("row_at"), now, db_set=db is not None,
                                   ledger_set=ledger is not None)
    title = jobs.RANKED_INGEST.send_title
    if v.action != jobs.RUN:
        return {"job": title, "action": v.action, "reason": v.reason}
    if dry_run:
        return {"job": title, "action": v.action, "reason": f"{v.reason}; dry run of limitless-jobs: not run"}
    try:
        mark, got = run_ranked_ingest(state_dir, db, ledger, v.trigger_at, now, mode)
    except OSError as e:
        return {"job": title, "action": jobs.HOLD,
                "reason": f"{v.reason}; a file was not written ({type(e).__name__}); the next run tries again"}
    return {"job": title, "action": v.action,
            "reason": f"{v.reason}; {_ranked_said(mark['action'], got.get('would_append', 0))}"}


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
            elif spec.name == jobs.WEEK_REVIEW.name:
                text = week_review_body(state_dir, p.habit, p.synced, env, home, tz, today, now)
                ok, how = _push(push, spec.send_title, text, _key(spec, v, p.evs, tz, p.habit), why=v.reason)
            else:
                miq = spec.name == jobs.MIQ.name
                plan = _overnight.plan_for(state_dir, now, env, home) if miq else ""
                wind = miq_wind_down(p.evs, v.trigger_at, env, home, tz, state_dir=state_dir, now=now) if miq else ""
                text = body(spec, p.habit, _phone(spec, v, p, state_dir, env, home), p.synced, overnight=plan,
                            target_days=weekly_target.target_days(env, home), wind_down_line=wind)
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
    noop = noop_export_row(state_dir, now, dry_run, env, home, tz)   # sends nothing; None (no row) when off
    apps = apps_ingest_row(state_dir, now, dry_run, env, home)        # sends nothing; None (no row) when off
    ranked = ranked_ingest_row(state_dir, now, dry_run, env, home)    # sends nothing; None (no row) when off
    from . import sender_ingest_job as _sender   # sends nothing; None (no row) when off
    sender = _sender.run(state_dir, now, dry_run=dry_run, env=env, home=home)
    from . import voice_miq as _voice_miq   # voice_miq reads MIQ_QUESTION and SENT_LOG from here
    voice = _voice_miq.run(state_dir, now, env=env, home=home, dry_run=dry_run)   # None (no row) when off
    from . import outage_recap_job as _recap   # outage_recap_job uses _push and _write_mark from here
    recap = _recap.run(state_dir, now, push=push, dry_run=dry_run, env=env, home=home, tz=tz)   # None when off
    return rows + [r for r in (noop, apps, ranked, sender, voice, recap) if r is not None]
