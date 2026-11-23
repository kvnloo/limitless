"""The habit card: one recurring self-check, as a generic, data-free primitive any host can reuse.

    card = HabitCard("Lights down", "wind_down", start_s=120)    # name, event cue, a start of two minutes or less
    state = record(state, "2030-01-07", "Done")                  # Done / No: the day's entry; Skip: no entry
    week_number(state, "2030-01-07")                             # -> {"done", "logged", "unknown"} | None
    verdict_inputs(state, "2030-01-07", "most_done")             # -> what a Keep / Drop rule reads | None

A card is a name, a cue and a start. The cue is an EVENT name (``wake``, ``wind_down``, ``habit_cue``):
lowercase words joined by ``_``, no digit, so never a clock time, a cron string or an ``@daily`` macro. The
start is the card's first step, at most MAX_START_S seconds. The replies are fixed: Done, No, Skip.

The card state is a mapping with a ``checkins`` table, ``{ISO day: "Done" | "No"}``; every other key is the
host's and is carried through untouched. ``record`` returns a new state, never changing its input: Done
and No set the day's entry, Skip leaves the day with no entry (unlogged, not a No), and anything else
(no reply, a word that is not a reply) leaves the state as it was.

Unknown is not No. ``week_number`` is the one day-seven number for the seven days from ``week_start``:
``done`` (Done days), ``logged`` (Done + No days) and ``unknown`` (days with no Done or No entry: skipped,
unanswered or never asked). ``unknown`` is never counted as a No, so there is no rate over seven and no
"N of seven failed". No valid ``week_start`` is None, never zero.

``verdict_inputs`` hands a Keep / Drop rule what it reads (the week number, the rule id as given and the
two decisions); the rule itself lives with the host (limitless: stop_rule.verdict). There is no score.

Pure: nothing here sends, schedules, reads a clock or touches a file. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Tuple

DONE, NO, SKIP = "Done", "No", "Skip"
REPLIES = (DONE, NO, SKIP)
MAX_START_S = 120
_EVENT = re.compile(r"[a-z]+(?:_[a-z]+)*")


def is_event_name(v) -> bool:
    """True for an event name: lowercase letters in words joined by ``_``, no digit, space or colon."""
    return isinstance(v, str) and _EVENT.fullmatch(v) is not None


@dataclass(frozen=True)
class HabitCard:
    """One recurring self-check. ValueError for an empty name, a cue that is not an event name, a start over
    MAX_START_S (or not a whole number of seconds above zero) or replies other than REPLIES."""
    name: str
    cue: str
    start_s: int = MAX_START_S
    replies: Tuple[str, ...] = REPLIES

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError(f"a habit card needs a name, got {self.name!r}")
        object.__setattr__(self, "name", self.name.strip())
        if not is_event_name(self.cue):
            raise ValueError(f"the cue must be an event name (no clock time), got {self.cue!r}")
        s = self.start_s
        if not isinstance(s, int) or isinstance(s, bool) or not 0 < s <= MAX_START_S:
            raise ValueError(f"start_s must be a whole number of seconds from 1 to {MAX_START_S}, got {s!r}")
        if tuple(self.replies) != REPLIES:
            raise ValueError(f"the replies are {REPLIES}, got {self.replies!r}")
        object.__setattr__(self, "replies", REPLIES)
