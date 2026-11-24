"""StateReader.ride_rows: bike rides from an exercise-session export (config ``rides_file``), read-only.

Synthetic rows only. One row per exercise session: {"start": ISO-8601 with offset, "duration_s", "kind",
"source"}. Only kinds in config ``ride_kinds`` (default biking_stationary, rehit, ride) are kept. No file
configured is no rows; malformed rows, future starts and duplicates (same start and source) are skipped;
nothing raises.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless.state_reader import RIDE_KINDS, RIDE_KINDS_CONFIG, RIDES_CONFIG, StateReader  # noqa: E402

TODAY = date(2030, 1, 15)


def ride(start="2030-01-10T07:30:00+01:00", duration_s=600, kind="rehit", source="synthetic-bike-app", **kw):
    r = {"start": start, "duration_s": duration_s, "kind": kind, "source": source}
    r.update(kw)
    return r


class RideRows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.cfg = self.root / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg)}
        self.reader = StateReader(self.st)

    def configure(self, value="rides.jsonl", **extra):
        self.cfg.write_text(json.dumps(dict({RIDES_CONFIG: value}, **extra)))

    def write(self, rows, name="rides.jsonl"):
        (self.st / name).write_text("".join((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in rows))

    def rows(self, today=TODAY):
        return self.reader.ride_rows(today, self.env, self.root)

    def test_the_config_keys_and_default_kinds(self):
        self.assertEqual(RIDES_CONFIG, "rides_file")
        self.assertEqual(RIDE_KINDS_CONFIG, "ride_kinds")
        self.assertEqual(list(RIDE_KINDS), ["biking_stationary", "rehit", "ride"])

    def test_no_file_configured_is_none_and_no_rows(self):
        self.assertIsNone(self.reader.rides_file(self.env, self.root))
        self.write([ride()])
        self.assertEqual(self.rows(), [])

    def test_a_relative_path_is_in_the_state_dir_and_an_absolute_one_is_kept(self):
        self.configure("sub/rides.jsonl")
        self.assertEqual(self.reader.rides_file(self.env, self.root), self.st / "sub" / "rides.jsonl")
        p = self.root / "elsewhere.jsonl"
        self.configure(str(p))
        self.assertEqual(self.reader.rides_file(self.env, self.root), p)

    def test_a_non_string_or_blank_value_is_not_configured(self):
        for v in (7, "", "  ", None, ["rides.jsonl"]):
            self.configure(v)
            self.assertIsNone(self.reader.rides_file(self.env, self.root), v)

    def test_valid_rows_come_back_oldest_first_in_the_documented_shape(self):
        self.configure()
        self.write([ride("2030-01-12T18:00:00-05:00", 540.0, "biking_stationary", extra="ignored", avg_hr=999),
                    ride("2030-01-10T07:30:00Z", 600)])
        self.assertEqual(self.rows(), [
            {"start": "2030-01-10T07:30:00Z", "duration_s": 600, "kind": "rehit", "source": "synthetic-bike-app"},
            {"start": "2030-01-12T18:00:00-05:00", "duration_s": 540, "kind": "biking_stationary",
             "source": "synthetic-bike-app"}])
        self.assertIsInstance(self.rows()[1]["duration_s"], int)

    def test_only_ride_kinds_are_kept(self):
        self.configure()
        self.write([ride(kind="walking"), ride(kind="running"), ride(kind="REHIT"), ride(kind="biking_stationary")])
        self.assertEqual([r["kind"] for r in self.rows()], ["biking_stationary"])

    def test_the_kinds_come_from_config(self):
        self.configure(ride_kinds=["spin"])
        self.write([ride(kind="rehit"), ride("2030-01-11T07:00:00Z", kind="spin")])
        self.assertEqual([r["kind"] for r in self.rows()], ["spin"])

    def test_a_bad_kinds_value_is_the_default(self):
        for v in ("rehit", [], [7, ""], {"a": 1}, None):
            self.configure(ride_kinds=v)
            self.write([ride(kind="rehit"), ride("2030-01-11T07:00:00Z", kind="spin")])
            self.assertEqual([r["kind"] for r in self.rows()], ["rehit"], v)

    def test_malformed_rows_are_skipped(self):
        self.configure()
        self.write([
            "not json", "[1, 2]", "",
            ride(start="2030-01-10T07:30:00"),            # no offset
            ride(start="2030-01-10"), ride(start="yesterday"), ride(start=1894300000), ride(start=None),
            {"duration_s": 600, "kind": "rehit", "source": "s"},
            ride(duration_s="600"), ride(duration_s=True), ride(duration_s=0), ride(duration_s=-5),
            ride(duration_s=float("nan")), ride(duration_s=float("inf")), ride(duration_s=None),
            ride(kind=None), ride(kind=3), ride(source=""), ride(source="  "), ride(source=None), ride(source=4),
            ride("2030-01-11T06:00:00+00:00", 480)])
        self.assertEqual(self.rows(), [{"start": "2030-01-11T06:00:00+00:00", "duration_s": 480, "kind": "rehit",
                                        "source": "synthetic-bike-app"}])

    def test_future_starts_are_skipped_and_today_is_kept(self):
        self.configure()
        self.write([ride("2030-01-16T00:10:00+00:00"), ride("2031-01-01T08:00:00Z"),
                    ride("2030-01-15T21:00:00-08:00")])
        self.assertEqual([r["start"] for r in self.rows()], ["2030-01-15T21:00:00-08:00"])

    def test_today_defaults_to_the_local_date(self):
        self.configure()
        self.write([ride("2000-01-01T08:00:00Z"), ride("9999-12-31T08:00:00Z")])
        self.assertEqual([r["start"] for r in self.reader.ride_rows(env=self.env, home=self.root)],
                         ["2000-01-01T08:00:00Z"])

    def test_duplicates_are_kept_once_per_start_and_source(self):
        self.configure()
        self.write([ride("2030-01-10T07:30:00+01:00", 600), ride("2030-01-10T06:30:00Z", 610),   # same instant
                    ride("2030-01-10T07:30:00+01:00", 600, source="another-synthetic-app"),
                    ride("2030-01-10T07:30:00+01:00", 600, kind="biking_stationary")])
        got = self.rows()
        self.assertEqual([(r["source"], r["duration_s"]) for r in got],
                         [("synthetic-bike-app", 600), ("another-synthetic-app", 600)])

    def test_a_missing_or_unreadable_file_is_no_rows(self):
        self.configure("absent.jsonl")
        self.assertEqual(self.rows(), [])
        self.configure("adir")
        (self.st / "adir").mkdir()
        self.assertEqual(self.rows(), [])

    def test_never_raises_on_odd_input(self):
        self.configure()
        (self.st / "rides.jsonl").write_bytes(b"\xff\xfe\x00garbage\n{\"start\": \"2030-01-10T07:30:00Z\"}\n")
        self.assertEqual(self.rows(), [])
        self.cfg.write_text("{not json")
        self.assertEqual(self.rows(), [])
        self.configure()
        self.write([ride()])
        self.assertEqual(self.rows(today="not a date"), [])
        self.write([ride(start="9999-12-31T23:59:59-23:59"), ride(start="0001-01-01T00:00:00+23:59")])
        self.assertIsInstance(self.rows(), list)

    def test_the_file_is_never_written(self):
        self.configure()
        self.write([ride()])
        p = self.st / "rides.jsonl"
        before = (p.read_bytes(), p.stat().st_mtime_ns)
        self.rows()
        self.assertEqual((p.read_bytes(), p.stat().st_mtime_ns), before)
        self.assertEqual(sorted(x.name for x in self.st.iterdir()), ["rides.jsonl"])


if __name__ == "__main__":
    unittest.main()
