"""Sleep debt, in words only: the last few nights against the person's own usual night.

    d = debt(nights, baseline_nights)
    # {"word": WORDS[i] | None, "label": T1 dict, "modality": "measured" | "proxy", "recent_nights": int,
    #  "unknown_nights": int, "baseline_nights": int, "proxy_nights": int, "baseline_median_s": int | None,
    #  "recent_mean_s": int | None, "short_s": int | None, "short_share": float | None}

Input is sleep.nights() rows: ``{"night": "YYYY-MM-DD", "wearable": asleep_s | None, "proxy": gap_s | None}``.
``nights`` holds the recent nights, ``baseline_nights`` the nights before them (limitless_sleep_debt passes the
RECENT_NIGHTS nights before today and the BASELINE_NIGHTS before those, both from the one sleep.nights call).

One value per night: the wearable's when the night has one, else the phone proxy's (and then the night is a
proxy night), else the night is unknown. An unknown night is skipped, never zero sleep. A value is a number of
seconds over zero and under MAX_NIGHT_S; anything else is unknown. Rows of one date are merged (the wearable on
any of them wins). The recent nights are the RECENT_NIGHTS calendar nights ending at the newest night in
``nights``; the baseline is every night in ``baseline_nights`` dated before them (at most BASELINE_NIGHTS).

The rule: the usual night is the median over the baseline's known nights; the shortfall share is (usual minus the
mean of the recent known nights) over the usual, floored at zero (a long night is no debt):

    share < SOME_SHARE              -> "little sleep debt"
    SOME_SHARE <= share < A_LOT_SHARE -> "some sleep debt"
    share >= A_LOT_SHARE            -> "a lot of sleep debt"

Both thresholds are shares of the person's own usual night: no population norm, no hours target. Fewer than
MIN_RECENT known recent nights or MIN_BASELINE known baseline nights is "unknown: too few nights". When any
night used (recent or baseline) is a proxy night the words end in " (phone estimate)" and the modality is
"proxy"; else it is "measured".

Tiers: seconds, shares and counts are T0 and stay in the dict (the tool shows them only under the raw opt-in);
``label`` is T1 words with no digit. Observation only: no advice, no target, no score, no clock time. Nothing
here reads the clock, touches a file or sends. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import math
import statistics
from datetime import date, timedelta
from typing import Optional

RECENT_NIGHTS = 3            # the last few nights the debt is about
MIN_RECENT = 2               # fewer known recent nights than this: unknown
BASELINE_NIGHTS = 14         # the usual night is the median over at most this many calendar nights before them
MIN_BASELINE = 5             # fewer known baseline nights than this: unknown
SOME_SHARE = 0.10            # recent nights this share or more shorter than the usual night: some sleep debt
A_LOT_SHARE = 0.25           # this share or more shorter: a lot of sleep debt
MAX_NIGHT_S = 24 * 3600      # a night this long or longer is a hole in the data, not sleep
SOURCES = ("wearable", "proxy")   # the wearable first; the proxy only when the wearable has no night that date
WORDS = ("little sleep debt", "some sleep debt", "a lot of sleep debt")
PHONE = " (phone estimate)"
UNKNOWN = "unknown: too few nights"
KNOWN_LABELS = WORDS + tuple(w + PHONE for w in WORDS)
LABELS = KNOWN_LABELS + (UNKNOWN,)


def _seconds(v) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v) if 0 < v < MAX_NIGHT_S else None


def _day(v) -> Optional[date]:
    try:
        return date.fromisoformat(v) if isinstance(v, str) and len(v) == 10 else None
    except ValueError:
        return None


def _by_date(rows) -> dict:
    """date -> (seconds, source) | None: the wearable's first valid value, else the proxy's, else None."""
    seen = {}
    for r in rows if isinstance(rows, (list, tuple)) else ():
        d = _day(r.get("night")) if isinstance(r, dict) else None
        if d is None:
            continue
        got = seen.setdefault(d, {})
        for src in SOURCES:
            s = _seconds(r.get(src))
            if s is not None:
                got.setdefault(src, s)
    out = {}
    for d, got in seen.items():
        src = next((s for s in SOURCES if s in got), None)
        out[d] = None if src is None else (got[src], src)
    return out


def _t1(word: str, modality: str) -> dict:
    return {"label": word, "tier": "T1", "modality": modality}


def _word(share: float) -> str:
    return WORDS[2] if share >= A_LOT_SHARE else WORDS[1] if share >= SOME_SHARE else WORDS[0]


def debt(nights, baseline_nights) -> dict:
    """The recent nights against the median of the baseline's, in words; never raises, never changes its input."""
    rec = _by_date(nights)
    newest = max(rec) if rec else None
    window = [] if newest is None else [newest - timedelta(days=a) for a in range(RECENT_NIGHTS - 1, -1, -1)]
    used = [rec[d] for d in window if rec.get(d) is not None]
    start = window[0] if window else None
    base_all = _by_date(baseline_nights)
    base_days = sorted(d for d in base_all if start is None or d < start)[-BASELINE_NIGHTS:]
    if start is not None:
        base_days = [d for d in base_days if d >= start - timedelta(days=BASELINE_NIGHTS)]
    base = [base_all[d] for d in base_days if base_all[d] is not None]
    proxy_nights = sum(1 for _, src in used + base if src == "proxy")
    modality = "proxy" if proxy_nights else "measured"
    out = {"word": None, "modality": modality, "recent_nights": len(used),
           "unknown_nights": RECENT_NIGHTS - len(used) if window else RECENT_NIGHTS,
           "baseline_nights": len(base), "proxy_nights": proxy_nights, "baseline_median_s": None,
           "recent_mean_s": None, "short_s": None, "short_share": None}
    if len(base) >= MIN_BASELINE:
        out["baseline_median_s"] = int(round(statistics.median(s for s, _ in base)))
    if len(used) >= MIN_RECENT:
        out["recent_mean_s"] = int(round(statistics.mean(s for s, _ in used)))
    if out["baseline_median_s"] is None or out["recent_mean_s"] is None:
        out["label"] = _t1(UNKNOWN, modality)
        return out
    usual = statistics.median(s for s, _ in base)
    mean = statistics.mean(s for s, _ in used)
    share = max(0.0, (usual - mean) / usual)
    out.update(short_s=int(round(max(0.0, sum(usual - s for s, _ in used)))), short_share=share, word=_word(share))
    out["label"] = _t1(out["word"] + (PHONE if proxy_nights else ""), modality)
    return out
