"""StateReader.body_rows: the body-composition file's rows (config ``body_file``), read-only.

Synthetic rows only. One row per measurement visit: {"day", "bf_pct", "method", "calibrated"}. No file
configured is no rows; a malformed row or a future day is skipped; nothing raises.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless.state_reader import BODY_CONFIG, StateReader  # noqa: E402

TODAY = date(2030, 1, 15)


def row(day, bf=20.0, method="synthetic-scale", calibrated=True, **kw):
    r = {"day": day, "bf_pct": bf, "method": method, "calibrated": calibrated}
    r.update(kw)
    return r


class BodyRows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.cfg = self.root / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg)}
        self.reader = StateReader(self.st)

    def configure(self, value="body.jsonl"):
        self.cfg.write_text(json.dumps({BODY_CONFIG: value}))

    def write(self, rows, name="body.jsonl"):
        (self.st / name).write_text("".join((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in rows))

    def rows(self):
        return self.reader.body_rows(self.env, self.root, today=TODAY)

    def test_the_config_key_is_body_file(self):
        self.assertEqual(BODY_CONFIG, "body_file")

    def test_no_file_configured_is_none_and_no_rows(self):
        self.assertIsNone(self.reader.body_file(self.env, self.root))
        self.write([row("2030-01-10")])
        self.assertEqual(self.rows(), [])

    def test_a_relative_path_is_in_the_state_dir(self):
        self.configure("sub/body.jsonl")
        self.assertEqual(self.reader.body_file(self.env, self.root), self.st / "sub" / "body.jsonl")

    def test_an_absolute_path_is_kept(self):
        p = self.root / "elsewhere.jsonl"
        self.configure(str(p))
        self.assertEqual(self.reader.body_file(self.env, self.root), p)

    def test_a_non_string_or_blank_value_is_not_configured(self):
        for v in (7, "", "  ", None, ["body.jsonl"]):
            self.configure(v)
            self.assertIsNone(self.reader.body_file(self.env, self.root), v)

    def test_valid_rows_come_back_oldest_first_in_the_documented_shape(self):
        self.configure()
        self.write([row("2030-01-12", 21.5, calibrated=False, extra="ignored"), row("2030-01-10", 22)])
        self.assertEqual(self.rows(), [
            {"day": "2030-01-10", "bf_pct": 22.0, "method": "synthetic-scale", "calibrated": True},
            {"day": "2030-01-12", "bf_pct": 21.5, "method": "synthetic-scale", "calibrated": False}])
        self.assertIsInstance(self.rows()[0]["bf_pct"], float)

    def test_two_visits_on_one_day_are_both_kept(self):
        self.configure()
        self.write([row("2030-01-10", 22.0), row("2030-01-10", 21.0)])
        self.assertEqual([r["bf_pct"] for r in self.rows()], [22.0, 21.0])

    def test_malformed_rows_are_skipped(self):
        self.configure()
        self.write([
            "not json", "[1, 2]", "",
            row("2030-02-30"), row("15/01/2030"), row(20300110), {"bf_pct": 20.0, "method": "m", "calibrated": True},
            row("2030-01-10", bf="20"), row("2030-01-10", bf=True), row("2030-01-10", bf=float("nan")),
            row("2030-01-10", bf=float("inf")), row("2030-01-10", bf=-1.0), row("2030-01-10", bf=0.0),
            row("2030-01-10", bf=101.0),
            row("2030-01-10", method=None), row("2030-01-10", method=""), row("2030-01-10", method=3),
            row("2030-01-10", calibrated="yes"), row("2030-01-10", calibrated=1), row("2030-01-10", calibrated=None),
            row("2030-01-11", 19.5)])
        self.assertEqual(self.rows(), [
            {"day": "2030-01-11", "bf_pct": 19.5, "method": "synthetic-scale", "calibrated": True}])

    def test_future_days_are_skipped_and_today_is_kept(self):
        self.configure()
        self.write([row("2030-01-16"), row("2031-01-01"), row("2030-01-15", 18.0)])
        self.assertEqual([r["day"] for r in self.rows()], ["2030-01-15"])

    def test_today_defaults_to_the_local_date(self):
        self.configure()
        self.write([row("2000-01-01"), row("9999-12-31")])
        self.assertEqual([r["day"] for r in self.reader.body_rows(self.env, self.root)], ["2000-01-01"])

    def test_a_missing_or_unreadable_file_is_no_rows(self):
        self.configure("absent.jsonl")
        self.assertEqual(self.rows(), [])
        self.configure("adir")
        (self.st / "adir").mkdir()
        self.assertEqual(self.rows(), [])

    def test_never_raises_on_odd_input(self):
        self.configure()
        (self.st / "body.jsonl").write_bytes(b"\xff\xfe\x00garbage\n{\"day\": \"2030-01-10\"}\n")
        self.assertEqual(self.rows(), [])
        self.cfg.write_text("{not json")
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.reader.body_rows(self.env, self.root, today="not a date"), [])

    def test_the_file_is_never_written(self):
        self.configure()
        self.write([row("2030-01-10")])
        p = self.st / "body.jsonl"
        before = (p.read_bytes(), p.stat().st_mtime_ns)
        self.rows()
        self.assertEqual((p.read_bytes(), p.stat().st_mtime_ns), before)
        self.assertEqual(sorted(x.name for x in self.st.iterdir()), ["body.jsonl"])


if __name__ == "__main__":
    unittest.main()
