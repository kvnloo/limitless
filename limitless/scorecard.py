"""North-star scorecard: the hand-kept Markdown table -> rows -> a short block for the weekly review.

The table's header is ``| # | Criterion | Status | Evidence (latest) | Weeks green |``. Status is
red, amber or green (anything else reads "unknown"); Weeks green is a whole number. The evidence column
is never read into a row: it may hold private detail and has no place in a summary.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, tzinfo
from pathlib import Path
from typing import List, Mapping, Optional

from .send_gate import scrub
from .state_reader import config

ENV_KEY, CONFIG_KEY = "LIMITLESS_SCORECARD", "scorecard"

HEADER = ("#", "criterion", "status", "evidence (latest)", "weeks green")
STATUSES = ("red", "amber", "green")
_SEPARATOR = re.compile(r"^:?-+:?$")
_WHOLE = re.compile(r"^\d+$")


def _cells(line: str) -> Optional[List[str]]:
    """A table line's cells, outer pipes optional; None when the line is not a table line."""
    s = line.strip()
    if "|" not in s:
        return None
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _row(cells: List[str]) -> Optional[dict]:
    if len(cells) != len(HEADER):
        return None
    n, criterion, status, _evidence, weeks = cells
    if not _WHOLE.match(n) or not _WHOLE.match(weeks) or not criterion:
        return None
    status = status.lower()
    return {"n": int(n), "criterion": criterion, "status": status if status in STATUSES else "unknown",
            "weeks_green": int(weeks)}


def parse(md_text: str) -> List[dict]:
    """Rows of the first scorecard table: [{n, criterion, status, weeks_green}]. Malformed rows are skipped;
    no table gives []. The table ends at the first line that is not a table line."""
    rows: List[dict] = []
    inside = False
    for line in (md_text or "").splitlines():
        cells = _cells(line)
        if not inside:
            inside = cells is not None and tuple(c.lower() for c in cells) == HEADER
            continue
        if cells is None:
            break
        if all(_SEPARATOR.match(c) for c in cells):
            continue
        row = _row(cells)
        if row is not None:
            rows.append(row)
    return rows


WEEKS_TO_STOP = 4
MAX_LINES = 5
_RANK = {"red": 0, "amber": 1, "unknown": 2}
_DIGITS = re.compile(r"\d+")


def _drop_parentheticals(text: str) -> str:
    """Text with every ``( ... )`` removed, nested ones included. An unclosed ``(`` drops the rest of the
    text and a stray ``)`` is dropped: thresholds sit in parentheses and must not leak half-open."""
    out, depth = [], 0
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    return "".join(out)


def _tidy(text: str) -> str:
    return re.sub(r"\s+", " ", _DIGITS.sub("#", text)).strip(" :")


def _name(criterion: str) -> str:
    """Plain words only: no card ids, no parenthetical thresholds, and every digit left masked (counts
    and weeks are the only numbers shown). A name that is all parenthetical keeps its masked full text."""
    text = scrub(criterion)
    return _tidy(_drop_parentheticals(text)) or _tidy(text) or "unnamed criterion"


def summary(rows: List[dict]) -> List[str]:
    """At most 5 plain-word lines: the counts, the stop-rule state, then up to three criteria furthest
    from green (red, then amber, then unknown; lowest number first). Reports counts only: it never says
    the north star is met. No rows, no lines."""
    if not rows:
        return []
    count = {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES}
    lines = [f"{count['green']} green, {count['amber']} amber, {count['red']} red of {len(rows)}"]
    if count["green"] == len(rows):
        weeks = min(WEEKS_TO_STOP, max(0, min(r["weeks_green"] for r in rows)))
        lines.append(f"all green for {weeks} of {WEEKS_TO_STOP} weeks")
    else:
        lines.append("not all green yet")
    behind = sorted((r for r in rows if r["status"] != "green"), key=lambda r: (_RANK[r["status"]], r["n"]))
    lines += [f"{_name(r['criterion'])}: {r['status']}" for r in behind[:MAX_LINES - len(lines)]]
    return lines


WEEKLY_TITLE = "North star (self-reported)"
_CLAIM = re.compile(r"(?i)\b(met|achieved)\b")


def _bullets(lines: List[str], strike: bool) -> List[str]:
    out = []
    for ln in lines or ():
        ln = re.sub(r"\s+", " ", _CLAIM.sub("", ln or "") if strike else (ln or ""))
        ln = re.sub(r" ([:,.])", r"\1", ln).strip()
        if ln and ln != ":":
            out.append(f"- {ln}")
    return out


def weekly_block(lines: List[str], measured_lines: Optional[List[str]] = None) -> str:
    """The weekly review's titled block: the title, then up to five lines as ``- `` bullets (six lines in
    all). Self-reported counts are not proof, so the words "met" and "achieved" are struck from every
    summary line. ``measured_lines`` (measured_lines(): what the audits measured, and any disagreement note)
    follow the summary and keep their words; they stay inside the five lines by replacing the lowest-priority
    summary lines (the last ones). Blank lines are skipped; no lines left gives ""."""
    extra = _bullets(measured_lines or [], strike=False)[:MAX_LINES]
    bullets = _bullets(lines, strike=True)[:MAX_LINES - len(extra)] + extra
    return "\n".join([WEEKLY_TITLE] + bullets) if bullets else ""


