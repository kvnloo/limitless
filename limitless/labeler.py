"""T1 labeler: one raw value in, one coarse label out, at the source.

Privacy tiers: T0 = raw values never enter a prompt; T1 = coarse labels made by code here (or, optionally,
by a small LOCAL model: LocalModelLabeler); T2 = a cloud model sees T1 labels only.

    label(kind, value, modality) -> {"label": str, "tier": "T1", "modality": modality | None}

A label never has a digit. A missing, malformed or out-of-range value, or a kind without a rule, is
"unknown": never a guess. Labels describe one value; nothing here computes a score.
"""
from __future__ import annotations

import math
from typing import Optional

from .envelope import MODALITIES, STALE_H

TIER = "T1"
UNKNOWN = "unknown"
ALLOWED = {
    "sleep_h": ("short", "ok", "long"),
    "readiness": ("low", "moderate", "high"),
    "age_h": ("fresh", "stale", "missing"),
}


def _num(v) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return float(v)


def _sleep(v) -> str:
    h = _num(v)
    if h is None or not 0 <= h <= 24:
        return UNKNOWN
    return "short" if h < 6 else "long" if h > 9 else "ok"


def _readiness(v) -> str:
    r = _num(v)
    if r is None or not 0 <= r <= 100:
        return UNKNOWN
    return "low" if r < 34 else "moderate" if r < 67 else "high"


def _age(v) -> str:
    if v is None:
        return "missing"
    a = _num(v)
    if a is None or a < 0:
        return UNKNOWN
    return "fresh" if a <= STALE_H else "stale"


RULES = {"sleep_h": _sleep, "readiness": _readiness, "age_h": _age}


def t1(lab: str, modality) -> dict:
    return {"label": lab, "tier": TIER, "modality": modality if modality in MODALITIES else None}


def rule_label(kind: str, value) -> str:
    rule = RULES.get(kind)
    lab = rule(value) if rule else UNKNOWN
    return lab if lab in ALLOWED.get(kind, ()) else UNKNOWN


def label(kind: str, value, modality=None) -> dict:
    """The rule-based T1 label for one value (the default labeler)."""
    return t1(rule_label(kind, value), modality)
