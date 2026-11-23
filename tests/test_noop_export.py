"""limitless/noop_export.py: wearable sleep summaries and pre-sleep heart rate from a NOOP app DB copy.

Synthetic DBs only (tests/noop_fixture.py: NOOP's public table and column names, made-up rows). UTC stands in
for the local zone. Nothing here sends.
"""
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from limitless import noop_export as nx  # noqa: E402
from noop_fixture import IMPORT, PHONE, RING, hr_before, make_db, stages  # noqa: E402

UTC = timezone.utc
H = 3600


def at(d, hh, mm=0):
    return int(datetime.combine(d, time(hh, mm), UTC).timestamp())


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.db = self.dir / "noop.db"


class ReadOnly(Base):
    def test_the_db_is_never_changed_and_nothing_is_created_beside_it(self):
        d = date(2030, 1, 10)
        on = at(d, 23)
        make_db(self.db, sessions=[(RING, on, on + 8 * H, 0.9, stages(on, 7 * H, H))], hr=hr_before(RING, on, 60))
        con = sqlite3.connect(str(self.db))
        con.execute("PRAGMA journal_mode=WAL")
        con.close()
        os.utime(self.db, (1_000_000_000, 1_000_000_000))
        before, mtime = self.db.read_bytes(), self.db.stat().st_mtime_ns
        got = nx.read(self.db, tz=UTC)
        self.assertIsNone(got["reason"])
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(self.db.stat().st_mtime_ns, mtime)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["noop.db"])

    def test_the_uri_is_read_only_and_immutable(self):
        uri = nx.uri(self.dir / "a b.db")
        self.assertTrue(uri.startswith("file:"))
        self.assertTrue(uri.endswith("?mode=ro&immutable=1"))
        self.assertIn("a%20b.db", uri)

    def test_a_missing_file_is_one_plain_reason(self):
        got = nx.read(self.dir / "absent.db", tz=UTC)
        self.assertEqual(got["reason"], nx.NO_FILE)
        self.assertEqual((got["sleep"], got["presleep"]), ([], []))
        self.assertFalse((self.dir / "absent.db").exists())

    def test_a_file_that_is_not_sqlite_is_one_plain_reason(self):
        self.db.write_text("not a database\n" * 20)
        self.assertEqual(nx.read(self.db, tz=UTC)["reason"], nx.NOT_NOOP)


class Schema(Base):
    def test_a_missing_table_is_named_and_nothing_is_read(self):
        for table in ("sleepSession", "hrSample", "pairedDevice"):
            with self.subTest(table=table):
                make_db(self.db, drop=table)
                got = nx.read(self.db, tz=UTC)
                self.assertEqual(got["reason"], f"{nx.SCHEMA_PREFIX}no table {table}")
                self.assertEqual((got["sleep"], got["presleep"]), ([], []))
                self.db.unlink()

    def test_a_missing_column_is_named(self):
        for table, col in (("sleepSession", "endTs"), ("sleepSession", "stagesJSON"),
                           ("pairedDevice", "sourceKind")):
            with self.subTest(column=col):
                make_db(self.db, drop_column=(table, col))
                self.assertEqual(nx.read(self.db, tz=UTC)["reason"], f"{nx.SCHEMA_PREFIX}no column {table}.{col}")
                self.db.unlink()

    def test_optional_parts_may_be_missing(self):
        d = date(2030, 1, 10)
        on = at(d, 23)
        make_db(self.db, sessions=[(RING, on, on + 8 * H, 0.9, stages(on, 7 * H, H))], drop="dismissedSleep")
        self.assertIsNone(nx.read(self.db, tz=UTC)["reason"])
        self.db.unlink()
        make_db(self.db, sessions=[(RING, on, on + 8 * H, 0.9, stages(on, 7 * H, H))],
                drop_column=("sleepSession", "startTsAdjusted"))
        self.assertIsNone(nx.read(self.db, tz=UTC)["reason"])


