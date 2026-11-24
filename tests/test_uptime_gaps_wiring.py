"""Loop gaps where the uptime audit shows: the doctor's uptime row, the weekly scorecard's measured line, the
limitless_uptime tool and bin/limitless-uptime-audit carry the same words, read through tools.uptime_audit with
the real ``now`` and config ``loop_gap_limit_s``. The words never set a status: the doctor row still follows the
uptime goal alone. Synthetic state dirs only, a fixed clock (the CLI reads the real one) and UTC.
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

from limitless import doctor, scorecard as sc, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

BIN = ROOT / "bin" / "limitless-uptime-audit"
UTC = timezone.utc
NOW = 1894708800.0
H, D = 3600.0, 86400.0
FRESH = "phone apps and whoop fresh every day"
MET = "uptime goal met"


def iso(t):
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def write(st, now, last_ago=0.5 * H, hole=None, days=28):
    """Hourly synthetic sync runs over ``days`` days, the newest ``last_ago`` before ``now``; ``hole`` is a
    (start_ago, stop_ago) stretch with no run (the loop was down)."""
    times = [now - last_ago - k * H for k in range(int(days * 24) - 2)]
    if hole:
        times = [t for t in times if not now - hole[0] < t < now - hole[1]]
    rows = [{"at": iso(t), "job": "sync", "ok": True, "inputs": "stale"} for t in sorted(times)]
    (st / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (st / "inputs.json").write_text(json.dumps({"at": iso(now - H), "ageHours": {"phoneApps": 1.0, "whoop": 1.0}}))


class Wiring(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.st = self.dir / "state"
        self.st.mkdir()
        self.cfg = self.dir / "config.json"
        self.config()
        p = mock.patch.dict(os.environ, {"LIMITLESS_CONFIG": str(self.cfg), "TZ": "UTC"}, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def config(self, **kw):
        self.cfg.write_text(json.dumps(dict(kw, state=str(self.st))))

    def row(self):
        r = doctor.uptime_row(StateReader(self.st), NOW)
        self.assertNotRegex(json.dumps(r), r"\d")
        return r

    def measured_line(self):
        m = sc.measured(self.st, json.loads(self.cfg.read_text()), NOW, UTC, env=dict(os.environ), home=self.dir)
        return sc.measured_lines([], [x for x in m if x["n"] == sc.UPTIME_ROW])

    def tool_words(self):
        return tools.uptime(StateReader(self.st), NOW, env=dict(os.environ), home=self.dir, tz=UTC)["label"]["label"]

    def test_regular_runs_add_nothing(self):
        write(self.st, NOW)
        self.assertEqual((self.row()["status"], self.row()["reason"]), (doctor.LIVE, f"{FRESH}; {MET}"))

    def test_an_open_gap_is_said_first_and_the_status_still_follows_the_goal(self):
        write(self.st, NOW, last_ago=5 * H)
        words = f"the loop has not run for hours; {FRESH}; {MET}"
        self.assertEqual((self.row()["status"], self.row()["reason"]), (doctor.LIVE, words))
        self.assertEqual(self.measured_line(), ["Measured: loop uptime: " + words])
        self.assertEqual(self.tool_words(), words)

    def test_a_gap_this_week_is_said_the_same_in_every_place(self):
        write(self.st, NOW, hole=(3 * D, 3 * D - 8 * H))
        words = f"{FRESH}; the loop stopped once this week for hours; {MET}"
        self.assertEqual((self.row()["status"], self.row()["reason"]), (doctor.LIVE, words))
        self.assertEqual(self.measured_line(), ["Measured: loop uptime: " + words])
        self.assertEqual(self.tool_words(), words)

    def test_the_config_limit_is_read(self):
        write(self.st, NOW, hole=(3 * D, 3 * D - 8 * H))
        self.config(loop_gap_limit_s=12 * H)
        self.assertEqual(self.row()["reason"], f"{FRESH}; {MET}")
        self.assertEqual(self.measured_line(), [f"Measured: loop uptime: {FRESH}; {MET}"])

    def test_too_few_rows_keep_the_unknown_reason(self):
        write(self.st, NOW, last_ago=2 * D, days=4)
        r = self.row()
        self.assertEqual((r["status"], r["reason"]), (doctor.MISSING, tools.uptime_reason(
            tools.uptime_audit(StateReader(self.st), NOW))))
        self.assertNotIn("loop", r["reason"])


class Cli(unittest.TestCase):
    def test_the_cli_prints_the_same_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            st = d / "state"
            st.mkdir()
            write(st, time.time(), last_ago=5 * H)       # the CLI reads the real clock
            cfg = d / "config.json"
            cfg.write_text(json.dumps({"state": str(st)}))
            keep = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "SYSTEMROOT")}
            env = dict(keep, LIMITLESS_CONFIG=str(cfg), LIMITLESS_STATE=str(st), HOME=str(d), TZ="UTC")
            r = subprocess.run([sys.executable, "-I", str(BIN)], env=child_env(env), capture_output=True, text=True,
                               timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout, f"the loop has not run for hours; {FRESH}; {MET}\n")


if __name__ == "__main__":
    unittest.main()
