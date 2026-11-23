"""Schedule cards: every recurring plugin job as one Hermes proactivity schedule card.

Hermes's proactivity roadmap (NousResearch/hermes-agent issue #158538) puts every proactive run on a job the
person approved, shown on a "Schedule this job?" card (PR #158289, approval kind ``schedule``). This module
describes each limitless job (jobs.SPECS) as one such card, so a host can show and govern it instead of the
plugin keeping a schedule nobody sees:

    card_for(spec) -> {id, kind, name, description, trigger, ends, window, stale_after_s, once_key,
                       budget, per_window, sender, words}
    cards(external=(), habit=None) -> [card_for(spec) for every job]

``trigger`` and ``ends`` are event names (jobs.EVENTS), never a clock time or a cron string: a test fails if
a card grows one. ``once_key`` is the template of the send gate's event key (jobs_runner._key) in words.
``budget`` is the send gate's per-day cap (shared by every limitless push); ``per_window`` the job's own
limit per trigger. ``sender`` is ``plugin`` (limitless-jobs sends it) or ``external`` (a job named in
``external_jobs``: its own sender has the content). ``words`` is jobs.to_schedule_card: the plain lines.
Field names follow #158289 where it has one (``kind``, ``name``, ``description``); docs/schedule-cards.md
has the mapping.

Host registration (plugin.register): a host ctx with a callable ``register_schedule_card`` (HOST_METHOD) gets
each card, one call per card. #158289 at its head dd4e675b has no such plugin method yet, so today every
host takes the other path: nothing is registered and the plugin logs NO_HOST, one content-free line.

Pure: no clock, no file, no network; nothing here sends or schedules. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

from typing import Iterable, Optional

from . import jobs, send_gate

KIND = "schedule"            # #158289: the approval kind of a "Schedule this job?" card
HOST_METHOD = "register_schedule_card"   # the host ctx method plugin.register looks for (hasattr)
NO_HOST = "limitless: the host has no schedule-card registration; nothing registered"
HOST_FAILED = "limitless: the host's schedule-card registration failed; register went on"
PLUGIN, EXTERNAL = "plugin", "external"
SENDERS = (PLUGIN, EXTERNAL)
# Keys that are not one per trigger event (jobs_runner._key): one per night, per habit week, per focus block.
_ONCE = {jobs.MIQ.name: f"{jobs.MIQ.name}:<night date>",
         jobs.WEEK_REVIEW.name: f"{jobs.WEEK_REVIEW.name}:<habit week start date>",
         jobs.BREAK_NUDGE.name: "break:<focus block start time>"}


def once_key(spec: jobs.JobSpec) -> str:
    """The send gate's event key for this job, as a template in words (jobs_runner._key)."""
    return _ONCE.get(spec.name) or f"{spec.name}:<{jobs._label(spec)} event time>"


def card_for(spec: jobs.JobSpec, external: Iterable[str] = ()) -> dict:
    """One schedule card for ``spec``: a new plain dict (JSON data), digit-free except ``stale_after_s``,
    ``budget`` and ``per_window``."""
    words = jobs.to_schedule_card(spec)
    desc = f'Schedule "{words["name"]}" ({words["speaks"]}; {words["window"]}): ends {words["ends"]}; ' \
           f'{words["delivery"]}'
    return {"id": spec.name, "kind": KIND, "name": spec.send_title, "description": desc,
            "trigger": spec.trigger_event, "ends": spec.expires, "window": spec.window_class,
            "stale_after_s": spec.stale_after_s, "once_key": once_key(spec), "budget": send_gate.DAILY_CAP,
            "per_window": spec.max_per_window, "sender": EXTERNAL if spec.name in set(external or ()) else PLUGIN,
            "words": words}


def specs(habit: Optional[dict] = None) -> list:
    """Every job spec, with the habit check-in and the week review on this week's habit cue (as run_once)."""
    per_habit = {jobs.HABIT_CHECKIN.name: jobs.habit_checkin, jobs.WEEK_REVIEW.name: jobs.week_review}
    return [per_habit[n](habit) if n in per_habit else s for n, s in jobs.SPECS.items()]


def cards(external: Iterable[str] = (), habit: Optional[dict] = None) -> list:
    """One card per job spec, in jobs.SPECS order. ``external``: job names another sender owns
    (jobs_runner.external_jobs); ``habit``: habit.json, whose ``cue`` moves the two habit cards."""
    ext = set(external or ())
    return [card_for(s, ext) for s in specs(habit)]
