"""Sender probe: settle an ``unknown: ...`` sender candidate with Hermes' own ``hermes -p <name> send --list telegram``.

    probe(cfg, env=None, hermes_home=None, timeout=TIMEOUT_S) -> [(name, verdict words, fingerprint)]
    save(state_dir, results, now)                             # push_sender.PROBE_FILE, atomic, 0600
    verdict(rc, out, err)                                      # TARGETS_FOUND / NO_TARGETS / CHECK_FAILED

push_sender.readiness judges a profile from its files only, so a profile whose ``config.yaml`` has a ``secrets:``
source stays a maybe (SECRET_SOURCE) and the push recovery words keep offering it. The operator can ask Hermes
instead: ``probe`` runs ``<hermes_bin> -p <name> send --list telegram`` (config ``hermes_bin``, default ``hermes``
on PATH; env = ``env``, default the current process's; TIMEOUT_S) once for each candidate push_sender.candidates
(without a probe applied) answers ``unknown: ...`` for, never for a READY / NO_TOKEN / NO_CHAT / MISSING one. It
lists targets only and never sends.

Mirrors NousResearch/hermes-agent hermes_cli/send_cmd.py: ``cmd_send`` short-circuits ``--list`` (the positional
``telegram`` is the platform filter) into ``_list_targets`` and exits with its return code. A platform filter that
matches nothing is ``_fail("hermes send: no targets found for platform '<p>'. Configured: ...")``, exit 1
(``_FAILURE_EXIT``): NO_TARGETS; so is the unfiltered "No messaging platforms configured" notice (exit 0). A
filtered listing prints ``telegram:`` then its channels (or "(no channels discovered yet)"), exit 0
(``_SUCCESS_EXIT``): Telegram is configured for the profile, TARGETS_FOUND. Anything else (a timeout, another
non-zero exit, a missing binary, an unexpected output) is CHECK_FAILED. The output is read only to pick the
verdict: it is never printed, stored or returned. hermes_cli/main.py loads the profile's ``.env`` and its external
secret sources (``load_hermes_dotenv``) before any subcommand, so a token kept in a secret source counts.

``save`` merges TARGETS_FOUND / NO_TARGETS verdicts into push_sender.PROBE_FILE with the time and the profile's
fingerprint (push_sender.fingerprint: ``config.yaml`` and ``.env`` st_mtime_ns); a CHECK_FAILED leaves that
profile's entry as it was. push_sender.candidates applies the record while the fingerprint matches. An operator
command only (bin/limitless-sender-probe): no job, timer or tool runs it. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import Mapping, Optional

from . import push_sender

PROBE_FILE = push_sender.PROBE_FILE   # sender-probe.json in the state dir
TARGETS_FOUND, NO_TARGETS = push_sender.PROBE_TARGETS, push_sender.PROBE_NONE
CHECK_FAILED = push_sender.UNKNOWN_PREFIX + "the check failed"
TIMEOUT_S = 15.0
HERMES_BIN_CONFIG, HERMES_BIN_DEFAULT = "hermes_bin", "hermes"
# hermes_cli/send_cmd.py _list_targets: the filtered no-match failure (stderr, exit 1) and the empty notice (stdout)
_NO_TARGETS_ERR = "no targets found for platform 'telegram'"
_NOTHING_CONFIGURED = "No messaging platforms configured"


def hermes_bin(cfg: Optional[Mapping]) -> str:
    """Config ``hermes_bin`` when it is a non-blank string, else ``hermes`` (looked up on the child's PATH)."""
    v = cfg.get(HERMES_BIN_CONFIG) if isinstance(cfg, Mapping) else None
    return v.strip() if isinstance(v, str) and v.strip() else HERMES_BIN_DEFAULT


def verdict(rc: Optional[int], out: str, err: str) -> str:
    """The words for one ``send --list telegram`` run (see the module doc)."""
    if rc == 1 and _NO_TARGETS_ERR in err:
        return NO_TARGETS
    if rc == 0 and out.lstrip().startswith(_NOTHING_CONFIGURED):
        return NO_TARGETS
    if rc == 0 and any(line.strip() == "telegram:" for line in out.splitlines()):
        return TARGETS_FOUND
    return CHECK_FAILED


def run_one(binary: str, name: str, env: Mapping[str, str], timeout: float = TIMEOUT_S) -> str:
    """Run ``<binary> -p <name> send --list telegram`` in its own process group with ``env`` and no stdin; the
    verdict words. A timeout kills that group (the child this started, nothing else). Never raises."""
    argv = [binary, "-p", name, "send", "--list", "telegram"]
    try:
        p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env=dict(env), start_new_session=True)
    except (OSError, ValueError, subprocess.SubprocessError):
        return CHECK_FAILED
    with p:
        try:
            out, err = p.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                p.kill()
            p.communicate()
            return CHECK_FAILED
        except Exception:  # noqa: BLE001 - a broken pipe is a failed check
            p.kill()
            p.communicate()
            return CHECK_FAILED
    return verdict(p.returncode, out.decode("utf-8", "replace"), err.decode("utf-8", "replace"))


def probe(cfg: Optional[Mapping], env: Optional[Mapping[str, str]] = None, hermes_home=None,
          timeout: float = TIMEOUT_S) -> Optional[list]:
    """``[(name, verdict, fingerprint)]`` for each candidate whose own readiness (push_sender.candidates with no
    probe applied) starts with ``unknown: ``, sorted by name; None when no Hermes home is known (nothing ran).
    The fingerprint is taken before the run, so a file changed meanwhile makes the record stale; a profile whose
    files cannot be stat'ed is CHECK_FAILED and hermes is not run for it."""
    env = os.environ if env is None else env
    cfg = cfg if isinstance(cfg, Mapping) else {}
    root = Path(hermes_home) if hermes_home is not None else push_sender.hermes_root(env)
    cands = push_sender.candidates(cfg, env, root, probed=False)
    if cands is None:
        return None
    binary, out = hermes_bin(cfg), []
    for name, words in cands:
        if not words.startswith(push_sender.UNKNOWN_PREFIX):
            continue
        fp = push_sender.fingerprint(push_sender.profile_dir(root, name))
        out.append((name, run_one(binary, name, env, timeout) if fp is not None else CHECK_FAILED, fp))
    return out


def save(state_dir, results: Optional[list], now: float) -> None:
    """Merge ``results`` (probe's) into push_sender.PROBE_FILE in ``state_dir``: each TARGETS_FOUND / NO_TARGETS
    as ``{"verdict": words, "at": now, "files": fingerprint}``; a CHECK_FAILED keeps that profile's old entry.
    Atomic (a temp file there, then a rename), mode 0600. No output of hermes is ever stored."""
    data = push_sender.load_probes(state_dir)
    for name, words, fp in results or ():
        if words in (TARGETS_FOUND, NO_TARGETS) and fp is not None:
            data[name] = {"verdict": words, "at": float(now), "files": dict(fp)}
    d = Path(state_dir)
    d.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + push_sender.PROBE_FILE + ".", suffix=".tmp", dir=str(d))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, d / push_sender.PROBE_FILE)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
