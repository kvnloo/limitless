"""limitless-doctor: a read-only report of which inputs are live and which tools would answer unknown, and why.

    report(cfg, now) -> [{"name", "kind", "status", "reason"}]

status is one of STATUSES: live, stale, missing or off. The rows are the state dir (exists, readable), each
input named in inputs.json against the stale threshold limitless_status already uses (envelope.STALE_H), the
last sync run's age in words from runs.jsonl, then the uptime row (uptime_audit over runs.jsonl: live when the
uptime goal was met, stale when not, missing when unknown; kind source, words only), the delivery row
(north-star row two as the scorecard measures it, complaints included: off with no push log, live when met,
stale when not, missing when unknown; kind source, words only), the push sender row (whether kevin-push's
Hermes profile can reach Telegram, push_sender.readiness: live when ready, missing when the profile does not
exist, has no Telegram bot token or no chat, or it cannot be told; hermes is never run and no secret value is
read; kind source, words only), the Sleep mode row (sleepmode.jsonl's last row as
kevin-push's hold reads it: off, on since some words, left on and ignored, stale when on far longer than a night,
or unknown; kind source, words only), the local labeler's row (env LIMITLESS_T1_CMD
or config t1_model_cmd: off, set or broken; files are checked, the model is never run), one row per tool in
plugin.yaml, from that tool's own
envelope for an empty call, the Open Wearables export's row (config open_wearables_export, its mark
open-wearables.json; the server is never called), the NOOP export job's row (config noop_export,
its mark noop-export.json), just before both the sleep coverage row (sleep_coverage over config sleep_file and
the phone proxy: live when the wearable goal was met, stale when not, missing when unknown, off with no sleep
file; words only) and, before that, the context packet's row (config context_packet_path: off, live
when written within STALE_H, else stale; read from the packet's own generated_at), with the voice MIQ's row
(config voice_miq, its mark voice-miq.json) just before it. Right after the tool rows comes the NOOP MCP row
(config noop_mcp and t0_tools; the server is never started), then the desktop ActivityWatch's row (config
desktop_aw_url or desktop_aw_export: off, live, stale, or unreachable as status missing; the only row that may
call a server, read-only, with a short timeout), then the feed reflex's row (config feed_apps and aw_db: off,
live, or unknown as status missing; words only, never its value), then the apps lists row (off, or each list
set from the environment, from config or from a reply; never an app name), then the apps ask row (the wake
brief's app-lists ask: off, waiting, told recently or not needed; words only), then the apps ingest job's row,
then the ranked ledger's row (scorecard row ten's private ledger, config ranked_ledger: off, live with row ten's
words, or broken as status missing; never an id or evidence text), then the ranked ingest job's row (config
ranked_ingest, its status file ranked-ingest.json: off, live with the mode and the last result in words, stale,
or broken as status missing).
Reasons are words only: a digit is never printed, and neither is a tool's value.
Nothing here writes, sends, pushes or starts a job.
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from datetime import date
from pathlib import Path
from typing import Mapping, Optional

from . import card, mock_guard, noop_mcp, tier_audit, tools
from .envelope import STALE_H
from .state_reader import StateReader, config, parse_ts

LIVE, STALE, MISSING, OFF = "live", "stale", "missing", "off"
STATUSES = (LIVE, STALE, MISSING, OFF)
STRICT_KINDS = ("state", "input", "run")   # the rows --strict counts


def _row(name: str, kind: str, status: str, reason: str) -> dict:
    return {"name": name, "kind": kind, "status": status, "reason": reason}


def state_path(cfg: Mapping, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> Path:
    """$LIMITLESS_STATE, else "state" in cfg, else ~/.local/state/limitless (state_reader.state_dir's rule)."""
    env = os.environ if env is None else env
    home = Path.home() if home is None else home
    if env.get("LIMITLESS_STATE"):
        return Path(env["LIMITLESS_STATE"])
    st = cfg.get("state") if isinstance(cfg, Mapping) else None
    return Path(st) if isinstance(st, str) and st else home / ".local/state/limitless"


def state_row(path: Path) -> dict:
    if not path.is_dir():
        return _row("state dir", "state", MISSING, "the state dir does not exist")
    try:
        with os.scandir(path) as it:
            next(it, None)
    except OSError:
        return _row("state dir", "state", MISSING, "the state dir exists but is not readable")
    return _row("state dir", "state", LIVE, "the state dir exists and is readable")


INPUT_WORDS = {   # limitless_status's state per input -> (status, reason)
    "recording": (LIVE, "recording: updated within the last day"),
    "not recording": (STALE, "not recording: no update for over a day"),
    "down": (STALE, "not recording: the sync reports it down"),
    "unknown": (MISSING, "no age for this input in inputs.json"),
    "demo": (MISSING, "a demo or sample device: demo rows never count as live"),
}


def input_rows(status_env: dict) -> list:
    """One row per input named in inputs.json, from limitless_status (tools.status): the same STALE_H
    threshold, the same snapshot-age rule. No inputs file is one missing row with that tool's reason."""
    if not isinstance(status_env, dict) or status_env.get("value") is None:
        reason = (status_env or {}).get("reason") or "no inputs.json in the state dir"
        return [_row("inputs", "input", MISSING, reason)]
    out = []
    for name, got in sorted(status_env["value"]["inputs"].items()):
        status, reason = INPUT_WORDS.get(got.get("state"), INPUT_WORDS["unknown"])
        out.append(_row(f"input {name}", "input", status, reason))
    return out


_NUMBERS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
            "sixteen seventeen eighteen nineteen twenty twenty-one twenty-two twenty-three").split()


