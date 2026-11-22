"""Read-only access to the private Limitless state dir. Nothing here writes, creates or locks a file.

Location: $LIMITLESS_STATE, else "state" in $LIMITLESS_CONFIG (default ~/.config/limitless/config.json),
else ~/.local/state/limitless. Shapes read (see tests/fixtures/state for synthetic examples):
  inputs.json          {"at": iso, "ageHours": {name: hours | "down" | null}}
  runs.jsonl           one row per pipeline run; only the last valid row is used
  digests.jsonl        {"date", "at", "metrics": {name: {"value", "modality"}}}
  asks-latest.json     {"at": epoch, "count", "lines"}
  habit.json           {"week_of": date, "habit", "start", "checkins": {date: Done|No|Skipped}}
  habit1.jsonl         one row per day from the sync: {"day", "wake", "feedMinFirstHour", "firstApp",
                       "firstCat", "minToFirstFeed", "met": bool}
  sleepmode.jsonl      {"at", "on"} phone Sleep-mode changes; sleepmode-poll.json {"at", "ok"}
  unlocks.jsonl        {"at"} phone unlocks
  screen-events.jsonl  {"ts": epoch_ms, "type", "pkg"} Android screen events (wake_proxy.events_from_screen)
Missing or malformed files read as None / []: callers report "no data", never a guess.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Mapping, Optional

TAIL_BYTES = 64 * 1024


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

    def screen_events(self) -> list:
        return self._jsonl("screen-events.jsonl")

    def last_unlock(self) -> Optional[dict]:
        return self._last_row("unlocks.jsonl")
