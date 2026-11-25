"""The Hermes cron job each plugin job would be, with its decision-window fields. Pure: it creates nothing.

A Hermes host with the cron decision-window gate (public fork kvnloo/hermes-agent, branch
up/cron-decision-window-gate-r2) stores ``window_class`` and ``stale_after_s`` on a recurring job. On that branch
neither ``hermes cron create`` nor the cronjob tool takes them; the Python job API does
(``cron.jobs.create_job(..., window_class=..., stale_after_s=...)``), and so does a job record in
``cron/jobs.json``. ``job_spec(spec)`` is therefore create_job's keyword arguments for one plugin job:

- ``name``: ``limitless-<job>``;
- ``prompt``: empty. create_job requires the argument; with ``no_agent`` the script is the whole job;
- ``schedule``: POLL, an interval. The cues are events (a wake, a wind-down); the interval only polls for them,
  it is never the time a message is meant for;
- ``no_agent`` + ``script``: the job runs a script, never an agent turn. ``script`` is a plain file name the
  operator puts in the host's scripts dir (``limitless-<job>.sh``), as the host wants it;
- ``deliver``: ``local``. The plugin's own send gate sends; the host never delivers the script's output;
- ``window_class`` / ``stale_after_s``: ``jobs.to_cron_fields(spec)``.

A job that sends nothing (the NOOP export and the ingests, SENDS_NOTHING) gets ``{}``: it has no message to hold
for a window, so it needs no gated host job; ``limitless-jobs --ingest`` runs it as before.

``script_body(spec)`` is the text of that ``limitless-<job>.sh``: a POSIX sh script that execs
``limitless-jobs --job <job> --send`` (``--send`` is the flag the systemd unit in docs/limitless-jobs-systemd.md
runs today) from the checkout ``$LIMITLESS_PLUGIN_DIR`` names. ``bin/limitless-cron-spec --scripts <dir>`` writes
one per sending job into the directory it is given; nothing here writes.

``diff_records(records, payloads)`` checks the host's job records (its cron jobs file) against these payloads,
one verdict in words per sending job, so a plugin update that changes a job's window or expiry shows up;
``bin/limitless-cron-spec --check <jobs file>`` prints them. It reads; it never writes or calls Hermes.
"""
import math
import re
from typing import Any, NamedTuple

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
    out = {"name": f"limitless-{spec.name}", "prompt": "", "schedule": POLL, "no_agent": True,
           "script": f"limitless-{spec.name}.sh", "deliver": "local"}
    out.update(fields)
    return out


def stale_words(seconds: Any) -> str:
    """How long until a held occurrence is stale, in words, never a digit: "stale after an hour".

    The span is jobs.span_words, the same words the schedule card's ``stale`` line uses, so the card and this
    plan cannot say one expiry two ways. Seconds round up to whole ones, as jobs.to_cron_fields stores them.
    """
    if seconds is None:
        return "never stale"
    return f"stale after {jobs.span_words(int(math.ceil(seconds)))}"


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


PLUGIN_DIR_ENV = "LIMITLESS_PLUGIN_DIR"    # the limitless checkout on the host; set in the host job's env
JOB_FLAGS = "--send"                      # the systemd unit's flags (docs/limitless-jobs-systemd.md), no new ones
_PLAIN = re.compile(r"[a-z][a-z_]*")
_SCRIPT = """#!/bin/sh
# limitless-{name}.sh: one pass of the limitless job {name} ({title}) for the host cron job limitless-{name}.
# Written by bin/limitless-cron-spec --scripts. The cron interval only polls for events; the plugin's own gates
# (decision window, quiet, send gate, --once key) decide whether anything is sent.
set -eu
if [ -z "${{{env}:-}}" ]; then
    echo "limitless-{name}.sh: set {env} to the limitless checkout" >&2
    exit 2
fi
exec "${{{env}}}/bin/limitless-jobs" --job {name} {flags}
"""


def script_body(spec: Any) -> str:
    """The text of the ``limitless-<job>.sh`` the host job for ``spec`` runs. Pure; a name that is not a plain
    lowercase word is a ValueError (it goes into a shell command)."""
    name = getattr(spec, "name", None)
    if not isinstance(name, str) or not _PLAIN.fullmatch(name):
        raise ValueError(f"job name {name!r} is not a plain word")
    title = re.sub(r"[^A-Za-z ?-]", "", str(getattr(spec, "send_title", "")))   # a comment line: words only
    return _SCRIPT.format(name=name, title=title, env=PLUGIN_DIR_ENV, flags=JOB_FLAGS)


def scripts() -> dict:
    """``{script file name: script_body}`` for every sending job, in all_specs order."""
    return {p["script"]: script_body(s) for s, p in ((s, job_spec(s)) for s in all_specs()) if p}


def payloads() -> list:
    """Every sending job's create_job keyword arguments, in all_specs order."""
    return [p for p in (job_spec(s) for s in all_specs()) if p]


# --- Checking a host's job records against the payloads -------------------------------------------------------
# The record shape is the fork's create_job (cron/jobs.py lines 1872-1921): ``name``, ``script``, ``no_agent``,
# ``schedule`` parsed to {"kind": "interval", "minutes": n, ...} (lines 787-788), ``enabled``, ``deliver``, and
# ``window_class`` / ``stale_after_s`` only when set (stale_after_s a float, cron/decision_window.py lines 72-84).
# The file is {"jobs": [...]} (cron/jobs.py line 1566); load_jobs also takes a bare list or an id-keyed map
# (lines 1407-1426). Pause markers besides ``enabled``: ``state`` "paused" and ``paused_at`` (lines 536-543).

