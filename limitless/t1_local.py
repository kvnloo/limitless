"""limitless-t1-local: a CPU-only runner for a llama.cpp-style CLI that meets LocalModelLabeler's command contract.

    LIMITLESS_T1_CMD="bin/limitless-t1-local"   (or config "t1_model_cmd")

It reads LocalModelLabeler's one fixed prompt on stdin, runs the CLI once on the CPU and prints exactly one word:
the first word of the prompt's own allowed list that appears in the model's output. Anything else (no allowed
word, any digit in the output, a non-zero exit, a timeout, a missing binary or model file, no allowed list in the
prompt) prints nothing and exits 1, so the labeler keeps the rule label.

- Paths: env LIMITLESS_T1_BIN / LIMITLESS_T1_MODEL, else config "t1_bin" / "t1_model". There is no default path:
  with either unset it never runs anything.
- CPU only: it refuses to start (exit 2) when CUDA_VISIBLE_DEVICES or HIP_VISIBLE_DEVICES is non-empty, gives the
  CLI both set to "" and passes -ngl 0 (no layer offloaded to a GPU). Threads: config "t1_threads", default 2.
- Short and greedy: at most MAX_TOKENS new tokens at temperature zero (top-k one).
- A wall-clock timeout below LocalModelLabeler's (config "t1_timeout_s" can only lower it): the CLI runs in its
  own process group, and the whole group is killed when the time is up, so nothing outlives the labeler.
- It never echoes the prompt, never prints a digit and never writes a file.
"""
from __future__ import annotations

import math
import os
import re
import signal
import subprocess
import sys
from typing import Mapping, Optional

from . import labeler
from .state_reader import config

BIN_ENV, MODEL_ENV = "LIMITLESS_T1_BIN", "LIMITLESS_T1_MODEL"
BIN_KEY, MODEL_KEY, THREADS_KEY, TIMEOUT_KEY = "t1_bin", "t1_model", "t1_threads", "t1_timeout_s"
THREADS = 2
MAX_TOKENS = 8
TIMEOUT_S = labeler.TIMEOUT_S - 1.5   # leaves the labeler time to start this runner and read its answer
MAX_PROMPT = 4096
MAX_OUTPUT = 4096
GPU_VARS = ("CUDA_VISIBLE_DEVICES", "HIP_VISIBLE_DEVICES")
NO_ANSWER, REFUSED = 1, 2
_ALLOWED = re.compile(r"from this set: ([^\n]*?)\.\n")
_WORD = re.compile(r"^[a-z]+(?: [a-z]+)*$")


def allowed_words(prompt: str) -> tuple:
    """The allowed set the prompt names (labeler.PROMPT's "from this set: a, b, c."); () when there is none or any
    entry is not plain lower-case words, so nothing with a digit can ever be printed."""
    m = _ALLOWED.search(prompt or "")
    if not m:
        return ()
    words = tuple(w.strip() for w in m.group(1).split(","))
    return words if words and all(_WORD.match(w) for w in words) else ()


def pick(output: str, prompt: str, allowed: tuple) -> Optional[str]:
    """The allowed word that comes first in the model's output (an echoed prompt removed); None on any doubt:
    no allowed word, or a digit anywhere in what the model said."""
    said = output or ""
    for echo in (prompt, prompt.strip()):
        if echo:
            said = said.replace(echo, " ")
    if re.search(r"\d", said):
        return None
    said = said.lower()
    best = None
    for w in allowed:
        m = re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", said)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), w)
    return best[1] if best else None


def _path(env: Mapping[str, str], cfg: Mapping, env_key: str, cfg_key: str) -> Optional[str]:
    v = env.get(env_key) or cfg.get(cfg_key)
    return v if isinstance(v, str) and v.strip() else None


def paths(env: Mapping[str, str], cfg: Mapping) -> tuple:
    """(binary, model): env first, then config; None for each that is unset. Never a default path."""
    return _path(env, cfg, BIN_ENV, BIN_KEY), _path(env, cfg, MODEL_ENV, MODEL_KEY)


def threads(cfg: Mapping) -> int:
    v = cfg.get(THREADS_KEY)
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else THREADS


def timeout_s(cfg: Mapping) -> float:
    """config t1_timeout_s when it is a positive number below TIMEOUT_S, else TIMEOUT_S: it can only be lowered."""
    v = cfg.get(TIMEOUT_KEY)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
        return TIMEOUT_S
    return min(float(v), TIMEOUT_S)


def argv(binary: str, model: str, prompt: str, n_threads: int) -> list:
    """The llama.cpp CLI call: CPU only (-ngl 0), greedy (--temp 0, --top-k 1), a short token cap, the prompt not
    shown back and no interactive conversation mode."""
    return [binary, "-m", model, "-p", prompt, "-n", str(MAX_TOKENS), "--temp", "0", "--top-k", "1",
            "-ngl", "0", "-t", str(n_threads), "--no-display-prompt", "-no-cnv"]


def _kill(p: subprocess.Popen) -> None:
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except OSError:
        p.kill()


def run_model(cmd: list, timeout: float) -> Optional[str]:
    """The CLI's stdout, or None for a non-zero exit, a timeout or a binary that cannot start. stdin is closed
    and stderr (the CLI's log) is dropped; the CLI gets no GPU and its own process group."""
    env = dict(os.environ, **{k: "" for k in GPU_VARS})
    try:
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             env=env, start_new_session=True)
    except (OSError, ValueError):
        return None
    try:
        out, _ = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill(p)
        p.communicate()
        return None
    finally:
        if p.poll() is None:
            _kill(p)
            p.wait()
    if p.returncode != 0:
        return None
    return out[:MAX_OUTPUT].decode("utf-8", "replace")


def _say(why: str) -> None:
    print(f"local labeler runner: {why}", file=sys.stderr)  # no digit, never the prompt


def main(stdin=None, env: Optional[Mapping[str, str]] = None) -> int:
    env = os.environ if env is None else env
    if any(env.get(k) for k in GPU_VARS):
        _say("refused: a GPU is visible (CUDA_VISIBLE_DEVICES or HIP_VISIBLE_DEVICES is set); run it on the CPU")
        return REFUSED
    prompt = (stdin or sys.stdin).read(MAX_PROMPT)
    allowed = allowed_words(prompt)
    if not allowed:
        _say("no allowed list in the prompt")
        return NO_ANSWER
    cfg = config(env)
    binary, model = paths(env, cfg)
    if binary is None or model is None:
        _say("no model binary or model file set")
        return NO_ANSWER
    if not os.path.isfile(binary) or not os.path.isfile(model):
        _say("the model binary or the model file does not exist")
        return NO_ANSWER
    out = run_model(argv(binary, model, prompt, threads(cfg)), timeout_s(cfg))
    word = None if out is None else pick(out, prompt, allowed)
    if word is None:
        _say("no answer: the rule label is used")
        return NO_ANSWER
    print(word)
    return 0