def age_words(age_h: float) -> str:
    """An age in hours as words, never a digit: under an hour, about N hours, about N days, over a week ago."""
    if age_h < 1:
        return "under an hour ago"
    if age_h < 2:
        return "about an hour ago"
    if age_h < 24:
        return f"about {_NUMBERS[int(age_h)]} hours ago"
    if age_h < 48:
        return "about a day ago"
    if age_h < 7 * 24:
        return f"about {_NUMBERS[int(age_h // 24)]} days ago"
    return "over a week ago"


def run_row(reader: StateReader, now: float) -> dict:
    """The last valid row of runs.jsonl (StateReader.last_run): live when at most STALE_H old and not failed."""
    run = reader.last_run()
    at = parse_ts((run or {}).get("at"))
    if at is None or not math.isfinite(at):
        return _row("last sync run", "run", MISSING, "no timestamped row in runs.jsonl")
    age_h = (now - at) / 3600
    if age_h < 0:
        return _row("last sync run", "run", STALE, "the last sync run is timestamped in the future")
    ok = run.get("ok")
    tail = " and failed" if ok is False else " and finished ok" if ok is True else ""
    status = LIVE if age_h <= STALE_H and ok is not False else STALE
    return _row("last sync run", "run", status, f"the last sync run was {age_words(age_h)}{tail}")


UPTIME_ROW = "uptime"
_UPTIME_STATUS = {"met": LIVE, "not met": STALE, "unknown": MISSING}   # uptime_audit's goal -> row status


def uptime_row(reader: StateReader, now: float) -> dict:
    """The uptime audit (tools.uptime_audit over runs.jsonl, config uptime_days, uptime_target and
    outage_ignore): live when the uptime goal was met over the window, stale when it was not, missing when it is
    unknown (no run log, no run in the window, too few runs that name their stale inputs, or too many unknown
    days). The reason is the audit's T1 words or why it is unknown, never a count. Kind ``source``: --strict does
    not count it. Read-only."""
    from . import uptime_audit as ua
    a = tools.uptime_audit(reader, now)
    if a is None:
        return _row(UPTIME_ROW, "source", MISSING, ua.NO_LOG_REASON)
    if not any(d["runs"] for d in a["days"]):
        return _row(UPTIME_ROW, "source", MISSING, ua.NO_ROWS_REASON)
    words = a["label"]["label"]
    if words == ua.UNKNOWN:
        return _row(UPTIME_ROW, "source", MISSING, ua.FEW_KNOWN_REASON)
    return _row(UPTIME_ROW, "source", _UPTIME_STATUS.get(a["goal"], MISSING), words)


DELIVERY_ROW = "delivery"
_DELIVERY_STATUS = {"met": LIVE, "not met": STALE}   # delivery_audit.goal -> row status; unknown is missing


def delivery_row(reader: StateReader, cfg: Mapping, now: float, env: Optional[Mapping[str, str]] = None,
                 home: Optional[Path] = None, tz=None) -> dict:
    """North-star row two as the scorecard measures it (scorecard._delivery_measured: the delivery audit of
    kevin-push's log, config push_log, with the complaints from the Hermes DB, config hermes_db, and
    quiet.json): off when no push log is set; live when the goal is met, stale when it is not, missing when it is
    unknown (complaints unknown included). The reason is the audit's T1 words, never a count or a reply; when
    the goal is not met and a wake brief was missed it ends with the most common miss reason
    (delivery_audit.miss_clause). Kind ``source``: --strict does not count it. Read-only."""
    from . import delivery_audit as da, scorecard
    try:
        label, goal, a = scorecard._delivery_measured(reader.path, cfg if isinstance(cfg, Mapping) else {}, now,
                                                      tz, env, home)
    except Exception as exc:  # noqa: BLE001 - a failing audit is a row, never a traceback (its message stays out)
        return _row(DELIVERY_ROW, "source", MISSING, f"the delivery audit failed with {type(exc).__name__}")
    if label == da.NO_LOG:
        return _row(DELIVERY_ROW, "source", OFF, da.NO_LOG_REASON)
    clause = da.miss_clause(a) if goal == da.GOAL_NOT_MET else ""
    return _row(DELIVERY_ROW, "source", _DELIVERY_STATUS.get(goal, MISSING), f"{label}; {clause}" if clause else label)


PUSH_SENDER_ROW = "push sender"


def push_sender_row(cfg: Mapping, env: Optional[Mapping[str, str]] = None,
                    hermes_home: "Path | str | None" = None) -> dict:
    """Whether bin/kevin-push's sender profile can reach Telegram (push_sender.readiness over the profile
    $KEVIN_PUSH_PROFILE, else config ``push_profile``, else the default, and its target): live when ``ready``;
    missing when the profile does not exist (``missing: ...``), has no Telegram bot token or no chat to send to,
    or it cannot be told (``unknown: ...``). Files only, and only whether a key is present: hermes is never run,
    no process is started, nothing is sent and no secret value is read. Report-only: kevin-push's own preflight
    is push_sender.check. Words only: never a value, the profile name, the target or a path. Kind ``source``:
    --strict does not count it."""
    from . import push_sender
    words = push_sender.readiness(cfg if isinstance(cfg, Mapping) else {}, os.environ if env is None else env,
                                  hermes_home)
    return _row(PUSH_SENDER_ROW, "source", LIVE if words == push_sender.READY else MISSING, words)


SLEEP_MODE_ROW = "Sleep mode"
SLEEP_LEFT_ON = "left on, ignored since the owner was seen up"
SLEEP_STALE = "stale: on far longer than a night"
SLEEP_HELD, SLEEP_NOT_HELD = "pushes are being held", "the Sleep mode poll is not fresh, so pushes are not held"