class Sleep(Base):
    D = date(2030, 1, 10)

    def sleep(self, sessions, **kw):
        make_db(self.db, sessions=sessions, **kw)
        got = nx.read(self.db, tz=UTC)
        self.assertIsNone(got["reason"])
        return got

    def test_one_row_per_night_named_by_the_evening_it_began(self):
        on = at(self.D, 23)
        late = at(self.D + timedelta(days=2), 1, 30)     # began after midnight: still the evening before's night
        got = self.sleep([(RING, on, on + 8 * H, 0.9, stages(on, 7 * H, H)),
                          (RING, late, late + 6 * H, 0.9, stages(late, 6 * H))])
        self.assertEqual(got["sleep"], [
            {"night": "2030-01-10", "asleep_s": 7 * H, "source": nx.SOURCE,
             "start": "2030-01-10T23:00:00Z", "end": "2030-01-11T07:00:00Z"},
            {"night": "2030-01-11", "asleep_s": 6 * H, "source": nx.SOURCE,
             "start": "2030-01-12T01:30:00Z", "end": "2030-01-12T07:30:00Z"}])

    def test_only_a_wearable_source_is_read(self):
        on = at(self.D, 23)
        got = self.sleep([(PHONE, on, on + 8 * H, 0.9, stages(on, 8 * H)),
                          (IMPORT, on + 60, on + 8 * H, 0.9, stages(on + 60, 7 * H))])
        self.assertEqual(got["sleep"], [])
        self.assertEqual(got["skipped"]["not_wearable"], 2)

    def test_a_strap_id_with_no_paired_row_is_still_the_wearable(self):
        # NOOP names strap ids in a "whoop-"/"oura-" namespace (WhoopSerialIdentity.ID_PREFIX), and the legacy
        # single-WHOOP seed is "my-whoop". A re-pair can orphan a strap's history from its pairedDevice row
        # (NOOP #1193), so with no row the id's own namespace says it is a strap; a paired row always wins.
        nights = [at(self.D + timedelta(days=i), 23) for i in range(5)]
        ids = ["whoop-SYNTH0001", "oura-SYNTH0002", "my-whoop", PHONE, "whoopish-0003"]
        got = self.sleep([(dev, on, on + 8 * H, 0.9, stages(on, 7 * H)) for dev, on in zip(ids, nights)])
        self.assertEqual([r["night"] for r in got["sleep"]], ["2030-01-10", "2030-01-11", "2030-01-12"])
        self.assertEqual(got["skipped"]["not_wearable"], 2)

    def test_a_paired_row_that_is_not_a_wearable_wins_over_the_id(self):
        on = at(self.D, 23)
        dev = {"id": "whoop-SYNTH0004", "brand": "Import", "model": "CSV", "nickname": None, "peripheralId": None,
               "sourceKind": "fileImport", "capabilities": "sleep", "status": "paired", "addedAt": 0, "lastSeenAt": 0}
        got = self.sleep([("whoop-SYNTH0004", on, on + 8 * H, 0.9, stages(on, 7 * H))], devices=[dev])
        self.assertEqual(got["sleep"], [])
        self.assertEqual(got["skipped"]["not_wearable"], 1)

    def test_the_longest_wearable_session_of_a_night_is_the_night(self):
        nap = at(self.D, 19)
        on = at(self.D, 23)
        got = self.sleep([(RING, nap, nap + H, 0.9, stages(nap, H)),
                          (RING, on, on + 8 * H, 0.9, stages(on, 7 * H, H))])
        self.assertEqual([(r["night"], r["asleep_s"]) for r in got["sleep"]], [("2030-01-10", 7 * H)])

    def test_asleep_time_comes_from_the_stages_else_the_efficiency_else_no_row(self):
        on = at(self.D, 23)
        on2, on3 = on + 86400, on + 2 * 86400
        got = self.sleep([(RING, on, on + 8 * H, 0.5, stages(on, 7 * H, H)),   # stages win over efficiency
                          (RING, on2, on2 + 8 * H, 0.75, None),
                          (RING, on3, on3 + 8 * H, None, None)])               # in bed is not asleep: no row
        self.assertEqual([(r["night"], r["asleep_s"]) for r in got["sleep"]],
                         [("2030-01-10", 7 * H), ("2030-01-11", 6 * H)])
        self.assertEqual(got["skipped"]["no_asleep_time"], 1)

    def test_imported_stage_shapes_are_read(self):
        on = at(self.D, 23)
        on2 = on + 86400
        got = self.sleep([(RING, on, on + 8 * H, None,
                           '[{"stage":"awake","min":60},{"stage":"light","min":240},{"stage":"deep","min":60},'
                           '{"stage":"rem","min":120}]'),
                          (RING, on2, on2 + 8 * H, None, '{"awake":30,"light":300,"deep":60,"rem":90}')])
        self.assertEqual([r["asleep_s"] for r in got["sleep"]], [7 * H, 7 * H + 30 * 60])

    def test_a_hand_set_onset_is_the_onset(self):
        on = at(self.D, 23)
        got = self.sleep([(RING, on, on + 8 * H, 0.9, stages(on, 7 * H, H), on + 30 * 60)])
        self.assertEqual(got["sleep"][0]["start"], "2030-01-10T23:30:00Z")

    def test_a_dismissed_or_impossible_session_is_skipped(self):
        on = at(self.D, 23)
        on2 = on + 86400
        on3 = on + 2 * 86400
        got = self.sleep([(RING, on, on + 8 * H, 0.9, stages(on, 7 * H, H)),
                          (RING, on2, on2 + 30 * H, 0.9, None),          # longer than a day: not a night
                          (RING, on3, on3, 0.9, None)],                  # no span
                         dismissed=[(RING, on, on + 8 * H)])
        self.assertEqual(got["sleep"], [])

    def test_a_bad_stages_text_falls_back_to_the_efficiency(self):
        on = at(self.D, 23)
        got = self.sleep([(RING, on, on + 8 * H, 0.75, "not json")])
        self.assertEqual(got["sleep"][0]["asleep_s"], 6 * H)

    def test_a_missing_hand_set_onset_column_reads_the_detected_onset(self):
        on = at(self.D, 23)
        got = self.sleep([(RING, on, on + 8 * H, 0.9, stages(on, 7 * H, H))],
                         drop_column=("sleepSession", "startTsAdjusted"))
        self.assertEqual(len(got["sleep"]), 1)


