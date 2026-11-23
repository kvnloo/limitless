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
passes to ``kevin-push --once``, so only the first message per event goes out. A push that reports
``send_gate.ONCE_DROP`` (another sender already sent for this event) drops the job. ``push`` returns what kevin-push reported
(``"telegram"`` or ``True`` for a real delivery). Only a real delivery appends ``jobs.sent_entry()``
to the sent log; a failed, log-only or held push is not a send, and the job holds until the next
run tries again. ``dry_run=True`` (the default) never calls ``push`` and never writes. Nothing here reads the
clock: ``now`` comes from the caller. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import inspect
import json
from datetime import date
from pathlib import Path
from typing import Callable, Mapping, NamedTuple, Optional

from . import aw_reader, jobs, send_gate, wake_proxy
from .glide_provider import GlideProvider
from .state_reader import StateReader, parse_ts
from .window_chain import EventProvider, first_known

SENT_LOG = "jobs-sent.jsonl"
DELIVERED = "telegram"
_BODY = {
    jobs.WAKE_BRIEF.name: "You are up. Your brief comes next.",
    jobs.NAP.name: "Welcome back from your nap. Anything held while you slept is in your brief.",
    jobs.MIQ.name: "Your wind-down has started. What is the one thing that matters most tomorrow?",
}


def body(spec: jobs.JobSpec, habit: Optional[dict] = None) -> str:
    """The plain-words message for one job. The habit check-in names this week's habit and its taps."""
    if spec.name == jobs.HABIT_CHECKIN.name:
        name = (habit or {}).get("habit") if isinstance(habit, dict) else None
        what = f"Did you do it today: {name}?" if isinstance(name, str) and name.strip() else "Did you do your habit today?"
        return f"{what} Reply {', '.join(spec.answers[:-1])} or {spec.answers[-1]}."
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


def _takes_once(push) -> bool:
    try:
        inspect.signature(push).bind("title", "body", once="key")
    except (TypeError, ValueError):
        return False
    return True


def _push(push, title: str, text: str, once: Optional[str] = None):
    """(delivered, how) for one push; an exception is a failed push, never a send."""
    try:
        result = push(title, text, once=once) if once is not None and _takes_once(push) else push(title, text)
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
    return [jobs.habit_checkin(reader.habit()) if name == jobs.HABIT_CHECKIN.name else spec
            for name, spec in jobs.SPECS.items()]


class _Pass(NamedTuple):
    """Everything one pass reads from the state dir, read once so every caller sees the same inputs."""
    evs: list
    window: object
    sent: list
    habit: Optional[dict]
    specs: list


def _read_pass(state_dir, now: float, env: Optional[Mapping[str, str]] = None,
               home: Optional[Path] = None) -> _Pass:
    reader = StateReader(Path(state_dir))
    ev_provider = EventProvider.from_reader(reader, now)
    state = first_known(GlideProvider.from_config(env=env, home=home, now=now), ev_provider)
    return _Pass(evs=events(reader, env=env, home=home),
                 window={"cls": "asleep"} if ev_provider.asleep else state,
                 sent=reader.jobs_sent(), habit=reader.habit(), specs=_specs(reader))


def _key(spec: jobs.JobSpec, v: jobs.Verdict) -> Optional[str]:
    """The event key for one verdict: once_key of its trigger, or None when nothing triggered it."""
    return once_key(spec, v.trigger_at) if v.trigger_at is not None else None


def event_key(state_dir, now: float, job: str = jobs.WAKE_BRIEF.name, env: Optional[Mapping[str, str]] = None,
              home: Optional[Path] = None) -> Optional[str]:
    """The ``kevin-push --once`` key run_once uses for ``job`` right now, or None when it has no trigger.

    Same events, same trigger as run_once (both read through _read_pass and should_fire), so another
    sender for the same event (bin/limitless-brief) gets the same key. The key is the latest trigger's
    whatever the verdict: after run_once has sent (a drop), a later sender still gets that event's key and
    kevin-push drops it. Reads only; never sends or writes.
    """
    p = _read_pass(state_dir, now, env=env, home=home)
    spec = next((s for s in p.specs if s.name == job), None)
    if spec is None:
        raise ValueError(f"job must be one of {sorted(jobs.SPECS)}, got {job!r}")
    return _key(spec, jobs.should_fire(spec, p.evs, p.window, p.sent, now))


def run_once(state_dir, now: float, push: Optional[Callable[[str, str], object]] = None, dry_run: bool = True,
             env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None,
             today: Optional[date] = None) -> list:
    """One ``{job, action, reason}`` row per job spec, in plain words. Sends only when not ``dry_run``.

    A triggered habit check-in drops outside a started habit week (jobs.habit_week_gate); ``today``
    is the local date of ``now`` unless the caller passes one.
    """
    p = _read_pass(state_dir, now, env=env, home=home)
    today = date.fromtimestamp(now) if today is None else today
    sent = p.sent
    proxy_at = {e["at"] for e in p.evs if e.get("source") == "screen"}   # screen wakes and their habit cues
    rows = []
    for spec in p.specs:
        v = jobs.should_fire(spec, p.evs, p.window, sent, now)
        gate = jobs.habit_week_gate(p.habit, today) if spec.name == jobs.HABIT_CHECKIN.name else None
        if gate is not None and v.action != jobs.NOT_TRIGGERED:
            v = gate._replace(trigger_at=v.trigger_at)      # a cue came, but no started week: drop, never send
        action, reason = v.action, v.reason
        if v.trigger_at is not None and v.trigger_at in proxy_at:
            reason = f"{reason}; the wake is a phone-quiet gap (proxy), not a sleep measure"
        if action == jobs.DELIVER and not dry_run and push is not None:
            ok, how = _push(push, spec.send_title, body(spec, p.habit), _key(spec, v))
            if ok:
                entry = jobs.sent_entry(spec, v.trigger_at, now)
                with open(Path(state_dir) / SENT_LOG, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")
                sent.append(entry)               # later jobs in this run see it (daily cap)
                reason = f"{reason}; sent"
            elif send_gate.ONCE_DROP in how:
                action, reason = jobs.DROP, f"{reason}; not sent: {send_gate.ONCE_DROP} by another sender"
            else:
                action, reason = jobs.HOLD, f"{reason}; not delivered: {how}; the next run tries again"
        rows.append({"job": spec.send_title, "action": action, "reason": reason})
    return rows