def sleep_mode_row(cfg: Mapping, now: float, env: Optional[Mapping[str, str]] = None) -> dict:
    """Phone Sleep mode as kevin-push's hold reads it (sleepmode.path: $LIMITLESS_SLEEPMODE, else sleepmode.jsonl in
    the state dir), from the last readable row: "off" (live); "on since <age words>" (live); "left on, ignored
    since the owner was seen up" (stale) when it is the poller's inferred off row with ``left_on``; "stale: on far
    longer than a night; pushes are being held" when the current activation began over sleepmode.NIGHT_H ago and
    no such row closed it. An on row adds that pushes are not held while the poll heartbeat is not fresh
    (kevin-push fails open). "unknown: <reason>" (missing) with no file, an unreadable one, no readable row or a
    last row in the future. Words only: never a time, a rule id or a path. Kind ``source``. Read-only."""
    from . import sleepmode
    env = os.environ if env is None else env
    p = sleepmode.path(state_path(cfg, env), env)
    if not p.exists():
        return _row(SLEEP_MODE_ROW, "source", MISSING, "unknown: no Sleep mode file in the state dir")
    got = sleepmode.read(p)
    if got is None:
        return _row(SLEEP_MODE_ROW, "source", MISSING, "unknown: the Sleep mode file could not be read")
    if not got:
        return _row(SLEEP_MODE_ROW, "source", MISSING, "unknown: no Sleep mode row with a time and an on or off")
    at, last = got[-1]
    if at > now:
        return _row(SLEEP_MODE_ROW, "source", MISSING, "unknown: the last Sleep mode row is timestamped in the future")
    if sleepmode.is_left_on(last):
        return _row(SLEEP_MODE_ROW, "source", STALE, SLEEP_LEFT_ON)
    if not last["on"]:
        return _row(SLEEP_MODE_ROW, "source", LIVE, "off")
    age_h = max(0.0, now - sleepmode.since(got)) / 3600
    held = sleepmode.poll_fresh(p, now)
    if age_h > sleepmode.NIGHT_H:
        return _row(SLEEP_MODE_ROW, "source", STALE, f"{SLEEP_STALE}; {SLEEP_HELD if held else SLEEP_NOT_HELD}")
    tail = "" if held else f"; {SLEEP_NOT_HELD}"
    return _row(SLEEP_MODE_ROW, "source", LIVE, f"on since {age_words(age_h)}{tail}")


LOCAL_LABELER_ROW = "local labeler"
RUNNER = "limitless-t1-local"
_RULES_USED = "; the rule labels are used"
LOCAL_WORDS = {   # local_labeler_row's verdict -> (status, reason); never the command, a path or a digit
    "off": (OFF, "no local model command set, so the rule labels are used"),
    "set": (LIVE, "set: the command, the model binary and the model file exist (the model is not run here)"),
    "set other": (LIVE, "set: the command exists; it is not the bundled runner, so no model file is checked (the "
                        "model is not run here)"),
    "unreadable": (MISSING, "broken: the command line cannot be read" + _RULES_USED),
    "no program": (MISSING, "broken: the command's program does not exist" + _RULES_USED),
    "no paths": (MISSING, "broken: the runner's model binary or model file is not set" + _RULES_USED),
    "no files": (MISSING, "broken: the model binary or the model file does not exist" + _RULES_USED),
}


def _local_verdict(cfg: Mapping, env: Mapping[str, str]) -> str:
    import shlex
    import shutil
    from . import labeler, t1_local
    cmd = env.get(labeler.ENV_KEY) or (cfg.get(labeler.CONFIG_KEY) if isinstance(cfg, Mapping) else None)
    if not isinstance(cmd, str) or not cmd.strip():
        return "off"
    try:
        argv = shlex.split(cmd)
    except ValueError:
        return "unreadable"
    if not argv or shutil.which(argv[0], path=env.get("PATH") or os.defpath) is None:
        return "no program"
    runner = [a for a in argv if os.path.basename(a) == RUNNER]
    if not runner:
        return "set other"
    if not all(os.path.isfile(a) for a in runner):
        return "no program"
    binary, model = t1_local.paths(env, cfg if isinstance(cfg, Mapping) else {})
    if binary is None or model is None:
        return "no paths"
    return "set" if os.path.isfile(binary) and os.path.isfile(model) else "no files"


def local_labeler_row(cfg: Mapping, env: Optional[Mapping[str, str]] = None) -> dict:
    """The optional local T1 model (labeler.LocalModelLabeler: $LIMITLESS_T1_CMD, else config ``t1_model_cmd``):
    off when unset; set when the command's program exists and, for the bundled runner (bin/limitless-t1-local),
    its model binary and model file ($LIMITLESS_T1_BIN / $LIMITLESS_T1_MODEL, else config ``t1_bin`` /
    ``t1_model``) exist too; broken (status missing) when the command cannot be read or a file is missing. Only
    checks that files exist: the model is never run and no process is started. Words only: never the command, a
    path or a digit. Kind ``labeler``: --strict does not count it.

    A set row also says whether a passing local model check (bin/limitless-t1-check) is on file: "set: checked,
    <its verdict words>" or "set: not checked yet". With config t1_check_file set, a missing or failing check
    makes the row off: the labeler keeps the rule labels then. Only the small saved file is read."""
    env = os.environ if env is None else env
    verdict = _local_verdict(cfg, env)
    status, reason = LOCAL_WORDS[verdict]
    if verdict in ("set", "set other"):
        status, reason = _checked(cfg if isinstance(cfg, Mapping) else {}, env, status, reason[len("set: "):])
    return _row(LOCAL_LABELER_ROW, "labeler", status, reason)


def _checked(cfg: Mapping, env: Mapping[str, str], status: str, files: str) -> tuple:
    from . import t1_agreement as ta
    if not ta.gated(cfg):
        return status, f"set: not checked yet (no check file is set, so none is required); {files}"
    words = ta.saved(cfg, env)
    if words is None:
        return OFF, f"set: not checked yet, so the rule labels are used until a passing check is on file; {files}"
    if not ta.allowed(cfg, words):
        return OFF, f"set: checked, {words}, below the minimum, so the rule labels are used; {files}"
    return status, f"set: checked, {words}; {files}"


