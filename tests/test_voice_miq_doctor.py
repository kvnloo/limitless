"""limitless-doctor's voice MIQ row: off by config, missing without the call sessions dir, else live with the
mode and the last capture in words. Reads the mark voice-miq.json only; never reads a call. Synthetic only.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import doctor, voice_miq  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

NOW = 1894708800.0
H = 3600


class Row(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.st = Path(self.tmp.name) / "state"
        self.sessions = Path(self.tmp.name) / "sessions"
        self.st.mkdir()

    def row(self, **cfg):
        return doctor.voice_miq_row(StateReader(self.st), cfg, NOW)

    def check(self, r, status, *words):
        self.assertEqual((r["name"], r["kind"], r["status"]), (doctor.VOICE_MIQ_ROW, "job", status), r)
        for w in words:
            self.assertIn(w, r["reason"])
        self.assertNotRegex(r["reason"], r"\d")

    def test_off_by_default(self):
        self.check(self.row(), doctor.OFF, "off", "config voice_miq")
        self.check(self.row(voice_miq="maybe"), doctor.OFF, "off")

    def test_no_sessions_dir_is_missing(self):
        self.check(self.row(voice_miq="write"), doctor.MISSING, "not configured")
        self.check(self.row(voice_miq="write", voice_miq_sessions=str(self.sessions)), doctor.MISSING,
                   "does not exist")

    def test_on_never_captured(self):
        self.sessions.mkdir()
        self.check(self.row(voice_miq="dry_run", voice_miq_sessions=str(self.sessions)), doctor.LIVE,
                   "dry run", "no spoken MIQ answer captured yet")

    def test_on_last_capture_in_words(self):
        self.sessions.mkdir()
        (self.st / voice_miq.MARK).write_text(json.dumps({"miq_sent_at": NOW - 4 * H, "captured_at": NOW - 3 * H}))
        self.check(self.row(voice_miq="write", voice_miq_sessions=str(self.sessions)), doctor.LIVE,
                   "write mode", "last spoken MIQ answer captured about three hours ago")

    def test_in_the_report_before_the_exports_and_not_strict(self):
        cfg = {"state": str(self.st), "voice_miq": "write"}
        rows = doctor.report(cfg, NOW)
        names = [r["name"] for r in rows]
        self.assertEqual(names.count(doctor.VOICE_MIQ_ROW), 1)
        self.assertEqual(names[names.index(doctor.VOICE_MIQ_ROW) + 1], doctor.PACKET_ROW)
        self.assertNotIn("job", doctor.STRICT_KINDS)


if __name__ == "__main__":
    unittest.main()
