"""Plugin wiring: tool schemas -> handlers, hooks. Uses only the published ctx API (hermes_cli/plugins_context.py):
ctx.register_tool(name, toolset, schema, handler, check_fn=None, requires_env=None, is_async=False,
description="", emoji="", override=False) and ctx.register_hook(hook_name, callback). Hooks: pre_llm_call (the
state card) and post_gateway_admission (bedtime capture, bedtime.py).
Handlers follow the documented contract: handler(args: dict, **kwargs) -> str (JSON), never raising.
Every result is an evidence envelope (envelope.py), with a T1 age label next to a non-null value; every labeled
result is recorded by tier_audit (content-free).
"""
from __future__ import annotations

import json
import os
import time
from datetime import date
from typing import Callable

from . import bedtime, capture, card, catchup, labeler, scorecard, tier_audit, tools
from .envelope import missing
from .state_reader import StateReader, config, state_dir

TOOLSET = "limitless"
_ENVELOPE = ("Returns an evidence envelope {value, modality (measured|imported|proxy|self_report|messages), age_h, "
             "evidence_tier}; value null means no data and comes with a reason. Never guess a missing value.")


def _bands():
    b = config().get("window_bands")
    return b if isinstance(b, dict) else None


def _reader() -> StateReader:
    return StateReader(state_dir())


def _status(args, now):
    return tools.status(_reader(), now)


def _state(args, now):
    return card.state(_reader(), now, date.fromtimestamp(now), raw=card.raw_in_prompt(os.environ), bands=_bands(),
                      labeler=labeler.from_config())


def _window(args, now):
    return tools.window(_reader(), now, _bands())


def _habit(args, now):
    today, confirm = date.fromtimestamp(now), args.get("confirm") is True
    if args.get("start") is not None:
        return tools.habit_start(state_dir(), args.get("start"), today, now, confirm=confirm)
    if args.get("predict") is not None:
        return tools.habit_predict(state_dir(), args.get("predict"), args.get("metric", "logged"),
                                   args.get("direction"), today, now, confirm=confirm)
    if args.get("receipt") is True:
        return tools.habit_receipt(state_dir(), today, now, confirm=confirm)
    return tools.habit(_reader(), now, today)


def _scorecard(args, now):
    return tools.scorecard(scorecard.path(), now)


def _capture(args, now):
    return capture.capture(state_dir(), args.get("text"), now)


def _catchup(args, now):
    return catchup.tool(_reader(), now)


def _body(args, now):
    return tools.body(_reader(), now, date.fromtimestamp(now), raw=card.raw_in_prompt(os.environ))


