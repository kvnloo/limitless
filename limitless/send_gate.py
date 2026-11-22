"""Send gate: the one policy every push to Kevin passes through."""
from __future__ import annotations

import hashlib
import re

from . import decision_window

DAILY_CAP, DEDUP_S = 6, 12 * 3600
ALWAYS = {("limitless", "Wake-up brief"), ("limitless", "Back from nap"), ("limitless", "MIQ for tonight?")}
# 'Asks waiting on you' hit the cap 133x on 11-21 and starved real messages: it becomes one brief line.
FOLD = {"asks"}
# Two senders can word one event differently; the event key lets only the first through.
ONCE_DROP = "already sent for this event"

# Kanban card ids (t_510c250d) mean nothing to Kevin: plain words only.
_CARD_ID = re.compile(r"[ \t]*\bt_[0-9a-f]{6,12}\b:?")


def scrub(text: str) -> str:
    return _CARD_ID.sub("", text)


def key(title: str, body: str) -> str:
    return hashlib.sha256(f"{scrub(title)}\n{scrub(body)}".encode()).hexdigest()[:16]


def once_sent(sent: list, once_key: "str | None", now: float) -> bool:
    """True when a send in `sent` already claimed `once_key` within the 12 h dedupe window."""
    if not once_key:
        return False
    return any(isinstance(s, dict) and s.get("once") == once_key and isinstance(s.get("t"), (int, float))
               and now - s["t"] < DEDUP_S for s in sent)


def decide(tag: str, title: str, body: str, cls: str, now: float, sent: list, asleep: bool,
           window: "decision_window.JobWindow | None" = None, once_key: "str | None" = None) -> str:
    """Return send | log | fold | hold | drop | duplicate | cap. `sent` = [{t, k[, once]}] Telegram sends.

    `window` (optional) gates on the job's decision window: hold when its window is not open,
    drop when the peak budget is spent. Without it every result is as before.
    `once_key` (optional) names the event the message is about (e.g. "wake_brief:<event time>"):
    drop (ONCE_DROP) when a send already claimed it within 12 h, whatever its words. Without it
    every result is as before.
    """
    if tag in FOLD:
        return "fold"
    if not (cls in ("decision", "critical") or (tag, title) in ALWAYS):
        return "log"
    if once_sent(sent, once_key, now):
        return "drop"   # before the sleep hold: a held message is replayed later, this one must not be
    if cls != "critical" and title != "Back from nap" and asleep:
        return "hold"
    if window is not None:
        # Sleep was handled above (with its nap exception), so the window check sees asleep=False.
        w = decision_window.decide(window.job_class, window.state, budget_left=window.budget_left,
                                   asleep=False, critical=cls == "critical")
        if w.action != decision_window.DELIVER:
            return w.action
    k = key(title, body)
    recent = [s for s in sent if now - s["t"] < 86400]
    if any(s["k"] == k and now - s["t"] < DEDUP_S for s in recent):
        return "duplicate"
    if len(recent) >= DAILY_CAP:
        return "cap"
    return "send"
