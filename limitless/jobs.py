"""Event-triggered job specs: the wake brief, the post-nap message, the bedtime question, the habit check-in.

A job says which event wakes it (``trigger_event``), which decision window it speaks in
(``window_class``), how often it may speak per window and which event ends it. There are no
clock times and no cron strings here: a test fails if a spec grows one.

Everything is a pure function. Nothing in this module sends; delivery stays in ``bin/kevin-push``.
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from .decision_window import WINDOW_CLASSES

# Events a job can wake on or end on. sleep_mode_on/off come from the phone; wake is a Sleep-mode
# off after a long on; wind_down and habit_cue come from whatever automation marks them.
EVENTS = ("wake", "sleep_mode_on", "sleep_mode_off", "wind_down", "habit_cue", "focus_end")
TRIGGER_AFTER = ("", "short_on")


@dataclass(frozen=True)
class JobSpec:
    name: str
    trigger_event: str
    window_class: str
    send_title: str
    max_per_window: int
    expires: str
    trigger_after: str = ""                  # "short_on": only a Sleep-mode off after a short on (a nap)
    answers: Tuple[str, ...] = ()            # 1-tap replies the message offers

    def __post_init__(self):
        if self.trigger_event not in EVENTS:
            raise ValueError(f"trigger_event must be one of {EVENTS}, got {self.trigger_event!r}")
        if self.expires not in EVENTS:
            raise ValueError(f"expires must be one of {EVENTS}, got {self.expires!r}")
        if self.window_class not in WINDOW_CLASSES:
            raise ValueError(f"window_class must be one of {WINDOW_CLASSES}, got {self.window_class!r}")
        if self.trigger_after not in TRIGGER_AFTER:
            raise ValueError(f"trigger_after must be one of {TRIGGER_AFTER}, got {self.trigger_after!r}")
        if not isinstance(self.max_per_window, int) or self.max_per_window < 1:
            raise ValueError(f"max_per_window must be a positive int, got {self.max_per_window!r}")


WAKE_BRIEF = JobSpec("wake_brief", "wake", "anytime", "Wake-up brief", 1, "sleep_mode_on")
NAP = JobSpec("nap", "sleep_mode_off", "anytime", "Back from nap", 1, "sleep_mode_on", trigger_after="short_on")
MIQ = JobSpec("miq", "wind_down", "wind_down", "MIQ for tonight?", 1, "sleep_mode_on")
HABIT_CHECKIN = JobSpec("habit_checkin", "habit_cue", "anytime", "Habit check-in", 1, "sleep_mode_on",
                        answers=("Done", "No", "Skip"))
SPECS = {s.name: s for s in (WAKE_BRIEF, NAP, MIQ, HABIT_CHECKIN)}


def wake_brief(decision: bool = False) -> JobSpec:
    """The wake brief speaks in a peak window only when it carries a decision; else anytime."""
    return JobSpec(WAKE_BRIEF.name, "wake", "peak", WAKE_BRIEF.send_title, 1, "sleep_mode_on") if decision \
        else WAKE_BRIEF


def habit_checkin(habit: Optional[dict]) -> JobSpec:
    """The check-in for this week's habit; its cue is habit.json's ``cue`` when that names an event."""
    cue = (habit or {}).get("cue") if isinstance(habit, dict) else None
    if cue in EVENTS and cue != HABIT_CHECKIN.trigger_event:
        return JobSpec(HABIT_CHECKIN.name, cue, "anytime", HABIT_CHECKIN.send_title, 1, "sleep_mode_on",
                       answers=HABIT_CHECKIN.answers)
    return HABIT_CHECKIN
