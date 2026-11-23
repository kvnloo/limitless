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

The idea ledger (idea_ledger.py) adds one more card when a ledger is configured: ``ledger_card()``, sender
``local`` (bin/limitless-ledger-append --write on the wind_down event; nothing is sent, budget zero).

Pure: no clock, no file, no network; nothing here sends or schedules. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

from typing import Iterable, Optional

from . import jobs, send_gate

KIND = "schedule"            # #158289: the approval kind of a "Schedule this job?" card
HOST_METHOD = "register_schedule_card"   # the host ctx method plugin.register looks for (hasattr)
NO_HOST = "limitless: the host has no schedule-card registration; nothing registered"
HOST_FAILED = "limitless: the host's schedule-card registration failed; register went on"
PLUGIN, EXTERNAL, LOCAL = "plugin", "external", "local"
SENDERS = (PLUGIN, EXTERNAL, LOCAL)      # local: a job on this machine that sends nothing (the idea ledger)
OWN_SENDER = "; sent by its own sender, not by limitless-jobs"   # jobs_runner.OWN_SENDER, as a clause
HOOK = "tool:limitless_schedule"
MODALITY = "derived"          # computed from the job specs and config, not measured (as propose.MODALITY)
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
    sender = EXTERNAL if spec.name in set(external or ()) else PLUGIN
    desc = f'Schedule "{words["name"]}" ({words["speaks"]}; {words["window"]}): ends {words["ends"]}; ' \
           f'{words["delivery"]}' + (OWN_SENDER if sender == EXTERNAL else "")
    return {"id": spec.name, "kind": KIND, "name": spec.send_title, "description": desc,
            "trigger": spec.trigger_event, "ends": spec.expires, "window": spec.window_class,
            "stale_after_s": spec.stale_after_s, "once_key": once_key(spec), "budget": send_gate.DAILY_CAP,
            "per_window": spec.max_per_window, "sender": sender, "words": words}


def specs(habit: Optional[dict] = None) -> list:
    """Every job spec, with the habit check-in and the week review on this week's habit cue (as run_once)."""
    per_habit = {jobs.HABIT_CHECKIN.name: jobs.habit_checkin, jobs.WEEK_REVIEW.name: jobs.week_review}
    return [per_habit[n](habit) if n in per_habit else s for n, s in jobs.SPECS.items()]


def cards(external: Iterable[str] = (), habit: Optional[dict] = None, ledger: bool = False,
          noop: bool = False, apps: bool = False) -> list:
    """One card per job spec, in jobs.SPECS order. ``external``: job names another sender owns
    (jobs_runner.external_jobs); ``habit``: habit.json, whose ``cue`` moves the two habit cards; ``ledger``
    (an idea ledger is configured) adds ledger_card(); ``noop`` (config ``noop_export`` is not off) adds
    noop_export_card(); ``apps`` (config ``apps_ingest`` is not off) adds apps_ingest_card() last."""
    ext = set(external or ())
    return [card_for(s, ext) for s in specs(habit)] + ([ledger_card()] if ledger else []) + \
        ([noop_export_card()] if noop else []) + ([apps_ingest_card()] if apps else [])


LEDGER_ID = "idea_ledger"
LEDGER_SPEC = jobs.JobSpec(LEDGER_ID, "wind_down", "wind_down", "Idea ledger", 1, "sleep_mode_on")   # not in SPECS
LEDGER_RUNS = "limitless-ledger-append --write"
LEDGER_DOES = "nothing is sent; it appends the new captures to your idea ledger"


def ledger_card() -> dict:
    """The idea ledger's one card (idea_ledger.py): bin/limitless-ledger-append --write once per wind-down.
    Not a jobs.SPECS job: limitless-jobs never runs it, it pushes nothing (budget zero) and it has no clock
    time; whoever approves the card runs the command on the event."""
    w = jobs.to_schedule_card(LEDGER_SPEC)
    w.update(delivery=LEDGER_DOES, runs=LEDGER_RUNS)
    desc = f'Schedule "{w["name"]}" ({w["speaks"]}; {w["window"]}): ends {w["ends"]}; {LEDGER_DOES}'
    return {"id": LEDGER_ID, "kind": KIND, "name": LEDGER_SPEC.send_title, "description": desc,
            "trigger": LEDGER_SPEC.trigger_event, "ends": LEDGER_SPEC.expires, "window": LEDGER_SPEC.window_class,
            "stale_after_s": None, "once_key": f"{LEDGER_ID}:<night date>", "budget": 0,
            "per_window": LEDGER_SPEC.max_per_window, "sender": LOCAL, "words": w}


NOOP_RUNS = "limitless-jobs --send"
NOOP_DOES = ("nothing is sent; it reads the NOOP copy and, in write mode, merges the sleep file and the pre-sleep "
             "heart-rate file")
NOOP_WINDOW = "asleep or awake: it sends nothing, so no window holds it"


def noop_export_card() -> dict:
    """The NOOP export's one card (jobs.NOOP_EXPORT): limitless-jobs runs noop_export.main once per sync that
    copied the NOOP database (a runs.jsonl row whose ``noop`` says so). Not a jobs.SPECS job: it pushes nothing
    (budget zero), no decision window holds it and it has no clock time."""
    spec = jobs.NOOP_EXPORT
    w = jobs.to_schedule_card(spec)
    w.update(window=NOOP_WINDOW, delivery=NOOP_DOES, runs=NOOP_RUNS)
    desc = f'Schedule "{w["name"]}" ({w["speaks"]}; {w["window"]}): ends {w["ends"]}; {NOOP_DOES}'
    return {"id": spec.name, "kind": KIND, "name": spec.send_title, "description": desc,
            "trigger": spec.trigger_event, "ends": spec.expires, "window": spec.window_class,
            "stale_after_s": None, "once_key": f"{spec.name}:<sync run time>", "budget": 0,
            "per_window": spec.max_per_window, "sender": LOCAL, "words": w}


APPS_DOES = ("nothing is sent; it reads your work apps or feed apps reply and, in write mode, sets the app lists "
             "from it")


def apps_ingest_card() -> dict:
    """The apps ingest's one card (jobs.APPS_INGEST): limitless-jobs reads the apps reply once per sync run (a new
    runs.jsonl row). Not a jobs.SPECS job: it pushes nothing (budget zero), no decision window holds it and it has
    no clock time. Never an app name."""
    spec = jobs.APPS_INGEST
    w = jobs.to_schedule_card(spec)
    w.update(window=NOOP_WINDOW, delivery=APPS_DOES, runs=NOOP_RUNS)
    desc = f'Schedule "{w["name"]}" ({w["speaks"]}; {w["window"]}): ends {w["ends"]}; {APPS_DOES}'
    return {"id": spec.name, "kind": KIND, "name": spec.send_title, "description": desc,
            "trigger": spec.trigger_event, "ends": spec.expires, "window": spec.window_class,
            "stale_after_s": None, "once_key": f"{spec.name}:<sync run time>", "budget": 0,
            "per_window": spec.max_per_window, "sender": LOCAL, "words": w}


def label(n: int) -> str:
    """The T1 label for ``n`` cards, digit-free."""
    count = jobs._NUM[n] if 0 <= n < len(jobs._NUM) else "several"
    return f"{count} schedule card{'' if n == 1 else 's'}, each on an event, none on a clock"
