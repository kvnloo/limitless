"""The doctor's `rides source` row: whether the ONE rides file (config rides_file) is wired in, in words.

Synthetic rides files in a temp state dir only; made-up sources. No network, nothing written by the doctor.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import doctor  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

NOW = 1894708800.0   # 2030-01-15T12:00:00Z
NOT_CONFIGURED = "not configured: set rides_file to the rides export (a relative path is in the state dir)"


def ride(start, source, kind="ride", dur=600):
    return {"start": start, "duration_s": dur, "kind": kind, "source": source}


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.state = self.root / "state"
        self.state.mkdir()
        self.cfg_path = self.root / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg_path), "LIMITLESS_STATE": str(self.state)}
        p = mock.patch.dict(os.environ, {"TZ": "UTC"}, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def config(self, **cfg):
        cfg.setdefault("state", str(self.state))
        self.cfg_path.write_text(json.dumps(cfg))
        return cfg

    def rides(self, rows, name="rides.jsonl", where=None):
        p = (where or self.state) / name
        p.write_text("".join(json.dumps(r) + "\n" if isinstance(r, dict) else r + "\n" for r in rows))
        return p

    def row(self):
        return doctor.rides_source_row(StateReader(self.state), NOW, env=self.env, home=self.root)

    def check(self, r, status, reason):
        self.assertEqual((r["name"], r["kind"], r["status"], r["reason"]),
                         (doctor.RIDES_SOURCE_ROW, "source", status, reason))
        line = doctor.text([r])
        self.assertEqual(line, f"rides source: {status}: {reason}")
        self.assertNotRegex(line, r"\d")
        self.assertNotIn(str(self.root), line)
        self.assertNotIn("/", reason)


class Statuses(Case):
    def test_not_configured_names_the_key_and_the_relative_rule(self):
        self.config()
        self.check(self.row(), doctor.MISSING, NOT_CONFIGURED)
        self.config(rides_file="")
        self.check(self.row(), doctor.MISSING, NOT_CONFIGURED)
        self.config(rides_file=["not", "a", "path"])
        self.check(self.row(), doctor.MISSING, NOT_CONFIGURED)

    def test_no_config_file_at_all_is_not_configured(self):
        self.check(self.row(), doctor.MISSING, NOT_CONFIGURED)

    def test_file_missing(self):
        self.config(rides_file="rides.jsonl")
        self.check(self.row(), doctor.MISSING, "file missing")
        self.config(rides_file=str(self.root / "elsewhere" / "rides.jsonl"))
        self.check(self.row(), doctor.MISSING, "file missing")

    def test_unreadable(self):
        (self.state / "adir").mkdir()
        self.config(rides_file="adir")
        self.check(self.row(), doctor.MISSING, "unreadable")
        self.config(rides_file="bad\0name")
        self.check(self.row(), doctor.MISSING, "unreadable")
        p = self.rides([ride("2030-01-14T07:00:00Z", "carol-fit")])
        self.config(rides_file=p.name)
        with mock.patch("builtins.open", side_effect=PermissionError("denied")):
            self.check(self.row(), doctor.MISSING, "unreadable")

    def test_no_rides_yet_when_the_file_reads_but_holds_no_ride(self):
        self.config(rides_file="rides.jsonl")
        self.rides([])
        self.check(self.row(), doctor.MISSING, "no rides yet")
        self.rides(["{torn", ride("2030-01-14T07:00:00Z", "synthetic-phone", kind="walking"),
                    ride("2030-01-14T07:00:00", "carol-fit"),           # no offset: skipped
                    ride("2030-01-20T07:00:00Z", "carol-fit")])         # after today: skipped
        self.check(self.row(), doctor.MISSING, "no rides yet")

    def test_live_with_the_last_ride_and_both_sources(self):
        self.config(rides_file="rides.jsonl")
        self.rides([ride("2030-01-10T07:00:00+01:00", "synthetic-bike-app", kind="rehit"),
                    ride("2030-01-13T10:00:00Z", "carol-fit"),
                    ride("2030-01-12T18:00:00Z", "synthetic-bike-app", kind="biking_stationary")])
        self.check(self.row(), doctor.LIVE, "last ride about two days ago; sources: carol-fit, synthetic-bike-app")

    def test_the_age_is_the_newest_start_in_words(self):
        self.config(rides_file="rides.jsonl")
        self.rides([ride("2030-01-15T09:30:00Z", "carol-fit")])
        self.check(self.row(), doctor.LIVE, "last ride about two hours ago; sources: carol-fit")
        self.rides([ride("2030-01-15T11:40:00Z", "carol-fit")])
        self.check(self.row(), doctor.LIVE, "last ride under an hour ago; sources: carol-fit")
        self.rides([ride("2029-12-01T11:40:00Z", "carol-fit")])
        self.check(self.row(), doctor.LIVE, "last ride over a week ago; sources: carol-fit")

    def test_a_later_start_today_reads_as_under_an_hour(self):
        self.config(rides_file="rides.jsonl")
        self.rides([ride("2030-01-15T18:00:00Z", "carol-fit")])   # today, later than now: never a negative age
        self.check(self.row(), doctor.LIVE, "last ride under an hour ago; sources: carol-fit")


class Paths(Case):
    def test_a_relative_path_is_in_the_state_dir(self):
        self.rides([ride("2030-01-14T07:00:00Z", "carol-fit")], name="rides.jsonl")
        self.config(rides_file="rides.jsonl")
        self.check(self.row(), doctor.LIVE, "last ride about a day ago; sources: carol-fit")
        (self.state / "rides.jsonl").unlink()
        self.rides([ride("2030-01-14T07:00:00Z", "carol-fit")], name="rides.jsonl", where=self.root)
        self.check(self.row(), doctor.MISSING, "file missing")   # the copy beside the config is not in the state dir

    def test_an_absolute_path_is_used_as_it_is(self):
        other = self.root / "exports"
        other.mkdir()
        p = self.rides([ride("2030-01-14T07:00:00Z", "synthetic-bike-app", kind="rehit")], where=other)
        self.config(rides_file=str(p))
        self.check(self.row(), doctor.LIVE, "last ride about a day ago; sources: synthetic-bike-app")


class Sources(Case):
    def setUp(self):
        super().setUp()
        self.config(rides_file="rides.jsonl")

    def sources(self, names):
        self.rides([ride(f"2030-01-14T0{i}:00:00Z", n) for i, n in enumerate(names)])
        return self.row()["reason"].split("; sources: ", 1)[1]

    def test_a_carol_fit_row_and_an_exercise_row(self):
        self.rides([ride("2030-01-14T07:00:00Z", "carol-fit"),
                    ride("2030-01-13T07:00:00+01:00", "synthetic-health-export", kind="biking_stationary")])
        self.check(self.row(), doctor.LIVE, "last ride about a day ago; sources: carol-fit, synthetic-health-export")

    def test_sorted_and_said_once(self):
        self.assertEqual(self.sources(["zeta", "alpha", "zeta", "mid"]), "alpha, mid, zeta")

    def test_at_most_three_then_and_more(self):
        self.assertEqual(self.sources(["d-src", "c-src", "b-src", "a-src"]), "a-src, b-src, c-src and more")

    def test_a_source_with_a_digit_is_a_source(self):
        self.assertEqual(self.sources(["bike2", "carol-fit"]), "carol-fit, a source")
        self.assertEqual(self.sources(["bike2", "bike3"]), "a source")
        self.check(self.row(), doctor.LIVE, "last ride about a day ago; sources: a source")

    def test_a_source_that_looks_like_a_path_is_a_source(self):
        self.assertEqual(self.sources(["exports/bike", "carol-fit"]), "carol-fit, a source")

    def test_whitespace_in_a_source_stays_one_line(self):
        self.assertEqual(self.sources(["synthetic\nbike   app"]), "synthetic bike app")


class Report(Case):
    def test_right_after_the_glide_source_row_and_not_strict(self):
        cfg = self.config(rides_file="rides.jsonl")
        self.rides([ride("2030-01-14T07:00:00Z", "carol-fit")])
        with mock.patch.dict(os.environ, self.env):
            rows = doctor.report(cfg, NOW)
        names = [r["name"] for r in rows]
        self.assertEqual(names.count(doctor.RIDES_SOURCE_ROW), 1)
        at = names.index(doctor.RIDES_SOURCE_ROW)
        self.assertEqual(names[at - 1], doctor.GLIDE_SOURCE_ROW)
        self.assertEqual(names[at + 1], doctor.LOCAL_LABELER_ROW)
        self.assertEqual((rows[at]["status"], rows[at]["reason"]),
                         (doctor.LIVE, "last ride about a day ago; sources: carol-fit"))
        self.assertNotIn("source", doctor.STRICT_KINDS)
        self.assertNotRegex(doctor.text([rows[at]]), r"\d")

    def test_not_configured_in_the_report(self):
        cfg = self.config()
        with mock.patch.dict(os.environ, self.env):
            rows = doctor.report(cfg, NOW)
        r = next(r for r in rows if r["name"] == doctor.RIDES_SOURCE_ROW)
        self.assertEqual((r["status"], r["reason"]), (doctor.MISSING, NOT_CONFIGURED))

    def test_the_row_writes_nothing(self):
        self.config(rides_file="rides.jsonl")
        self.rides([ride("2030-01-14T07:00:00Z", "carol-fit")])
        before = sorted((str(p), p.stat().st_mtime_ns) for p in self.root.rglob("*"))
        self.row()
        self.assertEqual(sorted((str(p), p.stat().st_mtime_ns) for p in self.root.rglob("*")), before)


if __name__ == "__main__":
    unittest.main()
