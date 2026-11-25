"""The sender confirmation job: one plain push right after the owner's reply changes the sender, so a broken new
sender shows up at once instead of at some later push.

    run(state_dir, now, push=None, dry_run=True, env=None, home=None) -> {"job", "action", "reason"} | None
    run_pass(...) -> (that row, whether push was called in this pass)   # jobs_runner.run_once uses it
    state(state_dir, cfg, now, env=None) -> (one of STATES, the epoch it happened or None), for limitless-doctor

limitless-jobs calls ``run_pass`` once per pass (jobs_runner.run_once, right after the sender ingest row, so a reply
the ingest applies in a pass is confirmed in the same pass). Its event is jobs' ``sender_changed``: push-sender.json
(push_sender.reply_at, written by sender_reply for a profile that exists) records a reply newer than the last one
the mark settled (jobs.sender_changed_verdict), never a clock time. Config ``sender_confirm``: ``off`` (the
default: no row, nothing read), ``dry_run`` (the row says what it would send; nothing is pushed or written) or
``write``. A pass that is itself a dry run (``limitless-jobs`` without ``--send``, or no ``push``) is a dry run too;
``limitless-jobs --ingest --confirm`` (run_once ``confirm``) is the one pass that is a dry run for every other job and
still sends this confirmation.

In write mode the confirmation (title TITLE_SENT "Pushes", body BODY: plain words, never the profile name, a path,
a card id or a digit) goes once through ``push`` (bin/limitless-jobs: ``kevin-push --once sender_confirm:<reply
time> --why WHY``, KEVIN_PUSH_STRICT=1): kevin-push's normal send gate decides, its Sleep-mode hold included, and
it resolves the sender the reply set. That delivery result is the proof the new sender works. The mark MARK
``sender-confirm.json`` (atomic, 0600: the reply epoch, an outcome word and the pass epoch; never a name or any
message text) records each attempt: TOLD on a real delivery (push reports ``telegram``), FAILED when the send
failed (a hermes error or a missing profile: the new sender did not reach the owner), HELD when Sleep mode held
it, DROPPED when kevin-push dropped it (quiet, the once key already claimed, or the same text within the dedupe
window). TOLD and DROPPED settle that reply; FAILED, HELD and the daily cap try again next pass. While
``$KEVIN_PUSH_PROFILE`` is set it beats the reply (push_sender.profile), so nothing is sent: the confirmation
would not travel the new route. Reasons are words only. Starts no process itself; never restarts anything.
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Callable, Mapping, Optional

from . import delivery_audit as _da, jobs, push_sender, send_gate
from .state_reader import config

OFF, DRY_RUN, WRITE = jobs.SENDER_CONFIRM_OFF, jobs.SENDER_CONFIRM_DRY_RUN, jobs.SENDER_CONFIRM_WRITE
CONFIG_KEY = jobs.SENDER_CONFIRM_CONFIG
MARK = "sender-confirm.json"
_WORDS = jobs.job_words(jobs.SENDER_CONFIRM.name)   # "sender confirmation"
TITLE = _WORDS[:1].upper() + _WORDS[1:]              # the job's row name in limitless-jobs: its JOB_WORDS name
TITLE_SENT = jobs.SENDER_CONFIRM.send_title  # "Pushes": the message's title
BODY = "This is the new route for your phone pushes. If you see this, it works."
WHY = "your reply changed the sender for your phone pushes"
KEY_PREFIX = jobs.SENDER_CONFIRM.name
TOLD, FAILED, HELD, DROPPED = "told", "failed", "held", "dropped"
OUTCOMES = (TOLD, FAILED, HELD, DROPPED)
SETTLED = (TOLD, DROPPED)
ENV_WINS = f"{push_sender.PROFILE_ENV} is set and still wins"
RECAP_WAITS = "the sender confirmation went out in this pass"   # outage_recap_job's wait words (run_once)
NOT_REACHED = "the new sender did not reach you"
_FAILED = (("no sender profile", "the sender profile does not exist"), ("telegram rc=", "the send failed"),
           ("did not run", "the send failed"), ("push failed", "the send failed"),
           ("no report", "the send failed"), ("no delivery reported", "the send failed"))
_DUPLICATE = "log (duplicate)"
_HELD = "held (sleep mode)"
_CAP = "log (daily cap)"
# For the doctor (state): off, nothing to confirm, waiting (changed, not yet tried), held, failed, told, dropped.
S_OFF, S_NOTHING, S_WAITING, S_HELD, S_FAILED, S_TOLD, S_DROPPED, S_ENV = \
    "off", "nothing", "waiting", "held", "failed", "told", "dropped", "env wins"
STATES = (S_OFF, S_NOTHING, S_WAITING, S_HELD, S_FAILED, S_TOLD, S_DROPPED, S_ENV)


def mode(cfg) -> str:
    """Config ``sender_confirm`` (jobs.sender_confirm_mode): off, dry_run or write."""
    return jobs.sender_confirm_mode(cfg)


def once_key(reply_at: float) -> str:
    """``sender_confirm:<the reply's epoch>``: the same on every pass for one sender change."""
    return f"{KEY_PREFIX}:{int(reply_at)}"


