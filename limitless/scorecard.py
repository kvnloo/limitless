"""North-star scorecard: the hand-kept Markdown table -> rows -> a short block for the weekly review.

The table's header is ``| # | Criterion | Status | Evidence (latest) | Weeks green |``. Status is
red, amber or green (anything else reads "unknown"); Weeks green is a whole number. The evidence column
is never read into a row: it may hold private detail and has no place in a summary.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta, tzinfo
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
    """The weekly review's titled block: the title, then at most five lines as ``- `` bullets (six lines in
    all). Self-reported counts are not proof, so the words "met" and "achieved" are struck from every
    summary line. The first bullet is always the summary's self-reported counts line. ``measured_lines``
    (measured_lines(): what the audits measured, and any disagreement note) keep their words and follow the
    summary; they stay inside the five lines by replacing the lower-priority summary lines (the last ones), never
    the counts line. Measured lines past the room left fold into "More measured rows in limitless_scorecard."
    Blank lines are skipped; no lines left gives ""."""
    summary = _bullets(lines, strike=True)[:MAX_LINES]
    head = summary[:1]
    room = MAX_LINES - len(head)
    extra = _bullets(measured_lines or [], strike=False)
    if len(extra) > room:
        extra = extra[:room - 1] + [f"- {MORE_LINE}"]
    bullets = head + summary[1:][:room - len(extra)] + extra
    return "\n".join([WEEKLY_TITLE] + bullets) if bullets else ""


def path(env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> Optional[Path]:
    """The scorecard file: $LIMITLESS_SCORECARD, else ``scorecard`` in config.json; None if neither."""
    env = os.environ if env is None else env
    if env.get(ENV_KEY):
        return Path(env[ENV_KEY])
    p = config(env, home).get(CONFIG_KEY)
    return Path(p) if isinstance(p, str) and p else None


# --- measured rows: north-star rows one, two, three, four and seven as code measured them ---------------------

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


HABIT_ROW, EVIDENCE_ROW, PRIVACY_ROW = 3, 4, 7
HABIT_WORDS, EVIDENCE_WORDS, PRIVACY_WORDS = "habit loop", "evidence loop", "privacy"

CYCLES = 4                    # row three: the last four habit weeks each closed with a Keep or Drop
HABIT_MET = "the last four habit weeks each closed with a Keep or Drop decision"
HABIT_OPEN = "a finished habit week has no Keep or Drop decision"
HABIT_FEW = "fewer than four habit weeks closed with a decision so far"
HABIT_RAW_KEYS = ("weeks_started", "weeks_decided", "recent_closed", "recent_open", "cycles")


def _week_of(v) -> Optional[date]:
    try:
        return date.fromisoformat(v) if isinstance(v, str) else None
    except ValueError:
        return None


def _habit_weeks(state_dir) -> set:
    """The start dates of every confirmed habit week: habit.json and each kept habit-<week_of>.json that names a
    habit and a week_of (habit_start writes them only after the person said yes). An unreadable file is skipped."""
    from . import jobs
    from .habit_replies import HABIT_FILE
    st = Path(state_dir)
    weeks = set()
    for p in [st / HABIT_FILE] + sorted(st.glob("habit-*.json")):
        try:
            h = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        start = jobs._week_start(h if isinstance(h, dict) else None)
        if start is not None:
            weeks.add(start)
    return weeks


def _habit_measured(state_dir, cfg: Mapping, now: float, tz, env, home) -> tuple:
    """(label, goal, audit) of row three from the stop rule's loop rows (predictions.jsonl) and the habit files.

    A cycle is a started habit week with a Keep or Drop loop row (stop_rule.record_loop writes one only for a
    started week, so a loop row's week counts as started too). The weeks judged are the last four that are
    decided or finished (day eight on): the running, undecided week is still open and never counts against the
    goal. Day answers are not read, so a skipped or unanswered day never counts against a cycle."""
    from . import jobs, stop_rule
    loops = stop_rule.loop_rows(state_dir)
    decided = {_week_of(r.get("week_of")) for r in loops if r.get("decision") in jobs.DECISIONS} - {None}
    started = _habit_weeks(state_dir) | ({_week_of(r.get("week_of")) for r in loops} - {None})
    if not started:
        return UNKNOWN_PREFIX + jobs.NO_WEEK, "unknown", None
    today = datetime.fromtimestamp(now, tz).date()
    judged = sorted(w for w in started
                    if w in decided or today >= w + timedelta(days=jobs.HABIT_WEEK_DAYS))[-CYCLES:]
    open_ = [w for w in judged if w not in decided]
    if open_:
        label, goal = HABIT_OPEN, "not met"
    elif len(judged) >= CYCLES:
        label, goal = HABIT_MET, "met"
    else:
        label, goal = HABIT_FEW, "not met"
    audit = {"weeks_started": len(started), "weeks_decided": len(decided), "recent_closed": len(judged) - len(open_),
             "recent_open": len(open_), "cycles": CYCLES, "label": {"label": label}}
    return label, goal, audit


EVIDENCE_NEEDED = 2           # row four: at least two locked experiments judged by an outcome receipt
JUDGED = ("supports", "contradicts", "inconclusive")   # prediction's receipt verdicts; pending is not judged
EVIDENCE_MET = "two or more locked experiments have a judged outcome receipt"
EVIDENCE_FEW = "fewer than two locked experiments have a judged outcome receipt"
NO_LOCK = "no experiment locked"
EVIDENCE_RAW_KEYS = ("locked", "judged", "not_judged", "needed")


def _evidence_measured(state_dir, cfg: Mapping, now: float, tz, env, home) -> tuple:
    """(label, goal, audit) of row four from the locks and receipts in predictions.jsonl: each week's locked
    prediction (prediction.locked: the first lock of a week) and its receipt (prediction.receipt_for: the one
    written for that lock). Judged is a receipt whose verdict is supports, contradicts or inconclusive."""
    from . import prediction
    weeks = []
    for r in prediction.rows(state_dir):
        w = r.get("week_of")
        if r.get("kind") == "prediction" and isinstance(w, str) and w not in weeks:
            weeks.append(w)
    if not weeks:
        return UNKNOWN_PREFIX + NO_LOCK, "unknown", None
    judged = 0
    for w in weeks:
        receipt = prediction.receipt_for(state_dir, w)
        judged += isinstance(receipt, dict) and receipt.get("verdict") in JUDGED
    label, goal = (EVIDENCE_MET, "met") if judged >= EVIDENCE_NEEDED else (EVIDENCE_FEW, "not met")
    audit = {"locked": len(weeks), "judged": judged, "not_judged": len(weeks) - judged, "needed": EVIDENCE_NEEDED,
             "label": {"label": label}}
    return label, goal, audit


PRIVACY_WINDOW_DAYS = 7       # row seven: the tier audit log over the last seven days
PRIVACY_MET = "nothing with raw numbers went out without the opt-in this week"
PRIVACY_LEAK = "something with raw numbers went out without the opt-in this week"
NO_AUDIT_LOG = "no audit log set"
NO_AUDIT_ROWS = "no audit rows this week"
PRIVACY_RAW_KEYS = ("injections", "t0_with_opt_in", "t0_without_opt_in", "blocked", "window_days")


def _privacy_measured(state_dir, cfg: Mapping, now: float, tz, env, home) -> tuple:
    """(label, goal, audit) of row seven: tier_audit.check over the audit log ($LIMITLESS_AUDIT, else config
    ``audit_path``, as tier_audit.audit_path reads it) for the last seven days. A blocked row was stopped and is
    fine; a digit-bearing row that went out without the opt-in is a leak."""
    from . import tier_audit
    env = os.environ if env is None else env
    v = env.get(tier_audit.ENV_KEY) or cfg.get(tier_audit.CONFIG_KEY)
    if not isinstance(v, str) or not v.strip():
        return UNKNOWN_PREFIX + NO_AUDIT_LOG, "unknown", None
    counts = tier_audit.check(Path(v).expanduser(), since=now - PRIVACY_WINDOW_DAYS * 86400)
    if not counts["injections"] + counts["blocked"]:
        return UNKNOWN_PREFIX + NO_AUDIT_ROWS, "unknown", None
    label, goal = (PRIVACY_LEAK, "not met") if counts["t0_without_opt_in"] else (PRIVACY_MET, "met")
    return label, goal, dict(counts, window_days=PRIVACY_WINDOW_DAYS, label={"label": label})


FOUNDATION_ROW = 5
FOUNDATION_WORDS = "foundation"


def _foundation_measured(state_dir, cfg: Mapping, now: float, tz, env, home) -> tuple:
    """(label, goal, audit) of row five: tools.sleep_coverage_audit, the same read as limitless_sleep_coverage and
    the doctor's sleep coverage row, with sleep_coverage's own goal and unknown rules (the host config's
    ``sleep_file``, ``sleep_coverage_days`` and ``sleep_coverage_target``)."""
    from . import tools   # lazily: tools reads this module
    from .state_reader import StateReader
    a, reason = tools.sleep_coverage_audit(StateReader(Path(state_dir)), now, env, home, tz)
    if reason or a is None:
        return UNKNOWN_PREFIX + (reason or "no wearable sleep file"), "unknown", None
    return a["label"]["label"], a["goal"], a


FLOW_ROW = 6
FLOW_WORDS = "flow"
FLOW_MET = "deep work and feed leak measured for the last finished week"
FLOW_PART = "{}{} unknown for the last finished week: {}"
NO_WORK_APPS = "no work apps set"
NO_FLOW_DATA = "no activity data in the last finished week"
FLOW_RAW_KEYS = ("deep_min", "block_hours", "feed_leak_min", "leak_per_block_hour", "days_with_data")


def _flow_measured(state_dir, cfg: Mapping, now: float, tz, env, home) -> tuple:
    """(label, goal, audit) of row six: flow_week.week over the last finished week (the seven local days before
    today), from the inputs flow_week.for_week reads: the ActivityWatch DB ($LIMITLESS_AW_DB, else config
    ``aw_db``), the desktop's ActivityWatch (config desktop_aw_url or desktop_aw_export), the work and feed apps
    (env, else config, else apps.json in the state dir, as apps_reply.list_for reads them) and Glide's block.
    Met when the deep-work amount and the feed leak are both known; the trend is never judged."""
    from . import apps_reply, aw_desktop, flow_week, glide_provider
    env = os.environ if env is None else env
    st = Path(state_dir)
    work = apps_reply.list_for(apps_reply.WORK, cfg, st, env)[0]
    if not work:
        return UNKNOWN_PREFIX + NO_WORK_APPS, "unknown", None
    db = env.get("LIMITLESS_AW_DB") or cfg.get("aw_db")
    db = Path(db).expanduser() if isinstance(db, str) and db else None
    db = st / db if db is not None and not db.is_absolute() else db         # as StateReader.aw_db_path
    glide = env.get(glide_provider.ENV_KEY) or cfg.get(glide_provider.CONFIG_KEY)
    today = datetime.fromtimestamp(now, tz).date()
    r = flow_week.week(db, today - timedelta(days=flow_week.DAYS), tz, blocks=flow_week.blocks_at(glide),
                       work_apps=work, feed_apps=apps_reply.list_for(apps_reply.FEED, cfg, st, env)[0],
                       desktop=lambda lo, hi: aw_desktop.from_settings(cfg, st, lo, hi))
    if not r.get("days_with_data"):
        return UNKNOWN_PREFIX + NO_FLOW_DATA, "unknown", None
    deep, leak = r.get("deep_min") is not None, r.get("leak_per_block_hour") is not None
    if deep and leak:
        label, goal = FLOW_MET, "met"
    else:
        unknown = " and ".join(p for p, ok in (("deep work", deep), ("feed leak", leak)) if not ok)
        have = "deep work measured but " if deep else "feed leak measured but " if leak else ""
        why = flow_week._why(r, "leak" if deep else "deep")
        label, goal = FLOW_PART.format(have, unknown, why), "not met"
    audit = {k: r.get(k) for k in FLOW_RAW_KEYS}
    audit["label"] = {"label": label}
    return label, goal, audit


INTEGRATED_ROW = 8
INTEGRATED_WORDS = "integrated"
LIVE, STALE, MISSING, OFF = "live", "stale", "missing", "off"
INTEGRATIONS = (("glide", "Glide"), ("call_brief", "call brief"), ("asks", "asks queue"), ("voice_miq", "voice MIQ"))
_STATE_WORDS = {STALE: "stale", MISSING: "missing", OFF: "not set up"}
INTEGRATED_MET = "Glide, call brief, asks queue and voice MIQ all live"
NOT_LIVE = "not live: "
NO_INTEGRATION = "no local integration set up"
Z0_REGISTRY = "z0 registry: not measured here"
INTEGRATED_RAW_KEYS = ("glide", "call_brief", "asks", "voice_miq", "z0_registry", "live", "set_up", "checks")


def _readable(path) -> bool:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            f.read()
    except (OSError, ValueError):
        return False
    return True


def _glide_state(state_dir, cfg: Mapping, now: float, env: Mapping) -> str:
    """Glide's attention.json ($LIMITLESS_GLIDE_ATTENTION, else config glide_attention): live when it reads as a
    JSON object (as glide_provider.attention reads it)."""
    from . import glide_provider
    path = env.get(glide_provider.ENV_KEY) or cfg.get(glide_provider.CONFIG_KEY)
    if not isinstance(path, str) or not path:
        return OFF
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return MISSING
    return LIVE if isinstance(data, dict) else MISSING


def _call_brief_state(state_dir, cfg: Mapping, now: float, env: Mapping) -> str:
    """The call brief (config call_brief_file; a relative path is in the state dir, as call_brief.out_path): live
    when its mtime is at most call_brief.STALE_S old, z0live's own freshness rule."""
    from . import call_brief
    v = cfg.get(call_brief.CONFIG_KEY)
    if not isinstance(v, str) or not v.strip():
        return OFF
    p = Path(v).expanduser()
    p = p if p.is_absolute() else Path(state_dir) / p
    try:
        age = now - p.stat().st_mtime
    except OSError:
        return MISSING
    if not p.is_file():
        return MISSING
    return LIVE if 0 <= age <= call_brief.STALE_S else STALE


def _asks_state(state_dir, cfg: Mapping, now: float, env: Mapping) -> str:
    """The asks queue ($LIMITLESS_ASKS, else config asks_path, as asks.queue_path): live when it can be read."""
    from . import asks
    path = env.get(asks.ENV_KEY) or cfg.get(asks.CONFIG_KEY)
    if not isinstance(path, str) or not path:
        return OFF
    return LIVE if _readable(path) else MISSING


def _voice_state(state_dir, cfg: Mapping, now: float, env: Mapping) -> str:
    """The voice MIQ (config voice_miq, as the doctor's voice MIQ row): off by config, missing without an existing
    call sessions dir (config voice_miq_sessions), else live. No call is read."""
    from . import voice_miq   # voice_miq -> jobs_runner -> card
    if voice_miq.mode(cfg) == voice_miq.OFF:
        return OFF
    sessions = voice_miq.sessions_dir(cfg)
    return LIVE if sessions is not None and sessions.is_dir() else MISSING


_INTEGRATION_CHECKS = {"glide": _glide_state, "call_brief": _call_brief_state, "asks": _asks_state,
                       "voice_miq": _voice_state}


def _integrated_measured(state_dir, cfg: Mapping, now: float, tz, env, home) -> tuple:
    """(label, goal, audit) of row eight: one sub-check per local integration the plugin can see (Glide's attention
    file, the call brief, the asks queue, the voice MIQ), each live, stale, missing or off. The z0 registry cannot
    be checked here and is never counted live. Met only when all four are live; unknown when none is set up."""
    env = os.environ if env is None else env
    states = {}
    for key, _words in INTEGRATIONS:
        try:
            states[key] = _INTEGRATION_CHECKS[key](state_dir, cfg, now, env)
        except Exception:  # noqa: BLE001 - one broken input is that check missing, never a traceback
            states[key] = MISSING
    set_up = sum(1 for v in states.values() if v != OFF)
    live = sum(1 for v in states.values() if v == LIVE)
    if not set_up:
        return UNKNOWN_PREFIX + NO_INTEGRATION, "unknown", None
    if live == len(INTEGRATIONS):
        label, goal = INTEGRATED_MET, "met"
    else:
        label = NOT_LIVE + ", ".join(f"{words} {_STATE_WORDS[states[key]]}" for key, words in INTEGRATIONS
                                     if states[key] != LIVE)
        goal = "not met"
    audit = dict(states, z0_registry=Z0_REGISTRY, live=live, set_up=set_up, checks=len(INTEGRATIONS),
                 label={"label": label})
    return label, goal, audit


_READS = ((UPTIME_ROW, UPTIME_WORDS, _uptime_measured),
          (DELIVERY_ROW, DELIVERY_WORDS, _delivery_measured),
          (HABIT_ROW, HABIT_WORDS, _habit_measured),
          (EVIDENCE_ROW, EVIDENCE_WORDS, _evidence_measured),
          (FOUNDATION_ROW, FOUNDATION_WORDS, _foundation_measured),
          (FLOW_ROW, FLOW_WORDS, _flow_measured),
          (PRIVACY_ROW, PRIVACY_WORDS, _privacy_measured),
          (INTEGRATED_ROW, INTEGRATED_WORDS, _integrated_measured))


def measured_audits(state_dir, cfg: Optional[Mapping], now: float, tz: Optional[tzinfo] = None, *,
                    env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> List[tuple]:
    """``[(row, audit)]`` for every measured row, in row order (MEASURED_ROWS): ``row`` as measured() gives it,
    ``audit`` the audit's own dict (its T0 counts, and its ``label``) or None when there was nothing to audit."""
    cfg = cfg if isinstance(cfg, Mapping) else {}
    out = []
    for n, words, read in _READS:
        try:
            label, goal, audit = read(state_dir, cfg, now, tz, env, home)
        except Exception:  # noqa: BLE001 - a broken log is unknown, never a traceback in the review
            label, goal, audit = UNKNOWN_PREFIX + "the log could not be read", "unknown", None
        out.append(({"n": n, "criterion_words": words, "label": label, "goal": goal}, audit))
    return out


def measured(state_dir, cfg: Optional[Mapping], now: float, tz: Optional[tzinfo] = None, *,
             env: Optional[Mapping[str, str]] = None, home: Optional[Path] = None) -> List[dict]:
    """North-star rows one, two, three, four and seven as code measured them: ``[{n, criterion_words, label,
    goal}]``.

    Row one is the uptime audit of the state dir's runs.jsonl, row two the delivery audit of kevin-push's log
    (config ``push_log``), row three the habit loop (the stop rule's loop rows in predictions.jsonl and the habit
    files), row four the evidence loop (the locks and receipts in predictions.jsonl) and row seven privacy
    (tier_audit.check over the audit log for the last seven days). ``label`` is the audit's own T1 words (no
    digit) or ``unknown: <why>``; ``goal`` is
    met, not met or unknown. A missing or unreadable log is unknown, never an error and never met. Read-only:
    nothing is written or sent, and no hand status is changed.
    """
    return [row for row, _audit in measured_audits(state_dir, cfg, now, tz, env=env, home=home)]


MEASURED_LINE = "Measured: {}: {}"
DISAGREE_LINE = "Row {} says green but the measurement says not met."
MORE_LINE = "More measured rows in limitless_scorecard."
MEASURED_ROWS = tuple(n for n, _words, _read in _READS)


def disagreement(rows: List[dict], m: Mapping) -> Optional[str]:
    """"Row <name> says green but the measurement says not met." when the hand-kept row numbered like ``m`` is
    green and ``m``'s goal is not met; else None. It only words the gap: the status is never changed."""
    row = next((r for r in rows or () if isinstance(r, dict) and r.get("n") == m.get("n")), None)
    if row is None or row.get("status") != "green" or m.get("goal") != "not met":
        return None
    return DISAGREE_LINE.format(_name(row["criterion"]))


def measured_lines(rows: List[dict], measured_rows: List[dict], limit: int = MAX_LINES - 1) -> List[str]:
    """The weekly block's measured lines, digit-free and at most ``limit`` (default four: the block's first line
    is the self-reported counts line): "Measured: <row words>: <label>" for every measured row (at most one each,
    in row order, MEASURED_ROWS, whatever the input order), each followed by "Row <name> says green but the
    measurement says not met." when the hand-kept row with that number is green and the goal is not met. When
    they would pass ``limit``, whole rows (a row with its note) are kept in that order and the rest fold into one
    line, "More measured rows in limitless_scorecard." Only words: no status is changed here, and code never
    marks a row green."""
    first = {}
    for m in measured_rows or ():
        n = m.get("n") if isinstance(m, dict) else None
        if n in MEASURED_ROWS and n not in first:
            first[n] = m
    groups = []
    for n in MEASURED_ROWS:
        if n in first:
            m = first[n]
            note = disagreement(rows, m)
            groups.append([_DIGITS.sub("#", MEASURED_LINE.format(m.get("criterion_words"), m.get("label")))]
                          + ([note] if note else []))
    out = [ln for g in groups for ln in g]
    if len(out) <= limit:
        return out
    out = []
    for g in groups:
        if len(out) + len(g) > limit - 1:
            break
        out += g
    return out + [MORE_LINE]
