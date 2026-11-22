"""One pass over the event-triggered jobs: a verdict per job, and a send only through ``push``.

    rows = run_once(state_dir, now, push=push, dry_run=False)

Events are the phone's Sleep-mode changes (``sleepmode.jsonl``). The window is
``first_known(GlideProvider, EventProvider)``; asleep comes from the EventProvider. Each job's
verdict is ``jobs.should_fire`` against the sent log ``jobs-sent.jsonl`` in the state dir.

``dry_run=True`` (the default) never calls ``push`` and never writes. Nothing here reads the
clock: ``now`` comes from the caller. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping, Optional

from . import jobs
from .glide_provider import GlideProvider
from .state_reader import StateReader
from .window_chain import EventProvider, first_known

SENT_LOG = "jobs-sent.jsonl"


def _specs(reader: StateReader) -> list:
    return [jobs.habit_checkin(reader.habit()) if name == jobs.HABIT_CHECKIN.name else spec
            for name, spec in jobs.SPECS.items()]


def run_once(state_dir, now: float, push: Optional[Callable[[str, str], object]] = None, dry_run: bool = True,
             env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> list:
    """One ``{job, action, reason}`` row per job spec, in plain words."""
    reader = StateReader(Path(state_dir))
    events = jobs.events_from_sleepmode(reader.sleepmode())
    ev_provider = EventProvider.from_reader(reader, now)
    state = first_known(GlideProvider.from_config(env=env, home=home, now=now), ev_provider)
    window = {"cls": "asleep"} if ev_provider.asleep else state
    sent = reader._jsonl(SENT_LOG)
    rows = []
    for spec in _specs(reader):
        v = jobs.should_fire(spec, events, window, sent, now)
        rows.append({"job": spec.send_title, "action": v.action, "reason": v.reason})
    return rows
