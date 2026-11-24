"""The sender ingest job: the owner's "push via <profile>" reply sets kevin-push's sender by itself.

    run(state_dir, now, dry_run=True, env=None, home=None) -> {"job", "action", "reason"} | None
    state(state_dir, cfg, now, env=None) -> (status word, reason words) for limitless-doctor

limitless-jobs calls ``run`` once per pass (jobs_runner.run_once, right after the ranked ingest row), by the apps
ingest's rule: its event is any new sync row in runs.jsonl (jobs.sender_ingest_verdict), never a clock time.
Config ``sender_ingest``: ``off`` (the default: no row, nothing read), ``dry_run`` or ``write``. A due pass that is
not itself a dry run reads the owner's messages from the Hermes session DB (config ``hermes_db``, the same read as
the apps ingest: habit_replies.replies_from_hermes_db, role ``user`` in Telegram sessions; none set: skipped) and
runs sender_reply.ingest: the newest whole ``push via <name>`` message after the mark, applied only when
push_sender.check says that profile exists and push_sender.readiness does not say it has no Telegram bot token or
no chat for kevin-push's target (files only; an unknown still applies). Write mode writes ``push-sender.json``; dry
run writes only the mark. Then it writes the mark ``push-sender-ingest.json`` (sender_reply.MARK: epochs and words
only, atomic, 0600), whose ``refused_at`` keeps the newest refused reply until a later one is applied: while the
push outage is open, ``refusal_words`` says so for the doctor's row (push_recovery.REFUSED).

Reasons are words only: never the profile name, a message or a digit. When ``$KEVIN_PUSH_PROFILE`` is set in the
env the job sees, the row says that it still wins (push_sender.profile's order). Nothing is pushed or logged as
sent; no process is started and nothing is restarted. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional

from . import habit_replies as _habit_replies, jobs, push_sender, sender_reply as _sr
from .state_reader import StateReader, config

TITLE = jobs.SENDER_INGEST.send_title           # "Sender ingest": the job's row name in limitless-jobs
ENV_WINS = f"{push_sender.PROFILE_ENV} is set and still wins"
_MODE_WORDS = {jobs.SENDER_DRY_RUN: "dry run mode (only the mark is written)", jobs.SENDER_WRITE: "write mode"}


def said(action: Optional[str]) -> str:
    """What one pass did, in words (sender_reply.SAID); a dry run's would-write names the config that writes."""
    if action == _sr.WOULD_WRITE:
        return f'{_sr.SAID[action]} (config {jobs.SENDER_CONFIG} "{jobs.SENDER_WRITE}" sets it)'
    return _sr.SAID.get(action or "", "unknown")


def env_wins(env: Optional[Mapping[str, str]] = None) -> bool:
    """True when $KEVIN_PUSH_PROFILE is set (non-blank) in ``env``: it beats the reply (push_sender.profile)."""
    v = (os.environ if env is None else env).get(push_sender.PROFILE_ENV)
    return isinstance(v, str) and bool(v.strip())


def run_ingest(state_dir, db, row_at: Optional[float], now: float, mode: str,
               env: Optional[Mapping[str, str]] = None, cfg: Optional[Mapping] = None) -> tuple:
    """Read the owner's messages after the mark from ``db`` (read-only), run sender_reply.ingest (writing
    push-sender.json only in write mode; ``cfg`` gives kevin-push's target for the readiness gate) and record the
    pass in the mark: the runs.jsonl row it acted on (``row_at``), this pass (``ran_at``), the mode, the action
    word, ``after`` (moved only by a write pass that read messages; else kept) and ``refused_at`` (set by a
    refusal, cleared by an applied reply, else kept). Returns (mark, ingest result). Sends nothing."""
    replies = _habit_replies.replies_from_hermes_db(db, _sr.read_after(state_dir, now))
    got = _sr.ingest(state_dir, replies, now, write=mode == jobs.SENDER_WRITE, env=env, cfg=cfg)
    after = got["after"] if got["after"] is not None else _sr.load_mark(state_dir).get("after")
    if got["action"] in _sr.REFUSALS:
        refused = got["refused_at"]
    elif got["action"] in (_sr.WRITE, _sr.WOULD_WRITE):
        refused = None
    else:
        refused = _sr.refused_at(state_dir)
    mark = {"row_at": row_at, "ran_at": now, "mode": mode, "action": got["action"], "after": after,
            "refused_at": refused}
    _sr.write_mark(state_dir, mark)
    return mark, got