class PreSleepHr(Base):
    D = date(2030, 1, 10)

    def presleep(self, sessions, hr, **kw):
        make_db(self.db, sessions=sessions, hr=hr, **kw)
        got = nx.read(self.db, tz=UTC)
        self.assertIsNone(got["reason"])
        return got

    def night(self, on, hours=8):
        return (RING, on, on + hours * H, 0.9, stages(on, (hours - 1) * H, H))

    def test_the_mean_over_the_window_before_onset_is_the_nights_row(self):
        on = at(self.D, 23)
        hr = hr_before(RING, on, 60, n=15) + hr_before(RING, on - 15 * 60, 64, n=15)
        got = self.presleep([self.night(on)], hr)
        self.assertEqual(got["presleep"], [{"night": "2030-01-10", "bpm": 62.0, "modality": "measured"}])

    def test_the_window_is_anchored_on_each_nights_onset_never_a_clock_time(self):
        on1, on2 = at(self.D, 22), at(self.D + timedelta(days=1), 23, 45)
        hr = (hr_before(RING, on1, 58) + hr_before(RING, on2, 66)
              + [(RING, on1 + 60 * i, 90) for i in range(30)]                    # after onset: asleep, not read
              + [(RING, on1 - nx.WINDOW_S - 60 * (i + 1), 90) for i in range(30)])  # before the window
        got = self.presleep([self.night(on1), self.night(on2)], hr)
        self.assertEqual([(r["night"], r["bpm"]) for r in got["presleep"]],
                         [("2030-01-10", 58.0), ("2030-01-11", 66.0)])

    def test_a_hand_set_onset_moves_the_window(self):
        on = at(self.D, 23)
        moved = on + 3600
        hr = hr_before(RING, on, 60) + hr_before(RING, moved, 70)
        got = self.presleep([self.night(on) + (moved,)], hr)
        self.assertEqual(got["presleep"][0]["bpm"], 70.0)

    def test_too_few_samples_is_no_row_never_a_guess(self):
        on = at(self.D, 23)
        got = self.presleep([self.night(on)], hr_before(RING, on, 60, n=nx.MIN_SAMPLES - 1))
        self.assertEqual(got["presleep"], [])
        self.assertEqual(got["skipped"]["too_few_hr"], 1)
        self.assertEqual(len(got["sleep"]), 1)

    def test_only_the_sleeping_wearables_own_plausible_samples_count(self):
        on = at(self.D, 23)
        hr = (hr_before(RING, on, 60, n=nx.MIN_SAMPLES - 1)
              + hr_before(IMPORT, on, 60, n=30)                           # another source: never read
              + [(RING, on - 30 * 60 + 7, 0), (RING, on - 30 * 60 + 9, 300)])  # not heart rates
        got = self.presleep([self.night(on)], hr)
        self.assertEqual(got["presleep"], [])

    def test_no_wearable_night_is_no_presleep_row(self):
        on = at(self.D, 23)
        got = self.presleep([(PHONE, on, on + 8 * H, 0.9, None)], hr_before(PHONE, on, 60))
        self.assertEqual(got["presleep"], [])

    def test_the_bpm_is_rounded_to_a_tenth(self):
        on = at(self.D, 23)
        hr = hr_before(RING, on, 60, n=2) + hr_before(RING, on - 120, 61, n=1) + hr_before(RING, on - 180, 60, n=9)
        got = self.presleep([self.night(on)], hr)
        self.assertEqual(got["presleep"][0]["bpm"], round((60 * 11 + 61) / 12, 1))


if __name__ == "__main__":
    unittest.main()
