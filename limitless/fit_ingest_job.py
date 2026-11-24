"""The FIT import job: CAROL bike FIT files dropped in one folder reach the rides file by themselves.

    run(state_dir, now, dry_run=True, env=None, home=None) -> {"job", "action", "reason"} | None
    state(state_dir, cfg, now) -> (status word, words) for limitless-doctor's "fit import" row

limitless-jobs calls ``run`` once per pass (jobs_runner.run_once, right after the sender ingest row), by the apps
ingest's rule: its event is any new sync row in runs.jsonl (jobs.fit_ingest_verdict), never a clock time. Config
``fit_ingest``: ``off`` (the default: no row, nothing read), ``dry_run`` or ``write``; config ``fit_drop_dir`` names
the folder (a relative path is in the state dir; not set, or not there: skipped).

A due pass that is not itself a dry run lists the ``*.fit`` / ``*.FIT`` files directly in the folder: no
recursion, no symlink (a link is never followed, in or out), no dotfile, only regular files whose modification time
is after the mark's ``read_to``, oldest modification time first, at most FILES_PER_PASS of them (never splitting
files that share one modification time, unless that one time alone fills the pass). It runs fit_ride.run over them
with write=(mode == "write"): only rides whose start instant is not already in the rides file are appended, so a
file imported before, by hand or by an earlier pass, is a duplicate and re-running is safe. A source file is never
moved, renamed, deleted or rewritten.

``read_to`` (the modification time of the newest file read) moves only on a write pass that wrote (or had nothing
to write), so the next pass goes on after it and a dry run always previews the same next files. A file copied into
the folder keeping a modification time older than ``read_to`` is not read; bin/limitless-import-fit imports it by
hand (docs/carol-fit-import.md).

The mark MARK (``fit-ingest.json``, atomic, 0600) holds epoch seconds (``row_at``: the sync row the pass acted on,
``ran_at``: the pass, ``read_to``) and words only: the mode and what the pass did ("added two rides", "nothing
new", "skipped one file: not a bike ride", "more files wait for the next pass"); never a file name, a path or a
number from a ride. Nothing is pushed or logged as sent; no process is started. Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping, Optional

from . import fit_ride, jobs
from .state_reader import StateReader, config

TITLE = jobs.FIT_INGEST.send_title        # "FIT import": the job's row name in limitless-jobs
MARK = "fit-ingest.json"
FILES_PER_PASS = 20                       # at most this many files read per pass; the rest wait for the next
SUFFIX = ".fit"                           # matched without case: *.fit and *.FIT
NOTHING_NEW = "nothing new"
MORE_WAIT = "more files wait for the next pass"
MODE_WORDS = {jobs.FIT_DRY_RUN: "dry run", jobs.FIT_WRITE: "write"}
_EPOCHS = ("row_at", "ran_at", "read_to")
_WORD_KEYS = ("mode", "said")


def drop_dir(state_dir, cfg: Optional[Mapping]) -> Optional[Path]:
    """Config ``fit_drop_dir`` as a path (a relative one is in the state dir); None when not set or blank."""
    v = cfg.get(jobs.FIT_DIR_CONFIG) if isinstance(cfg, Mapping) else None
    if not isinstance(v, str) or not v.strip():
        return None
    p = Path(v.strip()).expanduser()
    return p if p.is_absolute() else Path(state_dir) / p


def load_mark(state_dir) -> dict:
    """MARK as ``{"row_at", "ran_at", "read_to", "mode", "said"}`` (epochs or None, words or None); {} when missing
    or malformed."""
    try:
        data = json.loads((Path(state_dir) / MARK).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for k in _EPOCHS:
        v = data.get(k)
        out[k] = float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    for k in _WORD_KEYS:
        out[k] = data.get(k) if isinstance(data.get(k), str) else None
    return out


def listing(folder, after: Optional[float] = None, cap: int = FILES_PER_PASS) -> tuple:
    """(paths to read this pass, oldest modification time first; whether more wait; the newest modification time
    read, else ``after``). Only regular ``*.fit`` files directly in ``folder``, never a symlink or a dotfile, with a
    modification time after ``after``. Never more than ``cap`` unless the files at the cap share one modification
    time from the first one on. An unreadable folder lists nothing."""
    found = []
    try:
        with os.scandir(folder) as it:
            for e in it:
                if e.name.startswith(".") or not e.name.lower().endswith(SUFFIX):
                    continue
                try:
                    if e.is_symlink() or not e.is_file(follow_symlinks=False):
                        continue
                    mt = e.stat(follow_symlinks=False).st_mtime
                except OSError:
                    continue
                if after is None or mt > after:
                    found.append((mt, e.name, e.path))
    except OSError:
        return [], False, after
    found.sort()
    take = len(found)
    if take > cap:
        edge = found[cap][0]
        take = cap
        while take > 0 and found[take - 1][0] == edge:     # never split one modification time across passes
            take -= 1
        if take == 0:                                      # one time fills the pass: take all of it
            take = sum(1 for f in found if f[0] == edge)
    chosen = found[:take]
    return [Path(p) for _, _, p in chosen], take < len(found), (chosen[-1][0] if chosen else after)


def said(out: dict, write: bool, more: bool = False) -> str:
    """What one pass did, in words, digit-free (fit_ride.run's result): the rides added (or that would be), else
    "nothing new"; each skip reason with its file count; files already imported; whether more files wait."""
    parts = []
    if out.get("why"):
        parts.append(f"added no rides: {out['why']}")
    elif out.get("added"):
        parts.append(("added " if write else "would add ") + fit_ride.rides_words(out["added"]))
    else:
        parts.append(NOTHING_NEW)
    files = out.get("files") or []
    for reason in dict.fromkeys(f["reason"] for f in files if f["status"] == fit_ride.SKIPPED):
        n = sum(1 for f in files if f["status"] == fit_ride.SKIPPED and f["reason"] == reason)
        parts.append(f"skipped {fit_ride.count_words(n, 'file')}: {reason}")
    already = sum(1 for f in files if f["status"] == fit_ride.DUPLICATE and f["reason"] == fit_ride.ALREADY)
    twice = sum(1 for f in files if f["status"] == fit_ride.DUPLICATE and f["reason"] != fit_ride.ALREADY)
    if already:
        parts.append(f"{fit_ride.count_words(already, 'file')} already in the rides file")
    if twice:
        parts.append(f"{fit_ride.count_words(twice, 'file')} the same ride as an earlier file")
    if more:
        parts.append(MORE_WAIT)
    return "; ".join(parts)


def run_pass(state_dir, folder, rides_file, row_at: Optional[float], now: float, mode: str) -> dict:
    """List the folder after the mark's ``read_to`` (listing), run fit_ride.run over those files (appending only
    in write mode) and write the mark: ``row_at``, ``ran_at`` (``now``), ``read_to`` (moved only by a write pass
    that wrote or had nothing to write; else kept), the mode and what it did in words. Returns the mark. Never
    touches a source file; sends nothing."""
    from .jobs_runner import _write_mark    # late: jobs_runner imports this module inside run_once
    write = mode == jobs.FIT_WRITE
    after = load_mark(state_dir).get("read_to")
    paths, more, read_to = listing(folder, after)
    out = fit_ride.run(paths, rides_file, write=write)
    mark = {"row_at": row_at, "ran_at": float(now), "mode": mode, "said": said(out, write, more)}
    keep = read_to if write and out.get("written") else after
    if keep is not None:
        mark["read_to"] = keep
    _write_mark(state_dir, MARK, mark)
    return mark


def _verdict(state_dir, cfg: Mapping, mode: str, now: float):
    folder = drop_dir(state_dir, cfg)
    exists = folder is not None and folder.is_dir()
    v = jobs.fit_ingest_verdict(mode, StateReader(Path(state_dir)).last_run(), load_mark(state_dir).get("row_at"),
                                now, dir_set=folder is not None, dir_exists=exists)
    return v, folder


def run(state_dir, now: float, dry_run: bool = True, env: Optional[Mapping[str, str]] = None,
        home: Optional[Path] = None) -> Optional[dict]:
    """The FIT import's ``{job, action, reason}`` row, or None when config ``fit_ingest`` is off (no row, nothing
    read). Due and not ``dry_run``: runs it (run_pass) and says what it did in words; ``dry_run``: the verdict
    only, nothing read, run or written."""
    cfg = config(env, home)
    mode = jobs.fit_mode(cfg)
    if mode == jobs.FIT_OFF:
        return None
    v, folder = _verdict(state_dir, cfg, mode, now)
    if v.action != jobs.RUN:
        return {"job": TITLE, "action": v.action, "reason": v.reason}
    if dry_run:
        return {"job": TITLE, "action": v.action, "reason": f"{v.reason}; dry run of limitless-jobs: not run"}
    rides_file = StateReader(Path(state_dir)).rides_file(env, home)
    try:
        mark = run_pass(state_dir, folder, rides_file, v.trigger_at, now, mode)
    except OSError as e:
        return {"job": TITLE, "action": jobs.HOLD,
                "reason": f"{v.reason}; a file was not written ({type(e).__name__}); the next run tries again"}
    return {"job": TITLE, "action": v.action, "reason": f"{v.reason}; {MODE_WORDS[mode]}: {mark['said']}"}


def state(state_dir, cfg: Mapping, now: float) -> tuple:
    """(``off`` / ``no folder`` / ``missing`` / ``waiting`` / ``not run`` / ``ran``, words) for the doctor's row,
    from config, runs.jsonl and the mark. ``ran`` carries (mode words, the mark's ``ran_at``, what that pass did).
    Words only, never a path or a file name. Read-only."""
    mode = jobs.fit_mode(cfg)
    if mode == jobs.FIT_OFF:
        return "off", f"the FIT import is {jobs.FIT_IS_OFF}"
    v, _ = _verdict(state_dir, cfg, mode, now)
    on = MODE_WORDS[mode]
    if v.reason == jobs.FIT_NO_DIR:
        return "no folder", f"{on}: no drop folder set (config {jobs.FIT_DIR_CONFIG})"
    if v.reason == jobs.FIT_DIR_MISSING:
        return "missing", f"{on}: the drop folder does not exist (config {jobs.FIT_DIR_CONFIG})"
    if v.action == jobs.RUN:
        return "waiting", f"{on}: a sync ran and the FIT import has not run after it yet ({jobs.INGEST_RUNS} runs it)"
    mark = load_mark(state_dir)
    if mark.get("ran_at") is None:
        return "not run", f"{on}: it has not run yet: {v.reason}"
    return "ran", (MODE_WORDS.get(mark.get("mode") or "", "unknown mode"), mark["ran_at"],
                   mark.get("said") or "unknown")
