"""The outage recap job: after phone pushes reach the person again, one plain recap of what the outage swallowed.

    run(state_dir, now, push=None, dry_run=True, env=None, home=None, tz=None) -> {"job", "action", "reason"} | None
    state(state_dir, cfg, now) -> one of STATES, for limitless-doctor

limitless-jobs calls ``run`` once per pass (jobs_runner.run_once, after the voice MIQ row). Its event is jobs'
``push_back``: a push kevin-push delivered after an outage (outage_recap.outage over kevin-push's log, config
``push_log``), never a clock time. Config ``outage_recap``: ``off`` (the default: no row, nothing read),
``dry_run`` (the row says it would send; nothing is pushed or written) or ``write``. A pass that is itself a dry
run (``limitless-jobs`` without ``--send``, or no ``push``) is a dry run too.

In write mode, a closed outage not yet settled is sent once through ``push`` (bin/limitless-jobs: ``kevin-push
--once outage_recap:<first failed push time> --why WHY``, KEVIN_PUSH_STRICT=1), so every poll of one outage
carries the same key and kevin-push lets at most one recap out. The mark ``outage-recap.json`` (atomic, 0600:
the once key, an outcome word and an epoch; never a title, a kind or any message text) is written TOLD only on a
real delivery (push reports ``telegram``, kevin-push's rc 0). A push kevin-push drops because the key was
already claimed or quiet holds is DROPPED: settled, never told, never retried. Any other result (a failed send,
the daily cap, a Sleep-mode hold) holds and the next pass tries again. An outage still open, no outage, or one
that closed more than jobs.OUTAGE_RECAP_STALE_S ago sends nothing. Reasons are words only. Starts no process
itself; never restarts anything. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Callable, Mapping, Optional

from . import delivery_audit as _da, jobs, outage_recap as _rc, send_gate
from .state_reader import config

OFF, DRY_RUN, WRITE = jobs.OUTAGE_RECAP_OFF, jobs.OUTAGE_RECAP_DRY_RUN, jobs.OUTAGE_RECAP_WRITE
CONFIG_KEY = jobs.OUTAGE_RECAP_CONFIG
MARK = "outage-recap.json"
TITLE = "Outage recap"            # the job's row name in limitless-jobs and the doctor
STALE_S = jobs.OUTAGE_RECAP_STALE_S
TOLD, DROPPED = "told", "dropped"
WHY = "pushes are reaching you again after an outage"
NO_LOG_REASON = _da.NO_LOG_REASON                  # "no push log set (config push_log)"
UNREADABLE_REASON = _da.UNREADABLE_REASON
NOTHING_REASON = "no push outage to recap"
OPEN_REASON = "pushes are still failing; the state card already says so"
EVENT = "pushes came back after an outage"
# For the doctor (state): off, no push log, waiting (an outage open, or closed and not yet told), told, nothing.
S_OFF, S_NO_LOG, S_OPEN, S_WAITING, S_TOLD, S_NOTHING = "off", "no push log", "open", "waiting", "told", "nothing"
STATES = (S_OFF, S_NO_LOG, S_OPEN, S_WAITING, S_TOLD, S_NOTHING)


def mode(cfg) -> str:
    """Config ``outage_recap`` (jobs.outage_recap_mode): off, dry_run or write."""
    return jobs.outage_recap_mode(cfg)


def _epoch(v) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def load_mark(state_dir) -> dict:
    """outage-recap.json as ``{"key", "outcome", "at"}``; {} when missing or malformed."""
    try:
        data = json.loads((Path(state_dir) / MARK).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or not isinstance(data.get("key"), str):
        return {}
    return {"key": data["key"], "outcome": data.get("outcome") if data.get("outcome") in (TOLD, DROPPED) else None,
            "at": _epoch(data.get("at"))}


def _write_mark(state_dir, key: str, outcome: str, now: float) -> None:
    from . import jobs_runner   # jobs_runner imports this module inside run_once
    jobs_runner._write_mark(state_dir, MARK, {"key": key, "outcome": outcome, "at": float(now)})


def _rows(state_dir, cfg) -> tuple:
    """(rows, why): kevin-push's log rows, or None with the reason they cannot be read."""
    path = _da.log_path(cfg, state_dir)
    if path is None:
        return None, NO_LOG_REASON
    got = _da.read_log(path)
    if got is None:
        return None, UNREADABLE_REASON
    return got[0], None


