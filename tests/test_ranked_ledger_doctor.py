"""The doctor's ranked ledger row: off with no path, live with row ten's words, broken when it cannot be read.

Synthetic ids only; never an id, evidence text or a digit in the row.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import doctor  # noqa: E402

NOW = 1894708800.0
A, B = "synthetic-item-a", "synthetic-item-b"
EVIDENCE = "synthetic-receipt-words"


class Row(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.ledger = self.root / "ranked.jsonl"
        p = mock.patch.dict(os.environ, {}, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def seed(self, *rows, tail=""):
        self.ledger.write_text("".join(json.dumps(r) + "\n" for r in rows) + tail)

    def row(self, env=None, **cfg):
        cfg.setdefault("state", str(self.st))
        r = doctor.ranked_ledger_row(cfg, env)
        self.assertEqual((r["name"], r["kind"]), (doctor.RANKED_ROW, "source"))
        text = json.dumps(r)
        for secret in (A, B, EVIDENCE, str(self.root)):
            self.assertNotIn(secret, text)
        self.assertNotRegex(doctor.words(r["reason"]), r"\d")
        self.assertNotRegex(r["reason"], r"\d")
        return r

    def test_off_with_no_path(self):
        r = self.row()
        self.assertEqual(r["status"], doctor.OFF)
        self.assertEqual(r["reason"], "no ranked ledger set (LIMITLESS_RANKED_LEDGER or config \"ranked_ledger\")")

    def test_live_with_row_ten_words(self):
        self.seed({"id": A, "status": "verified", "by": "agent", "evidence": EVIDENCE},
                  {"id": B, "status": "open", "by": "agent", "evidence": ""})
        r = self.row(ranked_ledger=str(self.ledger))
        self.assertEqual(r["status"], doctor.LIVE)
        self.assertEqual(r["reason"], "rows read: some of the ranked items verified or dropped by the owner")

    def test_the_env_path_and_a_relative_config_path(self):
        self.seed({"id": A, "status": "verified", "by": "agent", "evidence": EVIDENCE})
        self.assertEqual(self.row({"LIMITLESS_RANKED_LEDGER": str(self.ledger)})["status"], doctor.LIVE)
        (self.st / "ranked.jsonl").write_text(self.ledger.read_text())
        self.assertEqual(self.row(ranked_ledger="ranked.jsonl")["reason"],
                         "rows read: all of the ranked items verified or dropped by the owner")

    def test_live_says_when_lines_were_skipped(self):
        self.seed({"id": A, "status": "open", "by": "agent", "evidence": ""}, tail="{\"id\": torn\n")
        r = self.row(ranked_ledger=str(self.ledger))
        self.assertEqual(r["status"], doctor.LIVE)
        self.assertEqual(r["reason"], "rows read: none of the ranked items verified or dropped by the owner; "
                                      "some lines could not be read and were skipped")

    def test_broken_when_missing_unreadable_or_without_rows(self):
        cases = {"absent": "broken: the ranked ledger is missing or cannot be read",
                 "dir": "broken: the ranked ledger is missing or cannot be read",
                 "empty": "broken: the ranked ledger has no rows",
                 "junk": "broken: the ranked ledger has no rows"}
        (self.root / "dir").mkdir()
        (self.root / "empty").write_text("")
        (self.root / "junk").write_text("not json\n{\"id\": \"x\", \"status\": \"done\"}\n")
        for name, reason in cases.items():
            r = self.row(ranked_ledger=str(self.root / name))
            self.assertEqual((r["status"], r["reason"]), (doctor.MISSING, reason), name)

    def test_the_row_reads_only(self):
        self.seed({"id": A, "status": "open", "by": "agent", "evidence": ""})
        before = sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in self.root.rglob("*"))
        self.row(ranked_ledger=str(self.ledger))
        after = sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in self.root.rglob("*"))
        self.assertEqual(after, before)

    def test_the_report_has_it_after_the_apps_ingest_row_and_before_the_voice_miq_row(self):
        self.seed({"id": A, "status": "verified", "by": "agent", "evidence": EVIDENCE})
        rows = doctor.report({"state": str(self.st), "ranked_ledger": str(self.ledger)}, NOW)
        names = [r["name"] for r in rows]
        self.assertEqual(names.index(doctor.RANKED_ROW), names.index(doctor.APPS_INGEST_ROW) + 1)
        self.assertEqual(names.index(doctor.VOICE_MIQ_ROW), names.index(doctor.RANKED_ROW) + 1)
        self.assertEqual(rows[names.index(doctor.RANKED_ROW)]["status"], doctor.LIVE)
        for secret in (A, EVIDENCE):
            self.assertNotIn(secret, json.dumps(rows))


if __name__ == "__main__":
    unittest.main()
