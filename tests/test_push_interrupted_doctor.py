"""limitless-doctor's "push interrupted" row: kevin-push marks a sent.json row ``"unknown": true`` when a push was
killed between its reservation and its settle (bin/kevin-push, send_gate.PENDING_UNKNOWN_S). The row says so in
words: ``live: none`` with no such row in the last day, else ``missing: a push may have been cut off before it was
confirmed``. Never a digit, a title, a body or a dedupe key. Synthetic sent.json rows under a temp HOME only.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import doctor, send_gate  # noqa: E402

NOW = 1894708800.0  # 2030-01-15T12:00:00Z, the fixture clock
NONE = ("live", "none")
CUT_OFF = ("missing", "a push may have been cut off before it was confirmed")


class PushInterruptedRow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.st = self.home / "state"
        self.st.mkdir()
        self.push_dir = self.home / ".local/state/kevin-push"
        self.key = send_gate.key("Synthetic title words", "Synthetic body words")

    def write_sent(self, rows):
        self.push_dir.mkdir(parents=True, exist_ok=True)
        (self.push_dir / "sent.json").write_text(json.dumps(rows))

    def rows(self):
        cfg = {"state": str(self.st)}
        cfg_path = self.home / "config.json"
        cfg_path.write_text(json.dumps(cfg))
        env = {k: v for k, v in os.environ.items() if not k.startswith("LIMITLESS_")}
        env.update(HOME=str(self.home), LIMITLESS_CONFIG=str(cfg_path))
        # hermetic_env pins Path.home() to the shared test home: point it at this test's own temp HOME
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(Path, "home", classmethod(lambda cls: cls(self.home))):
            return doctor.report(cfg, NOW)

    def row(self):
        got = [r for r in self.rows() if r["name"] == "push interrupted"]
        self.assertEqual(len(got), 1)
        return got[0]

    def said(self):
        r = self.row()
        self.assertEqual(r["kind"], "source")
        return r["status"], r["reason"]

    def test_no_sent_json_is_none(self):
        self.assertEqual(self.said(), NONE)

    def test_delivered_and_pending_rows_are_none(self):
        self.write_sent([{"t": NOW - 3600, "k": self.key},
                         {"t": NOW - 30, "k": "synthetic01", "pending": "aaaa"},
                         {"t": NOW - 7200, "k": "synthetic02", "pending": "bbbb"}])
        self.assertEqual(self.said(), NONE)

    def test_an_unknown_row_in_the_last_day_is_named(self):
        self.write_sent([{"t": NOW - 3600, "k": "synthetic01"}, {"t": NOW - 7200, "k": self.key, "unknown": True}])
        self.assertEqual(self.said(), CUT_OFF)

    def test_an_unknown_row_older_than_a_day_is_none(self):
        self.write_sent([{"t": NOW - 86400 - 60, "k": self.key, "unknown": True}])
        self.assertEqual(self.said(), NONE)

    def test_the_line_has_no_digit_title_body_or_key(self):
        self.write_sent([{"t": NOW - 7200, "k": self.key, "once": "synthetic_event:1999990000", "unknown": True}])
        line = doctor.text([self.row()])
        self.assertEqual(line, "push interrupted: missing: a push may have been cut off before it was confirmed")
        self.assertIsNone(re.search(r"\d", line))
        for word in ("Synthetic", "title", "body", self.key, "synthetic_event"):
            self.assertNotIn(word, line)

    def test_the_row_comes_right_after_push_recovery(self):
        names = [r["name"] for r in self.rows()]
        self.assertEqual(names[names.index("push recovery") + 1], "push interrupted")


if __name__ == "__main__":
    unittest.main()
