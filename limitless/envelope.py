"""Evidence envelope: the one shape every limitless tool result takes.

    {"value": ..., "modality": measured|imported|proxy|self_report, "age_h": float|None,
     "evidence_tier": direct|indirect|stale|none}

Missing data is ``value: None`` plus a ``reason``; nothing is ever filled in by a guess.
evidence_tier is a label for how the value was obtained, not a score:
direct = measured, imported or self-reported and at most STALE_H old; indirect = a fresh proxy;
stale = older than STALE_H or of unknown age; none = no value.
"""
from __future__ import annotations

from typing import Any, Optional

MODALITIES = ("measured", "imported", "proxy", "self_report")
STALE_H = 24.0


def _tier(modality: str, age_h: Optional[float]) -> str:
    if age_h is None or age_h > STALE_H:
        return "stale"
    return "indirect" if modality == "proxy" else "direct"


def envelope(value: Any, modality: str, age_h: Optional[float], reason: Optional[str] = None) -> dict:
    if modality not in MODALITIES:
        raise ValueError(f"modality must be one of {MODALITIES}, got {modality!r}")
    if age_h is not None and age_h < 0:
        raise ValueError(f"age_h must be >= 0, got {age_h!r}")
    age = None if age_h is None else round(float(age_h), 1)
    if value is None:
        if not reason:
            raise ValueError("a null value needs a reason")
        return {"value": None, "modality": modality, "age_h": age, "evidence_tier": "none", "reason": reason}
    return {"value": value, "modality": modality, "age_h": age, "evidence_tier": _tier(modality, age_h)}


def missing(reason: str) -> dict:
    """No data at all: say why instead of guessing."""
    if not reason or not reason.strip():
        raise ValueError("a null value needs a reason")
    return {"value": None, "modality": None, "age_h": None, "evidence_tier": "none", "reason": reason}
