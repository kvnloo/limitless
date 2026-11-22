"""One pass over the event-triggered jobs: a verdict per job, and a send only through ``push``.

    rows = run_once(state_dir, now, push=push, dry_run=False)

Events are the phone's Sleep-mode changes (``sleepmode.jsonl``) plus any ``{"event", "at"}`` rows
in ``events.jsonl`` (any name in ``jobs.EVENTS``; others are ignored). The window is
``first_known(GlideProvider, EventProvider)``; asleep comes from the EventProvider. Each job's
verdict is ``jobs.should_fire`` against the sent log ``jobs-sent.jsonl`` in the state dir.

Only a ``deliver`` verdict calls ``push(title, body)``. ``push`` returns what kevin-push reported
(``"telegram"`` or ``True`` for a real delivery). Only a real delivery appends ``jobs.sent_entry()``
to the sent log; a failed, log-only or held push is not a send, and the job holds until the next
run tries again. ``dry_run=True`` (the default) never calls ``push`` and never writes. Nothing here reads the
clock: ``now`` comes from the caller. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Mapping, Optional

from . import jobs, wake_proxy
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


def _push(push, title: str, text: str):
    """(delivered, how) for one push; an exception is a failed push, never a send."""
    try:
        result = push(title, text)
    except Exception as e:  # noqa: BLE001 - a broken push must not stop the other jobs
        return False, f"push failed ({type(e).__name__})"
    return delivered(result), (result if isinstance(result, str) and result else "no delivery reported")


def events(reader: StateReader) -> list:
    """Sleep-mode events, screen-event wakes Sleep mode does not cover (and their habit cues), plus the
    valid rows of events.jsonl, oldest first."""
    out = jobs.merged_events(jobs.events_from_sleepmode(reader.sleepmode()),
                             wake_proxy.events_from_screen(reader.screen_events()))
    for r in reader.events():
        at = parse_ts(r.get("at"))
        if at is not None and r.get("event") in jobs.EVENTS:
            out.append({"event": r["event"], "at": at})
    return sorted(out, key=lambda e: e["at"])


def _specs(reader: StateReader) -> list:
    return [jobs.habit_checkin(reader.habit()) if name == jobs.HABIT_CHECKIN.name else spec
            for name, spec in jobs.SPECS.items()]


def run_once(state_dir, now: float, push: Optional[Callable[[str, str], object]] = None, dry_run: bool = True,
             env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> list:
    """One ``{job, action, reason}`` row per job spec, in plain words. Sends only when not ``dry_run``."""
    reader = StateReader(Path(state_dir))
    evs = events(reader)
    ev_provider = EventProvider.from_reader(reader, now)
    state = first_known(GlideProvider.from_config(env=env, home=home, now=now), ev_provider)
    window = {"cls": "asleep"} if ev_provider.asleep else state
    sent = reader.jobs_sent()
    habit = reader.habit()
    rows = []
    for spec in _specs(reader):
        v = jobs.should_fire(spec, evs, window, sent, now)
        action, reason = v.action, v.reason
        if action == jobs.DELIVER and not dry_run and push is not None:
            ok, how = _push(push, spec.send_title, body(spec, habit))
            if ok:
                entry = jobs.sent_entry(spec, v.trigger_at, now)
                with open(Path(state_dir) / SENT_LOG, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")
                sent.append(entry)               # later jobs in this run see it (daily cap)
                reason = f"{reason}; sent"
            else:
                action, reason = jobs.HOLD, f"{reason}; not delivered: {how}; the next run tries again"
        rows.append({"job": spec.send_title, "action": action, "reason": reason})
    return rows
