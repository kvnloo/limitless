"""Pre-sleep heart rate, in words only and from the wearable only: lower than usual, about usual or higher.

    got = latest(rows, now, tz=None)
    # {"word": "lower than usual" | "about usual" | "higher than usual" | None, "label": T1 dict,
    #  "modality": "measured", "age_h": float | None, "night": "YYYY-MM-DD" | None, "bpm": float | None,
    #  "baseline_bpm": float | None, "baseline_nights": int, "reason": str | None}
    w = week(rows, today)        # {"word": the majority word | NO_PATTERN | None, "compared": int, ...}
    review_line(w)               # "Pre-sleep heart rate: about usual most nights (wearable)." or ""

Rows are StateReader.presleep_hr_rows(): ``{"night": "YYYY-MM-DD" (the evening the night began), "bpm",
"modality"}``, one per night, written by whatever exports the wearable's pre-sleep reading (for example a mean
over the half hour before the main sleep began). Only rows with ``modality`` "measured" (the wearable) are
read; a phone or any other row is never used, not even for a night the wearable missed. A night with no valid
wearable row is unknown: it is skipped, never zero and never filled in. The first valid wearable row of a
night wins; a night after the local date of ``now`` is ignored.

The last night is the newest wearable night. It is compared with the median of the BASELINE_NIGHTS wearable
nights before it (a count of measured nights, not a calendar span, so holes do not shrink the baseline):
within ABOUT_BPM of that median is "about usual", below it "lower than usual", above it "higher than usual".
ABOUT_BPM is wording only: a band for the words, not a target, a norm or a score. Unknown, with a plain
reason: no wearable row (NO_WEARABLE; PHONE_ONLY when only phone rows exist), fewer than MIN_NIGHTS earlier
wearable nights (TOO_FEW), or the last night older than MAX_AGE_H (STALE). A night's age runs from the local
midnight after its date (the reading is taken before sleep, so it is never fresher than that).

The week: each of the seven nights before ``today`` with a wearable reading is compared the same way with the
BASELINE_NIGHTS wearable nights before it. With at least MIN_WEEK_NIGHTS compared nights, the word that holds
a strict majority of them is the week's word ("most nights"), else NO_PATTERN; fewer compared nights is
unknown, and the week review says nothing.

Tiers: beats per minute are T0 and stay in code (the tool shows them only under the raw opt-in); ``label``,
``reason`` and ``review_line`` are T1 words with no digit. Observation only: no advice, no target, no score, no
clock time. Nothing here reads the clock, touches a file or sends. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import math
import statistics
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Optional

MEASURED = "measured"         # the only modality read: the wearable's own reading
BASELINE_NIGHTS = 14          # the last night is compared with the median of this many earlier wearable nights
MIN_NIGHTS = 5                # fewer earlier wearable nights than this: unknown
ABOUT_BPM = 3.0               # within this of the median reads "about usual" (wording only, not a target)
MAX_AGE_H = 36.0              # a last night older than this is unknown (stale), never shown as current
MIN_BPM, MAX_BPM = 25.0, 250.0   # outside this a reading is not a heart rate: the row is skipped
WEEK_NIGHTS = 7
MIN_WEEK_NIGHTS = 4           # fewer compared nights this week: no week line
WORDS = ("lower than usual", "about usual", "higher than usual")
SOURCE = "wearable"
NO_WEARABLE = "pre-sleep heart rate unknown: no wearable reading"
PHONE_ONLY = "pre-sleep heart rate unknown: only phone readings, and the phone is never used for heart rate"
TOO_FEW = "pre-sleep heart rate unknown: fewer than five earlier wearable nights to compare with"
STALE = "pre-sleep heart rate unknown: the newest wearable reading is more than a day and a half old"
REASONS = (NO_WEARABLE, PHONE_ONLY, TOO_FEW, STALE)
LABELS = tuple(f"pre-sleep heart rate {w} ({SOURCE})" for w in WORDS) + REASONS
NO_PATTERN = "no clear pattern this week"
REVIEW_LINES = tuple(f"Pre-sleep heart rate: {w} most nights ({SOURCE})." for w in WORDS) + (
    f"Pre-sleep heart rate: {NO_PATTERN} ({SOURCE}).",)


def _num(v) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def _day(v) -> Optional[date]:
    try:
        return date.fromisoformat(v) if isinstance(v, str) and len(v) == 10 else None
    except ValueError:
        return None


def _valid(rows, last_day: Optional[date] = None) -> tuple:
    """(night -> bpm for the first valid wearable row of each night, oldest first; any valid non-wearable row?)"""
    wear, other = {}, False
    for r in rows if isinstance(rows, (list, tuple)) else ():
        if not isinstance(r, dict):
            continue
        d, bpm = _day(r.get("night")), _num(r.get("bpm"))
        if d is None or bpm is None or not MIN_BPM <= bpm <= MAX_BPM or (last_day is not None and d > last_day):
            continue
        if r.get("modality") != MEASURED:
            other = other or isinstance(r.get("modality"), str)
            continue
        wear.setdefault(d.isoformat(), bpm)
    return {n: wear[n] for n in sorted(wear)}, other


def nights(rows, last_day: Optional[date] = None) -> dict:
    """night -> bpm, wearable rows only (first valid row per night), oldest first; never raises."""
    return _valid(rows, last_day)[0]


def _word(bpm: float, baseline: float) -> str:
    d = bpm - baseline
    return WORDS[1] if abs(d) <= ABOUT_BPM else WORDS[0] if d < 0 else WORDS[2]


def _compare(wear: dict, n: str) -> tuple:
    """(word | None, baseline median | None, baseline nights) for night ``n`` against the wearable nights before it."""
    prior = [wear[k] for k in wear if k < n][-BASELINE_NIGHTS:]
    if len(prior) < MIN_NIGHTS:
        return None, None, len(prior)
    base = float(statistics.median(prior))
    return _word(wear[n], base), base, len(prior)


def _night_end(night: str, tz: Optional[tzinfo]) -> Optional[float]:
    try:
        dt = datetime.combine(date.fromisoformat(night) + timedelta(days=1), time(0))
        return (dt.replace(tzinfo=tz) if tz is not None else dt).timestamp()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _t1(word: str) -> dict:
    return {"label": word, "tier": "T1", "modality": MEASURED}


def latest(rows, now: float, tz: Optional[tzinfo] = None) -> dict:
    """The newest wearable night against the BASELINE_NIGHTS before it, in words; never raises."""
    out = {"word": None, "modality": MEASURED, "age_h": None, "night": None, "bpm": None, "baseline_bpm": None,
           "baseline_nights": 0, "reason": None}
    try:
        today = datetime.fromtimestamp(now, tz).date()
    except (TypeError, ValueError, OverflowError, OSError):
        today = None
    wear, other = _valid(rows, today) if today is not None else ({}, False)
    if not wear:
        out["reason"] = PHONE_ONLY if other else NO_WEARABLE
    else:
        n = list(wear)[-1]
        end = _night_end(n, tz)
        out.update(night=n, bpm=wear[n], age_h=None if end is None else round(max(0.0, now - end) / 3600, 1))
        word, base, k = _compare(wear, n)
        out.update(baseline_bpm=base, baseline_nights=k)
        if out["age_h"] is None or out["age_h"] > MAX_AGE_H:
            out["reason"] = STALE
        elif word is None:
            out["reason"] = TOO_FEW
        else:
            out["word"] = word
    out["label"] = _t1(out["reason"] if out["word"] is None else f"pre-sleep heart rate {out['word']} ({SOURCE})")
    return out


def week(rows, today: date) -> dict:
    """The seven nights before ``today``, each against the wearable nights before it; never raises."""
    out = {"word": None, "compared": 0, "nights": []}
    if not isinstance(today, date):
        return out
    wear = nights(rows, today - timedelta(days=1))
    first = (today - timedelta(days=WEEK_NIGHTS)).isoformat()
    words = []
    for n in wear:
        if n >= first:
            w, base, _ = _compare(wear, n)
            out["nights"].append({"night": n, "word": w, "bpm": wear[n], "baseline_bpm": base})
            if w is not None:
                words.append(w)
    out["compared"] = len(words)
    if len(words) >= MIN_WEEK_NIGHTS:
        top = max(WORDS, key=words.count)
        out["word"] = top if words.count(top) * 2 > len(words) else NO_PATTERN
    return out


def review_line(w) -> str:
    """The week review's pre-sleep heart-rate line, digit-free; "" when the week is unknown."""
    word = w.get("word") if isinstance(w, dict) else None
    if word in WORDS:
        line = f"Pre-sleep heart rate: {word} most nights ({SOURCE})."
    elif word == NO_PATTERN:
        line = f"Pre-sleep heart rate: {NO_PATTERN} ({SOURCE})."
    else:
        return ""
    return line if line in REVIEW_LINES else ""