NOOP_ROW = "job NOOP export"
_NOOP_MODE_WORDS = {"dry_run": "dry run mode (counts only, no file written)", "write": "write mode"}


def noop_export_row(reader: StateReader, cfg: Mapping, now: float) -> dict:
    """The NOOP export job (jobs.NOOP_EXPORT, config ``noop_export``) from runs.jsonl and its mark noop-export.json:
    off by config; stale while the newest sync copied the NOOP database and the export has not run after it, when
    no sync has copied it yet, or when the last run exported nothing or could not write; else live. Words only."""
    from . import jobs, jobs_runner   # jobs_runner -> noop_export; card imports jobs_runner too
    mode = jobs.noop_mode(cfg)
    if mode == jobs.NOOP_OFF:
        return _row(NOOP_ROW, "job", OFF, f"the NOOP export job is {jobs.NOOP_IS_OFF}")
    mark = jobs_runner.load_noop_mark(reader.path)
    v = jobs.noop_export_verdict(mode, reader.last_run(), mark.get("row_at"), now)
    if v.action == jobs.RUN:
        return _row(NOOP_ROW, "job", STALE, "a sync copied the NOOP database and the export has not run after it "
                                            "yet (limitless-jobs --send runs it)")
    if mark.get("ran_at") is None:
        return _row(NOOP_ROW, "job", STALE, f"on ({_NOOP_MODE_WORDS[mode]}), but no sync run has copied the NOOP "
                                            "database yet")
    ago = age_words(max(0.0, now - mark["ran_at"]) / 3600)
    said = mark["said"][0] if mark.get("said") else "nothing said"
    outcome = mark.get("outcome") or "unknown"
    ran = f"{_NOOP_MODE_WORDS.get(mark.get('mode'), 'unknown mode')}: ran {ago} after a sync that copied the NOOP " \
          f"database"
    if outcome == jobs_runner.NOOP_DONE:
        demo = f"; {mock_guard.LEFT_OUT}" if any(mock_guard.LEFT_OUT in s for s in mark.get("said") or ()) else ""
        return _row(NOOP_ROW, "job", LIVE, f"{ran}: {outcome}{demo}")
    if outcome == jobs_runner.NOOP_NOTHING:
        return _row(NOOP_ROW, "job", STALE, f"{ran}: {outcome}: {said}")
    return _row(NOOP_ROW, "job", STALE, f"{ran}: {outcome}")


APPS_INGEST_ROW = "job apps ingest"
_APPS_DID = {"nothing": "no new apps reply", "would write": "would write the app lists",
             "write": "wrote the app lists"}
APPS_TOLD, APPS_NOT_TOLD = "told in a brief", "not told yet"   # the last write, after it (apps-set.json)


def apps_ingest_row(reader: StateReader, cfg: Mapping, now: float, env: Optional[Mapping[str, str]] = None) -> dict:
    """The apps ingest job (jobs.APPS_INGEST, config ``apps_ingest``) from runs.jsonl and its mark apps-ingest.json:
    off by config; stale with no Hermes DB set, before any sync run, or while the newest sync is one it has not run
    after; else live, with what the last run did in words and, once any run wrote the lists, whether that write was
    "told in a brief" or "not told yet" (jobs_runner.apps_set_told). Never an app name or reply text; read-only."""
    from . import habit_replies, jobs, jobs_runner
    mode = jobs.apps_mode(cfg)
    if mode == jobs.APPS_OFF:
        return _row(APPS_INGEST_ROW, "job", OFF, f"the apps ingest job is {jobs.APPS_IS_OFF}")
    db = habit_replies.hermes_db_from(reader.path, cfg, env)
    mark = jobs_runner.load_apps_mark(reader.path)
    v = jobs.apps_ingest_verdict(mode, reader.last_run(), mark.get("row_at"), now, db_set=db is not None)
    on = f"on ({_NOOP_MODE_WORDS[mode]})"
    if v.reason == jobs.APPS_NO_DB:
        return _row(APPS_INGEST_ROW, "job", STALE, f"{on}, but {v.reason}")
    if v.action == jobs.RUN:
        return _row(APPS_INGEST_ROW, "job", STALE, "a sync ran and the apps ingest has not run after it yet "
                                                   "(limitless-jobs --send runs it)")
    if mark.get("ran_at") is None:
        return _row(APPS_INGEST_ROW, "job", STALE, f"{on}, but it has not run yet: {v.reason}")
    ago = age_words(max(0.0, now - mark["ran_at"]) / 3600)
    did = _APPS_DID.get(mark.get("action"), "unknown")
    told = jobs_runner.apps_set_told(reader.path)
    said = "" if told is None else f"; {APPS_TOLD if told else APPS_NOT_TOLD}"
    return _row(APPS_INGEST_ROW, "job", LIVE,
                f"{_NOOP_MODE_WORDS.get(mark.get('mode'), 'unknown mode')}: ran {ago} after a sync: {did}{said}")


RANKED_INGEST_ROW = "job ranked ingest"
_RANKED_DID = {"nothing": "no new owner message", "ignore": "no owner drop to append",
               "would write": "would append owner drop rows", "write": "appended owner drop rows"}


