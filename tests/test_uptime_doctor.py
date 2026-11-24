"""The doctor's uptime row and bin/limitless-uptime-audit: read-only, words only in the row, counts only in --json.

The row sits right after the last-sync row, kind source (--strict never counts it): live when the uptime goal
was met, stale when it was not, missing when unknown. Synthetic state dirs only.
"""
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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import doctor, uptime_audit as ua  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "limitless-uptime-audit"
NOW = 1894708800.0
H, D = 3600.0, 86400.0


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write(st, now, stale_by_day, days=28, inputs=True, lag=2 * H):
    rows = []
    for n in range(days):
        r = {"at": iso(now - lag - n * D), "job": "sync", "ok": True}
        if inputs:
            r["inputs"] = "stale " + ",".join(stale_by_day(n))
        rows.append(r)
    (st / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (st / "inputs.json").write_text(json.dumps({"at": iso(now - H), "ageHours": {"phoneApps": 1.0, "whoop": 1.0}}))


class Row(unittest.TestCase):
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
        self.assertEqual((r["name"], r["kind"]), (doctor.UPTIME_ROW, "source"))
        self.assertEqual(doctor.UPTIME_ROW, "uptime")
        self.assertNotRegex(json.dumps(r), r"\d")
        return r

    def test_goal_met_is_live_with_the_label_words(self):
        write(self.st, NOW, lambda n: [])
        r = self.row()
        self.assertEqual((r["status"], r["reason"]), (doctor.LIVE, "phone apps and whoop fresh every day; uptime goal met"))

    def test_goal_not_met_is_stale(self):
        write(self.st, NOW, lambda n: ["whoop"])
        r = self.row()
        self.assertEqual(r["status"], doctor.STALE)
        self.assertEqual(r["reason"], "phone apps fresh every day; whoop stale all month; uptime goal not met")

    def test_unknown_is_missing_with_the_reason(self):
        write(self.st, NOW, lambda n: [], inputs=False)
        self.assertEqual((self.row()["status"], self.row()["reason"]), (doctor.MISSING, ua.FEW_KNOWN_REASON))
        (self.st / "runs.jsonl").unlink()
        self.assertEqual((self.row()["status"], self.row()["reason"]), (doctor.MISSING, ua.NO_LOG_REASON))
        write(self.st, NOW - 90 * D, lambda n: [])
        self.assertEqual((self.row()["status"], self.row()["reason"]), (doctor.MISSING, ua.NO_ROWS_REASON))

    def test_goal_unknown_is_missing_with_the_label(self):
        write(self.st, NOW, lambda n: [], days=20)
        r = self.row()
        self.assertEqual(r["status"], doctor.MISSING)
        self.assertTrue(r["reason"].endswith(ua.GOAL_WORDS[ua.GOAL_UNKNOWN]), r["reason"])

    def test_the_report_has_it_right_after_the_last_sync_row(self):
        write(self.st, NOW, lambda n: ["whoop"])
        rows = doctor.report({"state": str(self.st)}, NOW)
        names = [r["name"] for r in rows]
        self.assertEqual(names.index(doctor.UPTIME_ROW), names.index("last sync run") + 1)
        self.assertLess(names.index(doctor.UPTIME_ROW), names.index("tool limitless_status"))
        self.assertEqual(names.count(doctor.UPTIME_ROW), 1)

    def test_strict_never_counts_it(self):
        write(self.st, NOW, lambda n: ["whoop"])
        rows = [r for r in doctor.report({"state": str(self.st)}, NOW) if r["kind"] in doctor.STRICT_KINDS]
        self.assertNotIn(doctor.UPTIME_ROW, [r["name"] for r in rows])


class Cli(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.st = self.dir / "state"
        self.st.mkdir()

    def env(self, **cfg):
        cfg.setdefault("state", str(self.st))
        p = self.dir / "config.json"
        p.write_text(json.dumps(cfg))
        keep = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "SYSTEMROOT")}
        return dict(keep, LIMITLESS_CONFIG=str(p), LIMITLESS_STATE=str(self.st), HOME=str(self.dir), TZ="UTC")

    def run_cli(self, env, *args):
        return subprocess.run([sys.executable, "-I", str(BIN), *args], env=env, capture_output=True, text=True,
                              timeout=60)

    def test_prints_the_label(self):
        write(self.st, time.time(), lambda n: ["whoop"], lag=0)   # the CLI reads the real clock: runs up to it
        r = self.run_cli(self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "phone apps fresh every day; whoop stale all month; uptime goal not met\n")

    def test_json_prints_the_counts(self):
        write(self.st, time.time(), lambda n: ["whoop"], lag=0)
        r = self.run_cli(self.env(outage_ignore=["phoneApps"]), "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual(got["inputs"], {"whoop": {"fresh": 0, "stale": 28, "unknown": 0}})
        self.assertEqual((got["known_days"], got["window_days"], got["goal"]), (28, 28, "not met"))
        self.assertEqual(got["label"], "whoop stale all month; uptime goal not met")

    def test_no_log_says_unknown_and_why(self):
        r = self.run_cli(self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, f"unknown: {ua.NO_LOG_REASON}\n")
        got = json.loads(self.run_cli(self.env(), "--json").stdout)
        self.assertEqual(got, {"label": "unknown", "reason": ua.NO_LOG_REASON})

    def test_writes_nothing(self):
        write(self.st, time.time(), lambda n: [], lag=0)
        before = {p.name: p.read_bytes() for p in self.st.iterdir()}
        self.run_cli(self.env())
        self.run_cli(self.env(), "--json")
        self.assertEqual({p.name: p.read_bytes() for p in self.st.iterdir()}, before)


if __name__ == "__main__":
    unittest.main()
