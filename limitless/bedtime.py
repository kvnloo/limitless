"""Bedtime capture: after wind-down or while asleep, an owner message is saved for tomorrow, not started.

    route(text, window_class, opt_out) -> {"action": "capture" | "pass", "reply": str | None}

Capture applies only when the window from state (window_chain: Glide's wind-down nudge, Sleep mode) is
``asleep`` or ``wind_down``; it never reads a clock time. A slash command, a message with an urgent word
(config ``bedtime_urgent_words``, default ``["urgent", "now"]``, whole words, any case) and a bare habit
or week answer (Done, No, Skip, Keep, Drop: their own jobs read those) pass to the agent as usual.
Config ``bedtime_capture``: ``"on"`` turns it on; anything else (the default) is off.

    make_post_gateway_admission(env, clock) -> the Hermes ``post_gateway_admission`` hook

That hook (hermes_cli/plugins.py VALID_HOOKS; gateway/run_inbound_consumer.py) fires once per admitted
inbound gateway message, after auth and slash-command dispatch, with ``text``. Returning
``{"action": "handled", "reply": ...}`` skips the agent turn and delivers ``reply`` on the normal route;
anything else runs the turn. A capture is written through ``capture.capture`` (one store, source
``"bedtime"``) before ``handled`` is returned; a refused capture, or any error, returns None so the
message reaches the agent untouched. The text is never logged: only the capture file holds it.
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional

from . import capture, habit_replies
from .glide_provider import GlideProvider
from .state_reader import StateReader, config, state_dir
from .window_chain import EventProvider, first_known

logger = logging.getLogger(__name__)
SOURCE = "bedtime"

CAPTURE_CLASSES = ("asleep", "wind_down")
DEFAULT_URGENT_WORDS = ("urgent", "now")
REPLY = "Saved for tomorrow."
CONFIG_KEY, WORDS_KEY = "bedtime_capture", "bedtime_urgent_words"
CAPTURE, PASS = "capture", "pass"


def enabled(cfg: Mapping) -> bool:
    """True only when config says ``"bedtime_capture": "on"``."""
    return isinstance(cfg, Mapping) and cfg.get(CONFIG_KEY) == "on"


def urgent_words(cfg: Mapping) -> list:
    """The configured urgent words (a list of strings, lower-cased), else the default."""
    v = cfg.get(WORDS_KEY) if isinstance(cfg, Mapping) else None
    if not isinstance(v, list):
        return list(DEFAULT_URGENT_WORDS)
    return [w.strip().lower() for w in v if isinstance(w, str) and w.strip()]


def _urgent(text: str, words: Iterable[str]) -> bool:
    low = text.lower()
    return any(re.search(r"(?<!\w)" + re.escape(w.lower()) + r"(?!\w)", low) for w in words if w)


def _pass() -> dict:
    return {"action": PASS, "reply": None}


def route(message_text, window_class: Optional[str], opt_out: bool,
          urgent_words: Iterable[str] = DEFAULT_URGENT_WORDS) -> dict:
    """Capture or pass one inbound message. ``opt_out`` True (bedtime capture off) always passes."""
    if opt_out or window_class not in CAPTURE_CLASSES:
        return _pass()
    if not isinstance(message_text, str) or not message_text.strip():
        return _pass()
    text = message_text.strip()
    if text.startswith("/") or _urgent(text, urgent_words):
        return _pass()
    if len(text.split()) == 1 and (habit_replies.tap(text) or habit_replies.decision(text)):
        return _pass()
    return {"action": CAPTURE, "reply": REPLY}


def window_class(state, now: float, env: Optional[Mapping[str, str]] = None,
                 home: Optional[Path] = None) -> str:
    """The window open now, as jobs_runner reads it: asleep (Sleep mode), else first_known(Glide, events)."""
    events = EventProvider.from_reader(StateReader(Path(state)), now)
    if events.asleep:
        return "asleep"
    return first_known(GlideProvider.from_config(env=env, home=home, now=now), events).cls


def make_post_gateway_admission(env: Optional[Mapping[str, str]] = None,
                                clock: Callable[[], float] = time.time):
    def post_gateway_admission(text=None, **kwargs) -> Optional[dict]:
        try:
            e = os.environ if env is None else env
            cfg = config(e)
            if not enabled(cfg) or not isinstance(text, str):
                return None
            now, state = clock(), state_dir(e)
            out = route(text, window_class(state, now, env=e), False, urgent_words(cfg))
            if out["action"] != CAPTURE:
                return None
            saved = capture.capture(state, text, now, source=SOURCE)
            if saved.get("value") is None:
                return None                       # nothing recorded: the agent gets the message
            return {"action": "handled", "reply": out["reply"]}
        except Exception as exc:  # noqa: BLE001 - fail open: never drop the person's message
            logger.debug("bedtime capture skipped (%s); the message goes to the agent", type(exc).__name__)
            return None

    return post_gateway_admission