def ranked_ingest_row(reader: StateReader, cfg: Mapping, now: float, env: Optional[Mapping[str, str]] = None) -> dict:
    """The ranked ingest job (jobs.RANKED_INGEST, config ``ranked_ingest``) from runs.jsonl and its status file
    ranked-ingest.json: off by config; broken (status missing) with no ranked ledger set, a ledger that is missing or
    cannot be read, or no Hermes DB set; stale before any sync run or while the newest sync is one it has not run
    after; else live, with the mode and what the last pass did in words. Never an id, evidence or message text, a
    count or a path; read-only."""
    from . import habit_replies, jobs, jobs_runner, ranked_ledger as rl, scorecard
    mode = jobs.ranked_mode(cfg)
    if mode == jobs.RANKED_OFF:
        return _row(RANKED_INGEST_ROW, "job", OFF, f"the ranked ingest job is {jobs.RANKED_IS_OFF}")
    env = os.environ if env is None else env
    on = f"on ({_NOOP_MODE_WORDS[mode]})"
    ledger = scorecard.ledger_path(reader.path, cfg, env)
    db = habit_replies.hermes_db_from(reader.path, cfg, env)
    mark = jobs_runner.load_ranked_mark(reader.path)
    v = jobs.ranked_ingest_verdict(mode, reader.last_run(), mark.get("row_at"), now, db_set=db is not None,
                                   ledger_set=ledger is not None)
    if v.reason in (jobs.RANKED_NO_LEDGER, jobs.APPS_NO_DB):
        return _row(RANKED_INGEST_ROW, "job", MISSING, f"broken: {on}, but {v.reason[len('skipped: '):]}")
    if rl.read(ledger) is None:
        return _row(RANKED_INGEST_ROW, "job", MISSING, f"broken: {on}, but the ranked ledger is missing or cannot be "
                                                       "read")
    if v.action == jobs.RUN:
        return _row(RANKED_INGEST_ROW, "job", STALE, "a sync ran and the ranked ingest has not run after it yet "
                                                     "(limitless-jobs --send runs it)")
    if mark.get("ran_at") is None:
        return _row(RANKED_INGEST_ROW, "job", STALE, f"{on}, but it has not run yet: {v.reason}")
    ago = age_words(max(0.0, now - mark["ran_at"]) / 3600)
    did = _RANKED_DID.get(mark.get("action"), "unknown")
    return _row(RANKED_INGEST_ROW, "job", LIVE,
                f"{_NOOP_MODE_WORDS.get(mark.get('mode'), 'unknown mode')}: ran {ago} after a sync: {did}")


RANKED_ROW = "ranked ledger"
RANKED_SKIPPED = "some lines could not be read and were skipped"


def ranked_ledger_row(cfg: Mapping, env: Optional[Mapping[str, str]] = None) -> dict:
    """The ranked ledger scorecard row ten reads (scorecard.ledger_path: $LIMITLESS_RANKED_LEDGER, else config
    ``ranked_ledger``): off when neither names a path; live when it has valid rows, with row ten's own label
    (``rows read: <label>``, plus a note when some lines were skipped); broken (status missing) when it is missing,
    cannot be read or has no valid row. Words only: never an id, evidence text, a count or a path. Kind
    ``source``: --strict does not count it. Read-only."""
    from . import ranked_ledger as rl, scorecard
    env = os.environ if env is None else env
    st = state_path(cfg, env)
    if scorecard.ledger_path(st, cfg, env) is None:
        return _row(RANKED_ROW, "source", OFF, rl.NO_LEDGER)
    label, counts = rl.summary(st, cfg, env)
    if counts is None:
        return _row(RANKED_ROW, "source", MISSING, "broken: " + label[len(scorecard.UNKNOWN_PREFIX):])
    skipped = rl.skipped_lines(rl.read(scorecard.ledger_path(st, cfg, env)) or "")
    return _row(RANKED_ROW, "source", LIVE, f"rows read: {label}" + (f"; {RANKED_SKIPPED}" if skipped else ""))


NOOP_MCP_ROW = "NOOP MCP"
NOOP_MCP_WORDS = {   # noop_mcp.state -> (status, reason); never the command, an env value or the server name
    noop_mcp.OFF: (OFF, "no noop_mcp set"),
    noop_mcp.MALFORMED: (MISSING, "noop_mcp is set but is not a command list"),
    noop_mcp.REFUSED: (MISSING, "refused: t0_tools does not cover its tools"),
    noop_mcp.BY_HAND: (MISSING, "set but the host cannot register MCP servers; add it to mcp_servers by hand"),
}


def noop_mcp_row(cfg: Mapping) -> dict:
    """The NOOP agent MCP server (config ``noop_mcp``, noop_mcp.state): off when unset; refused while t0_tools
    does not cover its tools; else set, for the person to add to the host's mcp_servers (Hermes has no plugin API
    to register one). Reads config only: the server is never started and the host's config is never read."""
    status, reason = NOOP_MCP_WORDS[noop_mcp.state(cfg)]
    return _row(NOOP_MCP_ROW, "mcp", status, reason)


VOICE_MIQ_ROW = "job voice MIQ"
_VOICE_MODE_WORDS = {"dry_run": "dry run mode (nothing written)", "write": "write mode"}


def voice_miq_row(reader: StateReader, cfg: Mapping, now: float) -> dict:
    """The voice MIQ (voice_miq.run, config ``voice_miq``) from config and its mark voice-miq.json: off by config;
    missing without the call sessions dir (config ``voice_miq_sessions``); else live, with the mode and when the
    last spoken MIQ answer was captured. Never reads a call. Words only."""
    from . import voice_miq   # voice_miq -> jobs_runner -> card
    mode = voice_miq.mode(cfg)
    if mode == voice_miq.OFF:
        return _row(VOICE_MIQ_ROW, "job", OFF, f"the voice MIQ is off (config {voice_miq.CONFIG_KEY})")
    sessions = voice_miq.sessions_dir(cfg)
    if sessions is None:
        return _row(VOICE_MIQ_ROW, "job", MISSING, f"on, but the call sessions dir is not configured (config "
                                                   f"{voice_miq.SESSIONS_KEY})")
    if not sessions.is_dir():
        return _row(VOICE_MIQ_ROW, "job", MISSING, "on, but the call sessions dir does not exist")
    at = voice_miq.load_mark(reader.path).get("captured_at")
    said = "no spoken MIQ answer captured yet" if at is None else \
        f"last spoken MIQ answer captured {age_words(max(0.0, now - at) / 3600)}"
    return _row(VOICE_MIQ_ROW, "job", LIVE, f"{_VOICE_MODE_WORDS[mode]}: {said}")


