"""The habit catalogue: a short, fixed, ordered list for one habit a week, Foundation first, easiest first.

    habit_catalogue.CATALOGUE                  -> the list (read-only entries)
    habit_catalogue.find("Feeds-free first hour")   -> that entry (by id or name, any case), else None

Few good habits, not many goals. When a week ends with Drop, or before the first week, the agent offers the
next habit from this list instead of inventing one. The list is ordered by layer (foundation: sleep, energy
and recovery; then learning; then flow) and, inside a layer, easiest first. The first entry is the existing
week-one habit, the feeds-free first hour, on its existing cue (jobs.HABIT_CHECKIN: ``habit_cue``, an hour
after the wake).

Each entry is ``{id, layer, name, cue, start, environment}``: ``cue`` is an event name from jobs.EVENTS,
never a clock time; ``start`` is a first step of two minutes or less, in plain words; ``environment`` is one
optional thing to set up around you (None when there is none). ``name`` is what habit.json's ``habit`` holds
once the person starts it (habit_start.start_week): this module keeps no habit store of its own.

No entry has a digit, a clock time, or a drug, supplement, caffeine or dosing word (``problems`` says which,
and a test holds every entry to it). Pure: nothing here reads a clock, touches a file or sends. It never
starts a habit: that needs the person's yes and habit_start. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import re
from types import MappingProxyType
from typing import Iterable, List, Optional

from . import jobs

LAYERS = ("foundation", "learning", "flow")
FIELDS = ("id", "layer", "name", "cue", "start", "environment")
MAX_HABITS = 8


def _habit(id_, layer, name, cue, start, environment=None):
    return MappingProxyType({"id": id_, "layer": layer, "name": name, "cue": cue, "start": start,
                             "environment": environment})


CATALOGUE = (
    _habit("feeds_free_first_hour", "foundation", "Feeds-free first hour", "habit_cue",
           "after you wake, put the phone face down and do one thing that is not a feed",
           "phone charging away from the bed"),
    _habit("daylight_after_wake", "foundation", "Daylight after waking", "wake",
           "open the curtains and stand by the window for a moment", "curtains left half open"),
    _habit("lights_down_at_wind_down", "foundation", "Lights down at wind-down", "wind_down",
           "switch off the big light and turn on one lamp", "a lamp by the couch"),
    _habit("phone_sleeps_outside", "foundation", "Phone sleeps outside the bedroom", "sleep_mode_on",
           "put the phone on a charger outside the bedroom", "a charger in the hall"),
    _habit("stand_after_long_block", "foundation", "Stand up after a long block", "long_block",
           "stand up and walk to the window and back", "a water glass across the room"),
    _habit("easy_ride", "foundation", "An easy ride", "focus_end",
           "put on your riding shoes and sit on the bike", "bike in view"),
    _habit("short_review_after_focus", "learning", "A short review after focus", "focus_end",
           "open your review deck and answer one card", "the deck one tap away"),
    _habit("next_step_before_break", "flow", "Next step before the break", "focus_end",
           "write the first step of the next block on a note", "a notepad beside the keyboard"),
)

# A clock time in any common spelling, or a schedule by the clock.
_CLOCK = re.compile(r"(?i)\b(\d{1,2}\s*(:\s*\d{2})?\s*(am|pm|a\.m\.|p\.m\.|h)\b|o'?clock|noon|midnight|"
                    r"half past|quarter (past|to)|in the morning|at night|tonight|every day at)\b")
# Drug, supplement, caffeine and dosing words.
_SUBSTANCE = re.compile(r"(?i)\b(caffeine|coffee|espresso|tea|energy drink|drugs?|supplements?|melatonin|"
                        r"magnesium|vitamins?|pills?|tablets?|capsules?|doses?|dosing|dosage|mg|milligrams?|"
                        r"medication|medicine|nicotine|alcohol|stimulants?|nootropics?|modafinil|adderall|"
                        r"microdose)\b")


def problems(entries: Iterable) -> List[str]:
    """Plain reasons an entry list breaks the catalogue's rules; [] when none does. Checks the fields, the
    layer, the order (layer by layer), the cue (an event in jobs.EVENTS), and every word for a digit, a clock
    time and a drug, supplement, caffeine or dosing word."""
    out, last = [], 0
    entries = tuple(entries)
    if len(entries) > MAX_HABITS:
        out.append("more habits than the catalogue holds")
    for h in entries:
        hid = h.get("id") if hasattr(h, "get") else None
        who = hid if isinstance(hid, str) else "an entry"
        if not hasattr(h, "keys") or set(h.keys()) != set(FIELDS):
            out.append(f"{who}: fields are not {', '.join(FIELDS)}")
            continue
        if h["layer"] not in LAYERS:
            out.append(f"{who}: layer is not foundation, learning or flow")
        elif LAYERS.index(h["layer"]) < last:
            out.append(f"{who}: out of layer order")
        else:
            last = LAYERS.index(h["layer"])
        if h["cue"] not in jobs.EVENTS:
            out.append(f"{who}: cue is not an event")
        for k in FIELDS:
            w = h[k]
            if w is None and k == "environment":
                continue
            if not isinstance(w, str) or not w.strip():
                out.append(f"{who}: {k} is empty")
                continue
            if any(c.isdigit() for c in w):
                out.append(f"{who}: {k} has a digit")
            if _CLOCK.search(w):
                out.append(f"{who}: {k} has a clock time")
            if _SUBSTANCE.search(w):
                out.append(f"{who}: {k} has a substance or dosing word")
    return out


def _key(v) -> str:
    return " ".join(v.split()).lower() if isinstance(v, str) else ""


def find(v) -> Optional[MappingProxyType]:
    """The catalogue entry whose id or name is ``v`` (case and spacing ignored), else None."""
    k = _key(v)
    if not k:
        return None
    for h in CATALOGUE:
        if k in (h["id"], _key(h["name"])):
            return h
    return None
