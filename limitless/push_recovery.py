"""Push recovery: where a push-outage recovery stands, as one plain stage, for limitless-doctor's "push recovery" row.

    stage(state_dir, rows, cfg, now) -> (status, words)
    from_state(state_dir, cfg, now)  -> the same, reading kevin-push's log (config ``push_log``) itself

During a push outage the recovery runs in stages across several limitless-jobs passes: pushes fail and the owner
is asked to reply ``push via <name>``; sender_ingest_job applies the reply (push-sender.json); sender_confirm_job
sends the one confirmation through the new sender (kevin-push's log, else its mark sender-confirm.json);
outage_recap_job sends or settles the recap a pass later (its mark outage-recap.json). ``stage`` names which one
holds, from those files alone:

    no outage (none open, none closed within the recap's stale window)    live     NO_OUTAGE
    an outage open, no sender reply after it began                        missing  WAITING_REPLY
    an outage open, the last reply after it began was refused             missing  REFUSED
    an outage open, the reply applied, its confirmation not delivered     stale    NOT_DELIVERED + why
    pushes back, the recap not sent or settled yet                         stale    BACK + the recap's mode
    pushes back, the recap sent / settled without one                      live     RECAP_SENT / SETTLED

A refused reply is the sender ingest mark's ``refused_at`` (sender_reply.refused_at: a reply naming a profile that
does not exist, or one with no Telegram bot token or no chat); it counts when it came after the outage began and
after the reply push-sender.json holds. The outage is outage_recap.outage over the log rows (the same rule the
recap and the state card use). No push log (``rows`` None) is missing with the reason, never a guess. Words only:
never a digit, a path, a profile name, a host or a time stamp. Pure and read-only: it reads the small reply and mark files and writes nothing, sends
nothing and starts no process. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

from typing import Iterable, Mapping, Optional

from . import delivery_audit as _da, jobs, outage_recap as _rc, push_sender, sender_reply as _sr
from . import outage_recap_job as _recap, sender_confirm_job as _confirm

LIVE, STALE, MISSING = "live", "stale", "missing"   # doctor's statuses
UNKNOWN_PREFIX = "unknown: "
NO_OUTAGE = "no outage: pushes are reaching you"
WAITING_REPLY = "pushes are failing; waiting for a sender reply"
REFUSED = "pushes are failing; your last reply named a profile that cannot reach Telegram"
NOT_DELIVERED = "sender set from your reply; the confirmation has not been delivered yet"
HELD = "held while Sleep mode was on"
FAILED = "failed to send"
NOT_SENT = "not sent yet"
CONFIRM_OFF = "the confirmation is off"
BACK = "pushes are back"
RECAP_WAITS = f"{BACK}; the recap waits for the next pass"
RECAP_OFF = f"{BACK}; the recap is off"
RECAP_DRY_RUN = f"{BACK}; the recap is in dry run mode"
RECAP_SENT = f"{BACK}; recap sent"
SETTLED = f"{BACK}; settled without a recap"
BROKEN = UNKNOWN_PREFIX + "the push log or a mark could not be read"


def _confirmation(state_dir, rows, cfg, reply_at: float) -> str:
    """Why the confirmation of the reply at ``reply_at`` is not delivered yet: its newest log row
    (sender_confirm_job.logged), else its mark for this reply, else not sent yet."""
    got = _confirm.logged(rows, reply_at)
    st = got[0] if got is not None else None
    if st is None:
        mark = _confirm.load_mark(state_dir)
        if mark.get("reply_at") == reply_at:
            st = {_confirm.HELD: _confirm.S_HELD, _confirm.FAILED: _confirm.S_FAILED}.get(mark.get("outcome"))
    if st == _confirm.S_HELD:
        return HELD
    if st == _confirm.S_FAILED:
        return FAILED
    if _confirm.mode(cfg) == _confirm.OFF:
        return CONFIRM_OFF
    return NOT_SENT


def stage(state_dir, rows: Optional[Iterable], cfg: Optional[Mapping], now: float,
          why: Optional[str] = None) -> tuple:
    """(status, words) for the recovery stage (see the module doc). ``rows`` are kevin-push's log rows; None when
    there is no push log, then ``why`` (default delivery_audit.NO_LOG_REASON) is the missing reason."""
    if rows is None:
        return MISSING, UNKNOWN_PREFIX + (why or _da.NO_LOG_REASON)
    cfg = cfg if isinstance(cfg, Mapping) else {}
    rows = list(rows)
    o = _rc.outage(rows)
    if o is None:
        return LIVE, NO_OUTAGE
    if o["state"] == _rc.OPEN:
        reply_at = push_sender.reply_at(state_dir)
        if reply_at is not None and reply_at < o["first_at"]:
            reply_at = None
        refused = _sr.refused_at(state_dir)
        if refused is not None and refused >= o["first_at"] and (reply_at is None or refused > reply_at):
            return MISSING, REFUSED
        if reply_at is None:
            return MISSING, WAITING_REPLY
        return STALE, f"{NOT_DELIVERED} ({_confirmation(state_dir, rows, cfg, reply_at)})"
    if now - o["closed_at"] > jobs.OUTAGE_RECAP_STALE_S:
        return LIVE, NO_OUTAGE
    mark = _recap.load_mark(state_dir)
    if mark.get("key") == _rc.once_key(o) and mark.get("outcome") in (_recap.TOLD, _recap.DROPPED):
        return LIVE, RECAP_SENT if mark["outcome"] == _recap.TOLD else SETTLED
    return STALE, {_recap.OFF: RECAP_OFF, _recap.DRY_RUN: RECAP_DRY_RUN}.get(_recap.mode(cfg), RECAP_WAITS)


def from_state(state_dir, cfg: Optional[Mapping], now: float) -> tuple:
    """``stage`` over kevin-push's log at config ``push_log`` (delivery_audit.log_path): no log set or one that
    cannot be read is missing with that reason. Never raises; read-only."""
    try:
        path = _da.log_path(cfg, state_dir)
        if path is None:
            return stage(state_dir, None, cfg, now, _da.NO_LOG_REASON)
        got = _da.read_log(path)
        if got is None:
            return stage(state_dir, None, cfg, now, _da.UNREADABLE_REASON)
        return stage(state_dir, got[0], cfg, now)
    except Exception:  # noqa: BLE001 - a broken file is one row, never a traceback
        return MISSING, BROKEN