PACKET_ROW = "export context packet"


def context_packet_row(cfg: Mapping, now: float) -> dict:
    """The context packet (limitless-context-packet --write, config ``context_packet_path``): off when unset; stale
    when not written yet, not a packet this plugin wrote, or older than STALE_H by its own generated_at; else live.
    Reads that one file; words only, never a path."""
    from . import context_packet as cp   # context_packet imports doctor (age_words)
    path = cp.resolve_path(cfg.get(cp.CONFIG_KEY) if isinstance(cfg, Mapping) else None, state_path(cfg))
    if path is None:
        return _row(PACKET_ROW, "export", OFF, f"the context packet is not written (config {cp.CONFIG_KEY})")
    if not path.is_file():
        return _row(PACKET_ROW, "export", STALE, "set, but not written yet (limitless-context-packet --write "
                                                 "writes it)")
    try:
        p = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        p = None
    at = parse_ts(p.get("generated_at")) if isinstance(p, dict) and p.get("schema") == cp.SCHEMA else None
    if at is None:
        return _row(PACKET_ROW, "export", STALE, "the file there is not a context packet this plugin wrote")
    age_h = max(0.0, now - at) / 3600
    if age_h > STALE_H:
        return _row(PACKET_ROW, "export", STALE, f"written {age_words(age_h)}: older than a day")
    return _row(PACKET_ROW, "export", LIVE, f"written {age_words(age_h)}")


OW_ROW = "export Open Wearables"
_OW_MODE_WORDS = {"dry_run": "dry run mode (counts only, no file written)", "write": "write mode"}


def open_wearables_row(reader: StateReader, cfg: Mapping, now: float) -> dict:
    """The Open Wearables export (config ``open_wearables_export``) from its mark open-wearables.json, never the
    server: off by config; live when the last run read the server within STALE_H; failing (stale) when it could
    not, with its one plain reason; stale when it has not run yet or its last good run is older. Words only."""
    from . import open_wearables as ow
    mode = ow.mode(cfg)
    if mode == ow.OFF:
        return _row(OW_ROW, "export", OFF, ow.IS_OFF)
    mark = ow.load_mark(reader.path)
    if mark.get("ran_at") is None:
        return _row(OW_ROW, "export", STALE, f"on ({_OW_MODE_WORDS[mode]}), but limitless-ow-export has not run "
                                             "yet")
    age_h = max(0.0, now - mark["ran_at"]) / 3600
    ran = f"{_OW_MODE_WORDS.get(mark.get('mode'), 'unknown mode')}: ran {age_words(age_h)}"
    said = mark.get("said") or "nothing said"
    if mark.get("outcome") != ow.DONE:
        return _row(OW_ROW, "export", STALE, f"failing: {ran}: {said}")
    return _row(OW_ROW, "export", LIVE if age_h <= STALE_H else STALE, f"{ran}: {said}")


SLEEP_COVERAGE_ROW = "sleep coverage"
_SLEEP_COVERAGE_STATUS = {"met": LIVE, "not met": STALE}   # sleep_coverage's goal -> row status; unknown is missing


def sleep_coverage_row(reader: StateReader, now: float) -> dict:
    """The sleep coverage audit (tools.sleep_coverage_audit over config sleep_file and the phone proxy, config
    sleep_coverage_days and sleep_coverage_target, demo rows dropped): live when the wearable goal was met over the
    window, stale when it was not, missing when it is unknown (a missing or unreadable sleep file, no night with
    any data, fewer than a week of known nights, or too many nights with no data to tell), off when no sleep file
    is set. The reason is the audit's T1 words or why it is unknown, never a count. Kind ``source``: --strict does
    not count it. Read-only."""
    from . import sleep_coverage as sc
    a, reason = tools.sleep_coverage_audit(reader, now)
    if a is None:
        return _row(SLEEP_COVERAGE_ROW, "source", OFF if reason == sc.NO_FILE_REASON else MISSING, reason)
    if reason:
        return _row(SLEEP_COVERAGE_ROW, "source", MISSING, reason)
    return _row(SLEEP_COVERAGE_ROW, "source", _SLEEP_COVERAGE_STATUS.get(a["goal"], MISSING), a["label"]["label"])


MANIFEST = Path(__file__).resolve().parents[1] / "plugin.yaml"


def manifest_tools(path: Path = MANIFEST) -> list:
    """The names under ``provides_tools:`` in plugin.yaml (stdlib only: the simple ``  - name`` lines)."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    out, inside = [], False
    for ln in lines:
        if ln.strip() == "provides_tools:":
            inside = True
        elif inside and ln.startswith("  - "):
            out.append(ln[4:].strip())
        elif inside:
            break
    return out


def _card_view(args, now):
    """limitless_card_view's default call (kind state), rendered only: the doctor never writes a card file."""
    from . import card_view, labeler, plugin
    from .state_reader import state_dir
    return card_view.view(state_dir(), now, date.fromtimestamp(now), "state", bands=plugin._bands(),
                          labeler=labeler.from_config(), write=False)


# tools whose plugin function would write for an empty call: the doctor calls a read-only twin instead
READ_ONLY_CALLS = {"limitless_card_view": _card_view}

