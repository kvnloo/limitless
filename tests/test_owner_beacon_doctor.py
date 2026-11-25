"""limitless/doctor.py: the "owner beacon" row. Present only when config owner_beacons is set: missing (absent,
unreadable or not a beacon), stale (older than catchup_after_h, default catchup.DEFAULT_AFTER_H) or live, the
age in words and never a digit. Synthetic beacons and a fixed fixture clock only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import catchup, doctor  # noqa: E402

NOW = 1894708800.0  # 2030-01-15T12:00:00Z, the fixture clock
H = 3600.0
ROOT = Path(__file__).resolve().parents[1]
ROW = "owner beacon"


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")


def clean_env(**extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("LIMITLESS_")}
    env.update(extra)
    return env


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.st = self.home / "state"
        (self.st / "beacons").mkdir(parents=True)
        self.cfg_path = self.home / "config.json"

    def beacon(self, name, age_h=None, body=None):
        p = self.st / "beacons" / name
        p.write_text(json.dumps({"at": iso(NOW - age_h * H), "v": 1}) if body is None else body)
        return "beacons/" + name

    def rows(self, **cfg):
        cfg = dict({"state": str(self.st)}, **cfg)
        self.cfg_path.write_text(json.dumps(cfg))
        with mock.patch.dict(os.environ, clean_env(HOME=str(self.home), LIMITLESS_CONFIG=str(self.cfg_path)),
                             clear=True):
            return doctor.report(cfg, NOW)

    def row(self, **cfg):
        rows = self.rows(**cfg)
        got = [r for r in rows if r["name"] == ROW]
        self.assertEqual(len(got), 1, [r["name"] for r in rows])
        r = got[0]
        self.assertEqual(r["kind"], "source")
        self.assertIsNone(re.search(r"\d", r["name"] + r["reason"]), r)
        return r

    def direct(self, **cfg):
        """The row before report()'s words() pass: it must hold no digit by itself."""
        cfg = dict({"state": str(self.st)}, **cfg)
        self.cfg_path.write_text(json.dumps(cfg))
        with mock.patch.dict(os.environ, clean_env(HOME=str(self.home), LIMITLESS_CONFIG=str(self.cfg_path)),
                             clear=True):
            r = doctor.owner_beacon_row(cfg, NOW)
        self.assertIsNone(re.search(r"\d", r["reason"]), r)
        return r


class NotSet(Case):
    def test_no_row_without_owner_beacons(self):
        for cfg in ({}, {"owner_beacons": []}, {"owner_beacons": [""]}, {"owner_beacons": "beacons/a.json"}):
            self.assertNotIn(ROW, [r["name"] for r in self.rows(**cfg)], cfg)

    def test_the_row_comes_right_after_the_rides_source_row(self):
        names = [r["name"] for r in self.rows(owner_beacons=[self.beacon("a.json", 2)])]
        self.assertEqual(names[names.index("rides source") + 1], ROW)
        self.assertEqual(names[names.index(ROW) + 1], "local labeler")


class Missing(Case):
    def assert_missing(self, rel, why):
        r = self.row(owner_beacons=[rel])
        self.assertEqual(r["status"], "missing", r)
        self.assertIn(why, r["reason"])

    def test_absent(self):
        self.assert_missing("beacons/gone.json", "file missing")

    def test_unreadable(self):
        (self.st / "beacons" / "dir.json").mkdir()
        self.assert_missing("beacons/dir.json", "unreadable")
        (self.st / "beacons" / "bin.json").write_bytes(b"\xff\xfe{")
        self.assert_missing("beacons/bin.json", "not a beacon")

    def test_not_a_beacon(self):
        at = iso(NOW - H)
        for i, body in enumerate(("", "not json", json.dumps({"at": at, "v": 2}), json.dumps({"at": at}),
                                  json.dumps({"at": at[:-6], "v": 1}), json.dumps([at, 1]),
                                  json.dumps({"at": at, "v": 1, "pad": "x" * 5000}))):
            self.assert_missing(self.beacon(f"bad{i}.json", body=body), "not a beacon")

    def test_stamped_in_the_future(self):
        self.assert_missing(self.beacon("future.json", -2), "in the future")


class Age(Case):
    def test_live_within_the_default_day(self):
        r = self.row(owner_beacons=[self.beacon("a.json", 2)])
        self.assertEqual(r["status"], "live", r)
        self.assertIn("about two hours ago", r["reason"])
        self.assertEqual(catchup.DEFAULT_AFTER_H, 24.0)

    def test_a_small_clock_skew_reads_as_now(self):
        r = self.row(owner_beacons=[self.beacon("a.json", -0.01)])
        self.assertEqual(r["status"], "live", r)
        self.assertIn("under an hour ago", r["reason"])

    def test_stale_past_the_default_day(self):
        r = self.row(owner_beacons=[self.beacon("a.json", 30)])
        self.assertEqual(r["status"], "stale", r)
        self.assertIn("about a day ago", r["reason"])

    def test_catchup_after_h_sets_the_threshold(self):
        rel = self.beacon("a.json", 30)
        self.assertEqual(self.row(owner_beacons=[rel], catchup_after_h=48)["status"], "live")
        rel = self.beacon("a.json", 2)
        self.assertEqual(self.row(owner_beacons=[rel], catchup_after_h=1)["status"], "stale")
        for bad in (0, -5, "48", True, None):
            self.assertEqual(self.row(owner_beacons=[self.beacon("b.json", 30)], catchup_after_h=bad)["status"],
                             "stale", bad)

    def test_an_absolute_path_works(self):
        rel = self.beacon("a.json", 3)
        r = self.row(owner_beacons=[str(self.st / rel)])
        self.assertEqual((r["status"], "about three hours ago" in r["reason"]), ("live", True))

    def test_the_row_itself_holds_no_digit(self):
        for age in (0.5, 5, 30, 100, 400):
            self.direct(owner_beacons=[self.beacon("a.json", age)])
        self.direct(owner_beacons=["beacons/gone.json", self.beacon("b.json", 3)])


class Several(Case):
    def test_the_worst_beacon_sets_the_status_and_each_is_said(self):
        live, stale = self.beacon("a.json", 2), self.beacon("b.json", 50)
        r = self.row(owner_beacons=[live, stale])
        self.assertEqual(r["status"], "stale", r)
        self.assertIn("about two hours ago", r["reason"])
        self.assertIn("about two days ago", r["reason"])
        r = self.row(owner_beacons=[live, stale, "beacons/gone.json"])
        self.assertEqual(r["status"], "missing", r)
        self.assertIn("file missing", r["reason"])
        r = self.row(owner_beacons=[live, self.beacon("c.json", 4)])
        self.assertEqual(r["status"], "live", r)


class Docs(unittest.TestCase):
    def test_doctor_and_beacon_docs_name_the_row(self):
        for doc in ("doctor.md", "owner-beacon.md"):
            text = (ROOT / "docs" / doc).read_text()
            self.assertIn("owner beacon", text, doc)
            self.assertIn("catchup_after_h", text, doc)


if __name__ == "__main__":
    unittest.main()
