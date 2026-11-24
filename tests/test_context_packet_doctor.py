"""limitless-doctor's `export context packet` row: off (no context_packet_path), live (written within STALE_H) or
stale (not written yet, older, or not a packet this plugin wrote). Words only. Synthetic fixtures only."""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import context_packet as cp, doctor  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "state"
NOW = 1894708800.0
TODAY = date(2030, 1, 15)
H = 3600.0


class Row(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.st = self.home / "state"
        shutil.copytree(FIX, self.st)

    def row(self, **cfg):
        r = doctor.context_packet_row(dict({"state": str(self.st)}, **cfg), NOW)
        self.assertEqual((r["name"], r["kind"]), (doctor.PACKET_ROW, "export"))
        self.assertEqual(re.findall(r"\d", r["reason"]), [])
        return r

    def written(self, at: float, name="context.json"):
        p = cp.packet(self.st, at, TODAY, env={"LIMITLESS_CONFIG": str(self.home / "absent.json")})
        cp.write(p, self.st / name)

    def test_off_by_default(self):
        r = self.row()
        self.assertEqual(r["status"], doctor.OFF)
        self.assertIn("context_packet_path", r["reason"])

    def test_set_but_not_written_yet_is_stale(self):
        r = self.row(context_packet_path="context.json")
        self.assertEqual(r["status"], doctor.STALE)
        self.assertIn("not written yet", r["reason"])
        self.assertIn("limitless-context-packet --write", r["reason"])

    def test_fresh_is_live(self):
        self.written(NOW - 3 * H)
        r = self.row(context_packet_path="context.json")
        self.assertEqual(r["status"], doctor.LIVE)
        self.assertEqual(r["reason"], "written about three hours ago")

    def test_absolute_path(self):
        self.written(NOW - 0.5 * H, name="sub/context.json")
        r = self.row(context_packet_path=str(self.st / "sub" / "context.json"))
        self.assertEqual(r["status"], doctor.LIVE)
        self.assertNotIn(str(self.home), r["reason"])   # never a path

    def test_older_than_stale_h_is_stale(self):
        self.written(NOW - 30 * H)
        r = self.row(context_packet_path="context.json")
        self.assertEqual(r["status"], doctor.STALE)
        self.assertIn("about a day ago", r["reason"])

    def test_not_a_packet_is_stale(self):
        for text in ("{not json", json.dumps({"schema": "other/9", "generated_at": "2030-01-15T11:00:00Z"}),
                     json.dumps({"schema": cp.SCHEMA}), json.dumps(["a"])):
            (self.st / "context.json").write_text(text)
            r = self.row(context_packet_path="context.json")
            self.assertEqual(r["status"], doctor.STALE, text)
            self.assertIn("not a context packet", r["reason"])

    def test_in_the_report_before_the_exports_and_read_only(self):
        self.written(NOW - H)
        cfg_file = self.home / "config.json"
        cfg = {"state": str(self.st), "context_packet_path": "context.json"}
        cfg_file.write_text(json.dumps(cfg))
        before = sorted((str(p), p.stat().st_mtime_ns, p.read_bytes()) for p in self.home.rglob("*") if p.is_file())
        old = {k: os.environ.get(k) for k in ("LIMITLESS_CONFIG", "LIMITLESS_STATE", "HOME")}
        os.environ.update(LIMITLESS_CONFIG=str(cfg_file), HOME=str(self.home))
        os.environ.pop("LIMITLESS_STATE", None)
        try:
            names = [r["name"] for r in doctor.report(cfg, NOW)]
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.assertEqual(names.count(doctor.PACKET_ROW), 1)
        at = names.index(doctor.PACKET_ROW)
        self.assertEqual(names[at + 1:at + 3], [doctor.SLEEP_COVERAGE_ROW, doctor.OW_ROW])
        after = sorted((str(p), p.stat().st_mtime_ns, p.read_bytes()) for p in self.home.rglob("*") if p.is_file())
        self.assertEqual(after, before)

    def test_strict_never_counts_it(self):
        self.assertNotIn("export", doctor.STRICT_KINDS)


if __name__ == "__main__":
    unittest.main()