# a feature off by config still answers with a value: these read the value to say so
OFF_WHEN = {
    "limitless_focus_safe": (lambda e: (e.get("value") or {}).get("mode") == "off",
                             "the focus guard is off (config focus_safe)"),
    "limitless_breathing": (lambda e: (e.get("value") or {}).get("link_set") is False,
                            "no breathing link set (config wind_down_breathing_link)"),
    "limitless_palace": (lambda e: "why" in (e.get("value") or {}),
                         "no memory palace link set (config palace_link)"),
    "limitless_outages": (lambda e: (e.get("value") or {}).get("label") == "off",
                          "the input outage notice is off (config input_outage)"),
    "limitless_result_tier": (lambda e: (e.get("value") or {}).get("tool_globs") == "no globs",
                              "no health tools listed (config t0_tools)"),
    "limitless_card_view": (lambda e: bool(e.get("note")),
                            "no card dir set (config card_dir): the card is rendered only"),
}
# a null value whose reason says an input or feature is not configured: "...: set X in config", "... set"
_NOT_SET = re.compile(r": set \S|\bset$|\bset \(")
_DIGITS = re.compile(r"\d+(?:[.,:]\d+)*")
# config keys a reason names whose digit is part of the name, not a value: kept as they are by words()
CONFIG_KEYS_WITH_A_DIGIT = ("t0_tools",)
_KEYS = re.compile("(" + "|".join(re.escape(k) for k in CONFIG_KEYS_WITH_A_DIGIT) + ")")
TIER_WORDS = {
    "direct": "answers from direct evidence",
    "indirect": "answers from a proxy",
    "observed-activity": "answers from observed app activity",
    "none": "answers, with nothing measured behind it yet",
}


def words(text) -> str:
    """A reason as words only: every number becomes "a number"; a key in CONFIG_KEYS_WITH_A_DIGIT stays."""
    return "".join(p if p in CONFIG_KEYS_WITH_A_DIGIT else _DIGITS.sub("a number", p)
                   for p in _KEYS.split(str(text))).strip()


def _unknown(value) -> bool:
    if value == "unknown":
        return True
    return isinstance(value, dict) and any(v == "unknown" for v in value.values())


def classify(name: str, env, needs_args: bool = False) -> tuple:
    """(status, reason) for one tool from its envelope. The value itself is read, never returned."""
    if not isinstance(env, dict):
        return MISSING, "the tool returned no envelope"
    value = env.get("value")
    if value is None or (_unknown(value) and env.get("reason")):
        reason = str(env.get("reason") or "no reason given")
        if needs_args:
            return MISSING, words(f"needs its arguments: {reason}")
        return (OFF if _NOT_SET.search(reason) else MISSING), words(reason)
    off = OFF_WHEN.get(name)
    if off is not None and off[0](env):
        return OFF, off[1]
    tier = env.get("evidence_tier")
    if tier == "stale":
        return STALE, "answers, but its evidence is stale or of unknown age"
    return LIVE, TIER_WORDS.get(tier, "answers")


def tool_row(name: str, now: float) -> dict:
    """Call the tool's plugin function with {} as its handler does (tools.labeled, then tier_audit.audit_result)
    at ``now``, with the audit log held (tier_audit.held: nothing appended), and read its envelope."""
    from . import plugin
    entry = plugin.TOOLS.get(name)
    if entry is None:
        return _row(f"tool {name}", "tool", MISSING, "listed in plugin.yaml but not registered")
    schema, fn = entry[0], READ_ONLY_CALLS.get(name, entry[1])
    needs_args = bool(((schema or {}).get("parameters") or {}).get("required"))
    try:
        with tier_audit.held():
            env = tier_audit.audit_result(f"tool:{name}", tools.labeled(fn({}, now)),
                                          card.raw_in_prompt(os.environ), now=now)
    except Exception as exc:  # noqa: BLE001 - a failing tool is a row, never a traceback (its message stays out)
        return _row(f"tool {name}", "tool", MISSING, f"the tool failed with {type(exc).__name__}")
    status, reason = classify(name, env, needs_args)
    return _row(f"tool {name}", "tool", status, reason)


DESKTOP_AW_ROW = "desktop AW"


def desktop_aw_row(cfg: Mapping, now: float, fetch=None) -> dict:
    """The desktop's ActivityWatch (aw_desktop: config ``desktop_aw_url``, else ``desktop_aw_export``), read for
    the STALE_H up to ``now``: off when unset (nothing is called); live when it shows app activity in that time;
    stale when it answers with none; unreachable (status missing) when it cannot be read, with the reason.
    Words only: never the address, a path, an app name or a title. Kind ``source``: --strict does not count it."""
    from . import aw_desktop
    got = aw_desktop.from_settings(cfg, state_path(cfg), now - STALE_H * 3600, now, fetch=fetch)
    if got["state"] == aw_desktop.OFF:
        return _row(DESKTOP_AW_ROW, "source", OFF, aw_desktop.OFF_WHY)
    if got["events"] is None:
        return _row(DESKTOP_AW_ROW, "source", MISSING, f"unreachable: {got['why']}")
    if got["newest"] is None:
        return _row(DESKTOP_AW_ROW, "source", STALE, "it answers, with no active app time in the last day")
    return _row(DESKTOP_AW_ROW, "source", LIVE,
                f"active app time {age_words(max(0.0, now - got['newest']) / 3600)}")


FEED_REFLEX_ROW = "feed reflex"
FEED_REFLEX_LIVE = "reads unlocks and phone app rows from the last week"


def feed_reflex_row(cfg: Mapping, now: float) -> dict:
    """The feed reflex (feed_reflex.from_settings over the last LOOKBACK_DAYS days up to ``now``): off when no
    feed apps are set; unknown (status missing) with the plain reason when it cannot say (no DB, no unlock, too
    few unlocks); live when it can. Words only: never the words it would say, a count, an app name or a path.
    Kind ``source``: --strict does not count it. Read-only."""
    from . import feed_reflex
    got = feed_reflex.from_settings(cfg, state_path(cfg), now - feed_reflex.LOOKBACK_DAYS * 86400.0, now)
    if got["label"] in feed_reflex.WORDS:
        return _row(FEED_REFLEX_ROW, "source", LIVE, FEED_REFLEX_LIVE)
    why = got["label"][len(feed_reflex.UNKNOWN_PREFIX):]
    if why == feed_reflex.NO_FEEDS:
        return _row(FEED_REFLEX_ROW, "source", OFF, why)
    return _row(FEED_REFLEX_ROW, "source", MISSING, got["label"])