def path(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> Optional[Path]:
    """The scorecard file: $LIMITLESS_SCORECARD, else ``scorecard`` in config.json; None if neither."""
    env = os.environ if env is None else env
    if env.get(ENV_KEY):
        return Path(env[ENV_KEY])
    p = config(env, home).get(CONFIG_KEY)
    return Path(p) if isinstance(p, str) and p else None


# --- measured rows: north-star rows one and two as the audits measured them -----------------------------------

UPTIME_ROW, DELIVERY_ROW = 1, 2
UPTIME_WORDS, DELIVERY_WORDS = "loop uptime", "delivery"
UNKNOWN_PREFIX = "unknown: "


def _uptime_measured(state_dir, cfg: Mapping, now: float, tz, env, home) -> tuple:
    """(label, goal, audit) of row one: tools.uptime_audit (the same read as limitless_uptime and the doctor)."""
    from . import tools   # lazily: tools reads this module
    from .state_reader import StateReader
    a = tools.uptime_audit(StateReader(Path(state_dir)), now, env, home, tz, cfg=cfg)
    why = tools.uptime_reason(a)
    if why:
        return UNKNOWN_PREFIX + why, "unknown", a
    return a["label"]["label"], a["goal"], a


def _delivery_measured(state_dir, cfg: Mapping, now: float, tz, env, home) -> tuple:
    """(label, goal, audit) of row two: delivery_audit over kevin-push's log (config push_log), like
    limitless_delivery and the week review's Pushes line."""
    from . import delivery_audit as da, jobs_runner   # lazily: jobs_runner is heavy and reads tools
    path = da.log_path(cfg, state_dir)
    if path is None:
        return da.NO_LOG, da.GOAL_UNKNOWN, None
    got = da.read_log(path)
    if got is None:
        return UNKNOWN_PREFIX + da.UNREADABLE_REASON, da.GOAL_UNKNOWN, None
    rows, skipped = got
    a = da.audit(rows, wake_days=jobs_runner.delivery_wake_days(state_dir, now, env, home, tz),
                 today=datetime.fromtimestamp(now, tz).date(), tz=tz, cap=da.push_cap(cfg), skipped=skipped)
    if not a["known_days"]:
        return da.UNKNOWN_ROWS, da.GOAL_UNKNOWN, a
    return a["label"]["label"], da.goal(a), a


def measured_audits(state_dir, cfg: Optional[Mapping], now: float, tz: Optional[tzinfo] = None, *,
                    env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> List[tuple]:
    """``[(row, audit)]`` for rows one and two: ``row`` as measured() gives it, ``audit`` the audit's own dict
    (its T0 counts) or None when there was no log to audit."""
    cfg = cfg if isinstance(cfg, Mapping) else {}
    out = []
    for n, words, read in ((UPTIME_ROW, UPTIME_WORDS, _uptime_measured),
                           (DELIVERY_ROW, DELIVERY_WORDS, _delivery_measured)):
        try:
            label, goal, audit = read(state_dir, cfg, now, tz, env, home)
        except Exception:  # noqa: BLE001 - a broken log is unknown, never a traceback in the review
            label, goal, audit = UNKNOWN_PREFIX + "the log could not be read", "unknown", None
        out.append(({"n": n, "criterion_words": words, "label": label, "goal": goal}, audit))
    return out


def measured(state_dir, cfg: Optional[Mapping], now: float, tz: Optional[tzinfo] = None, *,
             env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> List[dict]:
    """North-star rows one and two as code measured them: ``[{n, criterion_words, label, goal}]``.

    Row one is the uptime audit of the state dir's runs.jsonl, row two the delivery audit of kevin-push's log
    (config ``push_log``). ``label`` is the audit's own T1 words (no digit) or ``unknown: <why>``; ``goal`` is
    met, not met or unknown. A missing or unreadable log is unknown, never an error and never met. Read-only:
    nothing is written or sent, and no hand status is changed.
    """
    return [row for row, _audit in measured_audits(state_dir, cfg, now, tz, env=env, home=home)]


MEASURED_LINE = "Measured: {}: {}"
DISAGREE_LINE = "Row {} says green but the measurement says not met."


def disagreement(rows: List[dict], m: Mapping) -> Optional[str]:
    """"Row <name> says green but the measurement says not met." when the hand-kept row numbered like ``m`` is
    green and ``m``'s goal is not met; else None. It only words the gap: the status is never changed."""
    row = next((r for r in rows or () if isinstance(r, dict) and r.get("n") == m.get("n")), None)
    if row is None or row.get("status") != "green" or m.get("goal") != "not met":
        return None
    return DISAGREE_LINE.format(_name(row["criterion"]))


def measured_lines(rows: List[dict], measured_rows: List[dict]) -> List[str]:
    """The weekly block's measured lines, digit-free: "Measured: loop uptime: <label>" and "Measured: delivery:
    <label>" (at most one each, in that order), each followed by "Row <name> says green but the measurement says
    not met." when the hand-kept row with that number is green and the audit's goal is not met. Only words:
    no status is changed here, and code never marks a row green."""
    out, seen = [], set()
    for m in measured_rows or ():
        n = m.get("n") if isinstance(m, dict) else None
        if n not in (UPTIME_ROW, DELIVERY_ROW) or n in seen:
            continue
        seen.add(n)
        out.append(_DIGITS.sub("#", MEASURED_LINE.format(m.get("criterion_words"), m.get("label"))))
        note = disagreement(rows, m)
        if note:
            out.append(note)
    return out
