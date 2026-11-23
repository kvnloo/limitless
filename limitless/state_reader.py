"""Read-only access to the private Limitless state dir. Nothing here writes, creates or locks a file.

Location: $LIMITLESS_STATE, else "state" in $LIMITLESS_CONFIG (default ~/.config/limitless/config.json),
else ~/.local/state/limitless. Shapes read (see tests/fixtures/state for synthetic examples):
  inputs.json          {"at": iso, "ageHours": {name: hours | "down" | null}}
  runs.jsonl           one row per pipeline run; only the last valid row is used
  digests.jsonl        {"date", "at", "metrics": {name: {"value", "modality"}}}
  asks-latest.json     {"at": epoch, "count", "lines"}
  habit.json           {"week_of": date, "habit", "start", "at", "checkins": {date: Done|No|Skipped}}
  habit1.jsonl         one row per day from the sync: {"day", "wake", "feedMinFirstHour", "firstApp",
                       "firstCat", "minToFirstFeed", "met": bool}
  sleepmode.jsonl      {"at", "on"} phone Sleep-mode changes; sleepmode-poll.json {"at", "ok"}
  unlocks.jsonl        {"at"} phone unlocks
  events.jsonl         {"event", "at"} other job events (wind_down, habit_cue, focus_end, ...)
  jobs-sent.jsonl      {"t", "k", "job"} job messages really delivered (written by jobs_runner only)
  captures.jsonl       {"at", "text", "source"} captures (written by capture.py only; source "bedtime"
                       for a message saved by bedtime capture)
  screen-events.jsonl  {"ts": epoch_ms, "type", "pkg"} Android screen events (wake_proxy.events_from_screen)
  ActivityWatch DB     optional SQLite copy at $LIMITLESS_AW_DB, else config "aw_db" (relative to the
                       state dir); read only through aw_reader.person_rows (aw_db_path)
  passive habit file   optional JSONL from an older loop, config "passive_habit_file" (relative to the state
                       dir; none by default), the habit1.jsonl row shape; read only through
                       passive_habit_days: measured evidence (a proxy), never a check-in
  owner session DBs    optional Hermes session stores, one per machine the person chats from:
                       $LIMITLESS_OWNER_DBS (os.pathsep-separated), else config "owner_dbs" (a list;
                       relative paths in the state dir); read only through owner_messages (owner_db_paths)
  owner beacons        optional {"at": iso, "v": 1} files from bin/limitless-owner-beacon on other machines:
                       $LIMITLESS_OWNER_BEACONS, else config "owner_beacons"; same path rules
                       (owner_beacon_paths); read only through owner_messages
  body file            optional JSONL from a body-composition app, config "body_file" (relative to the state
                       dir; none by default), one row per measurement visit: {"day", "bf_pct", "method",
                       "calibrated": bool}; read only through body_rows (tier T0: raw numbers stay in code)
  work queue dir       optional overnight lane queue, config "work_queue_dir" (relative to the state dir; none
                       by default): subdirs queue/, running/, done/, failed/ with one <name>.md per item; read
                       only through work_items, which reads file names and mtimes, never the content
Missing or malformed files read as None / []: callers report "no data", never a guess.
"""
from __future__ import annotations

import json
import math
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Mapping, Optional

TAIL_BYTES = 64 * 1024
OWNER_DBS_ENV = "LIMITLESS_OWNER_DBS"
OWNER_DBS_CONFIG = "owner_dbs"
OWNER_BEACONS_ENV = "LIMITLESS_OWNER_BEACONS"
OWNER_BEACONS_CONFIG = "owner_beacons"
PASSIVE_HABIT_CONFIG = "passive_habit_file"
BODY_CONFIG = "body_file"
WORK_QUEUE_CONFIG = "work_queue_dir"
WORK_STATUS = {"queue": "queued", "running": "running", "done": "done", "failed": "failed"}  # subdir -> status
_ID_NAME = re.compile(r"t_[0-9a-f]+")   # a card id as a file name means nothing to the person: skipped
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def _valid_day(v) -> bool:
    if not isinstance(v, str) or not _DAY.fullmatch(v):
        return False
    try:
        date.fromisoformat(v)
    except ValueError:
        return False
    return True


