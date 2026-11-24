"""T1 labeler: one raw value in, one coarse label out, at the source.

Privacy tiers: T0 = raw values never enter a prompt; T1 = coarse labels made by code here (or, optionally,
by a small LOCAL model: LocalModelLabeler); T2 = a cloud model sees T1 labels only.

    label(kind, value, modality) -> {"label": str, "tier": "T1", "modality": modality | None}

A label never has a digit. A missing, malformed or out-of-range value, or a kind without a rule, is
"unknown": never a guess. Labels describe one value; nothing here computes a score.

Local model (optional, none by default): set env LIMITLESS_T1_CMD or config key "t1_model_cmd" to a
command line for a small model CLI on this machine. It reads one fixed prompt on stdin and must print one
word from the kind's allowed set; anything else, a non-zero exit, a timeout or a missing binary gives the
rule label instead. A value the rules call unknown or missing is never sent to the model. Run it on the
CPU: the child gets CUDA_VISIBLE_DEVICES="" and HIP_VISIBLE_DEVICES="", and the command must not take a
GPU that another job owns (pick a CPU build or flags; never point it at a shared GPU server).
bin/limitless-t1-local is such a command for a llama.cpp-style CLI on the CPU (limitless/t1_local.py).
"""
from __future__ import annotations

import math
import os
import shlex
import subprocess
from contextlib import contextmanager
from pathlib import Path
from typing import Mapping, Optional, Sequence, Union

from .envelope import MODALITIES, STALE_H
from .state_reader import config

TIER = "T1"
UNKNOWN = "unknown"
ALLOWED = {
    "sleep_h": ("short", "ok", "long"),
    "readiness": ("low", "moderate", "high"),
    "age_h": ("fresh", "stale", "missing"),
    "owner_message_age_h": ("wrote recently", "quiet for a while", "no data"),
}
OWNER_RECENT_H = 2.0  # hours since the person's newest message to any agent that still reads as "wrote recently"


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


def _owner_age(v) -> str:
    if v is None:
        return "no data"
    a = _num(v)
    if a is None or a < 0:
        return UNKNOWN
    return "wrote recently" if a <= OWNER_RECENT_H else "quiet for a while"


RULES = {"sleep_h": _sleep, "readiness": _readiness, "age_h": _age, "owner_message_age_h": _owner_age}


def count_word(n: Optional[int]) -> str:
    """The T1 count words: none | one | a few | many; None (the source is missing) is unknown, never none."""
    if n is None:
        return UNKNOWN
    return "none" if n <= 0 else "one" if n == 1 else "a few" if n < 5 else "many"


def t1(lab: str, modality) -> dict:
    return {"label": lab, "tier": TIER, "modality": modality if modality in MODALITIES else None}


def rule_label(kind: str, value) -> str:
    rule = RULES.get(kind)
    lab = rule(value) if rule else UNKNOWN
    return lab if lab in ALLOWED.get(kind, ()) else UNKNOWN


def label(kind: str, value, modality=None) -> dict:
    """The rule-based T1 label for one value (the default labeler)."""
    return t1(rule_label(kind, value), modality)


ENV_KEY = "LIMITLESS_T1_CMD"
CONFIG_KEY = "t1_model_cmd"
TIMEOUT_S = 5.0
MAX_ANSWER = 64
PROMPT = ("Label one {kind} value with exactly one word from this set: {allowed}.\n"
          "Answer with that word only.\n"
          "Value: {value}\n")
_NO_GPU = {"CUDA_VISIBLE_DEVICES": "", "HIP_VISIBLE_DEVICES": ""}


class LocalModelLabeler:
    """label(kind, value, modality) through a local CLI, with the rule label as the fallback for any failure."""

    def __init__(self, cmd: Union[str, Sequence[str], None], timeout_s: float = TIMEOUT_S):
        if isinstance(cmd, str):
            cmd = shlex.split(cmd)
        self.cmd = list(cmd) if cmd else None
        self.timeout_s = timeout_s

    def _ask(self, kind: str, value, allowed: tuple) -> Optional[str]:
        prompt = PROMPT.format(kind=kind, allowed=", ".join(allowed), value=value)
        try:
            p = subprocess.run(self.cmd, input=prompt, capture_output=True, text=True, timeout=self.timeout_s,
                               env=dict(os.environ, **_NO_GPU))
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
        out = (p.stdout or "").strip().lower()
        if p.returncode != 0 or len(out) > MAX_ANSWER:
            return None
        return out if out in allowed else None

    def label(self, kind: str, value, modality=None) -> dict:
        rule = label(kind, value, modality)
        if not self.cmd or rule["label"] in (UNKNOWN, "missing", "no data"):
            return rule
        allowed = tuple(x for x in ALLOWED[kind] if x not in ("missing", "no data"))
        answer = self._ask(kind, value, allowed)
        return rule if answer is None else t1(answer, modality)

    __call__ = label


def t1_model_cmd(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> Optional[str]:
    """The local model command: $LIMITLESS_T1_CMD, else config "t1_model_cmd"; None (rules only) by default."""
    env = os.environ if env is None else env
    v = env.get(ENV_KEY) or config(env, home).get(CONFIG_KEY)
    return v if isinstance(v, str) and v.strip() else None


_RULES_ONLY = []


@contextmanager
def rules_only():
    """Inside this block from_config gives the rule labeler, so the local model is never run. For
    limitless-doctor, whose read-only tool calls must not start the configured model."""
    _RULES_ONLY.append(True)
    try:
        yield
    finally:
        _RULES_ONLY.pop()


def from_config(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> LocalModelLabeler:
    return LocalModelLabeler(None if _RULES_ONLY else t1_model_cmd(env, home))
