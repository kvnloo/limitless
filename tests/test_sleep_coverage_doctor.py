"""The doctor's sleep coverage row and bin/limitless-sleep-coverage: read-only, words only in the row, counts only
in --json.

The row sits right before the two wearable export rows that write the sleep file (Open Wearables, then the NOOP
export job) and right after the context packet's row, kind source
(--strict never counts it): live when the wearable goal was met, stale when it was not, missing when unknown,
off when no sleep file is set. Synthetic state dirs only.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import doctor, sleep_coverage as sc  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "limitless-sleep-coverage"
TODAY = date(2030, 1, 29)
H = 3600


def local(day, hour):
    return datetime.combine(day, time(0)).timestamp() + hour * H


NOW = local(TODAY, 9)


def write_sleep(st, agos, **extra):
    rows = [dict({"night": (TODAY - timedelta(days=a)).isoformat(), "asleep_s": 7 * H, "source": "synthetic-band"},
                 **extra) for a in agos]
    (st / "sleep.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def write_unlocks(st, agos):
    rows = []
    for a in agos:
        s = local(TODAY - timedelta(days=a), 23)
        rows += [{"ts": int(s * 1000), "type": "KEYGUARD_HIDDEN", "pkg": "synthetic"},
                 {"ts": int((s + 8 * H) * 1000), "type": "KEYGUARD_HIDDEN", "pkg": "synthetic"}]
    (st / "screen-events.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.st = self.dir / "state"
        self.st.mkdir()
        self.cfg = self.dir / "config.json"
        self.config({"sleep_file": "sleep.jsonl"})
        p = mock.patch.dict(os.environ, {"LIMITLESS_CONFIG": str(self.cfg)}, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def config(self, extra):
        self.cfg.write_text(json.dumps(dict({"state": str(self.st)}, **extra)))


class Row(Case):
    def row(self):
        r = doctor.sleep_coverage_row(StateReader(self.st), NOW)
        self.assertEqual((r["name"], r["kind"]), (doctor.SLEEP_COVERAGE_ROW, "source"))
        self.assertEqual(doctor.SLEEP_COVERAGE_ROW, "sleep coverage")
        self.assertEqual(re.findall(r"\d", json.dumps(r)), [])
        return r

    def test_goal_met_is_live_with_the_label_words(self):
        write_sleep(self.st, range(1, 29))
        r = self.row()
        self.assertEqual((r["status"], r["reason"]), (doctor.LIVE, "wearable sleep on every night; wearable goal met"))

    def test_goal_not_met_is_stale_and_demo_rows_never_count(self):
        write_sleep(self.st, range(1, 29), deviceId="demo-strap")
        write_unlocks(self.st, range(1, 29))
        r = self.row()
        self.assertEqual(r["status"], doctor.STALE)
        self.assertEqual(r["reason"], "no wearable sleep, phone estimate on every night; wearable goal not met; "
                                      "some demo rows were left out")

    def test_unknown_is_missing_with_the_reason(self):
        write_sleep(self.st, range(1, 4))
        self.assertEqual((self.row()["status"], self.row()["reason"]), (doctor.MISSING, sc.FEW_KNOWN_REASON))
        write_sleep(self.st, range(1, 22))
        self.assertEqual((self.row()["status"], self.row()["reason"]),
                         (doctor.MISSING, "wearable sleep on most nights, no sleep data on some nights; "
                                          "wearable goal unknown: too many nights with no sleep data"))
        (self.st / "sleep.jsonl").unlink()
        self.assertEqual((self.row()["status"], self.row()["reason"]), (doctor.MISSING, sc.UNREADABLE_REASON))
        self.assertNotIn(str(self.dir), json.dumps(self.row()))

    def test_no_sleep_file_set_is_off(self):
        self.config({})
        self.assertEqual((self.row()["status"], self.row()["reason"]), (doctor.OFF, sc.NO_FILE_REASON))


class Order(Case):
    def test_the_row_comes_right_before_the_wearable_export_rows_and_strict_skips_it(self):
        write_sleep(self.st, range(1, 29))
        rows = doctor.report(json.loads(self.cfg.read_text()), NOW)
        names = [r["name"] for r in rows]
        self.assertEqual(names.count("sleep coverage"), 1)
        at = names.index("sleep coverage")
        self.assertEqual(names[at + 1:at + 3], [doctor.OW_ROW, doctor.NOOP_ROW])
        self.assertEqual(names[at - 1], "export context packet")
        self.assertLess(names.index("tool limitless_sleep_coverage"), names.index(doctor.OW_ROW))
        self.assertNotIn("source", doctor.STRICT_KINDS)
        self.assertEqual(rows[at]["status"], doctor.LIVE)


class Cli(Case):
    """The CLI reads the real clock: its synthetic nights are the real nights before today, in UTC (TZ=UTC)."""

    def write(self, wear_agos, phone_agos=()):
        today = datetime.now(timezone.utc).date()
        rows = [{"night": (today - timedelta(days=a)).isoformat(), "asleep_s": 7 * H, "source": "synthetic-band"}
                for a in wear_agos]
        (self.st / "sleep.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        ev = []
        for a in phone_agos:
            d = today - timedelta(days=a)
            s = datetime(d.year, d.month, d.day, 23, tzinfo=timezone.utc).timestamp()
            ev += [{"ts": int(s * 1000), "type": "KEYGUARD_HIDDEN", "pkg": "synthetic"},
                   {"ts": int((s + 8 * H) * 1000), "type": "KEYGUARD_HIDDEN", "pkg": "synthetic"}]
        (self.st / "screen-events.jsonl").write_text("".join(json.dumps(r) + "\n" for r in ev))

    def run_bin(self, *args):
        keep = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "SYSTEMROOT")}
        env = dict(keep, LIMITLESS_CONFIG=str(self.cfg), LIMITLESS_STATE=str(self.st), HOME=str(self.dir), TZ="UTC")
        r = subprocess.run([sys.executable, "-I", str(BIN), *args], capture_output=True, text=True, timeout=60,
                           env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_words_by_default_counts_with_json(self):
        self.write(range(1, 11), range(1, 29))
        out = self.run_bin()
        self.assertEqual(out, "wearable sleep on some nights, phone estimate on most nights; wearable goal "
                              "not met\n")
        got = json.loads(self.run_bin("--json"))
        self.assertEqual((got["wearable_nights"], got["proxy_only_nights"], got["unknown_nights"]), (10, 18, 0))
        self.assertEqual((got["window_nights"], got["target"], got["goal"], got["demo_rows"]), (28, 0.8, "not met", 0))
        self.assertEqual(got["label"], out.strip())
        self.assertNotIn("reason", got)

    def test_unknown_prints_the_reason_and_json_keeps_it(self):
        out = self.run_bin()
        self.assertEqual(out, "unknown: " + sc.UNREADABLE_REASON + "\n")
        got = json.loads(self.run_bin("--json"))
        self.assertEqual((got["label"], got["reason"]), ("unknown", sc.UNREADABLE_REASON))
        self.assertNotIn("wearable_nights", got)
        self.assertNotIn(str(self.dir), json.dumps(got))

    def test_json_keeps_the_counts_when_too_few_nights_are_known(self):
        self.write(range(1, 4))
        got = json.loads(self.run_bin("--json"))
        self.assertEqual((got["label"], got["reason"], got["wearable_nights"]), ("unknown", sc.FEW_KNOWN_REASON, 3))

    def test_read_only(self):
        self.write(range(1, 29))
        before = sorted((str(p), p.read_bytes()) for p in self.dir.rglob("*") if p.is_file())
        self.run_bin()
        self.run_bin("--json")
        self.assertEqual(sorted((str(p), p.read_bytes()) for p in self.dir.rglob("*") if p.is_file()), before)

    def test_executable(self):
        self.assertTrue(os.access(BIN, os.X_OK))


if __name__ == "__main__":
    unittest.main()
