"""Window chain: ask providers in order and take the first window that is known.

    state = first_known(GlideProvider.from_config(now=now), EventProvider.from_reader(reader, now))
    decide(job_class, state, budget_left=..., asleep=events.asleep)

Glide goes first (focus blocks, the wind-down nudge), then the Sleep-mode/unlock classifier in
``window.py`` adapted to ``WindowState``. Asleep is a flag on ``EventProvider``, not a window
class: it feeds ``decide(asleep=...)`` and the provider's own window reads as unknown.
No provider here reads the clock; ``now`` comes from the caller. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

from typing import Mapping, Optional

from .decision_window import MIN_CONFIDENCE, UNKNOWN, WINDOW_CLASSES, WindowState
from .state_reader import StateReader
from .window import classify


def _known(state) -> bool:
    return (isinstance(state, WindowState) and state.cls in WINDOW_CLASSES
            and state.confidence >= MIN_CONFIDENCE)


def first_known(*providers) -> WindowState:
    """The first provider state that is not unknown; None or failing providers are skipped."""
    for provider in providers:
        if provider is None:
            continue
        try:
            state = provider.current()
        except Exception:  # noqa: BLE001 - one broken source must not stop the chain
            continue
        if _known(state):
            return state
    return WindowState(cls=UNKNOWN, source="chain", confidence=0.0)


class EventProvider:
    """``window.classify`` (Sleep mode, wake event, last unlock) as a ``WindowProvider``."""

    def __init__(self, sleep_rows: list, poll: Optional[dict], last_unlock: Optional[dict], *, now: float,
                 bands: Optional[Mapping] = None):
        self.classification = classify(sleep_rows, poll, last_unlock, now=now, bands=bands)

    @classmethod
    def from_reader(cls, reader: StateReader, now: float, bands: Optional[Mapping] = None) -> "EventProvider":
        return cls(reader.sleepmode(), reader.sleepmode_poll(), reader.last_unlock(), now=now, bands=bands)

    @property
    def asleep(self) -> bool:
        return self.classification.get("value") == "asleep"

    def current(self) -> WindowState:
        value = self.classification.get("value")
        if value in WINDOW_CLASSES:
            return WindowState(cls=value, since="wake", source="events")
        return WindowState(cls=UNKNOWN, source="events", confidence=0.0)