def run(state_dir, now: float, dry_run: bool = True, env: Optional[Mapping[str, str]] = None,
        home: Optional[Path] = None) -> Optional[dict]:
    """The sender ingest's ``{job, action, reason}`` row, or None when config ``sender_ingest`` is off (no row,
    nothing read). Due and not ``dry_run``: runs it (run_ingest) and says what it did in words; ``dry_run``: the
    verdict only, nothing read, run or written."""
    cfg = config(env, home)
    mode = jobs.sender_mode(cfg)
    if mode == jobs.SENDER_OFF:
        return None
    db = _habit_replies.hermes_db_path(state_dir, env, home)
    v = jobs.sender_ingest_verdict(mode, StateReader(Path(state_dir)).last_run(),
                                   _sr.load_mark(state_dir).get("row_at"), now, db_set=db is not None)
    if v.action != jobs.RUN:
        return {"job": TITLE, "action": v.action, "reason": v.reason}
    if dry_run:
        return {"job": TITLE, "action": v.action, "reason": f"{v.reason}; dry run of limitless-jobs: not run"}
    try:
        mark, got = run_ingest(state_dir, db, v.trigger_at, now, mode, os.environ if env is None else env, cfg)
    except OSError as e:
        return {"job": TITLE, "action": jobs.HOLD,
                "reason": f"{v.reason}; a file was not written ({type(e).__name__}); the next run tries again"}
    reason = f"{v.reason}; {said(mark['action'])}" if got["action"] != _sr.UNKNOWN else f"{v.reason}; {got['reason']}"
    if env_wins(env):
        reason += f"; {ENV_WINS}"
    return {"job": TITLE, "action": v.action, "reason": reason}


def refusal_words(state_dir, cfg: Optional[Mapping], now: float) -> Optional[str]:
    """push_recovery.REFUSED ("pushes are failing; your last reply named a profile that cannot reach Telegram")
    while the push outage is open and the owner's last reply after it began was refused; else None. Read-only."""
    from . import push_recovery     # late: push_recovery reads the sender confirm and recap jobs
    _, words = push_recovery.from_state(state_dir, cfg if isinstance(cfg, Mapping) else {}, now)
    return words if words == push_recovery.REFUSED else None


def state(state_dir, cfg: Mapping, now: float, env: Optional[Mapping[str, str]] = None) -> tuple:
    """(``off`` / ``no db`` / ``waiting`` / ``not run`` / ``ran``, words) for the doctor's row, from config,
    runs.jsonl and the mark. ``ran`` carries the mode, the mark's ``ran_at`` and what that pass did; words only,
    never a profile name. Read-only."""
    mode = jobs.sender_mode(cfg)
    if mode == jobs.SENDER_OFF:
        return "off", f"the sender ingest job is {jobs.SENDER_IS_OFF}"
    db = _habit_replies.hermes_db_from(state_dir, cfg, env)
    mark = _sr.load_mark(state_dir)
    v = jobs.sender_ingest_verdict(mode, StateReader(Path(state_dir)).last_run(), mark.get("row_at"), now,
                                   db_set=db is not None)
    on = f"on ({_MODE_WORDS[mode]})"
    if v.reason == jobs.APPS_NO_DB:
        return "no db", f"{on}, but {v.reason}"
    if v.action == jobs.RUN:
        return "waiting", f"a sync ran and the sender ingest has not run after it yet ({jobs.INGEST_RUNS} runs it)"
    if mark.get("ran_at") is None:
        return "not run", f"{on}, but it has not run yet: {v.reason}"
    return "ran", (_MODE_WORDS.get(mark.get("mode") or "", "unknown mode"), mark["ran_at"], said(mark.get("action")))