PREFIX = "limitless-"


class Verdict(NamedTuple):
    """One host job in words: ``name`` (a host job name, or "record four" when the record has none) and ``words``
    ("ok", "missing", "differs: window and expiry", "unreadable", ...)."""
    name: str
    words: str

    @property
    def ok(self) -> bool:
        return self.words == "ok"


class _Unreadable(Exception):
    pass


def _poll_interval(value: Any) -> tuple:
    """A payload's ``every <n>m`` schedule as (kind, minutes): the part of the fork's parse_duration the payloads
    use (cron/jobs.py lines 681-690)."""
    m = re.fullmatch(r"every\s+(\d*)\s*(m|min|mins|minute|minutes|h|hr|hrs|hour|hours|d|day|days)",
                     str(value).strip().lower())
    if not m:
        return "unparsed", value
    return "interval", int(m.group(1) or 1) * {"m": 1, "h": 60, "d": 1440}[m.group(2)[0]]


def _stored_interval(value: Any) -> tuple:
    """A stored record's schedule as (kind, minutes): create_job stores it parsed, a dict (cron/jobs.py lines
    787-788, 1887); anything else is unreadable."""
    if not isinstance(value, dict) or not isinstance(value.get("kind"), str):
        raise _Unreadable
    minutes = value.get("minutes")
    if isinstance(minutes, bool) or (minutes is not None and not isinstance(minutes, int)):
        raise _Unreadable
    return value["kind"], minutes


def _text(value: Any) -> Any:
    if value is not None and not isinstance(value, str):
        raise _Unreadable
    return value


def _window(value: Any) -> Any:
    """As the host normalizes it (cron/decision_window.py lines 58-69): blank is none, else stripped lowercase."""
    value = _text(value)
    return None if value is None else (value.strip().lower() or None)


def _expiry(value: Any) -> Any:
    """As the host normalizes it (cron/decision_window.py lines 72-84): positive finite seconds, or none."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise _Unreadable
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        raise _Unreadable from None
    if not math.isfinite(seconds) or seconds <= 0:
        raise _Unreadable
    return seconds


# (key, how the host record is read, how the payload is read, the word for it); a missing key reads as None.
_FIELDS = (("schedule", _stored_interval, _poll_interval, "interval"), ("script", _text, _text, "script"),
           ("no_agent", bool, bool, "agent mode"), ("deliver", _text, _text, "delivery"),
           ("window_class", _window, _window, "window"), ("stale_after_s", _expiry, _expiry, "expiry"))


def _and(items: list) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _paused(record: dict) -> bool:
    return not record.get("enabled", True) or record.get("state") == "paused" or bool(record.get("paused_at"))


def _compare(record: dict, payload: dict) -> str:
    differs, unreadable = [], []
    for key, read, read_payload, word in _FIELDS:
        try:
            if read(record.get(key)) != read_payload(payload.get(key)):
                differs.append(word)
        except _Unreadable:
            unreadable.append(word)
    if unreadable:
        return "unreadable: " + _and(unreadable)
    paused = _paused(record)
    if differs:
        return "differs: " + _and(differs) + ("; paused on the host" if paused else "")
    return "paused on the host" if paused else "ok"


def records_in(data: Any) -> list:
    """The job records in a parsed jobs file, read as the host's load_jobs reads them (cron/jobs.py lines
    1407-1426): ``{"jobs": [...]}``, a bare list, or an id-keyed map (non-dict entries skipped). Entries are not
    checked here; diff_records says which are unreadable. Any other shape is a ValueError."""
    if isinstance(data, list):
        return list(data)
    if isinstance(data, dict):
        jobs_ = data.get("jobs", [])
        if isinstance(jobs_, list):
            return list(jobs_)
        if isinstance(jobs_, dict):
            return [{**v, "id": v.get("id") or k} for k, v in jobs_.items() if isinstance(v, dict)]
    raise ValueError("not a cron jobs file: expected {\"jobs\": [...]}")


def diff_records(records: Any, payloads: Any) -> list:
    """Each sending job's host record against its payload, in payload order, one Verdict each: "ok", "missing",
    "differs: <fields in words>", "paused on the host", "unreadable: <fields>" or "more than one host job with this
    name". Then each host record named ``limitless-...`` that no payload names ("not a plugin job any more"), then
    each record with no name to read ("unreadable"). Records of other jobs are left alone. Pure; never raises on
    a record, whatever its shape."""
    if records is None:
        records = []
    elif not isinstance(records, (list, tuple)):
        records = [records]
    named, unnamed = {}, []
    for i, rec in enumerate(records):
        name = rec.get("name") if isinstance(rec, dict) else None
        if isinstance(name, str) and name.strip():
            named.setdefault(name.strip(), []).append(rec)
        else:
            unnamed.append(f"record {jobs._number_words(i + 1)}")
    out, wanted = [], set()
    for p in payloads:
        wanted.add(p["name"])
        found = named.get(p["name"], [])
        if not found:
            words = "missing"
        elif len(found) > 1:
            words = "more than one host job with this name"
        else:
            try:
                words = _compare(found[0], p)
            except Exception:   # a record shape no reader expected: say so, never raise
                words = "unreadable"
        out.append(Verdict(p["name"], words))
    out += [Verdict(n, "not a plugin job any more") for n in named if n.startswith(PREFIX) and n not in wanted]
    out += [Verdict(n, "unreadable") for n in unnamed]
    return out


def check_lines(verdicts: list) -> list:
    """One line per Verdict: ``<name>: <words>``."""
    return [f"{v.name}: {v.words}" for v in verdicts]
