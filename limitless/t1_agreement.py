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
from pathlib import Path
from typing import Mapping, Optional

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


MIN_KEY, FILE_KEY = "t1_min_agreement", "t1_check_file"
MIN_DEFAULT = "most"
_RANK = {"few": 0, "most": 1, "all": 2}
_FROM_WORDS = {w: v for v, w in VERDICT_WORDS.items()}
MAX_SAVED = 256


def min_agreement(cfg: Mapping) -> str:
    """config t1_min_agreement: all, most or few; anything else is the default, most."""
    v = cfg.get(MIN_KEY) if isinstance(cfg, Mapping) else None
    return v if v in _RANK else MIN_DEFAULT


def _verdict_of(result) -> Optional[str]:
    if isinstance(result, Mapping):
        return result.get("verdict")
    if isinstance(result, str):
        return _FROM_WORDS.get(result.strip(), UNKNOWN if result.strip().startswith(UNKNOWN + ":") else None)
    return None


def allowed(cfg: Mapping, result) -> bool:
    """Whether the labeler may use the model: the check result (check()'s dict, or its saved words) is known
    and at least t1_min_agreement. Unknown, unreadable or missing never is."""
    v = _verdict_of(result)
    return v in _RANK and _RANK[v] >= _RANK[min_agreement(cfg)]


def gated(cfg: Mapping) -> bool:
    """True when config t1_check_file is set at all (even to a bad value): the model then needs a passing check
    on file. Unset (the default) keeps the labeler as it was: the model is used whenever its command is set."""
    return isinstance(cfg, Mapping) and cfg.get(FILE_KEY) not in (None, "")


def _state(cfg: Mapping, env: Mapping[str, str], home: Optional[Path]) -> Path:
    home = Path.home() if home is None else home
    if env.get("LIMITLESS_STATE"):
        return Path(env["LIMITLESS_STATE"])
    st = cfg.get("state")
    return Path(st) if isinstance(st, str) and st else home / ".local/state/limitless"


def check_path(cfg: Mapping, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> Optional[Path]:
    """The saved check file: config t1_check_file, a relative path inside the state dir ($LIMITLESS_STATE, else
    config state, else ~/.local/state/limitless). None when unset, or absolute, or it leaves the state dir."""
    env = os.environ if env is None else env
    v = cfg.get(FILE_KEY) if isinstance(cfg, Mapping) else None
    if not isinstance(v, str) or not v.strip():
        return None
    rel = Path(v)
    if rel.is_absolute() or ".." in rel.parts:
        return None
    return _state(cfg, env, home) / rel


def save(path: Path, result: dict) -> bool:
    """Write the verdict words (one line, no digit) to path, mode 0600, replacing any older verdict."""
    words = str(result.get("words", ""))
    if not words or any(c.isdigit() for c in words) or "\n" in words:
        return False
    tmp = path.with_name(path.name + ".tmp")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(words + "\n")
        os.replace(tmp, path)
    except OSError:
        return False
    return True


def saved(cfg: Mapping, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> Optional[str]:
    """The verdict words on file, or None (no t1_check_file, no file, unreadable, or not a verdict line)."""
    path = check_path(cfg, env, home)
    if path is None:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            line = f.read(MAX_SAVED).split("\n", 1)[0].strip()
    except (OSError, ValueError):
        return None
    if any(c.isdigit() for c in line) or _verdict_of(line) is None:
        return None
    return line


def main(argv=None, env: Optional[Mapping[str, str]] = None) -> int:
    import argparse
    import json
    from .state_reader import config
    p = argparse.ArgumentParser(prog="limitless-t1-check", description="Run the local T1 model once on each fixed "
                                "synthetic labeler prompt and say, in words, how often it agrees with the rule "
                                "labels. Exits zero only when the result meets the minimum agreement.")
    p.add_argument("--json", action="store_true", help="print the counts as JSON")
    args = p.parse_args(argv)
    env = os.environ if env is None else env
    cfg = config(env)
    result = check(labeler.t1_model_cmd(env))
    path = check_path(cfg, env)
    wrote = path is not None and save(path, result)
    ok = allowed(cfg, result)
    if args.json:
        print(json.dumps(dict(result, allowed=ok, saved=wrote, min_agreement=min_agreement(cfg)), sort_keys=True))
        return 0 if ok else 1
    print(text(result))
    print("saved for the labeler" if wrote else "not saved: no check file is set" if path is None
          else "not saved: the check file cannot be written")
    print(f"meets the minimum agreement ({min_agreement(cfg)}): {'yes' if ok else 'no'}")
    return 0 if ok else 1
