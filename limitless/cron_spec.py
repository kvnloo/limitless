"""The Hermes cron job each plugin job would be, with its decision-window fields. Pure: it creates nothing.

A Hermes host with the cron decision-window gate (public fork kvnloo/hermes-agent, branch
up/cron-decision-window-gate-r2) stores ``window_class`` and ``stale_after_s`` on a recurring job. On that branch
neither ``hermes cron create`` nor the cronjob tool takes them; the Python job API does
(``cron.jobs.create_job(..., window_class=..., stale_after_s=...)``), and so does a job record in
``cron/jobs.json``. ``job_spec(spec)`` is therefore create_job's keyword arguments for one plugin job:

- ``name``: ``limitless-<job>``;
- ``schedule``: POLL, an interval. The cues are events (a wake, a wind-down); the interval only polls for them,
  it is never the time a message is meant for;
- ``no_agent`` + ``script``: the job runs a script, never an agent turn. ``script`` is a plain file name the
  operator puts in the host's scripts dir (``limitless-<job>.sh``), as the host wants it;
- ``deliver``: ``local``. The plugin's own send gate sends; the host never delivers the script's output;
- ``window_class`` / ``stale_after_s``: ``jobs.to_cron_fields(spec)``.

A job that sends nothing (the NOOP export and the ingests, SENDS_NOTHING) gets ``{}``: it has no message to hold
for a window, so it needs no gated host job; ``limitless-jobs --ingest`` runs it as before.
"""
from typing import Any

from limitless import jobs

POLL = "every 5m"          # a poll for events, never a clock time
SENDS_NOTHING = frozenset(s.name for s in (jobs.NOOP_EXPORT, jobs.APPS_INGEST, jobs.RANKED_INGEST,
                                           jobs.SENDER_INGEST, jobs.FIT_INGEST))
_ORDER = tuple(jobs.SPECS.values()) + (jobs.OUTAGE_RECAP, jobs.SENDER_CONFIRM, jobs.NOOP_EXPORT, jobs.APPS_INGEST,
                                       jobs.RANKED_INGEST, jobs.SENDER_INGEST, jobs.FIT_INGEST)


def all_specs() -> tuple:
    """Every job spec jobs.py defines, sending jobs first, each once, in a fixed order."""
    return _ORDER


def job_spec(spec: Any) -> dict:
    """create_job's keyword arguments for this plugin job, or ``{}`` for a job that sends nothing.

    A sending spec with no window is a ValueError: the host job would fire whenever due, ungated.
    A new dict each call.
    """
    if getattr(spec, "name", None) in SENDS_NOTHING:
        return {}
    fields = jobs.to_cron_fields(spec)
    if not fields:
        raise ValueError(f"job {getattr(spec, 'name', spec)!r} has no window; it would fire ungated")
    out = {"name": f"limitless-{spec.name}", "schedule": POLL, "no_agent": True,
           "script": f"limitless-{spec.name}.sh", "deliver": "local"}
    out.update(fields)
    return out


_NUMBERS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
            "sixteen seventeen eighteen nineteen twenty twenty-one twenty-two twenty-three").split()


def stale_words(seconds: Any) -> str:
    """How long until a held occurrence is stale, in words, never a digit."""
    if seconds is None:
        return "never stale"
    hours = seconds / 3600
    if hours < 1:
        return "stale after under an hour"
    if hours >= 24:
        return "stale after over a day"
    whole = int(hours)
    word = f"{_NUMBERS[whole]} {'hour' if whole == 1 else 'hours'}"
    return f"stale after {word}" if whole == hours else f"stale after about {word}"


def plan_line(spec: Any) -> str:
    """One job in words: its host job name and title, the window it waits for and how long until stale; or why it
    is skipped."""
    p = job_spec(spec)
    head = f"limitless-{spec.name} ({spec.send_title})"
    if not p:
        return f"{head}: skipped, sends nothing"
    return f"{head}: window {p['window_class'].replace('_', ' ')}, {stale_words(p.get('stale_after_s'))}"


def plan_lines() -> list:
    return [plan_line(s) for s in all_specs()]


def payloads() -> list:
    """Every sending job's create_job keyword arguments, in all_specs order."""
    return [p for p in (job_spec(s) for s in all_specs()) if p]
