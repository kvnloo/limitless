"""StateReader.sleep_rows: wearable nightly sleep summaries from config sleep_file (JSONL, relative = state dir).

Synthetic rows only. Malformed, future and duplicate (same night and source) rows are dropped; never raises.
"""
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless.state_reader import SLEEP_CONFIG, StateReader  # noqa: E402

TODAY = date(2030, 1, 28)


def row(night="2030-01-27", asleep_s=25200, source="synthetic-ring"):
    return {"night": night, "asleep_s": asleep_s, "source": source}


class SleepRows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.cfg = self.root / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg)}
        self.reader = StateReader(self.st)

    def configure(self, value="sleep.jsonl"):
        self.cfg.write_text(json.dumps({SLEEP_CONFIG: value}))

    def write(self, rows, name="sleep.jsonl"):
        (self.st / name).write_text("".join((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in rows))

    def rows(self, today=TODAY):
        return self.reader.sleep_rows(today, self.env, self.root)

    def test_config_key_is_sleep_file(self):
        self.assertEqual(SLEEP_CONFIG, "sleep_file")

    def test_no_file_by_default(self):
        self.write([row()])
        self.assertIsNone(self.reader.sleep_file(self.env, self.root))
        self.assertEqual(self.rows(), [])

    def test_relative_is_in_the_state_dir_and_absolute_is_kept(self):
        self.configure()
        self.assertEqual(self.reader.sleep_file(self.env, self.root), self.st / "sleep.jsonl")
        other = self.root / "elsewhere.jsonl"
        self.configure(str(other))
        self.assertEqual(self.reader.sleep_file(self.env, self.root), other)
        for bad in ("", "   ", 7, None, ["sleep.jsonl"]):
            self.cfg.write_text(json.dumps({SLEEP_CONFIG: bad}))
            self.assertIsNone(self.reader.sleep_file(self.env, self.root), bad)

    def test_valid_rows_oldest_first_and_only_the_three_fields(self):
        self.configure()
        self.write([dict(row("2030-01-27", 25000), hrv=999), row("2030-01-25", 24000)])
        self.assertEqual(self.rows(), [row("2030-01-25", 24000), row("2030-01-27", 25000)])

    def test_malformed_rows_are_dropped(self):
        self.configure()
        self.write([
            "not json", "[1, 2]", "{}",
            row(night="2030-1-27"), row(night="2030-02-30"), row(night=None), row(night="2030-01-27T00:00:00"),
            row(asleep_s="25200"), row(asleep_s=True), row(asleep_s=25200.5), row(asleep_s=0), row(asleep_s=-5),
            row(asleep_s=24 * 3600 + 1), row(source=""), row(source="  "), row(source=None),
            row("2030-01-20", 20000),
        ])
        self.assertEqual(self.rows(), [row("2030-01-20", 20000)])

    def test_future_nights_are_dropped(self):
        self.configure()
        self.write([row("2030-01-29"), row("2031-01-01"), row("2030-01-28", 21000), row("2030-01-27")])
        self.assertEqual(self.rows(), [row("2030-01-27"), row("2030-01-28", 21000)])

    def test_duplicates_of_night_and_source_keep_the_first(self):
        self.configure()
        self.write([row(asleep_s=25000), row(asleep_s=26000), row(asleep_s=27000, source="synthetic-watch")])
        self.assertEqual(self.rows(), [row(asleep_s=25000), row(asleep_s=27000, source="synthetic-watch")])

    def test_never_raises(self):
        self.configure()
        self.assertEqual(self.rows(), [])                       # configured, missing
        (self.st / "sleep.jsonl").mkdir()
        self.assertEqual(self.rows(), [])                       # a directory
        self.configure("bin.jsonl")
        (self.st / "bin.jsonl").write_bytes(b"\xff\xfe\x00{")
        self.assertEqual(self.rows(), [])                       # junk bytes
        self.cfg.write_text("{not json")
        self.assertEqual(self.rows(), [])                       # broken config
        self.configure()
        self.assertEqual(self.reader.sleep_rows("2030-01-28", self.env, self.root), [])   # bad today

    def test_today_defaults_to_the_local_date(self):
        self.configure()
        self.write([row("2000-01-01"), row("2999-01-01")])
        self.assertEqual(self.reader.sleep_rows(env=self.env, home=self.root), [row("2000-01-01")])

    def test_reading_never_writes(self):
        self.configure()
        self.write([row()])
        p = self.st / "sleep.jsonl"
        before = (p.read_bytes(), p.stat().st_mtime_ns)
        self.rows()
        self.assertEqual((p.read_bytes(), p.stat().st_mtime_ns), before)
        self.assertEqual(sorted(x.name for x in self.st.iterdir()), ["sleep.jsonl"])


if __name__ == "__main__":
    unittest.main()