def _row(action: str, reason: str) -> dict:
    return {"job": TITLE, "action": action, "reason": reason}


def run(state_dir, now: float, push: Optional[Callable] = None, dry_run: bool = True,
        env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None, tz=None) -> Optional[dict]:
    """The outage recap's ``{job, action, reason}`` row; None when config ``outage_recap`` is off. Never raises."""
    cfg = config(env, home)
    m = mode(cfg)
    if m == OFF:
        return None
    try:
        return _run(state_dir, now, push, dry_run or m == DRY_RUN or push is None, m, cfg, tz)
    except Exception as e:  # noqa: BLE001 - a broken log or state is one row, never a traceback
        return _row(jobs.HOLD, f"could not read the push log or the mark ({type(e).__name__}); nothing sent")


def _run(state_dir, now: float, push, dry: bool, m: str, cfg, tz) -> dict:
    rows, why = _rows(state_dir, cfg)
    if rows is None:
        return _row(jobs.NOT_TRIGGERED, why)
    o = _rc.outage(rows)
    if o is None:
        return _row(jobs.NOT_TRIGGERED, NOTHING_REASON)
    if o["state"] == _rc.OPEN:
        return _row(jobs.NOT_TRIGGERED, OPEN_REASON)
    key = _rc.once_key(o)
    mark = load_mark(state_dir)
    if mark.get("key") == key:
        said = "already told about this outage" if mark.get("outcome") == TOLD else \
            "this outage was already settled without a recap"
        return _row(jobs.DROP, said)
    if o["closed_at"] > now:
        return _row(jobs.NOT_TRIGGERED, "the push that ended the outage is timestamped in the future")
    if now - o["closed_at"] > STALE_S:
        return _row(jobs.DROP, "too late: pushes came back a while ago; a late recap is noise")
    r = _rc.recap(rows, now, tz)
    if dry:
        hint = f'config {CONFIG_KEY} "{WRITE}" sends it' if m == DRY_RUN else "dry run of limitless-jobs"
        return _row(jobs.DELIVER, f"{EVENT}; would send the recap ({hint}): nothing sent")
    from . import jobs_runner   # jobs_runner imports this module inside run_once
    ok, how = jobs_runner._push(push, r["title"], r["body"], r["key"], why=WHY)
    if ok:
        try:
            _write_mark(state_dir, key, TOLD, now)
        except OSError as e:
            return _row(jobs.DELIVER, f"{EVENT}; sent; the mark was not written ({type(e).__name__}), so the next "
                                      f"pass relies on the once key")
        return _row(jobs.DELIVER, f"{EVENT}; sent")
    if send_gate.ONCE_DROP in how or jobs_runner.QUIET_DROP in how:
        _write_mark(state_dir, key, DROPPED, now)
        said = send_gate.ONCE_DROP if send_gate.ONCE_DROP in how else \
            how[how.index(jobs_runner.QUIET_DROP) + 1:].split(")")[0]
        return _row(jobs.DROP, f"{EVENT}; not sent: {said}")
    return _row(jobs.HOLD, f"{EVENT}; not delivered: {how}; the next run tries again")


def state(state_dir, cfg: Mapping, now: float) -> tuple:
    """(one of STATES, the mark's epoch or None) for the doctor. Read-only; never raises."""
    if mode(cfg) == OFF:
        return S_OFF, None
    try:
        rows, why = _rows(state_dir, cfg)
        if rows is None:
            return (S_NO_LOG if why == NO_LOG_REASON else S_NOTHING), None
        o = _rc.outage(rows)
        mark = load_mark(state_dir)
        if o is None:
            return S_NOTHING, None
        if o["state"] == _rc.OPEN:
            return S_OPEN, None
        if mark.get("key") == _rc.once_key(o):
            return (S_TOLD if mark.get("outcome") == TOLD else S_NOTHING), mark.get("at")
        if now - o["closed_at"] > STALE_S:
            return S_NOTHING, None
        return S_WAITING, None
    except Exception:  # noqa: BLE001
        return S_NOTHING, None
