"""Plugin wiring: tool schemas -> handlers, hooks. Uses only the published ctx API (hermes_cli/plugins_context.py):
ctx.register_tool(name, toolset, schema, handler, check_fn=None, requires_env=None, is_async=False,
description="", emoji="", override=False) and ctx.register_hook(hook_name, callback).
Handlers follow the documented contract: handler(args: dict, **kwargs) -> str (JSON), never raising.
Every result is an evidence envelope (envelope.py).
"""
from __future__ import annotations

import json
import os
import time
from datetime import date
from typing import Callable

from . import capture, card, tools
from .envelope import missing
from .state_reader import StateReader, config, state_dir
from .window import window

TOOLSET = "limitless"
_ENVELOPE = ("Returns an evidence envelope {value, modality (measured|imported|proxy|self_report), age_h, "
             "evidence_tier}; value null means no data and comes with a reason. Never guess a missing value.")


def _bands():
    b = config().get("window_bands")
    return b if isinstance(b, dict) else None


def _reader() -> StateReader:
    return StateReader(state_dir())


def _status(args, now):
    return tools.status(_reader(), now)


def _state(args, now):
    return card.state(_reader(), now, date.fromtimestamp(now), raw=card.raw_in_prompt(os.environ), bands=_bands())


def _window(args, now):
    return window(_reader(), now, _bands())


def _habit(args, now):
    return tools.habit(_reader(), now, date.fromtimestamp(now))


def _capture(args, now):
    return capture.capture(state_dir(), args.get("text"), now)


def _handler(fn: Callable) -> Callable:
    def handler(args: dict, **kwargs) -> str:
        try:
            env = fn(args if isinstance(args, dict) else {}, time.time())
        except Exception as exc:  # the handler contract: report, never raise into the agent loop
            env = missing(f"{type(exc).__name__}: {exc}")
        return json.dumps(env, ensure_ascii=False)
    handler.__name__ = fn.__name__.lstrip("_")
    return handler


def _schema(name: str, description: str, properties=None, required=()) -> dict:
    params = {"type": "object", "properties": properties or {}}
    if required:
        params["required"] = list(required)
    return {"name": name, "description": f"{description} {_ENVELOPE}", "parameters": params}


TOOLS = {
    "limitless_status": (_schema(
        "limitless_status",
        "Freshness of each Limitless input (wearable, phone, scale, ...): its age in hours, which inputs "
        "are not recording (over a day old or down) and when the pipeline last ran."), _status, "📡"),
    "limitless_state": (_schema(
        "limitless_state",
        "Today's state card: decision window, sleep and readiness as coarse labels with their modality, "
        "this week's habit and inputs that are not recording. Labels only, no advice."), _state, "🧭"),
    "limitless_window": (_schema(
        "limitless_window",
        "The current decision window: peak, trough, anytime, asleep or unknown, inferred from state "
        "events (phone Sleep mode, the wake event, the last unlock), never from the clock. Ask for "
        "decisions in peak, reviews in trough; capture works anytime."), _window, "🪟"),
    "limitless_habit": (_schema(
        "limitless_habit",
        "This week's one habit, its 2-minute start and the check-ins so far (Done, No, Skipped). A day "
        "with no answer is unlogged, never a No."), _habit, "🌱"),
    "limitless_capture": (_schema(
        "limitless_capture",
        "Record one thought, idea or to-do for later triage by appending it to the capture log. It only "
        "records: do not start, plan or delegate the captured item.",
        {"text": {"type": "string", "description": "The captured text, verbatim."}}, ["text"]),
        _capture, "📝"),
}


def register(ctx) -> None:
    for name, (schema, fn, emoji) in TOOLS.items():
        ctx.register_tool(name=name, toolset=TOOLSET, schema=schema, handler=_handler(fn),
                          description=schema["description"], emoji=emoji)
    ctx.register_hook("pre_llm_call", card.make_pre_llm_call(
        clock=lambda: time.time(), today=lambda: date.fromtimestamp(time.time()), bands=_bands()))