def config(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> dict:
    """Host config: $LIMITLESS_CONFIG, else ~/.config/limitless/config.json; {} when absent or not an object."""
    env = os.environ if env is None else env
    home = Path.home() if home is None else home
    path = Path(env.get("LIMITLESS_CONFIG") or home / ".config/limitless/config.json")
    try:
        cfg = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return cfg if isinstance(cfg, dict) else {}


def state_dir(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> Path:
    env = os.environ if env is None else env
    home = Path.home() if home is None else home
    if env.get("LIMITLESS_STATE"):
        return Path(env["LIMITLESS_STATE"])
    st = config(env, home).get("state")
    return Path(st) if isinstance(st, str) and st else home / ".local/state/limitless"


def parse_ts(v) -> Optional[float]:
    """Epoch seconds from an ISO-8601 string (Z or offset; naive = UTC) or an epoch number."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _rows(text: str) -> list:
    out = []
    for ln in text.splitlines():
        try:
            row = json.loads(ln)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def normalize_digest(row: Optional[dict]) -> Optional[dict]:
    """The live sync writes {builtAt, phoneProxy: {gapHours}, ...}; map it to {at, metrics}.

    Rows already in the {at, metrics} shape pass through unchanged. Only values that exist are
    mapped (sleep from the unlock-gap proxy); nothing is filled in.
    """
    if not isinstance(row, dict) or "metrics" in row:
        return row
    out = dict(row)
    out.setdefault("at", row.get("builtAt"))
    metrics = {}
    gap = (row.get("phoneProxy") or {}).get("gapHours") if isinstance(row.get("phoneProxy"), dict) else None
    if isinstance(gap, (int, float)) and not isinstance(gap, bool):
        metrics["sleep_h"] = {"value": gap, "modality": "proxy"}
    out["metrics"] = metrics
    return out


class StateReader:
    def __init__(self, path: Path):
        self.path = Path(path)

    def exists(self) -> bool:
        return self.path.is_dir()

    def mtime(self, name: str) -> Optional[int]:
        try:
            return (self.path / name).stat().st_mtime_ns
        except OSError:
            return None

    def _json(self, name: str) -> Optional[dict]:
        try:
            v = json.loads((self.path / name).read_text())
        except (OSError, ValueError):
            return None
        return v if isinstance(v, dict) else None

    def _jsonl(self, name: str) -> list:
        try:
            return _rows((self.path / name).read_text(errors="replace"))
        except OSError:
            return []

    def _last_row(self, name: str) -> Optional[dict]:
        try:
            with open(self.path / name, "rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - TAIL_BYTES))
                tail = f.read().decode(errors="replace")
        except OSError:
            return None
        rows = _rows(tail)
        return rows[-1] if rows else None

    def inputs(self) -> Optional[dict]:
        return self._json("inputs.json")

    def last_run(self) -> Optional[dict]:
        return self._last_row("runs.jsonl")

    def digests(self) -> list:
        return self._jsonl("digests.jsonl")

    def latest_digest(self) -> Optional[dict]:
        return normalize_digest(self._last_row("digests.jsonl"))

    def asks(self) -> Optional[dict]:
        return self._json("asks-latest.json")

    def habit(self) -> Optional[dict]:
        return self._json("habit.json")

    def habit1(self) -> list:
        return self._jsonl("habit1.jsonl")

    def habit_days(self) -> dict:
        """{day: "met" | "missed"} from habit1.jsonl. A row without a real date and a bool met is left out."""
        out = {}
        for r in self.habit1():
            day, met = r.get("day"), r.get("met")
            if not isinstance(met, bool) or not isinstance(day, str):
                continue
            try:
                date.fromisoformat(day)
            except ValueError:
                continue
            out[day] = "met" if met else "missed"
        return out

    def sleepmode(self) -> list:
        return self._jsonl("sleepmode.jsonl")

    def sleepmode_poll(self) -> Optional[dict]:
        return self._json("sleepmode-poll.json")

    def aw_db_path(self, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> Optional[Path]:
        """The ActivityWatch DB copy: $LIMITLESS_AW_DB, else config ``aw_db``; a relative path is in the
        state dir. None when neither is set (there is no default file name)."""
        env = os.environ if env is None else env
        v = env.get("LIMITLESS_AW_DB") or config(env, home).get("aw_db")
        if not isinstance(v, str) or not v:
            return None
        p = Path(v).expanduser()
        return p if p.is_absolute() else self.path / p

    def owner_db_paths(self, env: Optional[Mapping[str, str]] = None,
                       home: Optional[Path] = None) -> Optional[list]:
        """The person's Hermes session stores: $LIMITLESS_OWNER_DBS (os.pathsep-separated), else config
        ``owner_dbs`` (a list of strings); a relative path is in the state dir, empty entries are dropped.
        None when neither names a path (the input is missing, not zero)."""
        return self._owner_paths(OWNER_DBS_ENV, OWNER_DBS_CONFIG, env, home)

    def owner_beacon_paths(self, env: Optional[Mapping[str, str]] = None,
                           home: Optional[Path] = None) -> Optional[list]:
        """Owner beacons written on other machines (bin/limitless-owner-beacon): $LIMITLESS_OWNER_BEACONS
        (os.pathsep-separated), else config ``owner_beacons``; same rules as owner_db_paths."""
        return self._owner_paths(OWNER_BEACONS_ENV, OWNER_BEACONS_CONFIG, env, home)

    def _owner_paths(self, env_key: str, config_key: str, env: Optional[Mapping[str, str]],
                     home: Optional[Path]) -> Optional[list]:
        env = os.environ if env is None else env
        if env.get(env_key):
            items = env[env_key].split(os.pathsep)
        else:
            v = config(env, home).get(config_key)
            items = v if isinstance(v, list) else []
        out = []
        for v in items:
            if isinstance(v, str) and v.strip():
                p = Path(v).expanduser()
                out.append(p if p.is_absolute() else self.path / p)
        return out or None

    def passive_habit_file(self, env: Optional[Mapping[str, str]] = None,
                           home: Optional[Path] = None) -> Optional[Path]:
        """The older loop's per-day habit file: config ``passive_habit_file``; a relative path is in the
        state dir. None when it is not set (there is no default file name)."""
        v = config(env, home).get(PASSIVE_HABIT_CONFIG)
        if not isinstance(v, str) or not v.strip():
            return None
        p = Path(v).expanduser()
        return p if p.is_absolute() else self.path / p

    def passive_habit_days(self, env: Optional[Mapping[str, str]] = None,
                           home: Optional[Path] = None) -> list:
        """The passive file's rows with a real ``YYYY-MM-DD`` day and a bool ``met``, one per day (the last
        row for a day wins), oldest first. [] when no file is configured, it is missing or no row is valid."""
        p = self.passive_habit_file(env, home)
        if p is None:
            return []
        try:
            rows = _rows(p.read_text(errors="replace"))
        except OSError:
            return []
        by_day = {r["day"]: r for r in rows if _valid_day(r.get("day")) and isinstance(r.get("met"), bool)}
        return [by_day[d] for d in sorted(by_day)]

    def body_file(self, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> Optional[Path]:
        """The body-composition file: config ``body_file``; a relative path is in the state dir. None when it
        is not set (there is no default file name)."""
        v = config(env, home).get(BODY_CONFIG)
        if not isinstance(v, str) or not v.strip():
            return None
        p = Path(v).expanduser()
        return p if p.is_absolute() else self.path / p

    def body_rows(self, env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None,
                  today: Optional[date] = None) -> list:
        """The body file's valid rows ``{"day", "bf_pct": float, "method": str, "calibrated": bool}``, oldest
        first (rows of one day keep their file order). A row without a real day, a finite ``bf_pct`` in
        (0, 100), a non-empty ``method`` and a bool ``calibrated``, or with a day after ``today`` (default:
        the local date), is skipped. [] when no file is configured, it is missing or unreadable; never raises."""
        try:
            today = date.today() if today is None else today
            if not isinstance(today, date):
                return []
            p = self.body_file(env, home)
            if p is None:
                return []
            rows = _rows(p.read_text(errors="replace"))
        except Exception:  # noqa: BLE001 - unreadable body data is no rows, never a traceback
            return []
        out = []
        for r in rows:
            day, bf, method, cal = r.get("day"), r.get("bf_pct"), r.get("method"), r.get("calibrated")
            if not _valid_day(day) or date.fromisoformat(day) > today:
                continue
            if isinstance(bf, bool) or not isinstance(bf, (int, float)) or not math.isfinite(bf) \
                    or not 0 < bf < 100:
                continue
            if not isinstance(method, str) or not method.strip() or not isinstance(cal, bool):
                continue
            out.append({"day": day, "bf_pct": float(bf), "method": method, "calibrated": cal})
        return sorted(out, key=lambda r: r["day"])

    def work_queue_dir(self, env: Optional[Mapping[str, str]] = None,
                       home: Optional[Path] = None) -> Optional[Path]:
        """The overnight work queue: config ``work_queue_dir``; a relative path is in the state dir. None
        when it is not set (there is no default dir)."""
        v = config(env, home).get(WORK_QUEUE_CONFIG)
        if not isinstance(v, str) or not v.strip():
            return None
        p = Path(v).expanduser()
        return p if p.is_absolute() else self.path / p

    def work_items(self, since=None, env: Optional[Mapping[str, str]] = None,
                   home: Optional[Path] = None) -> list:
        """``[{"name", "status": queued | running | done | failed, "mtime": epoch s}]`` from the work queue's
        status subdirs, sorted by status then name. Only file names and mtimes are read, never the content.
        Not a ``.md`` file, a hidden file or a name that is a card id (``t_`` + hex) is skipped. With a
        numeric ``since``, done and failed items at or before it are dropped (queued and running are the
        current state and stay). [] when no dir is configured, it is missing or unreadable; never raises."""
        try:
            root = self.work_queue_dir(env, home)
            if root is None or not root.is_dir():
                return []
            cut = None
            if isinstance(since, (int, float)) and not isinstance(since, bool) and math.isfinite(since):
                cut = float(since)
            out = []
            for sub, status in WORK_STATUS.items():
                d = root / sub
                if not d.is_dir():
                    continue
                for f in sorted(d.iterdir()):
                    name = f.stem
                    if f.suffix != ".md" or name.startswith(".") or not name or _ID_NAME.fullmatch(name):
                        continue
                    try:
                        if not f.is_file():
                            continue
                        mtime = f.stat().st_mtime
                    except OSError:
                        continue
                    if cut is not None and status in ("done", "failed") and mtime <= cut:
                        continue
                    out.append({"name": name, "status": status, "mtime": mtime})
            return out
        except Exception:  # noqa: BLE001 - an unreadable queue is no items, never a traceback
            return []

    def screen_events(self) -> list:
        return self._jsonl("screen-events.jsonl")

    def last_unlock(self) -> Optional[dict]:
        return self._last_row("unlocks.jsonl")

    def events(self) -> list:
        return self._jsonl("events.jsonl")

    def jobs_sent(self) -> list:
        return self._jsonl("jobs-sent.jsonl")

    def captures(self) -> list:
        return self._jsonl("captures.jsonl")
