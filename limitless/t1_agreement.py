"""limitless-t1-check: does the local T1 model agree with the rule labels? Run it before the labeler may use it.

    check(cmd) -> {"verdict", "words", "checks", "agrees", "disagrees", "no_answer", "kinds": {kind: word}}

A FIXED set of synthetic inputs (CASES, shipped here: no state is read) gives one labeler prompt each, built by
LocalModelLabeler from its own PROMPT and the kind's answerable words. Each prompt is sent once through
LocalModelLabeler.answer, the labeler's own call path (same timeout, same parsing, no GPU), and the answer is
compared with the rule label for that input. No in-set answer (a digit, a non-zero exit, a timeout) is "no answer".

The verdict is words only, never a digit: "agrees on all checks", "agrees on most checks" (more than half),
"agrees on few checks", or "unknown: <reason>" (no command set, a command that cannot be read or whose program
does not exist, or every call failed). Per kind: "agrees" (every check), "disagrees" (any check said another
allowed word) or "no answer" (otherwise). The counts are T0 and only in --json. This is not a capability score:
it says whether the model gives the same coarse words as the rules on these inputs, nothing more.
"""
from __future__ import annotations

import os
import shlex
import shutil
from typing import Optional

from . import labeler

# (kind, synthetic value): every kind with a rule, every word a present value can get, away from the edges.
CASES = (
    ("sleep_h", 4.5), ("sleep_h", 7.5), ("sleep_h", 10.5),
    ("readiness", 20), ("readiness", 50), ("readiness", 85),
    ("age_h", 2.0), ("age_h", 40.0),
    ("owner_message_age_h", 0.5), ("owner_message_age_h", 6.0),
)
UNKNOWN = "unknown"
VERDICT_WORDS = {"all": "agrees on all checks", "most": "agrees on most checks", "few": "agrees on few checks"}
NO_CMD = "no local model command set"
UNREADABLE = "the command line cannot be read"
NO_PROGRAM = "the command's program does not exist"
ALL_FAILED = "every call failed"
AGREES, DISAGREES, NO_ANSWER = "agrees", "disagrees", "no answer"
answerable = labeler.answerable


def prompts() -> list:
    """The exact prompt each case sends, in CASES order (labeler.PROMPT with the kind's answerable words)."""
    return [labeler.PROMPT.format(kind=k, allowed=", ".join(answerable(k)), value=v) for k, v in CASES]


def verdict(agrees: int, checks: int) -> str:
    """all when every check agrees, most when more than half do, else few."""
    if checks and agrees == checks:
        return "all"
    return "most" if agrees * 2 > checks else "few"


def _unknown(reason: str, **counts) -> dict:
    out = {"verdict": UNKNOWN, "words": f"{UNKNOWN}: {reason}", "checks": len(CASES), "agrees": 0,
           "disagrees": 0, "no_answer": 0, "kinds": {}}
    out.update(counts)
    return out


def _argv(cmd) -> tuple:
    """(argv, None) or (None, why it cannot run). Nothing is started."""
    if cmd is None or (isinstance(cmd, str) and not cmd.strip()):
        return None, NO_CMD
    try:
        argv = shlex.split(cmd) if isinstance(cmd, str) else list(cmd)
    except ValueError:
        return None, UNREADABLE
    if not argv:
        return None, NO_CMD
    if shutil.which(argv[0], path=os.environ.get("PATH") or os.defpath) is None:
        return None, NO_PROGRAM
    return argv, None


def check(cmd, timeout_s: float = labeler.TIMEOUT_S) -> dict:
    """Run the command once per case through LocalModelLabeler.answer and compare with the rule label."""
    argv, why = _argv(cmd)
    if argv is None:
        return _unknown(why)
    model = labeler.LocalModelLabeler(argv, timeout_s)
    per_kind, n = {}, {AGREES: 0, DISAGREES: 0, NO_ANSWER: 0}
    for kind, value in CASES:
        said = model.answer(kind, value)
        got = NO_ANSWER if said is None else AGREES if said == labeler.rule_label(kind, value) else DISAGREES
        n[got] += 1
        per_kind.setdefault(kind, []).append(got)
    kinds = {k: DISAGREES if DISAGREES in g else AGREES if set(g) == {AGREES} else NO_ANSWER
             for k, g in per_kind.items()}
    counts = {"agrees": n[AGREES], "disagrees": n[DISAGREES], "no_answer": n[NO_ANSWER], "kinds": kinds}
    if n[NO_ANSWER] == len(CASES):
        return _unknown(ALL_FAILED, **counts)
    v = verdict(n[AGREES], len(CASES))
    return dict({"verdict": v, "words": VERDICT_WORDS[v], "checks": len(CASES)}, **counts)


def text(result: dict) -> str:
    """The words: the verdict line, then one line per kind. Never a digit."""
    lines = [f"local model check: {result['words']}"]
    lines += [f"{k}: {w}" for k, w in result.get("kinds", {}).items()]
    return "\n".join(lines)
