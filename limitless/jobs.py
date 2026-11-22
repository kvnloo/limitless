"""Event-triggered job specs: the wake brief, the post-nap message, the bedtime question, the habit check-in.

A job says which event wakes it (``trigger_event``), which decision window it speaks in
(``window_class``), how often it may speak per window and which event ends it. There are no
clock times and no cron strings here: a test fails if a spec grows one.

Everything is a pure function. Nothing in this module sends; delivery stays in ``bin/kevin-push``.
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NamedTuple, Optional, Tuple

from . import decision_window, send_gate
from .decision_window import WINDOW_CLASSES
from .state_reader import parse_ts
from .window import MAX_AWAKE_H

# Events a job can wake on or end on. sleep_mode_on/off come from the phone; wake is a Sleep-mode
# off after a long on; wind_down and habit_cue come from whatever automation marks them.
EVENTS = ("wake", "sleep_mode_on", "sleep_mode_off", "wind_down", "habit_cue", "focus_end")
TRIGGER_AFTER = ("", "short_on")
NAP_MAX_S = 3 * 3600        # a Sleep-mode on shorter than this, then off, is a nap; longer is a night
SLEEP_MODE_CONFIDENCE = 0.9  # a wake from Sleep mode; a screen-event wake (wake_proxy) carries less
DELIVER, HOLD, DROP, NOT_TRIGGERED = "deliver", "hold", "drop", "not_triggered"
ACTIONS = (DELIVER, HOLD, DROP, NOT_TRIGGERED)
_SLEEP = ("sleep_mode_on", "sleep_mode_off")
_WORDS = {"wake": "wake", "sleep_mode_on": "Sleep-mode on", "sleep_mode_off": "Sleep-mode off",
          "wind_down": "wind-down", "habit_cue": "habit cue", "focus_end": "focus-end", "nap": "nap"}


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


class Verdict(NamedTuple):
    action: str                        # deliver | hold | drop | not_triggered
    reason: str                        # one line; a held or dropped job shows it in the run log
    trigger_at: Optional[float] = None


def events_from_sleepmode(rows: list) -> list:
    """sleepmode.jsonl rows ({"at", "on"}) as events ({"event": "sleep_mode_on" | "sleep_mode_off", "at"})."""
    out = []
    for r in rows:
        at = parse_ts((r or {}).get("at")) if isinstance(r, dict) else None
        if at is not None:
            out.append({"event": "sleep_mode_on" if r.get("on") else "sleep_mode_off", "at": at})
    return sorted(out, key=lambda e: e["at"])


def _past(events: list, now: float) -> list:
    out = []
    for e in events or ():
        at = parse_ts(e.get("at")) if isinstance(e, dict) else None
        if at is not None and at <= now and e.get("event") in EVENTS:
            out.append((at, e["event"]))
    return sorted(out)


def _triggers(spec: JobSpec, evs: list) -> list:
    """Times of the events that wake this job. A Sleep-mode off counts by the length of the on before it."""
    hits, last_sleep = [], None
    for at, name in evs:
        if name in _SLEEP:
            prev, last_sleep = last_sleep, (at, name)
            if name == "sleep_mode_off" and prev is not None and prev[1] == "sleep_mode_on":
                short = at - prev[0] < NAP_MAX_S
                if spec.trigger_event == "wake" and not short:
                    hits.append(at)
                elif spec.trigger_event == "sleep_mode_off" and (short or spec.trigger_after != "short_on"):
                    hits.append(at)
            continue
        if name == spec.trigger_event:
            hits.append(at)
    return hits


def _label(spec: JobSpec) -> str:
    return "nap" if spec.trigger_after == "short_on" else _WORDS[spec.trigger_event]


def _window(state: Any):
    """(WindowState | None, asleep) from a decision_window.WindowState or a window.py envelope."""
    if state is None:
        return None, False
    if isinstance(state, dict):
        cls = state.get("cls", state.get("value"))
        if cls == "asleep":
            return None, True
        try:
            conf = float(state.get("confidence", 1.0))
        except (TypeError, ValueError):
            conf = 0.0
        return decision_window.WindowState(cls=cls if isinstance(cls, str) else decision_window.UNKNOWN,
                                           since=state.get("since"), source="window", confidence=conf), False
    if getattr(state, "cls", None) == "asleep":
        return None, True
    return state, False


def _dedupe_body(spec: JobSpec, trigger_at: float) -> str:
    return f"{spec.name} after {spec.trigger_event} {trigger_at:.0f}"


def dedupe_key(spec: JobSpec, trigger_at: float) -> str:
    """The send gate's key for this job's message about one trigger event."""
    return send_gate.key(spec.send_title, _dedupe_body(spec, trigger_at))


def sent_entry(spec: JobSpec, trigger_at: float, now: float) -> dict:
    """The sent-log record a caller appends after a real delivery (send gate shape plus the job name)."""
    return {"t": now, "k": dedupe_key(spec, trigger_at), "job": spec.name}


def _times(n: int) -> str:
    return {1: "once", 2: "twice"}.get(n, f"{n} times")


def should_fire(spec: JobSpec, events: list, window_state: Any, sent_log: list, now: float) -> Verdict:
    """Deliver, hold, drop, or not triggered, with a one-line reason. Pure: reads its inputs, sends nothing.

    Order: the latest trigger event; expiry; a trigger too old to trust; the per-window limit;
    decision_window.decide (asleep, class, peak budget); the send gate's 12 h dedupe and daily cap.
    A hold is not a send: nothing is counted until the caller delivers and appends sent_entry().
    """
    label = _label(spec)
    evs = _past(events, now)
    hits = _triggers(spec, evs)
    if not hits:
        return Verdict(NOT_TRIGGERED, f"no {label} event yet")
    trig = hits[-1]
    if any(trig < at and name == spec.expires for at, name in evs):
        return Verdict(DROP, f"expired: {_WORDS[spec.expires]} after the {label} event", trig)
    age_h = (now - trig) / 3600
    if age_h > MAX_AWAKE_H:
        return Verdict(DROP, f"the {label} event is {age_h:.0f} h old: missing data, not a long day", trig)
    sent = [s for s in (sent_log or ()) if isinstance(s, dict) and isinstance(s.get("t"), (int, float))]
    count = sum(1 for s in sent if s.get("job") == spec.name and trig <= s["t"] <= now)
    if count >= spec.max_per_window:
        return Verdict(DROP, f"already spoke {_times(count)} since the {label} event", trig)
    state, asleep = _window(window_state)
    w = decision_window.decide(spec.window_class, state, budget_left=spec.max_per_window - count, asleep=asleep)
    if w.action != decision_window.DELIVER:
        return Verdict(w.action, w.reason, trig)
    gate = send_gate.decide("limitless", spec.send_title, _dedupe_body(spec, trig), "decision", now, sent, False)
    if gate == "duplicate":
        return Verdict(DROP, "the send gate sent this same message within 12 h", trig)
    if gate == "cap":
        return Verdict(HOLD, f"the send gate's daily cap of {send_gate.DAILY_CAP} is reached", trig)
    if gate != "send":
        return Verdict(HOLD, f"the send gate says {gate}", trig)
    return Verdict(DELIVER, f"{label} event; {w.reason}", trig)


_SPEAKS = {"wake": "when you wake up", "sleep_mode_on": "when Sleep mode goes on",
           "sleep_mode_off": "when Sleep mode goes off", "wind_down": "when your wind-down starts",
           "habit_cue": "at your habit's cue", "focus_end": "when a focus block ends"}
_IN_WINDOW = {"peak": "in a peak window, at most one decision per window",
              "trough": "in a low-energy window, for a review or an easy read",
              "wind_down": "once your wind-down has started", "anytime": "any time you are awake"}
_ENDS = {"wake": "when you next wake up", "sleep_mode_on": "when Sleep mode goes on",
         "sleep_mode_off": "when Sleep mode goes off", "wind_down": "when your wind-down starts",
         "habit_cue": "at your habit's next cue", "focus_end": "when a focus block ends"}
_NUM = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")


def _at_most(n: int) -> str:
    return "at most " + {1: "once", 2: "twice"}.get(n, f"{_NUM[n] if n < len(_NUM) else 'a few'} times")


def to_schedule_card(spec: JobSpec) -> dict:
    """The plain-words fields a Hermes "Schedule this job?" card could show for this job. No internal ids."""
    when = "when you are back from a nap" if spec.trigger_after == "short_on" else _SPEAKS[spec.trigger_event]
    card = {"name": spec.send_title, "speaks": f"{when}, {_at_most(spec.max_per_window)}",
            "window": _IN_WINDOW[spec.window_class], "ends": _ENDS[spec.expires],
            "delivery": "you, through the send gate; this job never sends by itself"}
    if spec.answers:
        card["answers"] = f"{', '.join(spec.answers[:-1])} or {spec.answers[-1]} in one tap; no answer stays unlogged"
    return card


HABIT_TAPS = {"done": "Done", "no": "No", "skip": "Skipped"}   # tap -> the habit.json check-in word


def habit_answer(tap: Any) -> Optional[str]:
    """Done | No | Skipped for a real tap; None (unlogged) for no answer, an expired ask or anything else."""
    return HABIT_TAPS.get(tap.strip().lower()) if isinstance(tap, str) else None


def habit_day(habit: Optional[dict], day: str) -> str:
    """One day's check-in: Done | No | Skipped, else "unlogged". A day with no answer is never No."""
    checkins = habit.get("checkins") if isinstance(habit, dict) else None
    v = checkins.get(day) if isinstance(checkins, dict) else None
    if isinstance(v, str) and v.strip().lower() in ("done", "no", "skipped"):
        return v.strip().capitalize()
    return "unlogged"


def record_checkin(habit: Optional[dict], day: str, tap: Any) -> dict:
    """A copy of habit.json with the day's answer; no answer leaves the day as it was. The caller writes it."""
    out = dict(habit or {})
    checkins = dict(out.get("checkins") or {}) if isinstance(out.get("checkins"), dict) else {}
    answer = habit_answer(tap)
    if answer is not None:
        checkins[day] = answer
    out["checkins"] = checkins
    return out