APPS_ROW = "apps lists"
APPS_OFF = "no work apps or feed apps set (config flow_work_apps, feed_apps, or a reply)"
_APPS_FROM = {"env": "set from the environment", "config": "set from config", "reply": "set from a reply"}


def apps_row(cfg: Mapping, env: Optional[Mapping[str, str]] = None) -> dict:
    """Where the work-app and feed-app lists come from (apps_reply.lists_for: env, then config, then apps.json
    set from a reply): off when neither is set; live with each list's source in words. Never an app name or a
    count. Kind ``source``: --strict does not count it. Read-only."""
    from . import apps_reply
    got = apps_reply.lists_for(cfg, state_path(cfg, env), env)
    if not any(src for _, src in got.values()):
        return _row(APPS_ROW, "source", OFF, APPS_OFF)
    words = [f"{label} {_APPS_FROM.get(got[key][1], 'not set')}"
             for key, label in ((apps_reply.WORK, "work apps"), (apps_reply.FEED, "feed apps"))]
    return _row(APPS_ROW, "source", LIVE, "; ".join(words))


APPS_ASK_ROW = "apps ask"
APPS_ASK_WORDS = {   # apps_ask.state -> (status, reason); never an app name, a count or a date
    "off": (OFF, "the wake brief never asks for the app lists (config apps_ask)"),
    "waiting": (LIVE, "waiting: the next wake brief proposes the app lists once app time names a work or feed app"),
    "told recently": (LIVE, "told recently: asked in a delivered brief this week; asked again after a week if "
                            "both lists stay unset"),
    "not needed": (LIVE, "not needed: an app list is set"),
}


def apps_ask_row(cfg: Mapping, now: float, env: Optional[Mapping[str, str]] = None) -> dict:
    """The app-lists ask in the wake brief (apps_ask.state): off, waiting, told recently or not needed (a list is
    set), words only. Reads config and the small apps.json / apps-ask.json files, never app time. Kind
    ``source``: --strict does not count it. Read-only."""
    from . import apps_ask
    status, reason = APPS_ASK_WORDS[apps_ask.state(cfg, state_path(cfg, env), now, env)]
    return _row(APPS_ASK_ROW, "source", status, reason)


def report(cfg: Mapping, now: float) -> list:
    """Every row, in order: state dir, inputs, the last sync run, the uptime audit (uptime_row), north-star row
    two (delivery_row), kevin-push's sender profile (push_sender_row), phone Sleep mode as kevin-push's hold
    reads it (sleep_mode_row), the local labeler (local_labeler_row), each tool in plugin.yaml, the context
    packet (context_packet_row), the Open Wearables export (open_wearables_row), the NOOP export job
    (noop_export_row). The NOOP MCP server's row (noop_mcp_row) comes right after the tools, then the
    desktop's ActivityWatch (desktop_aw_row), then the feed reflex (feed_reflex_row), then where the app lists
    come from (apps_row), then the app-lists ask (apps_ask_row), then the apps ingest job's (apps_ingest_row),
    then the ranked ledger's (ranked_ledger_row), then the ranked ingest job's (ranked_ingest_row), then the voice
    MIQ's row (voice_miq_row) just before the context
    packet's, and the sleep coverage audit
    (sleep_coverage_row) right after the context packet's, just before the two wearable export rows that write
    the sleep file.

    cfg is the host config (state_reader.config()); the tools read the same config through the environment,
    as they do inside Hermes. The tools label with the rules only (labeler.rules_only): a configured local
    model is never run by the doctor."""
    from . import labeler
    path = state_path(cfg)
    reader = StateReader(path)
    rows = [state_row(path)] + input_rows(tools.status(reader, now, cfg)) + [run_row(reader, now)]
    rows += [uptime_row(reader, now), delivery_row(reader, cfg, now), push_sender_row(cfg),
             sleep_mode_row(cfg, now), local_labeler_row(cfg)]
    with labeler.rules_only():
        rows += [tool_row(name, now) for name in manifest_tools()]
    rows += [noop_mcp_row(cfg)]
    rows += [desktop_aw_row(cfg, now), feed_reflex_row(cfg, now), apps_row(cfg), apps_ask_row(cfg, now),
             apps_ingest_row(reader, cfg, now), ranked_ledger_row(cfg), ranked_ingest_row(reader, cfg, now),
             voice_miq_row(reader, cfg, now)]
    rows += [context_packet_row(cfg, now), sleep_coverage_row(reader, now), open_wearables_row(reader, cfg, now),
             noop_export_row(reader, cfg, now)]
    return [dict(r, reason=words(r["reason"])) for r in rows]


def text(rows: list) -> str:
    """One line per row: ``name: status: reason``."""
    return "\n".join(f"{r['name']}: {r['status']}: {r['reason']}" for r in rows)


def as_json(rows: list) -> str:
    """The full rows as a JSON list, one row per line."""
    return "[\n" + ",\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n]"


def strict_failed(rows: list) -> bool:
    """--strict: true when the state dir, an input or the last sync run is not live (tool and job rows never
    count)."""
    return any(r["kind"] in STRICT_KINDS and r["status"] != LIVE for r in rows)


def main(argv=None, now: Optional[float] = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="limitless-doctor", description="Read-only: which inputs are live and which "
                                "tools would answer unknown, and why. Never writes, sends or starts a job.")
    p.add_argument("--json", action="store_true", help="print the full rows as JSON")
    p.add_argument("--strict", action="store_true",
                   help="exit 1 when the state dir, an input or the last sync run is not live")
    args = p.parse_args(argv)
    rows = report(config(), time.time() if now is None else now)
    print(as_json(rows) if args.json else text(rows))
    return 1 if args.strict and strict_failed(rows) else 0
