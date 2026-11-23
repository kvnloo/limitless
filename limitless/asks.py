"""Asks: every needs-the-person ask carries a window class; at most one decision per peak window.

An ask is one row of a host's queue of things that need the person (an approval, a decision, an FYI).
This module is the adapter between that queue and the decision window; it never rebuilds the queue.

``classify(ask)`` reads the ask's own fields, never the clock:

- ``kind: decision``, or ``kind: approval`` with ``effort: deep`` -> ``peak``;
- ``kind: approval`` with ``effort: light`` (or no effort) -> ``anytime``;
- ``kind: fyi`` -> ``trough``;
- anything else -> ``anytime``: an ask with an unknown kind is never dropped.

``plan(asks, window, sent_this_window)`` says what happens to each ask now, as
``(ask_id, action, reason)`` with action deliver | hold | fold, in queue order:

- ``urgent: true`` delivers whatever the window and never counts against the peak limit;
- a focus block (a provider with ``hold_asks``, e.g. Glide) holds everything else until it ends;
- ``trough`` (an FYI) folds into the next brief line;
- asleep holds the rest until wake;
- ``anytime`` delivers, which means: it passes to the send gate (dedupe, daily cap);
- ``peak`` delivers in a peak window, at most ONE per window, oldest first, and only when
  ``sent_this_window`` is zero; every other peak ask holds for the next peak window.

Each reason starts with the ask's ``title`` in plain words: internal card ids (``t_510c250d``) are
removed with the send gate's ``scrub``.

The queue is JSONL, one ask per line, at ``$LIMITLESS_ASKS`` or config ``asks_path``:

    {"id", "kind": decision|approval|fyi, "effort": deep|light, "title", "at", "urgent": bool,
     "answers": ["Approve", "Deny", "Later"],   # optional one-tap replies; default Yes / No / Later
     "delivered_at": epoch | iso}   # set by the host once the ask really reached the person

This module only reads it. A missing, unreadable or malformed file is an empty plan; a bad line
is skipped. A row with ``delivered_at`` is done and is not planned again.

One tap: ``render(ask)`` is the ask as the person sees it, its title then one choices line from its own
``answers`` field (2-4 one-word options), default ``Reply: Yes / No / Later``. ``reply(ask, text)`` reads
a reply back whole (one_tap.parse, as the habit replies are read): an option is ``answered``; ``Later``
or anything else leaves the ask ``waiting``, never a no.

The window comes from the decision-window chain (``window_chain.first_known``), a
``decision_window.WindowState`` or a ``window.py`` envelope; nothing here reads a clock.

Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Optional, Tuple

from . import decision_window, jobs, one_tap
from .send_gate import scrub
from .state_reader import config, parse_ts

ENV_KEY, CONFIG_KEY = "LIMITLESS_ASKS", "asks_path"
TITLE_MAX = 80

PEAK, TROUGH, ANYTIME = "peak", "trough", "anytime"
DELIVER, HOLD, FOLD = "deliver", "hold", "fold"
ACTIONS = (DELIVER, HOLD, FOLD)

Row = Tuple[Any, str, str]


def _word(v: Any) -> str:
    return v.strip().lower() if isinstance(v, str) else ""


def classify(ask: Any) -> str:
    """peak | trough | anytime from the ask's ``kind`` and ``effort``."""
    if not isinstance(ask, dict):
        return ANYTIME
    kind, effort = _word(ask.get("kind")), _word(ask.get("effort"))
    if kind == "decision" or (kind == "approval" and effort == "deep"):
        return PEAK
    if kind == "fyi":
        return TROUGH
    return ANYTIME


def _open_peak(state) -> bool:
    return (state is not None and state.cls == PEAK and state.confidence >= decision_window.MIN_CONFIDENCE)


def _count(sent: Any) -> int:
    if isinstance(sent, bool):
        return int(sent)
    if isinstance(sent, (int, float)):
        return max(0, int(sent))
    try:
        return len(sent)  # a list of the asks already delivered in this window
    except TypeError:
        return 0


def _age_order(rows: list) -> list:
    """Indexes of rows, oldest ``at`` first; undated rows last, in queue order."""
    def k(i):
        t = parse_ts(rows[i].get("at")) if isinstance(rows[i], dict) else None
        return (t is None, t if t is not None else 0.0, i)
    return sorted(range(len(rows)), key=k)


def _why_not_peak(state) -> str:
    if state is None or state.cls not in decision_window.WINDOW_CLASSES \
            or state.confidence < decision_window.MIN_CONFIDENCE:
        return "decision held: the window is unknown; waits for a peak window"
    return f"decision held: a {state.cls} window is open; waits for a peak window"


def _decide(ask: Any, cls: str, state, asleep: bool, peak_free: bool) -> Tuple[str, str]:
    if isinstance(ask, dict) and ask.get("urgent") is True:
        return DELIVER, "urgent: delivers whatever the window"
    if state is not None and state.hold_asks:
        return HOLD, "focus block running: holds until it ends"
    if cls == TROUGH:
        return FOLD, "for your information: folds into the next brief line"
    if asleep:
        return HOLD, "asleep: holds until wake"
    if cls == ANYTIME:
        return DELIVER, "anytime ask: passes to the send gate"
    if not _open_peak(state):
        return HOLD, _why_not_peak(state)
    if not peak_free:
        return HOLD, "decision held: one decision per peak window; waits for the next peak window"
    return DELIVER, "peak window open: the one decision for this window"