def _epoch(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def load_mark(state_dir) -> dict:
    """sender-confirm.json as ``{"reply_at", "outcome", "ran_at"}``; {} when missing or malformed."""
    try:
        data = json.loads((Path(state_dir) / MARK).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or _epoch(data.get("reply_at")) is None:
        return {}
    return {"reply_at": _epoch(data["reply_at"]),
            "outcome": data.get("outcome") if data.get("outcome") in OUTCOMES else None,
            "ran_at": _epoch(data.get("ran_at"))}


def settled_at(mark: Mapping) -> Optional[float]:
    """The reply epoch the mark settled (told or dropped), else None."""
    return mark.get("reply_at") if mark.get("outcome") in SETTLED else None


def _write_mark(state_dir, reply_at: float, outcome: str, now: float) -> None:
    from . import jobs_runner   # jobs_runner imports this module inside run_once
    jobs_runner._write_mark(state_dir, MARK, {"reply_at": float(reply_at), "outcome": outcome, "ran_at": float(now)})


def env_wins(env: Optional[Mapping[str, str]]) -> bool:
    """True when $KEVIN_PUSH_PROFILE is set (non-blank): it beats the reply, so the reply is not the route."""
    v = (env or {}).get(push_sender.PROFILE_ENV)
    return isinstance(v, str) and bool(v.strip())


def _row(action: str, reason: str) -> dict:
    return {"job": TITLE, "action": action, "reason": reason}


def outcome_of(how: str) -> tuple:
    """(outcome word or None, words) for what kevin-push reported on a push that was not delivered. None: no mark
    (the daily cap, or anything unknown); the job holds and the next pass tries again. Words never hold a digit."""
    how = how if isinstance(how, str) else ""
    from . import jobs_runner
    if send_gate.ONCE_DROP in how:
        return DROPPED, send_gate.ONCE_DROP
    if jobs_runner.QUIET_DROP in how:
        return DROPPED, how[how.index(jobs_runner.QUIET_DROP) + 1:].split(")")[0]
    if _DUPLICATE in how:
        return DROPPED, "the same confirmation went out within half a day"
    if _HELD in how:
        return HELD, "Sleep mode holds it"
    if _CAP in how:
        return None, "the send gate's daily cap is reached"
    for marker, words in _FAILED:
        if marker in how:
            return FAILED, words
    return None, "kevin-push did not report a delivery"


def run(state_dir, now: float, push: Optional[Callable] = None, dry_run: bool = True,
        env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> Optional[dict]:
    """The sender confirmation's ``{job, action, reason}`` row; None when config ``sender_confirm`` is off."""
    return run_pass(state_dir, now, push, dry_run, env, home)[0]


def run_pass(state_dir, now: float, push: Optional[Callable] = None, dry_run: bool = True,
             env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> tuple:
    """(row or None, pushed): ``pushed`` is True when this pass called ``push`` (delivered, held or failed), so
    jobs_runner.run_once can keep the outage recap for the next pass. Never raises."""
    env = os.environ if env is None else env
    cfg = config(env, home)
    m = mode(cfg)
    if m == OFF:
        return None, False
    try:
        return _run(state_dir, now, push, dry_run or m == DRY_RUN or push is None, m, env)
    except Exception as e:  # noqa: BLE001 - a broken state file is one row, never a traceback
        return _row(jobs.HOLD, f"could not read the sender reply or the mark ({type(e).__name__}); nothing sent"), \
            False


def _run(state_dir, now: float, push, dry: bool, m: str, env) -> tuple:
    mark = load_mark(state_dir)
    v = jobs.sender_changed_verdict(m, push_sender.reply_at(state_dir), settled_at(mark), now)
    if v.action == jobs.DROP and v.reason == jobs.SENDER_SETTLED and mark.get("outcome") == DROPPED:
        return _row(jobs.DROP, "this sender change was settled without a confirmation"), False
    if v.action != jobs.DELIVER:
        return _row(v.action, v.reason), False
    if env_wins(env):
        return _row(jobs.NOT_TRIGGERED, f"{v.reason}, but {ENV_WINS}: the reply is not the route, so nothing "
                                        f"was sent"), False
    if dry:
        hint = f'config {CONFIG_KEY} "{WRITE}" sends it' if m == DRY_RUN else "dry run of limitless-jobs"
        return _row(jobs.DELIVER, f'{v.reason}; would send "{TITLE_SENT}": "{BODY}" ({hint}): nothing sent'), False
    from . import jobs_runner   # jobs_runner imports this module inside run_once
    ok, how = jobs_runner._push(push, TITLE_SENT, BODY, once_key(v.trigger_at), why=WHY)
    if ok:
        try:
            _write_mark(state_dir, v.trigger_at, TOLD, now)
        except OSError as e:
            return _row(jobs.DELIVER, f"{v.reason}; sent; the mark was not written ({type(e).__name__}), so the "
                                      f"next pass relies on the once key"), True
        return _row(jobs.DELIVER, f"{v.reason}; sent"), True
    outcome, said = outcome_of(how)
    if outcome is not None:
        _write_mark(state_dir, v.trigger_at, outcome, now)
    if outcome == DROPPED:
        return _row(jobs.DROP, f"{v.reason}; not sent: {said}"), True
    if outcome == FAILED:
        return _row(jobs.HOLD, f"{v.reason}; {NOT_REACHED}: {said}; the next pass tries again"), True
    return _row(jobs.HOLD, f"{v.reason}; not delivered: {said}; the next pass tries again"), True


BODY_FIRST = BODY.split(". ")[0] + "."   # how the confirmation's log row starts (kevin-push logs the shaped text)


def _log_rows(state_dir, cfg) -> Optional[list]:
    """kevin-push's log rows (config ``push_log``), or None when no log is set or it cannot be read."""
    path = _da.log_path(cfg, state_dir)
    got = _da.read_log(path) if path is not None else None
    return None if got is None else got[0]


def is_confirmation(r: Mapping, reply_at: float) -> bool:
    """True for a kevin-push log row of this sender change's confirmation: its title, its first words, logged at
    or after the reply."""
    body = r.get("body")
    return (_da.valid(r) and r.get("title") == TITLE_SENT and isinstance(body, str)
            and body.startswith(BODY_FIRST) and float(r["at"]) >= int(reply_at))


def logged(rows, reply_at: float) -> Optional[tuple]:
    """(state, epoch) from the newest confirmation row kevin-push logged after the reply: told when delivered,
    failed when the send failed (delivery_audit.send_failed), held for a Sleep-mode hold, waiting for the daily
    cap, dropped for anything else (quiet, a repeat, the once key); None when there is no such row."""
    mine = [r for r in rows or () if isinstance(r, dict) and is_confirmation(r, reply_at)]
    if not mine:
        return None
    r = max(mine, key=lambda x: float(x["at"]))
    at = float(r["at"])
    if _da.delivered(r):
        return S_TOLD, at
    if _da.send_failed(r):
        return S_FAILED, at
    if r["how"].startswith(_HELD):
        return S_HELD, at
    if r["how"].startswith(_CAP):
        return S_WAITING, at
    return S_DROPPED, at


_FROM_MARK = {TOLD: S_TOLD, FAILED: S_FAILED, HELD: S_HELD, DROPPED: S_DROPPED}


def state(state_dir, cfg: Mapping, now: float, env: Optional[Mapping[str, str]] = None) -> tuple:
    """(one of STATES, the epoch it happened or None) for the doctor. The confirmation's own delivery result is
    the proof: the newest confirmation row in kevin-push's log for this reply (logged); with no push log set, or
    no such row, the mark's outcome for this reply; else waiting, or nothing with the reply's epoch once the
    change is older than jobs.SENDER_CONFIRM_STALE_S (never confirmed). Read-only; never raises."""
    env = os.environ if env is None else env
    if mode(cfg) == OFF:
        return S_OFF, None
    try:
        reply_at = push_sender.reply_at(state_dir)
        if reply_at is None:
            return S_NOTHING, None
        if env_wins(env):
            return S_ENV, None
        got = logged(_log_rows(state_dir, cfg), reply_at)
        if got is not None:
            return got
        mark = load_mark(state_dir)
        if mark.get("reply_at") == reply_at and mark.get("outcome") in _FROM_MARK:
            return _FROM_MARK[mark["outcome"]], mark.get("ran_at")
        if now - reply_at > jobs.SENDER_CONFIRM_STALE_S:
            return S_NOTHING, reply_at
        return S_WAITING, None
    except Exception:  # noqa: BLE001
        return S_NOTHING, None
