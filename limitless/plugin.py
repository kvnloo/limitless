"""Plugin wiring: tool schemas -> handlers, hooks. Uses only the published ctx API (hermes_cli/plugins_context.py):
ctx.register_tool(name, toolset, schema, handler, check_fn=None, requires_env=None, is_async=False,
description="", emoji="", override=False), ctx.register_hook(hook_name, callback) and, when the host has it,
ctx.register_command(name, handler, description="", args_hint="") for the ``/limitless mode`` slash command
(attention modes, modes.py). Hooks: pre_llm_call (the state card) and post_gateway_admission (bedtime capture,
bedtime.py).
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

from . import bedtime, capture, card, catchup, labeler, modes, scorecard, tier_audit, tools
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


def _overnight(args, now):
    return tools.overnight(_reader(), now)


def _rides(args, now):
    return tools.rides(_reader(), now, date.fromtimestamp(now), raw=card.raw_in_prompt(os.environ))


def _sleep(args, now):
    return tools.sleep(_reader(), now, date.fromtimestamp(now), raw=card.raw_in_prompt(os.environ))


def _quiet(args, now):
    return tools.quiet(state_dir(), now)


def _blocks(args, now):
    return tools.blocks(_reader(), now)


def _flow_metrics(args, now):
    return tools.flow_metrics(_reader(), now, raw=card.raw_in_prompt(os.environ))


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
        "focus block holds all but urgent asks. It only reads the queue: nothing is sent. `post_wake_peak` says "
        "whether the stretch right after the detected wake event (config post_wake_peak_h, default two hours; "
        "wording, not a target) is open, in use (a focus block started inside it), closed or unknown (no wake "
        "seen), in T1 words; while it is open the person's pre-planned task fits now. Cued by the wake event, "
        "never a clock time."), _window, "🪟"),
    "limitless_habit": (_schema(
        "limitless_habit",
        "This week's one habit, its 2-minute start and the check-ins so far (Done, No, Skipped), plus "
        "\"N of M logged days\". A 1-tap answer beats the phone sync's met/missed; a day with neither is "
        "unlogged, never a No, and stays out of M. phone_hint (seen, not seen or unknown; a proxy) says whether "
        "the phone saw a feed app in the first hour after the latest wake: a hint, never the answer. "
        "`target` is the weekly target so far (Done days toward most days of the week; No, Skipped and "
        "unlogged days never reduce it and nothing resets), labelled not started, on the way or target "
        "reached this week. "
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
    "limitless_overnight": (_schema(
        "limitless_overnight",
        "The overnight work queue (config work_queue_dir): how many tasks are running and queued, and how \
many finished (done or failed) since the latest wind-down, with a plain label (none, one, a few, many). \
Counts only: task names never appear. Read-only; nothing is sent."), _overnight, "🌙"),
    "limitless_rides": (_schema(
        "limitless_rides",
        "Bike rides from the exercise-session export (config rides_file; kinds in ride_kinds): rides in the \
last seven days against the seven before, in plain words: rides this week none, one, two or a few, and the \
same as, more than or fewer than last week. Counts and the label only; total minutes need the person's raw \
opt-in; heart rate and power are never read. A week with no ride is none, never missed: no target, no streak, \
no score, no advice. Read-only; nothing is sent."), _rides, "🚲"),
    "limitless_sleep": (_schema(
        "limitless_sleep",
        "Sleep over the last seven nights from two sources kept apart: the wearable's nightly summary (config \
sleep_file) and a phone proxy (the longest screen-off gap that starts in the evening half of the day), each \
with its modality and age. Plain words: wearable on most, some or no nights, and whether the phone proxy says \
about the same, shorter or longer. Counts and the label only; per-night minutes need the person's raw opt-in. \
measured only when the wearable covers the newest night, else proxy; a night with neither is unknown, never \
zero. regularity says how regular sleep times have been over two weeks, the source named: sleep times steady, \
vary a lot, drifting later or drifting earlier, or unknown with too few nights; never a clock time. A quiet \
phone is not a sleep measure. No target, no advice. Read-only; nothing is sent."), _sleep, "😴"),
    "limitless_quiet": (_schema(
        "limitless_quiet",
        "Whether pushes to the person's phone are muted now: mode on, off (until they reply on), quiet \
tonight (until they wake up) or snoozed (until they write again), whether a push would be dropped and the \
plain reason, with a label. The person sets it with one whole-message reply (quiet, quiet tonight, snooze, \
on); there are no clock times or durations. Read-only; nothing is written or sent."), _quiet, "🔕"),
    "limitless_blocks": (_schema(
        "limitless_blocks",
        "Deep-work focus blocks from app activity (the ActivityWatch DB; work apps in config flow_work_apps): \
whether the person is in a long block now (past break_after_min), between blocks, or unknown, with how many \
blocks and long blocks the last day had. A proxy: app activity, not attention. No work apps or no data is \
unknown, never zero. No score, no target; the only suggestion anywhere is a short break after a long block, \
sent by the break nudge job, never by this tool. Read-only; nothing is written or sent."), _blocks, "⏳"),
    "limitless_flow_metrics": (_schema(
        "limitless_flow_metrics",
        "How broken up the person's work was over the last seven days, from observed app activity (the \
ActivityWatch DB; work apps in config flow_work_apps): how often the foreground switched from a work app to \
another app per work hour, the share of work time in blocks of at least break_after_min, and how soon work \
resumed after such a switch, in plain words: work stayed in long blocks, work was broken up, mixed, or \
unknown with the reason. A proxy (evidence_tier observed-activity): app activity, not attention or output; no \
score, no target. Counts and the words only; the numbers need the person's raw opt-in. No work apps or no data \
is unknown, never zero. Read-only; nothing is written or sent."), _flow_metrics, "🧩"),
}


def _mode_command(raw_args: str) -> str:
    """/limitless mode [...]: the host's slash-command handler contract, fn(raw_args) -> str; never raises."""
    try:
        return modes.command(raw_args, state_dir())
    except Exception:  # noqa: BLE001 - a slash command must never raise into the session
        return modes.NOT_SET


def register(ctx) -> None:
    for name, (schema, fn, emoji) in TOOLS.items():
        ctx.register_tool(name=name, toolset=TOOLSET, schema=schema, handler=_handler(fn, name),
                          description=schema["description"], emoji=emoji)
    # /limitless mode brainstorm|pm|copilot|focused|off (attention modes: presentation only, modes.py);
    # a host without the slash-command API gets everything else
    if callable(getattr(ctx, "register_command", None)):
        ctx.register_command("limitless", _mode_command, description=modes.DESCRIPTION, args_hint=modes.ARGS_HINT)
    ctx.register_hook("pre_llm_call", card.make_pre_llm_call(
        clock=lambda: time.time(), today=lambda: date.fromtimestamp(time.time()), bands=_bands()))
    # after an absence over catchup_after_h, the first turn also gets a short catch-up (once per absence)
    ctx.register_hook("pre_llm_call", catchup.make_pre_llm_call(clock=lambda: time.time()))
    # bedtime capture (off unless config bedtime_capture is "on"): an admitted message in an asleep or
    # wind_down window is saved for tomorrow and acknowledged; any error lets it through to the agent
    ctx.register_hook("post_gateway_admission", bedtime.make_post_gateway_admission(clock=lambda: time.time()))
