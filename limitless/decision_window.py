"""Decision windows: deliver a proactive message when the person can use it, not on a clock.

A proactive job declares a ``window_class``:

- ``peak``: needs a decision; asked while focus is high (after waking, after a deep-work block).
- ``trough``: a review or a low-effort read; fine when energy dips.
- ``wind_down``: an end-of-day question; only once the evening has started.
- ``anytime``: capture or a short note; any moment the person is awake.

A pluggable ``WindowProvider`` says which class is open *now*. Providers decide from events
(woke up, screen off, focus block ended), never from clock times, so this module has no
times of day in it. ``decide()`` turns (job class, current window) into deliver | hold | drop
plus a one-line "why now / why not" reason; ``plain(reason)`` is that reason in plain words for the person
(the "Why now" line), digit-free.

Context (Hermes Agent, public):

- Proactivity roadmap, STEP 2: every recurring job states when it speaks and when it ends;
  pacing is "one message at the moment it matters".
  https://github.com/NousResearch/hermes-agent/issues/158538
- Schedule cards (STEP 1): the model proposes a job and the person approves it on a
  "Schedule this job?" card. A ``window_class`` is one more field that card can show.
  https://github.com/NousResearch/hermes-agent/pull/158289

Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, NamedTuple, Optional, Protocol, runtime_checkable

WINDOW_CLASSES = ("peak", "trough", "anytime", "wind_down")
UNKNOWN = "unknown"
MIN_CONFIDENCE = 0.5
DELIVER, HOLD, DROP = "deliver", "hold", "drop"


@dataclass(frozen=True)
class WindowState:
    """The window open now. ``since`` names the event that opened it (e.g. "wake"), not a time.

    ``hold_asks``: the provider says every non-critical message waits (e.g. a focus block runs).
    """

    cls: str
    since: Any = None
    source: str = ""
    confidence: float = 1.0
    hold_asks: bool = False


@runtime_checkable
class WindowProvider(Protocol):
    def current(self) -> WindowState: ...


class Decision(NamedTuple):
    action: str  # deliver | hold | drop
    reason: str  # one line: why now / why not


@dataclass(frozen=True)
class JobWindow:
    """What a job brings to the send gate: its declared class, the current window, peak budget left."""

    job_class: str
    state: Optional[WindowState]
    budget_left: int = 1


def _open_class(state: Optional[WindowState]) -> str:
    if state is None or state.cls not in WINDOW_CLASSES or state.confidence < MIN_CONFIDENCE:
        return UNKNOWN
    return state.cls


def _opened_by(state: Optional[WindowState]) -> str:
    return f" (since {state.since})" if state is not None and state.since not in (None, "") else ""


def decide(job_window_class: str, state: Optional[WindowState], *, budget_left: int, asleep: bool,
           critical: bool = False) -> Decision:
    """Deliver, hold or drop one proactive message.

    Order: critical delivers; asleep holds; a provider holding asks (focus block) holds;
    anytime delivers; an unknown window holds;
    a class mismatch holds; a peak job with no budget left in this peak window drops
    (one decision per peak window; the job's next run may ask again).
    """
    if job_window_class not in WINDOW_CLASSES:
        raise ValueError(f"window_class must be one of {WINDOW_CLASSES}, got {job_window_class!r}")
    if critical:
        return Decision(DELIVER, "critical: delivers whatever the window")
    if asleep:
        return Decision(HOLD, "asleep: holds until wake")
    if state is not None and state.hold_asks:
        return Decision(HOLD, f"focus block running{_opened_by(state)}: holds until it ends")
    if job_window_class == "anytime":
        return Decision(DELIVER, "anytime job and awake")
    now = _open_class(state)
    if now == UNKNOWN:
        return Decision(HOLD, f"window unknown: holds the {job_window_class} job until a provider knows")
    if now != job_window_class:
        return Decision(HOLD, f"{now} window open{_opened_by(state)}: holds the {job_window_class} job")
    if job_window_class == "peak" and budget_left <= 0:
        return Decision(DROP, "peak budget spent: one decision per peak window")
    return Decision(DELIVER, f"{now} window open{_opened_by(state)}")


# Plain words for the person: decide's reasons are for logs and rows; the "Why now" line says these.
_MOMENT = {"peak": "your focus is high right now", "trough": "it is a lighter moment, fine for a short read",
           "wind_down": "your wind-down has started", "anytime": "you are awake"}
_NEED = {"peak": "a moment when your focus is high", "trough": "a lighter moment", "wind_down": "your wind-down",
         "anytime": "a moment you are awake"}
_SINCE = r"(?: \(since [^()]*\))?"
_CLS = "(" + "|".join(WINDOW_CLASSES) + ")"
_PLAIN = (
    (re.compile(r"critical: delivers whatever the window"), lambda m: "this is urgent, so it comes whatever you are doing"),
    (re.compile(r"asleep: holds until wake"), lambda m: "you are asleep, so this waits until you wake"),
    (re.compile(rf"focus block running{_SINCE}: holds until it ends"),
     lambda m: "you are in a focus block, so this waits until it ends"),
    (re.compile(r"anytime job and awake"), lambda m: "you are awake and this fits any moment"),
    (re.compile(rf"window unknown: holds the {_CLS} job until a provider knows"),
     lambda m: f"it is not clear yet what kind of moment this is, so this waits for {_NEED[m[1]]}"),
    (re.compile(rf"{_CLS} window open{_SINCE}: holds the {_CLS} job"),
     lambda m: f"{_MOMENT[m[1]]}, so this waits for {_NEED[m[2]]}"),
    (re.compile(r"peak budget spent: one decision per peak window"),
     lambda m: "you already had one decision in this focused stretch, so this one is skipped"),
    (re.compile(rf"{_CLS} window open{_SINCE}"), lambda m: _MOMENT[m[1]]),
)


def plain(reason) -> str:
    """The plain words for one of decide's reasons, for the person: digit-free, no window or job jargon.
    Any other text is returned as it is (stripped); a non-string is ""."""
    if not isinstance(reason, str):
        return ""
    text = " ".join(reason.split())
    for pat, words in _PLAIN:
        m = pat.fullmatch(text)
        if m:
            return words(m)
    return text


class StaticProvider:
    """A fixed window, for tests and hosts that set the window by hand."""

    def __init__(self, cls: str, since: Any = None, confidence: float = 1.0):
        self._state = WindowState(cls=cls, since=since, source="static", confidence=confidence)

    def current(self) -> WindowState:
        return self._state


class StateFileProvider:
    """Reads ``{"cls": "peak", "since": "wake", "confidence": 0.9}`` from a JSON file on every call.

    Whatever writes the file (a phone automation, a wearable adapter) owns the event logic.
    A missing, unreadable or malformed file is an unknown window, never an error.
    """

    def __init__(self, path: str):
        self.path = path

    def current(self) -> WindowState:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            cls = data.get("cls")
            confidence = float(data.get("confidence", 1.0))
        except (OSError, ValueError, AttributeError, TypeError):
            return WindowState(cls=UNKNOWN, source="state_file", confidence=0.0)
        if cls not in WINDOW_CLASSES:
            return WindowState(cls=UNKNOWN, since=data.get("since"), source="state_file", confidence=0.0)
        return WindowState(cls=cls, since=data.get("since"), source="state_file", confidence=confidence)
