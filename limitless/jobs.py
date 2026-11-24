"""Event-triggered job specs: the wake brief, the post-nap message, the bedtime question, the habit check-in,
the week review, the break nudge; the NOOP export (NOOP_EXPORT), which sends nothing and wakes on a sync that
copied the NOOP database (noop_export_verdict); and the apps ingest (APPS_INGEST) and the ranked ingest
(RANKED_INGEST) and the sender ingest (SENDER_INGEST), which send nothing and wake on any new sync row
(apps_ingest_verdict, ranked_ingest_verdict, sender_ingest_verdict), and the FIT import (FIT_INGEST), which
reads a drop folder of CAROL bike FIT files on the same event (fit_ingest_verdict).

A job says which event wakes it (``trigger_event``), which decision window it speaks in
(``window_class``), how often it may speak per window and which event ends it. There are no
clock times and no cron strings here: a test fails if a spec grows one.

Everything is a pure function. Nothing in this module sends; delivery stays in ``bin/kevin-push``.
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Any, Mapping, NamedTuple, Optional, Tuple

from . import decision_window, habit_card, send_gate
from .decision_window import WINDOW_CLASSES
from .state_reader import parse_ts
from .window import MAX_AWAKE_H

# Events a job can wake on or end on. sleep_mode_on/off come from the phone; wake is a Sleep-mode
# off after a long on, or a screen-event wake when Sleep mode is not used (merged_events); habit_cue is
# HABIT_CUE_AFTER_S after a wake (merged_events) or comes from whatever automation marks it. long_block is a
# focus block in the activity data that ran as long as the person's usual long block (blocks.long_block_events).
# noop_copy is a sync run whose runs.jsonl row says it copied the NOOP database (noop_copied); only the NOOP export
# job (NOOP_EXPORT) wakes on it. sync is any sync run's runs.jsonl row that did not fail (sync_ran); only the apps
# ingest job (APPS_INGEST), the ranked ingest job (RANKED_INGEST) and the sender ingest job (SENDER_INGEST) wake on
# it, and so does the FIT import (FIT_INGEST). push_back is a push kevin-push
# delivered after an outage (outage_recap.outage: SEND_FAIL_RUN or more failed sends in a row); only the outage
# recap (OUTAGE_RECAP) wakes on it. sender_changed is the owner's "push via <profile>" reply setting the sender
# (push-sender.json's ``at``, newer than the last confirmation; sender_changed_verdict); only the sender
# confirmation (SENDER_CONFIRM) wakes on it.
EVENTS = ("wake", "sleep_mode_on", "sleep_mode_off", "wind_down", "habit_cue", "focus_end", "long_block", "noop_copy",
          "sync", "push_back", "sender_changed")
TRIGGER_AFTER = ("", "short_on")
NAP_MAX_S = 3 * 3600        # a Sleep-mode on shorter than this, then off, is a nap; longer is a night
SLEEP_MODE_CONFIDENCE = 0.9  # a wake from Sleep mode; a screen-event wake (wake_proxy) carries less
HABIT_CUE_AFTER_S = 3600     # the feeds-free-first-hour check-in asks once the first hour after a wake has passed
DELIVER, HOLD, DROP, NOT_TRIGGERED = "deliver", "hold", "drop", "not_triggered"
RUN = "run"                  # a job that sends nothing (the NOOP export) is due and runs; never a message
# What runs the three reply ingests (apps, ranked, sender) and the FIT import for real: the timer's --ingest pass,
# or a --send pass
INGEST_RUNS = "limitless-jobs --ingest or --send"
# What sends the one sender confirmation: the timer's pass with --confirm (it sends nothing else), or a --send pass
CONFIRM_RUNS = "limitless-jobs --ingest --confirm or --send"
ACTIONS = (DELIVER, HOLD, DROP, NOT_TRIGGERED, RUN)
_SLEEP = ("sleep_mode_on", "sleep_mode_off")
_WORDS = {"wake": "wake", "sleep_mode_on": "Sleep-mode on", "sleep_mode_off": "Sleep-mode off",
          "wind_down": "wind-down", "habit_cue": "habit cue", "focus_end": "focus-end", "nap": "nap",
          "long_block": "long focus block", "noop_copy": "NOOP copy", "sync": "sync", "push_back": "pushes back",
          "sender_changed": "sender change"}


@dataclass(frozen=True)
class JobSpec:
    name: str
    trigger_event: str
    window_class: str
    send_title: str
    max_per_window: int
    expires: str
    trigger_after: str = ""                  # "short_on": only a Sleep-mode off after a short on (a nap)
    answers: Tuple[str, ...] = ()            # 1-tap replies the message offers
    stale_after_s: Optional[float] = None    # a trigger older than this drops the job: a late message is noise
    focus_holds: bool = True                 # False: a running focus block (Glide) does not hold this job

    def __post_init__(self):
        if self.stale_after_s is not None and not self.stale_after_s > 0:
            raise ValueError(f"stale_after_s must be positive, got {self.stale_after_s!r}")
        if self.trigger_event not in EVENTS:
            raise ValueError(f"trigger_event must be one of {EVENTS}, got {self.trigger_event!r}")
        if self.expires not in EVENTS:
            raise ValueError(f"expires must be one of {EVENTS}, got {self.expires!r}")
        if self.window_class not in WINDOW_CLASSES:
            raise ValueError(f"window_class must be one of {WINDOW_CLASSES}, got {self.window_class!r}")
        if self.trigger_after not in TRIGGER_AFTER:
            raise ValueError(f"trigger_after must be one of {TRIGGER_AFTER}, got {self.trigger_after!r}")
        if not isinstance(self.max_per_window, int) or self.max_per_window < 1:
            raise ValueError(f"max_per_window must be a positive int, got {self.max_per_window!r}")


WAKE_STALE_S = 3 * 3600      # the wake brief removes the first decisions of the day; hours later it is noise
NAP_STALE_S = 3600           # "back from nap" only makes sense right after the nap
MIQ_STALE_S = 3 * 3600       # the bedtime question belongs to this wind-down, not a later one
HABIT_STALE_S = 3 * 3600     # the check-in asks about the first hour; much later the answer is a guess
WAKE_BRIEF = JobSpec("wake_brief", "wake", "anytime", "Wake-up brief", 1, "sleep_mode_on",
                     stale_after_s=WAKE_STALE_S)
NAP = JobSpec("nap", "sleep_mode_off", "anytime", "Back from nap", 1, "sleep_mode_on", trigger_after="short_on",
              stale_after_s=NAP_STALE_S)
MIQ = JobSpec("miq", "wind_down", "wind_down", "MIQ for tonight?", 1, "sleep_mode_on", stale_after_s=MIQ_STALE_S)
HABIT_CHECKIN = JobSpec("habit_checkin", "habit_cue", "anytime", "Habit check-in", 1, "sleep_mode_on",
                        answers=("Done", "No", "Skip"), stale_after_s=HABIT_STALE_S)
DECISIONS = ("Keep", "Drop")
WEEK_REVIEW = JobSpec("week_review", "habit_cue", "anytime", "Week review", 1, "sleep_mode_on",
                      answers=DECISIONS, stale_after_s=HABIT_STALE_S)
# The break nudge: one soft message per long focus block. A running Glide block does not hold it (ending the
# block is the point); Sleep mode, quiet and the daily cap still do. A trigger this old is missing data.
BREAK_STALE_S = 6 * 3600
BREAK_JUST_ENDED_S = 3600    # a block that ended longer ago than this is history: the nudge drops
BLOCK_GAP_S = 600.0          # blocks.GAP_S (not imported: blocks -> flow_week -> feeds_evidence -> jobs)
BREAK_NUDGE = JobSpec("break_nudge", "long_block", "anytime", "Long focus block", 1, "sleep_mode_on",
                      stale_after_s=BREAK_STALE_S, focus_holds=False)
SPECS = {s.name: s for s in (WAKE_BRIEF, NAP, MIQ, HABIT_CHECKIN, WEEK_REVIEW, BREAK_NUDGE)}
# The NOOP export sends nothing: it reads the NOOP copy and writes the sleep files (noop_export.main), so it is
# not in SPECS (the message jobs) and no decision window, quiet or send gate holds it: it also runs while asleep.
NOOP_EXPORT = JobSpec("noop_export", "noop_copy", "anytime", "NOOP export", 1, "noop_copy")
NOOP_CONFIG = "noop_export"
NOOP_OFF, NOOP_DRY_RUN, NOOP_WRITE = "off", "dry_run", "write"
NOOP_MODES = (NOOP_OFF, NOOP_DRY_RUN, NOOP_WRITE)
NOOP_COPIED = ("copied", "fresh")    # how a runs.jsonl row's ``noop`` field says this sync copied the NOOP DB
NOOP_IS_OFF = f"off (config {NOOP_CONFIG})"


def noop_mode(cfg: Any) -> str:
    """Config ``noop_export``: off (the default, and for any value that is not one of NOOP_MODES), dry_run or
    write."""
    v = cfg.get(NOOP_CONFIG) if isinstance(cfg, Mapping) else None
    v = v.strip().lower() if isinstance(v, str) else v
    return v if v in NOOP_MODES else NOOP_OFF


def noop_copied(row: Any) -> bool:
    """True for a runs.jsonl row of a sync that copied the NOOP database: a time in ``at``, ``ok`` not false (a
    failed run's copy may be torn) and ``noop`` true, "copied" or "fresh", or an object with ``copied`` (or
    ``fresh``) true. Anything else (no field, false, a digest-style ``{"available": ...}``) is no copy."""
    if not isinstance(row, dict) or row.get("ok") is False or parse_ts(row.get("at")) is None:
        return False
    v = row.get("noop")
    if v is True:
        return True
    if isinstance(v, str):
        return v.strip().lower() in NOOP_COPIED
    return isinstance(v, dict) and any(v.get(k) is True for k in NOOP_COPIED)


def noop_export_verdict(mode: str, last_run: Any, mark_at: Optional[float], now: float) -> Verdict:
    """Run, drop or not triggered for the NOOP export. Pure: reads its inputs, runs and writes nothing.

    Due (RUN) only when ``mode`` is dry_run or write, the newest runs.jsonl row (``last_run``) says the NOOP
    database was freshly copied (noop_copied), it is not after ``now``, and it is newer than ``mark_at`` (the
    row the last export acted on, from noop-export.json). The same row again is a drop: once per copy.
    """
    if mode not in (NOOP_DRY_RUN, NOOP_WRITE):
        return Verdict(NOT_TRIGGERED, NOOP_IS_OFF)
    t = parse_ts(last_run.get("at")) if isinstance(last_run, dict) else None
    if t is None:
        return Verdict(NOT_TRIGGERED, "no sync run yet")
    if not noop_copied(last_run):
        return Verdict(NOT_TRIGGERED, "the last sync run did not copy the NOOP database")
    if t > now:
        return Verdict(NOT_TRIGGERED, "the last sync run is timestamped in the future")
    if mark_at is not None and t <= mark_at:
        return Verdict(DROP, "already ran after this sync of the NOOP database", t)
    return Verdict(RUN, "a sync copied the NOOP database", t)


# The apps ingest sends nothing: it reads the person's "work apps: ..." / "feed apps: ..." reply from the Hermes
# session DB and, in write mode, writes apps.json (apps_reply.ingest). Like the NOOP export it is not in SPECS and
# no window holds it. It wakes on any new sync row, never on a clock time.
APPS_INGEST = JobSpec("apps_ingest", "sync", "anytime", "Apps ingest", 1, "sync")
APPS_CONFIG = "apps_ingest"
APPS_OFF, APPS_DRY_RUN, APPS_WRITE = NOOP_OFF, NOOP_DRY_RUN, NOOP_WRITE
APPS_MODES = (APPS_OFF, APPS_DRY_RUN, APPS_WRITE)
APPS_IS_OFF = f"off (config {APPS_CONFIG})"
APPS_NO_DB = "skipped: no Hermes DB set (config hermes_db)"
APPS_LINE = "app lists set from your reply"   # the one T1 line after a write; a later wake brief may use it


def apps_mode(cfg: Any) -> str:
    """Config ``apps_ingest``: off (the default, and for any value that is not one of APPS_MODES), dry_run or
    write."""
    v = cfg.get(APPS_CONFIG) if isinstance(cfg, Mapping) else None
    v = v.strip().lower() if isinstance(v, str) else v
    return v if v in APPS_MODES else APPS_OFF


def sync_ran(row: Any) -> bool:
    """True for a runs.jsonl row of a sync run: a time in ``at`` and ``ok`` not false. What it copied does not
    matter."""
    return isinstance(row, dict) and row.get("ok") is not False and parse_ts(row.get("at")) is not None


def apps_ingest_verdict(mode: str, last_run: Any, mark_at: Optional[float], now: float,
                        db_set: bool = True) -> Verdict:
    """Run, drop or not triggered for the apps ingest. Pure: reads its inputs, runs and writes nothing.

    Due (RUN) only when ``mode`` is dry_run or write, a Hermes DB is set (``db_set``; else skipped, APPS_NO_DB), the
    newest runs.jsonl row (``last_run``) is a sync that did not fail (sync_ran), it is not after ``now``, and it is
    newer than ``mark_at`` (the row the last ingest acted on, from apps-ingest.json). The same row again is a drop.
    """
    if mode not in (APPS_DRY_RUN, APPS_WRITE):
        return Verdict(NOT_TRIGGERED, APPS_IS_OFF)
    if not db_set:
        return Verdict(NOT_TRIGGERED, APPS_NO_DB)
    t = parse_ts(last_run.get("at")) if isinstance(last_run, dict) else None
    if t is None:
        return Verdict(NOT_TRIGGERED, "no sync run yet")
    if not sync_ran(last_run):
        return Verdict(NOT_TRIGGERED, "the last sync run did not finish ok")
    if t > now:
        return Verdict(NOT_TRIGGERED, "the last sync run is timestamped in the future")
    if mark_at is not None and t <= mark_at:
        return Verdict(DROP, "already ran after this sync", t)
    return Verdict(RUN, "a sync ran", t)


# The ranked ingest sends nothing: it reads the owner's "drop: <id>[, <id>...]" replies from the Hermes session DB
# and runs ranked_ledger.ingest (write mode appends owner drop rows to the ranked ledger and moves ranked-drops.json).
# Like the apps ingest it is not in SPECS, no window holds it, and it wakes on any new sync row, never on a clock time.
RANKED_INGEST = JobSpec("ranked_ingest", "sync", "anytime", "Ranked ingest", 1, "sync")
RANKED_CONFIG = "ranked_ingest"
RANKED_OFF, RANKED_DRY_RUN, RANKED_WRITE = NOOP_OFF, NOOP_DRY_RUN, NOOP_WRITE
RANKED_MODES = (RANKED_OFF, RANKED_DRY_RUN, RANKED_WRITE)
RANKED_IS_OFF = f"off (config {RANKED_CONFIG})"
RANKED_NO_LEDGER = "skipped: no ranked ledger set (LIMITLESS_RANKED_LEDGER or config ranked_ledger)"


def ranked_mode(cfg: Any) -> str:
    """Config ``ranked_ingest``: off (the default, and for any value that is not one of RANKED_MODES), dry_run or
    write."""
    v = cfg.get(RANKED_CONFIG) if isinstance(cfg, Mapping) else None
    v = v.strip().lower() if isinstance(v, str) else v
    return v if v in RANKED_MODES else RANKED_OFF


def ranked_ingest_verdict(mode: str, last_run: Any, mark_at: Optional[float], now: float,
                          db_set: bool = True, ledger_set: bool = True) -> Verdict:
    """Run, drop or not triggered for the ranked ingest. Pure: reads its inputs, runs and writes nothing.

    Off unless ``mode`` is dry_run or write; skipped (RANKED_NO_LEDGER) with no ranked ledger set; then exactly the
    apps ingest's rule (apps_ingest_verdict): a Hermes DB set, the newest runs.jsonl row a sync that did not fail,
    not after ``now`` and newer than ``mark_at`` (the row the last pass acted on, from ranked-ingest.json). The same
    row again is a drop: at most once per sync row.
    """
    if mode not in (RANKED_DRY_RUN, RANKED_WRITE):
        return Verdict(NOT_TRIGGERED, RANKED_IS_OFF)
    if not ledger_set:
        return Verdict(NOT_TRIGGERED, RANKED_NO_LEDGER)
    return apps_ingest_verdict(mode, last_run, mark_at, now, db_set=db_set)


# The sender ingest sends nothing: it reads the owner's whole "push via <profile>" reply from the Hermes session DB
# and runs sender_reply.ingest (write mode writes push-sender.json, which kevin-push's sender resolution reads, only
# for a profile that exists and is not known to lack a Telegram bot or chat). Like the apps ingest it is not in
# SPECS, no window holds it, and it wakes on any new sync row, never on a clock time.
SENDER_INGEST = JobSpec("sender_ingest", "sync", "anytime", "Sender ingest", 1, "sync")
SENDER_CONFIG = "sender_ingest"
SENDER_OFF, SENDER_DRY_RUN, SENDER_WRITE = NOOP_OFF, NOOP_DRY_RUN, NOOP_WRITE
SENDER_MODES = (SENDER_OFF, SENDER_DRY_RUN, SENDER_WRITE)
SENDER_IS_OFF = f"off (config {SENDER_CONFIG})"


def sender_mode(cfg: Any) -> str:
    """Config ``sender_ingest``: off (the default, and for any value that is not one of SENDER_MODES), dry_run or
    write."""
    v = cfg.get(SENDER_CONFIG) if isinstance(cfg, Mapping) else None
    v = v.strip().lower() if isinstance(v, str) else v
    return v if v in SENDER_MODES else SENDER_OFF


def sender_ingest_verdict(mode: str, last_run: Any, mark_at: Optional[float], now: float,
                          db_set: bool = True) -> Verdict:
    """Run, drop or not triggered for the sender ingest: off unless ``mode`` is dry_run or write, then exactly the
    apps ingest's rule (apps_ingest_verdict): a Hermes DB set, the newest runs.jsonl row a sync that did not fail,
    not after ``now`` and newer than ``mark_at`` (the row the last pass acted on, from push-sender-ingest.json).
    The same row again is a drop: at most once per sync row. Pure."""
    if mode not in (SENDER_DRY_RUN, SENDER_WRITE):
        return Verdict(NOT_TRIGGERED, SENDER_IS_OFF)
    return apps_ingest_verdict(mode, last_run, mark_at, now, db_set=db_set)


# The FIT import sends nothing: it reads the CAROL bike FIT files dropped in one folder (config ``fit_drop_dir``)
# and runs fit_ride.run over them (write mode appends the new rides to the rides file; fit_ingest_job). Like the
# apps ingest it is not in SPECS, no window holds it, and it wakes on any new sync row, never on a clock time.
FIT_INGEST = JobSpec("fit_ingest", "sync", "anytime", "FIT import", 1, "sync")
FIT_CONFIG = "fit_ingest"
FIT_DIR_CONFIG = "fit_drop_dir"
FIT_OFF, FIT_DRY_RUN, FIT_WRITE = NOOP_OFF, NOOP_DRY_RUN, NOOP_WRITE
FIT_MODES = (FIT_OFF, FIT_DRY_RUN, FIT_WRITE)
FIT_IS_OFF = f"off (config {FIT_CONFIG})"
FIT_NO_DIR = f"skipped: no drop folder set (config {FIT_DIR_CONFIG})"
FIT_DIR_MISSING = "skipped: the drop folder does not exist"


def fit_mode(cfg: Any) -> str:
    """Config ``fit_ingest``: off (the default, and for any value that is not one of FIT_MODES), dry_run or
    write."""
    v = cfg.get(FIT_CONFIG) if isinstance(cfg, Mapping) else None
    v = v.strip().lower() if isinstance(v, str) else v
    return v if v in FIT_MODES else FIT_OFF


def fit_ingest_verdict(mode: str, last_run: Any, mark_at: Optional[float], now: float,
                       dir_set: bool = True, dir_exists: bool = True) -> Verdict:
    """Run, drop or not triggered for the FIT import: off unless ``mode`` is dry_run or write; skipped with no drop
    folder set (FIT_NO_DIR) or one that does not exist (FIT_DIR_MISSING); then exactly the apps ingest's rule
    (apps_ingest_verdict, no Hermes DB needed): the newest runs.jsonl row a sync that did not fail, not after
    ``now`` and newer than ``mark_at`` (the row the last pass acted on, from fit-ingest.json). The same row again
    is a drop: at most once per sync row. Pure."""
    if mode not in (FIT_DRY_RUN, FIT_WRITE):
        return Verdict(NOT_TRIGGERED, FIT_IS_OFF)
    if not dir_set:
        return Verdict(NOT_TRIGGERED, FIT_NO_DIR)
    if not dir_exists:
        return Verdict(NOT_TRIGGERED, FIT_DIR_MISSING)
    return apps_ingest_verdict(mode, last_run, mark_at, now, db_set=True)


# The outage recap: one plain message after phone pushes start reaching the person again, naming in words what an
# outage swallowed (outage_recap.recap). Its event is push_back (a delivery that closed an outage), never a clock.
# It is not in SPECS: should_fire's windows do not hold it (the delivery that woke it shows the person can be
# reached), but it still goes through kevin-push's send gate (--once, quiet, Sleep mode, daily cap).
# outage_recap_job runs it; config ``outage_recap`` is off (default), dry_run or write.
OUTAGE_RECAP_STALE_S = 12 * 3600   # pushes came back longer ago than this: a late recap is noise
OUTAGE_RECAP = JobSpec("outage_recap", "push_back", "anytime", "Pushes are back", 1, "push_back",
                       answers=("OK", "More"), stale_after_s=OUTAGE_RECAP_STALE_S)
OUTAGE_RECAP_CONFIG = "outage_recap"
OUTAGE_RECAP_OFF, OUTAGE_RECAP_DRY_RUN, OUTAGE_RECAP_WRITE = NOOP_OFF, NOOP_DRY_RUN, NOOP_WRITE
OUTAGE_RECAP_MODES = (OUTAGE_RECAP_OFF, OUTAGE_RECAP_DRY_RUN, OUTAGE_RECAP_WRITE)


def outage_recap_mode(cfg: Any) -> str:
    """Config ``outage_recap``: off (the default, and for any value that is not one of OUTAGE_RECAP_MODES),
    dry_run or write."""
    v = cfg.get(OUTAGE_RECAP_CONFIG) if isinstance(cfg, Mapping) else None
    v = v.strip().lower() if isinstance(v, str) else v
    return v if v in OUTAGE_RECAP_MODES else OUTAGE_RECAP_OFF


# The sender confirmation: one short plain message right after the owner's whole "push via <profile>" reply set the
# sender (sender_reply writes push-sender.json), so a broken new sender shows up at once instead of at some later
# push. Its event is sender_changed (push-sender.json's ``at`` newer than the last confirmation the mark
# sender-confirm.json settled), never a clock. Like the outage recap it is not in SPECS, but it goes through
# kevin-push's send gate (--once, quiet, Sleep mode, daily cap). sender_confirm_job runs it; config
# ``sender_confirm`` is off (default), dry_run or write.
SENDER_CONFIRM_STALE_S = 12 * 3600   # the sender changed longer ago than this: a late confirmation is noise
SENDER_CONFIRM = JobSpec("sender_confirm", "sender_changed", "anytime", "Pushes", 1, "sender_changed",
                         stale_after_s=SENDER_CONFIRM_STALE_S)
SENDER_CONFIRM_CONFIG = "sender_confirm"
SENDER_CONFIRM_OFF, SENDER_CONFIRM_DRY_RUN, SENDER_CONFIRM_WRITE = NOOP_OFF, NOOP_DRY_RUN, NOOP_WRITE
SENDER_CONFIRM_MODES = (SENDER_CONFIRM_OFF, SENDER_CONFIRM_DRY_RUN, SENDER_CONFIRM_WRITE)
SENDER_CONFIRM_IS_OFF = f"off (config {SENDER_CONFIRM_CONFIG})"
SENDER_CHANGED = "your reply changed the sender for your phone pushes"
SENDER_NO_REPLY = "no reply has set the sender"
SENDER_SETTLED = "this sender change was already confirmed"


def sender_confirm_mode(cfg: Any) -> str:
    """Config ``sender_confirm``: off (the default, and for any value that is not one of SENDER_CONFIRM_MODES),
    dry_run or write."""
    v = cfg.get(SENDER_CONFIRM_CONFIG) if isinstance(cfg, Mapping) else None
    v = v.strip().lower() if isinstance(v, str) else v
    return v if v in SENDER_CONFIRM_MODES else SENDER_CONFIRM_OFF


def sender_changed_verdict(mode: str, reply_at: Optional[float], settled_at: Optional[float],
                           now: float) -> Verdict:
    """Deliver, drop or not triggered for the sender confirmation. Pure: reads its inputs, sends nothing.

    Due (DELIVER, trigger_at the reply's epoch) only when ``mode`` is dry_run or write, push-sender.json names a
    sender with an epoch (``reply_at``, push_sender.reply_at), it is not after ``now``, it is newer than
    ``settled_at`` (the reply the mark last settled: told or dropped) and not older than SENDER_CONFIRM_STALE_S.
    The same reply again is a drop: one confirmation per sender change. Reasons are words, never a digit.
    """
    if mode not in (SENDER_CONFIRM_DRY_RUN, SENDER_CONFIRM_WRITE):
        return Verdict(NOT_TRIGGERED, SENDER_CONFIRM_IS_OFF)
    if reply_at is None:
        return Verdict(NOT_TRIGGERED, SENDER_NO_REPLY)
    if reply_at > now:
        return Verdict(NOT_TRIGGERED, "the sender reply is timestamped in the future")
    if settled_at is not None and reply_at <= settled_at:
        return Verdict(DROP, SENDER_SETTLED, reply_at)
    if now - reply_at > SENDER_CONFIRM_STALE_S:
        return Verdict(DROP, "too late: the sender changed a while ago; a late confirmation is noise", reply_at)
    return Verdict(DELIVER, SENDER_CHANGED, reply_at)


def wake_brief(decision: bool = False) -> JobSpec:
    """The wake brief speaks in a peak window only when it carries a decision; else anytime."""
    return JobSpec(WAKE_BRIEF.name, "wake", "peak", WAKE_BRIEF.send_title, 1, "sleep_mode_on",
                   stale_after_s=WAKE_BRIEF.stale_after_s) if decision \
        else WAKE_BRIEF


def habit_checkin(habit: Optional[dict]) -> JobSpec:
    """The check-in for this week's habit; its cue is habit.json's ``cue`` when that names an event."""
    cue = (habit or {}).get("cue") if isinstance(habit, dict) else None
    if cue in EVENTS and cue != HABIT_CHECKIN.trigger_event:
        return JobSpec(HABIT_CHECKIN.name, cue, "anytime", HABIT_CHECKIN.send_title, 1, "sleep_mode_on",
                       answers=HABIT_CHECKIN.answers, stale_after_s=HABIT_CHECKIN.stale_after_s)
    return HABIT_CHECKIN


def week_review(habit: Optional[dict]) -> JobSpec:
    """The week review wakes on this week's habit cue, the same event as its check-in (habit_checkin)."""
    cue = habit_checkin(habit).trigger_event
    if cue != WEEK_REVIEW.trigger_event:
        return JobSpec(WEEK_REVIEW.name, cue, "anytime", WEEK_REVIEW.send_title, 1, "sleep_mode_on",
                       answers=WEEK_REVIEW.answers, stale_after_s=WEEK_REVIEW.stale_after_s)
    return WEEK_REVIEW


class Verdict(NamedTuple):
    action: str                        # deliver | hold | drop | not_triggered
    reason: str                        # one line; a held or dropped job shows it in the run log
    trigger_at: Optional[float] = None


HABIT_WEEK_DAYS = 7
NO_WEEK = "no habit week started"


def _week_start(habit: Optional[dict]) -> Optional[date]:
    """The week_of date of a habit.json that names a habit; None when either is missing or invalid."""
    h = habit if isinstance(habit, dict) else {}
    name = h.get("habit")
    try:
        start = date.fromisoformat(str(h.get("week_of")))
    except ValueError:
        return None
    return start if isinstance(name, str) and name.strip() else None


def habit_decision(habit: Optional[dict]) -> Optional[str]:
    """Keep | Drop when habit.json records the week's decision; None (undecided) for anything else."""
    v = habit.get("decision") if isinstance(habit, dict) else None
    if isinstance(v, str):
        for d in DECISIONS:
            if v.strip().lower() == d.lower():
                return d
    return None


def habit_week_gate(habit: Optional[dict], today: date) -> Optional[Verdict]:
    """None inside a started habit week, else the check-in's drop verdict.

    Started: habit.json names a habit and its ``week_of`` is today or up to six days back (days one to
    seven). No habit, no valid week_of or a week_of after today: "no habit week started". From day
    eight on: "habit week over", so the check-in never runs past its week without a new start. A week
    with a Keep or Drop decision (the reply to its week review) is finished: "habit week closed".
    """
    start = _week_start(habit)
    if start is None or start > today:
        return Verdict(DROP, NO_WEEK)
    if today >= start + timedelta(days=HABIT_WEEK_DAYS):
        return Verdict(DROP, "habit week over")
    if habit_decision(habit) is not None:
        return Verdict(DROP, "habit week closed")
    return None


def review_day(habit: Optional[dict]) -> Optional[date]:
    """Day seven of the started week (week_of plus six days); None when no week is named."""
    start = _week_start(habit)
    return None if start is None else start + timedelta(days=HABIT_WEEK_DAYS - 1)


def week_review_gate(habit: Optional[dict], cue_day: Optional[date], reviewed: Any = ()) -> Optional[Verdict]:
    """None when a habit cue on ``cue_day`` may send the week review, else its verdict.

    ``cue_day`` is the local date of the latest cue event; ``reviewed`` the local dates of week reviews
    already sent. No started week (or one that starts after the cue): drop. A Keep or Drop already
    recorded: drop. A cue before day seven: not triggered. A review already sent on or after this
    week's day seven: drop, so the review goes out once per week, on the first cue from day seven on.
    """
    start, day7 = _week_start(habit), review_day(habit)
    if start is None or cue_day is None or start > cue_day:
        return Verdict(DROP, NO_WEEK)
    if habit_decision(habit) is not None:
        return Verdict(DROP, "this week already has a decision")
    if cue_day < day7:
        return Verdict(NOT_TRIGGERED, "no habit cue on or after day seven yet")
    if any(isinstance(d, date) and d >= day7 for d in reviewed or ()):
        return Verdict(DROP, "this week's review was already sent")
    return None


def events_from_sleepmode(rows: list) -> list:
    """sleepmode.jsonl rows ({"at", "on"}) as events ({"event": "sleep_mode_on" | "sleep_mode_off", "at"})."""
    out = []
    for r in rows:
        at = parse_ts((r or {}).get("at")) if isinstance(r, dict) else None
        if at is not None:
            out.append({"event": "sleep_mode_on" if r.get("on") else "sleep_mode_off", "at": at})
    return sorted(out, key=lambda e: e["at"])


def _sleep_spans(sleep_events: list) -> list:
    """(on_at, off_at) for each Sleep-mode on followed by an off, oldest first."""
    evs = sorted((parse_ts(e.get("at")), e.get("event")) for e in sleep_events or ()
                 if isinstance(e, dict) and e.get("event") in _SLEEP and parse_ts(e.get("at")) is not None)
    spans, on = [], None
    for t, name in evs:
        if name == "sleep_mode_on":
            on = t if on is None else on
        elif on is not None:
            spans.append((on, t))
            on = None
    return spans


def merged_events(sleep_events: list, screen_events: list) -> list:
    """Sleep-mode events, the screen-event wakes they do not cover, and a habit_cue after each wake.

    A screen wake (wake_proxy.events_from_screen) covers the quiet gap from its ``gap_from`` to its
    ``at``. When a Sleep-mode on/off overlaps that gap, Sleep mode wins: a long on is the wake (found by
    should_fire from the on/off pair, as before) and a short on is a nap, which stays Sleep-mode only.
    Otherwise the screen wake is used. Each wake, from either source, adds a ``habit_cue`` event
    HABIT_CUE_AFTER_S later (a duration from the event). Inputs are not changed; output is sorted.
    """
    sleep = [dict(e) for e in sleep_events or () if isinstance(e, dict) and e.get("event") in _SLEEP]
    spans = _sleep_spans(sleep)
    out = list(sleep)
    wake_from = [(off, "sleep_mode", SLEEP_MODE_CONFIDENCE) for on, off in spans if off - on >= NAP_MAX_S]
    for e in screen_events or ():
        t = parse_ts(e.get("at")) if isinstance(e, dict) and e.get("event") == "wake" else None
        if t is None:
            continue
        g = parse_ts(e.get("gap_from"))
        g = t if g is None else g
        if any(on < t and off > g for on, off in spans):
            continue
        out.append(dict(e, at=t))
        wake_from.append((t, e.get("source", "screen"), e.get("confidence")))
    for t, source, conf in wake_from:
        out.append({"event": "habit_cue", "at": t + HABIT_CUE_AFTER_S, "source": source, "confidence": conf})
    return sorted(out, key=lambda e: parse_ts(e["at"]))


def _past(events: list, now: float) -> list:
    out = []
    for e in events or ():
        at = parse_ts(e.get("at")) if isinstance(e, dict) else None
        if at is not None and at <= now and e.get("event") in EVENTS:
            out.append((at, e["event"]))
    return sorted(out)


def _triggers(spec: JobSpec, evs: list) -> list:
    """Times of the events that wake this job. A Sleep-mode off counts by the length of the on before it."""
    hits, last_sleep = [], None
    for at, name in evs:
        if name in _SLEEP:
            prev, last_sleep = last_sleep, (at, name)
            if name == "sleep_mode_off" and prev is not None and prev[1] == "sleep_mode_on":
                short = at - prev[0] < NAP_MAX_S
                if spec.trigger_event == "wake" and not short:
                    hits.append(at)
                elif spec.trigger_event == "sleep_mode_off" and (short or spec.trigger_after != "short_on"):
                    hits.append(at)
            continue
        if name == spec.trigger_event:
            hits.append(at)
    return hits


def wake_times(events: list, now: float) -> list:
    """Times of the wake events at or before ``now`` (a long Sleep-mode on then off, or a ``wake``), oldest first."""
    return _triggers(WAKE_BRIEF, _past(events, now))


def _label(spec: JobSpec) -> str:
    return "nap" if spec.trigger_after == "short_on" else _WORDS[spec.trigger_event]


def _window(state: Any):
    """(WindowState | None, asleep) from a decision_window.WindowState or a window.py envelope."""
    if state is None:
        return None, False
    if isinstance(state, dict):
        cls = state.get("cls", state.get("value"))
        if cls == "asleep":
            return None, True
        try:
            conf = float(state.get("confidence", 1.0))
        except (TypeError, ValueError):
            conf = 0.0
        return decision_window.WindowState(cls=cls if isinstance(cls, str) else decision_window.UNKNOWN,
                                           since=state.get("since"), source="window", confidence=conf), False
    if getattr(state, "cls", None) == "asleep":
        return None, True
    return state, False


def _dedupe_body(spec: JobSpec, trigger_at: float) -> str:
    return f"{spec.name} after {spec.trigger_event} {trigger_at:.0f}"


def dedupe_key(spec: JobSpec, trigger_at: float) -> str:
    """The send gate's key for this job's message about one trigger event."""
    return send_gate.key(spec.send_title, _dedupe_body(spec, trigger_at))


def sent_entry(spec: JobSpec, trigger_at: float, now: float) -> dict:
    """The sent-log record a caller appends after a real delivery (send gate shape plus the job name)."""
    return {"t": now, "k": dedupe_key(spec, trigger_at), "job": spec.name}


def _times(n: int) -> str:
    return {1: "once", 2: "twice"}.get(n, f"{n} times")


def should_fire(spec: JobSpec, events: list, window_state: Any, sent_log: list, now: float) -> Verdict:
    """Deliver, hold, drop, or not triggered, with a one-line reason. Pure: reads its inputs, sends nothing.

    Order: the latest trigger event; expiry; a trigger too old to trust; the per-window limit;
    decision_window.decide (asleep, class, peak budget); the send gate's 12 h dedupe and daily cap.
    A hold is not a send: nothing is counted until the caller delivers and appends sent_entry().
    """
    label = _label(spec)
    evs = _past(events, now)
    hits = _triggers(spec, evs)
    if not hits:
        return Verdict(NOT_TRIGGERED, f"no {label} event yet")
    trig = hits[-1]
    if any(trig < at and name == spec.expires for at, name in evs):
        return Verdict(DROP, f"expired: {_WORDS[spec.expires]} after the {label} event", trig)
    age_h = (now - trig) / 3600
    if age_h > MAX_AWAKE_H:
        return Verdict(DROP, f"the {label} event is {age_h:.0f} h old: missing data, not a long day", trig)
    if spec.stale_after_s is not None and now - trig > spec.stale_after_s:
        return Verdict(DROP, f"too late: the {label} event is {age_h:.1f} h old; a late message is noise", trig)
    sent = [s for s in (sent_log or ()) if isinstance(s, dict) and isinstance(s.get("t"), (int, float))]
    count = sum(1 for s in sent if s.get("job") == spec.name and trig <= s["t"] <= now)
    if count >= spec.max_per_window:
        return Verdict(DROP, f"already spoke {_times(count)} since the {label} event", trig)
    state, asleep = _window(window_state)
    if not spec.focus_holds and state is not None and state.hold_asks:
        state = replace(state, hold_asks=False)      # this job is about the block itself: it never waits for it
    w = decision_window.decide(spec.window_class, state, budget_left=spec.max_per_window - count, asleep=asleep)
    if w.action != decision_window.DELIVER:
        return Verdict(w.action, w.reason, trig)
    gate = send_gate.decide("limitless", spec.send_title, _dedupe_body(spec, trig), "decision", now, sent, False)
    if gate == "duplicate":
        return Verdict(DROP, "the send gate sent this same message within 12 h", trig)
    if gate == "cap":
        return Verdict(HOLD, f"the send gate's daily cap of {send_gate.DAILY_CAP} is reached", trig)
    if gate != "send":
        return Verdict(HOLD, f"the send gate says {gate}", trig)
    return Verdict(DELIVER, f"{label} event; {w.reason}", trig)


def _block_event(evs: list, trigger_at: Optional[float]) -> Optional[dict]:
    for e in evs or ():
        if isinstance(e, dict) and e.get("event") == "long_block" and parse_ts(e.get("at")) == trigger_at:
            return e
    return None


def _num(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def block_start(evs: list, trigger_at: float) -> float:
    """The start of the block a long_block trigger is about (its ``block_start``); a long_block row with
    none (e.g. from events.jsonl) is its own time."""
    e = _block_event(evs, trigger_at)
    s = _num(e.get("block_start")) if e is not None else None
    return trigger_at if s is None else s


def break_verdict(v: Verdict, evs: list, now: float, gap_s: float = BLOCK_GAP_S) -> Verdict:
    """should_fire's verdict for the break nudge, narrowed by the block it is about.

    Only a deliver changes. A block whose last work row is ``gap_s`` or more before ``now`` has ended: within
    BREAK_JUST_ENDED_S it "just ended" and delivers; later it drops (a late message is noise). A block still
    going delivers as having "run past its usual length". The reason stays digit-free: it is the Why-now line.
    """
    if v.action != DELIVER or v.trigger_at is None:
        return v
    e = _block_event(evs, v.trigger_at) or {}
    end = _num(e.get("block_end"))
    end = v.trigger_at if end is None else end
    rest = v.reason.split("; ", 1)[1] if "; " in v.reason else v.reason
    if now - end >= gap_s:
        if now - end > BREAK_JUST_ENDED_S:
            return Verdict(DROP, "too late: the long focus block ended a while ago; a late message is noise",
                           v.trigger_at)
        return Verdict(DELIVER, f"a long focus block just ended; {rest}", v.trigger_at)
    return Verdict(DELIVER, f"your focus block has run past its usual length; {rest}", v.trigger_at)


_SPEAKS = {"wake": "when you wake up", "sleep_mode_on": "when Sleep mode goes on",
           "sleep_mode_off": "when Sleep mode goes off", "wind_down": "when your wind-down starts",
           "habit_cue": "at your habit's cue", "focus_end": "when a focus block ends",
           "long_block": "when a focus block runs long",
           "noop_copy": "after a sync that copied the NOOP database", "sync": "after each sync run",
           "push_back": "when a push reaches you again after pushes stopped getting through",
           "sender_changed": "right after your reply changes the sender for your pushes"}
_IN_WINDOW = {"peak": "in a peak window, at most one decision per window",
              "trough": "in a low-energy window, for a review or an easy read",
              "wind_down": "once your wind-down has started", "anytime": "any time you are awake"}
_ENDS = {"wake": "when you next wake up", "sleep_mode_on": "when Sleep mode goes on",
         "sleep_mode_off": "when Sleep mode goes off", "wind_down": "when your wind-down starts",
         "habit_cue": "at your habit's next cue", "focus_end": "when a focus block ends",
         "long_block": "when a focus block next runs long",
         "noop_copy": "at the next sync that copies the NOOP database", "sync": "at the next sync run",
         "push_back": "when pushes next come back after an outage",
         "sender_changed": "when your next reply changes the sender again"}
_NUM = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")


def _at_most(n: int) -> str:
    return "at most " + {1: "once", 2: "twice"}.get(n, f"{_NUM[n] if n < len(_NUM) else 'a few'} times")


def to_schedule_card(spec: JobSpec) -> dict:
    """The plain-words fields a Hermes "Schedule this job?" card could show for this job. No internal ids."""
    when = "when you are back from a nap" if spec.trigger_after == "short_on" else _SPEAKS[spec.trigger_event]
    card = {"name": spec.send_title, "speaks": f"{when}, {_at_most(spec.max_per_window)}",
            "window": _IN_WINDOW[spec.window_class], "ends": _ENDS[spec.expires],
            "delivery": "you, through the send gate; this job never sends by itself"}
    if spec.answers:
        card["answers"] = f"{', '.join(spec.answers[:-1])} or {spec.answers[-1]} in one tap; no answer stays unlogged"
    return card


HABIT_TAPS = {"done": "Done", "no": "No", "skip": "Skipped"}   # tap -> the habit.json check-in word


def habit_answer(tap: Any) -> Optional[str]:
    """Done | No | Skipped for a real tap; None (unlogged) for no answer, an expired ask or anything else."""
    return HABIT_TAPS.get(tap.strip().lower()) if isinstance(tap, str) else None


SYNC_WORDS = {"met": "Done", "missed": "No"}   # StateReader.habit_days() -> the check-in word


def habit_day(habit: Optional[dict], day: str, synced: Optional[dict] = None) -> str:
    """One day's check-in: Done | No | Skipped, else "unlogged". A day with no answer is never No.

    A 1-tap answer in habit.json wins; else the sync's habit1.jsonl verdict (``synced``, from
    StateReader.habit_days(): met -> Done, missed -> No); a day with neither stays unlogged.
    """
    checkins = habit.get("checkins") if isinstance(habit, dict) else None
    v = checkins.get(day) if isinstance(checkins, dict) else None
    if isinstance(v, str) and v.strip().lower() in ("done", "no", "skipped"):
        return v.strip().capitalize()
    s = synced.get(day) if isinstance(synced, dict) else None
    return SYNC_WORDS.get(s, "unlogged") if isinstance(s, str) else "unlogged"


def record_checkin(habit: Optional[dict], day: str, tap: Any) -> dict:
    """A copy of habit.json with the day's answer; no answer leaves the day as it was. The caller writes it.

    habit_card.record does the recording. A Skip, which the card leaves with no entry, is then marked
    ``Skipped`` in habit.json, so the day reads as answered and a later tap never overwrites it (the first tap
    wins). Every reader still counts Skipped as unlogged, exactly as the card counts no entry."""
    out = habit_card.record(habit if isinstance(habit, dict) else None, day, tap)
    if habit_answer(tap) == HABIT_TAPS["skip"]:
        out[habit_card.CHECKINS][day] = HABIT_TAPS["skip"]
    return out


def week_card_state(habit: Optional[dict], synced: Optional[dict] = None) -> dict:
    """The started week as a habit_card state: ``{"checkins": {day: Done | No}}`` over its seven days, each
    day as habit_day reads it (a tap wins over the sync). Skipped and unlogged days have no entry; no started
    week is an empty table."""
    start = _week_start(habit)
    days = [] if start is None else [(start + timedelta(days=i)).isoformat() for i in range(HABIT_WEEK_DAYS)]
    words = ((d, habit_day(habit, d, synced)) for d in days)
    return {habit_card.CHECKINS: {d: w for d, w in words if w in (habit_card.DONE, habit_card.NO)}}


def week_logged(habit: Optional[dict], synced: Optional[dict] = None) -> Tuple[int, int]:
    """(N, M) for the week's seven days: N Done, M Done + No. Skipped and unlogged days stay out of M.
    The number is habit_card.week_number's ``done`` and ``logged``."""
    start = _week_start(habit)
    if start is None:
        return 0, 0
    n = habit_card.week_number(week_card_state(habit, synced), start)
    return n["done"], n["logged"]


def week_review_text(habit: Optional[dict], synced: Optional[dict] = None) -> str:
    """The week review's first line: the habit and "N of M logged days". Its Keep / Drop ask is the choices
    line (one_tap.choices_line(WEEK_REVIEW.answers)) jobs_runner.body puts last.

    With no Done or No day it says no days were logged, never that the week failed.
    """
    name = (habit or {}).get("habit") if isinstance(habit, dict) else None
    name = name.strip() if isinstance(name, str) and name.strip() else "Your habit"
    n, m = week_logged(habit, synced)
    what = f"{n} of {m} logged days this week" if m else "no days were logged this week"
    return f"{name}: {what}."
