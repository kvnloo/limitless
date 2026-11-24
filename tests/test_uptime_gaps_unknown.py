"""Loop gaps while the uptime goal is still unknown: too few runs name their stale inputs, so the goal is unknown
and its reason stands in for the audit's words, but the loop gaps come from the runs' own ``at`` times and are
known anyway. The doctor's uptime row, the limitless_uptime tool, bin/limitless-uptime-audit and the scorecard's
measured line say the open gap first and this week's closed gap before the unknown reason, in the same words as
the audit. No runs or no log keep their wording; the status stays missing. Synthetic state dirs, a fixed clock
(the CLI reads the real one) and UTC.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import doctor, scorecard as sc, tools, uptime_audit as ua  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

BIN = ROOT / "bin" / "limitless-uptime-audit"
UTC = timezone.utc
NOW = 1894708800.0
H, D = 3600.0, 86400.0
STOPPED = "the loop stopped once this week for over a day"
NOT_RUN = "the loop has not run for hours"


def iso(t):
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def write(st, now, last_ago=0.5 * H, hole=(4 * D, 2 * D), named=3):
    """Hourly synthetic sync runs on three days: one day of runs, a two-day hole ending two days before ``now``,
    then two days of runs, the newest ``last_ago`` before ``now``. Only the newest ``named`` runs carry
    ``inputs`` (older rows predate the field), so too few days are known for the goal."""
    first = now - last_ago - 5 * D + H
    times = [first + k * H for k in range(int(5 * D / H))]
    if hole:
        times = [t for t in times if not now - hole[0] < t < now - hole[1]]
    rows = [{"at": iso(t), "job": "sync", "ok": True} for t in times]
    for r in rows[len(rows) - named:]:
        r["inputs"] = "stale"
    (st / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (st / "inputs.json").write_text(json.dumps({"at": iso(now - H), "ageHours": {"phoneApps": 1.0, "whoop": 1.0}}))


class UnknownGoal(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.st = self.dir / "state"
        self.st.mkdir()
        self.cfg = self.dir / "config.json"
        self.cfg.write_text(json.dumps({"state": str(self.st)}))
        p = mock.patch.dict(os.environ, {"LIMITLESS_CONFIG": str(self.cfg), "TZ": "UTC"}, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def row(self):
        r = doctor.uptime_row(StateReader(self.st), NOW)
        self.assertNotRegex(json.dumps(r), r"\d")
        return r

    def tool(self):
        return tools.uptime(StateReader(self.st), NOW, env=dict(os.environ), home=self.dir, tz=UTC)

    def measured(self):
        m = sc.measured(self.st, json.loads(self.cfg.read_text()), NOW, UTC, env=dict(os.environ), home=self.dir)
        return [x for x in m if x["n"] == sc.UPTIME_ROW][0]

    def measured_line(self):
        return sc.measured_lines([], [self.measured()])

    def audit(self):
        return tools.uptime_audit(StateReader(self.st), NOW, env=dict(os.environ), home=self.dir, tz=UTC)

    def test_the_fixture_is_unknown_for_too_few_known_days_with_a_closed_gap_this_week(self):
        write(self.st, NOW)
        a = self.audit()
        self.assertEqual((a["goal"], a["label"]["label"]), (ua.GOAL_UNKNOWN, ua.UNKNOWN))
        self.assertLess(a["known_days"], ua.MIN_KNOWN_DAYS)
        self.assertEqual((a["loop"]["week_gaps"], a["loop"]["open_s"]), (1, None))
        self.assertGreater(a["loop"]["week_longest_s"], D)

    def test_the_doctor_row_says_the_stop_before_the_unknown_reason(self):
        write(self.st, NOW)
        r = self.row()
        self.assertIn("the loop stopped", r["reason"])
        self.assertEqual((r["status"], r["reason"]), (doctor.MISSING, f"{STOPPED}; {ua.FEW_KNOWN_REASON}"))

    def test_an_open_gap_comes_first(self):
        write(self.st, NOW, last_ago=5 * H)
        r = self.row()
        self.assertEqual((r["status"], r["reason"]),
                         (doctor.MISSING, f"{NOT_RUN}; {STOPPED}; {ua.FEW_KNOWN_REASON}"))

    def test_the_tool_says_the_same_and_stays_unknown(self):
        write(self.st, NOW, last_ago=5 * H)
        res = self.tool()
        self.assertIsNone(res["value"])
        self.assertEqual(res["label"]["label"], ua.UNKNOWN)
        self.assertEqual(res["reason"], f"{NOT_RUN}; {STOPPED}; {ua.FEW_KNOWN_REASON}")
        self.assertEqual(res["reason"], self.row()["reason"])

    def test_the_measured_line_says_the_same_and_the_goal_stays_unknown(self):
        write(self.st, NOW)
        self.assertEqual(self.measured()["goal"], "unknown")
        self.assertEqual(self.measured_line(),
                         [f"Measured: loop uptime: unknown: {STOPPED}; {ua.FEW_KNOWN_REASON}"])

    def test_without_a_gap_the_reason_is_unchanged(self):
        write(self.st, NOW, hole=None)
        self.assertEqual((self.row()["status"], self.row()["reason"]), (doctor.MISSING, ua.FEW_KNOWN_REASON))
        self.assertEqual(self.tool()["reason"], ua.FEW_KNOWN_REASON)
        self.assertEqual(self.measured_line(), [f"Measured: loop uptime: unknown: {ua.FEW_KNOWN_REASON}"])

    def test_no_log_is_unchanged(self):
        self.assertEqual((self.row()["status"], self.row()["reason"]), (doctor.MISSING, ua.NO_LOG_REASON))
        self.assertEqual(self.tool()["reason"], ua.NO_LOG_REASON)
        self.assertEqual(self.measured_line(), [f"Measured: loop uptime: unknown: {ua.NO_LOG_REASON}"])

    def test_no_run_in_the_window_is_unchanged(self):
        write(self.st, NOW - 60 * D, last_ago=5 * H)
        self.assertEqual((self.row()["status"], self.row()["reason"]), (doctor.MISSING, ua.NO_ROWS_REASON))
        self.assertEqual(self.tool()["reason"], ua.NO_ROWS_REASON)
        self.assertEqual(self.measured_line(), [f"Measured: loop uptime: unknown: {ua.NO_ROWS_REASON}"])

    def test_an_empty_log_is_unchanged(self):
        (self.st / "runs.jsonl").write_text("")
        self.assertEqual((self.row()["status"], self.row()["reason"]), (doctor.MISSING, ua.NO_ROWS_REASON))
        self.assertEqual(self.tool()["reason"], ua.NO_ROWS_REASON)


class Words(unittest.TestCase):
    def test_unknown_words_put_the_loop_clauses_before_the_reason(self):
        a = {"loop": {"open_s": 30 * 60.0, "week_gaps": 3, "week_longest_s": 2 * H}}
        self.assertEqual(ua.unknown_words(a), "the loop has not run for under an hour; the loop stopped a few "
                                              "times this week, the longest for hours; " + ua.FEW_KNOWN_REASON)

    def test_unknown_words_without_loop_facts_are_the_reason(self):
        self.assertEqual(ua.unknown_words({}), ua.FEW_KNOWN_REASON)
        self.assertEqual(ua.unknown_words({"loop": {"open_s": None, "week_gaps": 0}}), ua.FEW_KNOWN_REASON)


class Cli(unittest.TestCase):
    def test_the_cli_prints_the_stop_before_the_unknown_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            st = d / "state"
            st.mkdir()
            write(st, time.time())                       # the CLI reads the real clock
            cfg = d / "config.json"
            cfg.write_text(json.dumps({"state": str(st)}))
            keep = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "SYSTEMROOT")}
            env = dict(keep, LIMITLESS_CONFIG=str(cfg), LIMITLESS_STATE=str(st), HOME=str(d), TZ="UTC")
            r = subprocess.run([sys.executable, "-I", str(BIN)], env=child_env(env), capture_output=True, text=True,
                               timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout, f"unknown: {STOPPED}; {ua.FEW_KNOWN_REASON}\n")


if __name__ == "__main__":
    unittest.main()