def plan(asks: Optional[Iterable], window: Any, sent_this_window: Any = 0) -> List[Row]:
    """One (ask_id, deliver | hold | fold, reason) per ask, in queue order. Pure: sends nothing."""
    rows = list(asks or ())
    state, asleep = jobs._window(window)
    peak_free = _count(sent_this_window) == 0
    out = {}
    for i in _age_order(rows):
        ask = rows[i]
        cls = classify(ask)
        action, why = _decide(ask, cls, state, asleep, peak_free)
        if action == DELIVER and cls == PEAK and not (isinstance(ask, dict) and ask.get("urgent") is True):
            peak_free = False
        out[i] = (ask.get("id") if isinstance(ask, dict) else None, action, _reason(ask, why))
    return [out[i] for i in range(len(rows))]


def _title(ask: Any) -> str:
    title = ask.get("title") if isinstance(ask, dict) else None
    return " ".join(scrub(title).split()).strip(" :")[:TITLE_MAX] if isinstance(title, str) else ""


def _reason(ask: Any, why: str) -> str:
    title = _title(ask)
    return scrub(f"{title}: {why}" if title else why)


# One tap (L14): an ask the person sees ends in its own choices line; a reply is read back whole.
NO_TITLE = "Something is waiting on you"
LATER = "Later"
ANSWERED, REPLY_WAITING = "answered", "waiting"   # reply() actions; WAITING is the summary label


def answers(ask: Any) -> tuple:
    """The ask's one-tap replies: its own ``answers`` field when that is 2-4 one-word options
    (one_tap.options_ok), else Yes / No / Later."""
    own = ask.get("answers") if isinstance(ask, dict) else None
    if isinstance(own, (list, tuple)) and one_tap.options_ok(own):
        return tuple(own)
    return one_tap.YES_NO_LATER


def render(ask: Any) -> str:
    """The text the person gets for one ask: its title in plain words (card ids removed, one line), then its
    choices line, so one_tap.is_one_tap holds. Pure: the host sends it, through the send gate."""
    return f"{_title(ask) or NO_TITLE}\n{one_tap.choices_line(answers(ask))}"


def reply(ask: Any, text: Any) -> dict:
    """``{id, answer, action, reason}`` for one reply to a rendered ask: ``answered`` with the option the whole
    reply names (one_tap.parse), else ``waiting``. Later is always waiting, never a no; any other reply
    changes nothing. Pure: never echoes the reply, never writes the queue (the host sets ``delivered_at``)."""
    aid = ask.get("id") if isinstance(ask, dict) else None
    got = one_tap.parse(text, answers(ask))
    if got is None:
        return {"id": aid, "answer": None, "action": REPLY_WAITING, "reason": "not one of its choices: the ask stays waiting"}
    if got.lower() == LATER.lower():
        return {"id": aid, "answer": got, "action": REPLY_WAITING, "reason": "Later: the ask stays waiting, never a no"}
    return {"id": aid, "answer": got, "action": ANSWERED, "reason": "a whole reply that names one of its choices"}


def queue_path(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> Optional[str]:
    """$LIMITLESS_ASKS, else ``asks_path`` in config.json; None when neither names a path."""
    env = os.environ if env is None else env
    path = env.get(ENV_KEY) or config(env, home).get(CONFIG_KEY)
    return path if isinstance(path, str) and path else None


def read(path: Optional[str]) -> list:
    """The dict rows of the JSONL queue at ``path``; [] when it is missing or unreadable. Never writes."""
    if not path:
        return []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except (OSError, ValueError):
        return []
    rows = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def pending(rows: Iterable) -> list:
    """The asks still waiting: rows without ``delivered_at``."""
    return [r for r in rows if isinstance(r, dict) and r.get("delivered_at") in (None, "")]


def delivered_since(rows: Iterable, since: Optional[float]) -> int:
    """Peak asks (not urgent) the host delivered at or after ``since`` (the event that opened the window)."""
    if since is None:
        return 0
    n = 0
    for r in rows:
        if not isinstance(r, dict) or r.get("urgent") is True or classify(r) != PEAK:
            continue
        t = parse_ts(r.get("delivered_at"))
        if t is not None and t >= since:
            n += 1
    return n


READY, WAITING, NOTHING = "one decision ready", "decisions waiting", "nothing waiting"


def summary(asks: Iterable, planned: List[Row]) -> dict:
    """``{deliver, hold, fold}`` counts and a digit-free T1 label: one decision ready (a peak or urgent
    ask delivers now), decisions waiting (an ask holds), else nothing waiting. Anytime asks go through the
    send gate and FYIs into the brief, so they alone are nothing waiting. No titles, no ids."""
    rows = list(asks or ())
    counts = {a: 0 for a in ACTIONS}
    ready = False
    for ask, (_, action, _) in zip(rows, planned):
        counts[action] += 1
        urgent = isinstance(ask, dict) and ask.get("urgent") is True
        ready = ready or (action == DELIVER and (urgent or classify(ask) == PEAK))
    word = READY if ready else WAITING if counts[HOLD] else NOTHING
    return dict(counts, label={"label": word, "tier": "T1", "modality": None})


def plan_queue(window: Any, sent_this_window: Any = 0, env: Optional[Mapping[str, str]] = None,
               home: Optional[Path] = None) -> List[Row]:
    """plan() over the pending asks of the configured queue; [] when there is no readable queue."""
    return plan(pending(read(queue_path(env, home))), window, sent_this_window)