def _handler(fn: Callable, name: str = "") -> Callable:
    def handler(args: dict, **kwargs) -> str:
        try:
            now = time.time()
            env = tools.labeled(fn(args if isinstance(args, dict) else {}, now))
            # every labeled result is audited; a digit-bearing label without the opt-in is dropped
            env = tier_audit.audit_result(f"tool:{name or handler.__name__}", env,
                                          card.raw_in_prompt(os.environ), now=now)
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
        "this week's habit, inputs that are not recording and whether the person wrote to an agent recently "
        "(from every configured session DB). Labels only, no advice."), _state, "🧭"),
    "limitless_window": (_schema(
        "limitless_window",
        "The current decision window: peak, trough, anytime, asleep or unknown, inferred from state "
        "events (phone Sleep mode, the wake event, the last unlock), never from the clock. Ask for "
        "decisions in peak, reviews in trough; capture works anytime. `asks` plans the queue of asks waiting on "
        "the person (LIMITLESS_ASKS or config asks_path): deliver, hold and fold counts and a plain label "
        "(one decision ready, decisions waiting, nothing waiting); at most one decision per peak window, a "
        "focus block holds all but urgent asks. It only reads the queue: nothing is sent."), _window, "🪟"),
    "limitless_habit": (_schema(
        "limitless_habit",
        "This week's one habit, its 2-minute start and the check-ins so far (Done, No, Skipped), plus "
        "\"N of M logged days\". A 1-tap answer beats the phone sync's met/missed; a day with neither is "
        "unlogged, never a No, and stays out of M. phone_hint (seen, not seen or unknown; a proxy) says whether "
        "the phone saw a feed app in the first hour after the latest wake: a hint, never the answer. "
        "With `start` it starts this week's one habit instead: "
        "pass `confirm: true` only after the person said yes to that habit in this turn; without it nothing "
        "is written and the result says what would happen. A running week is never replaced. "
        "`prediction` shows a prediction locked for the week and its receipt when present. With `predict` it "
        "locks one prediction for the week before its check-ins (`metric` logged with `direction` "
        "\"at_least k of m\", or sleep_h / readiness with up or down); with `receipt` it judges the locked "
        "prediction after day seven: supports, contradicts or inconclusive. Both write only with "
        "`confirm: true` after the person said yes in this turn; a locked prediction or receipt is never "
        "rewritten.",
        {"start": {"type": "string", "description": "The habit to start this week, in the person's words. "
                                                    "Only after the person asked to start a habit."},
         "predict": {"type": "string", "description": "The person's prediction for this habit week, in "
                                                      "their words. Only when they asked to lock one."},
         "metric": {"type": "string", "enum": ["logged", "sleep_h", "readiness"],
                    "description": "What the prediction is about: logged (N of M logged days, the default) "
                                   "or a named state metric."},
         "direction": {"type": "string", "description": "For logged: \"at_least k of m\"; for a state "
                                                        "metric: up or down against the week before."},
         "receipt": {"type": "boolean", "description": "true to judge the locked prediction after day seven."},
         "confirm": {"type": "boolean", "description": "true only when the person said yes to starting "
                                                      "this habit, locking this prediction or writing this "
                                                      "receipt in this turn; otherwise leave it out."}}),
        _habit, "🌱"),
    "limitless_scorecard": (_schema(
        "limitless_scorecard",
        "The north-star scorecard block for the weekly review: at most 5 plain lines with the green, amber "
        "and red counts, whether every criterion has been green for 4 weeks, and the three criteria furthest "
        "from green. Counts only: it never says the north star is met. Read from the hand-kept scorecard "
        "table (self-reported)."), _scorecard, "🎯"),
    "limitless_capture": (_schema(
        "limitless_capture",
        "Record one thought, idea or to-do for later triage by appending it to the capture log. It only "
        "records: do not start, plan or delegate the captured item.",
        {"text": {"type": "string", "description": "The captured text, verbatim."}}, ["text"]),
        _capture, "📝"),
    "limitless_catchup": (_schema(
        "limitless_catchup",
        "A short catch-up since the person last wrote to an agent: at most 5 plain lines, TLDR first with at \
most one next step, then inputs not recording, the habit week, messages sent and captures saved while away \
(none, one, a few, many; unknown when the source is missing) and asks waiting. The label says away (gap \
over catchup_after_h, default a day) or not away. Read-only; nothing is sent."), _catchup, "🧳"),
    "limitless_body": (_schema(
        "limitless_body",
        "The body fat trend from the body-composition file (config body_file): the median of the last two \
weeks against the two weeks before, in plain words: trending down, flat or up (calibrated or uncalibrated \
estimate), or not enough measurements. Counts and the label only; raw numbers need the person's raw opt-in. \
A direction only: no score, no goal, no advice. Read-only; nothing is sent."), _body, "⚖️"),
}


def register(ctx) -> None:
    for name, (schema, fn, emoji) in TOOLS.items():
        ctx.register_tool(name=name, toolset=TOOLSET, schema=schema, handler=_handler(fn, name),
                          description=schema["description"], emoji=emoji)
    ctx.register_hook("pre_llm_call", card.make_pre_llm_call(
        clock=lambda: time.time(), today=lambda: date.fromtimestamp(time.time()), bands=_bands()))
    # after an absence over catchup_after_h, the first turn also gets a short catch-up (once per absence)
    ctx.register_hook("pre_llm_call", catchup.make_pre_llm_call(clock=lambda: time.time()))
    # bedtime capture (off unless config bedtime_capture is "on"): an admitted message in an asleep or
    # wind_down window is saved for tomorrow and acknowledged; any error lets it through to the agent
    ctx.register_hook("post_gateway_admission", bedtime.make_post_gateway_admission(clock=lambda: time.time()))
