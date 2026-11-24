"""Push recovery: where a push-outage recovery stands, as one plain stage, for limitless-doctor's "push recovery" row.

    stage(state_dir, rows, cfg, now, env=None) -> (status, words)
    from_state(state_dir, cfg, now, env=None)  -> the same, reading kevin-push's log (config ``push_log``) itself

During a push outage the recovery runs in stages across several limitless-jobs passes: pushes fail and the owner
is asked to reply ``push via <name>``; sender_ingest_job applies the reply (push-sender.json); sender_confirm_job
sends the one confirmation through the new sender (kevin-push's log, else its mark sender-confirm.json);
outage_recap_job sends or settles the recap a pass later (its mark outage-recap.json). ``stage`` names which one
holds, from those files alone:

    no outage (none open, none closed within the recap's stale window)    live     NO_OUTAGE
    an outage open, no sender reply after it began                        missing  WAITING_REPLY
    an outage open, the last reply after it began was refused             missing  REFUSED
    an outage open, the reply applied on an unknown readiness answer,
      and its confirmation failed to send (not held, not pending)         missing  UNKNOWN_FAILED
    an outage open, the reply applied, its confirmation not delivered     stale    NOT_DELIVERED + why
    pushes back, the recap not sent or settled yet                         stale    BACK + the recap's mode
    pushes back, the recap sent / settled without one                      live     RECAP_SENT / SETTLED

A refused reply is the sender ingest mark's ``refused_at`` (sender_reply.refused_at: a reply naming a profile that
does not exist, or one with no Telegram bot token or no chat); it counts when it came after the outage began and
after the reply push-sender.json holds. UNKNOWN_FAILED needs the same mark's ``applied_unknown``
(sender_reply.applied_unknown: the reply push-sender.json holds was applied although push_sender.readiness could
not tell whether that profile has a bot, e.g. a secret source) and the confirmation's own send failing for that
reply: the profile was set but could not send, so it may have no Telegram bot. A later applied reply moves the
stage on (a READY one drops the flag; any new reply waits for its own confirmation). While the owner must reply
(WAITING_REPLY, REFUSED) the words go on with the profiles the owner can name (push_sender.candidates over the
Hermes home of ``env``, files only): "; ready profiles: a, b", else "; profiles that may reach Telegram: c"
(readiness cannot tell), else "; no profile can reach Telegram"; nothing is added when no Hermes home is known.
WAITING_REPLY puts "; the sender profile was deleted and can be restored" (SENDER_DELETED) before that list when
push_sender.tombstoned: Hermes moved the sender to ``profiles/.deleted/``, so restoring it is a fix too.
A maybe already proven unable to send (proven_failed: the reply push-sender.json holds was applied on an unknown
answer and its confirmation failed, the UNKNOWN_FAILED condition) is not offered again; when it was the only one
and none is ready the words end "; no profile left that may reach Telegram (one already failed to send)".
The constant stays the prefix, so a caller matches with ``startswith``. The outage is outage_recap.outage over the log rows (the same rule the
recap and the state card use). No push log (``rows`` None) is missing with the reason, never a guess. Words only:
never a digit, a path, a host or a time stamp, and no profile name but the candidates' (a name with a digit is only
counted). Read-only: it reads the small reply and mark files and the profiles' files for presence, and writes
nothing, sends nothing and starts no process. Stdlib only, Python 3.9+.
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
UNKNOWN_FAILED = ("pushes are failing; the profile you named was set but could not send, so it may have no "
                  "Telegram bot; reply push via another profile")
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
READY_PROFILES = "; ready profiles: "
MAYBE_PROFILES = "; profiles that may reach Telegram: "
NO_PROFILE = "; no profile can reach Telegram"
# WAITING_REPLY when the sender is tombstoned (push_sender.tombstoned): before the candidate list
SENDER_DELETED = "; the sender profile was deleted and can be restored"
# the only maybe already failed to send (proven_failed) and no profile is ready
NO_MAYBE_LEFT = "; no profile left that may reach Telegram (one already failed to send)"


def proven_failed(state_dir, cfg: Optional[Mapping], rows: Optional[Iterable] = None) -> Optional[str]:
    """The profile push-sender.json names when it is proven unable to send: the reply there was applied on an
    ``unknown: ...`` readiness answer (sender_reply.applied_unknown) and its one confirmation failed to send (its
    newest row in kevin-push's log, else its mark sender-confirm.json): the same condition as UNKNOWN_FAILED, but
    whether or not an outage is open. ``rows`` default to kevin-push's log at config ``push_log``. None for anything
    else, no state dir or a file that cannot be read. Read-only; stores nothing; never raises."""
    try:
        if state_dir is None or not _sr.applied_unknown(state_dir):
            return None
        reply_at = push_sender.reply_at(state_dir)
        if reply_at is None:
            return None
        if rows is None:
            path = _da.log_path(cfg, state_dir)
            got = _da.read_log(path) if path is not None else None
            rows = got[0] if got is not None else []
        if _confirmation(state_dir, list(rows), cfg if isinstance(cfg, Mapping) else {}, reply_at) != FAILED:
            return None
        return push_sender.reply_profile(state_dir)
    except Exception:  # noqa: BLE001 - nothing is dropped when it cannot be told
        return None


def drop_failed(cands: Optional[list], failed: Optional[str]) -> tuple:
    """(candidates, dropped): ``cands`` without the ``failed`` profile when readiness only calls it a maybe
    (``unknown: ...``); a READY one is kept. ``dropped`` is True when one was taken out."""
    if cands is None or failed is None:
        return cands, False
    kept = [(n, w) for n, w in cands if not (n == failed and w.startswith(push_sender.UNKNOWN_PREFIX))]
    return kept, len(kept) != len(cands)


def _who_can_send(cfg, env, hermes_home, failed: Optional[str] = None) -> str:
    """What the owner could reply with, appended to WAITING_REPLY / REFUSED; "" when no Hermes home is known.
    ``failed`` (proven_failed) is a maybe that already failed to send: it is not offered again."""
    try:
        cands = push_sender.candidates(cfg, env, hermes_home)
    except Exception:  # noqa: BLE001 - the stage still holds without the names
        return ""
    if cands is None:
        return ""
    cands, dropped = drop_failed(cands, failed)
    ready, maybe = push_sender.ready_names(cands), push_sender.maybe_names(cands)
    if ready:
        return READY_PROFILES + ", ".join(ready)
    if maybe:
        return MAYBE_PROFILES + ", ".join(maybe)
    return NO_MAYBE_LEFT if dropped else NO_PROFILE


def _deleted(cfg, env, hermes_home) -> str:
    """SENDER_DELETED when Hermes deleted the sender profile (push_sender.tombstoned), else ""."""
    try:
        return SENDER_DELETED if push_sender.tombstoned(cfg, env, hermes_home) else ""
    except Exception:  # noqa: BLE001 - the stage still holds without it
        return ""


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
          why: Optional[str] = None, env: Optional[Mapping[str, str]] = None, hermes_home=None) -> tuple:
    """(status, words) for the recovery stage (see the module doc). ``rows`` are kevin-push's log rows; None when
    there is no push log, then ``why`` (default delivery_audit.NO_LOG_REASON) is the missing reason. ``env``
    (default os.environ) and ``hermes_home`` locate the Hermes home whose profiles the reply stages name."""
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
            return MISSING, REFUSED + _who_can_send(cfg, env, hermes_home, proven_failed(state_dir, cfg, rows))
        if reply_at is None:
            return MISSING, (WAITING_REPLY + _deleted(cfg, env, hermes_home)
                             + _who_can_send(cfg, env, hermes_home, proven_failed(state_dir, cfg, rows)))
        why = _confirmation(state_dir, rows, cfg, reply_at)
        if why == FAILED and _sr.applied_unknown(state_dir):
            return MISSING, UNKNOWN_FAILED
        return STALE, f"{NOT_DELIVERED} ({why})"
    if now - o["closed_at"] > jobs.OUTAGE_RECAP_STALE_S:
        return LIVE, NO_OUTAGE
    mark = _recap.load_mark(state_dir)
    if mark.get("key") == _rc.once_key(o) and mark.get("outcome") in (_recap.TOLD, _recap.DROPPED):
        return LIVE, RECAP_SENT if mark["outcome"] == _recap.TOLD else SETTLED
    return STALE, {_recap.OFF: RECAP_OFF, _recap.DRY_RUN: RECAP_DRY_RUN}.get(_recap.mode(cfg), RECAP_WAITS)


def from_state(state_dir, cfg: Optional[Mapping], now: float, env: Optional[Mapping[str, str]] = None,
               hermes_home=None) -> tuple:
    """``stage`` over kevin-push's log at config ``push_log`` (delivery_audit.log_path): no log set or one that
    cannot be read is missing with that reason. Never raises; read-only."""
    try:
        path = _da.log_path(cfg, state_dir)
        if path is None:
            return stage(state_dir, None, cfg, now, _da.NO_LOG_REASON)
        got = _da.read_log(path)
        if got is None:
            return stage(state_dir, None, cfg, now, _da.UNREADABLE_REASON)
        return stage(state_dir, got[0], cfg, now, env=env, hermes_home=hermes_home)
    except Exception:  # noqa: BLE001 - a broken file is one row, never a traceback
        return MISSING, BROKEN
