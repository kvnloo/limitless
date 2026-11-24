"""limitless/fit_ride.py and bin/limitless-import-fit over SYNTHETIC FIT files.

Every file here is built in the test by the tiny writer below from made-up values (a synthetic ride on a
synthetic date); no real ride file, person or device is involved.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import fit_ride  # noqa: E402
from limitless.state_reader import RIDE_KINDS, StateReader  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "limitless-import-fit"
FIT_EPOCH = 631065600  # 1989-12-31T00:00:00Z in Unix seconds

# --- a tiny synthetic FIT writer ----------------------------------------------------------------------------

_TABLE = (0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
          0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400)
ENUM, UINT8, UINT16, UINT32 = 0x00, 0x02, 0x84, 0x86
_FMT = {ENUM: "B", UINT8: "B", UINT16: "H", UINT32: "I"}


def crc16(data: bytes) -> int:
    crc = 0
    for b in data:
        for nib in (b & 0xF, b >> 4):
            tmp = _TABLE[crc & 0xF]
            crc = (crc >> 4) & 0x0FFF
            crc = crc ^ tmp ^ _TABLE[nib]
    return crc


def fit_time(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()) - FIT_EPOCH


class FitWriter:
    """Definition and data records into one FIT file. Synthetic test helper, not a general encoder."""

    def __init__(self):
        self.body = bytearray()
        self.defs = {}

    def define(self, local, global_num, fields, big=False, dev_fields=()):
        hdr = 0x40 | local | (0x20 if dev_fields else 0)
        e = ">" if big else "<"
        rec = bytes([hdr, 0, 1 if big else 0]) + struct.pack(e + "H", global_num) + bytes([len(fields)])
        for num, base in fields:
            rec += bytes([num, struct.calcsize(_FMT[base]), base])
        if dev_fields:
            rec += bytes([len(dev_fields)])
            for num, size, index in dev_fields:
                rec += bytes([num, size, index])
        self.body += rec
        self.defs[local] = (e, fields, sum(size for _, size, _ in dev_fields))
        return self

    def data(self, local, values, compressed_offset=None, dev=None):
        e, fields, dev_size = self.defs[local]
        hdr = bytes([0x80 | (local << 5) | compressed_offset]) if compressed_offset is not None else bytes([local])
        rec = hdr + b"".join(struct.pack(e + _FMT[base], values[num]) for num, base in fields)
        rec += dev if dev is not None else b"\xab" * dev_size
        self.body += rec
        return self

    def build(self, header_size=14, bad_header_crc=False, bad_crc=False):
        hdr = bytes([header_size, 0x20]) + struct.pack("<HI", 2100, len(self.body)) + b".FIT"
        if header_size == 14:
            c = crc16(hdr)
            hdr += struct.pack("<H", c ^ 0x5A5A if bad_header_crc else c)
        out = hdr + bytes(self.body)
        c = crc16(out)
        return out + struct.pack("<H", c ^ 0x0F0F if bad_crc else c)


SESSION_FIELDS = [(253, UINT32), (2, UINT32), (7, UINT32), (8, UINT32), (5, ENUM), (0, ENUM)]
ACTIVITY_FIELDS = [(253, UINT32), (5, UINT32), (1, UINT16)]
START = "2030-01-12T23:00:00Z"   # synthetic


def session(start=START, elapsed_ms=540250, timer_ms=530000, sport=2):
    s = fit_time(start)
    return {253: s + 540, 2: s, 7: elapsed_ms, 8: timer_ms, 5: sport, 0: 8}


def ride_file(start=START, elapsed_ms=540250, timer_ms=530000, sport=2, offset_s=None, big=False,
              header_size=14, bad_header_crc=False, bad_crc=False, with_session=True):
    w = FitWriter()
    w.define(0, 0, [(0, ENUM), (4, UINT32)]).data(0, {0: 4, 4: fit_time(start)})              # file_id
    w.define(1, 20, [(253, UINT32), (7, UINT16), (3, UINT8)])                                    # record
    for i in range(3):
        w.data(1, {253: fit_time(start) + i, 7: 150 + i, 3: 120 + i})                           # synthetic samples
    if with_session:
        w.define(2, 18, SESSION_FIELDS, big=big).data(2, session(start, elapsed_ms, timer_ms, sport))
    if offset_s is not None:
        end = fit_time(start) + 540
        w.define(3, 34, ACTIVITY_FIELDS).data(3, {253: end, 5: end + offset_s, 1: 1})
    return w.build(header_size=header_size, bad_header_crc=bad_header_crc, bad_crc=bad_crc)


ROW = {"start": START, "duration_s": 540, "kind": "ride", "source": "carol-fit"}


class Reader(unittest.TestCase):
    def test_crc_matches_the_fit_check_value(self):
        # a FIT file's CRC over itself plus its stored CRC is zero
        self.assertEqual(crc16(ride_file()), 0)
        self.assertEqual(fit_ride.crc16(b"123456789"), crc16(b"123456789"))

    def test_happy_path_cycling_session(self):
        self.assertEqual(fit_ride.read(ride_file()), ROW)

    def test_twelve_byte_header_has_no_header_crc(self):
        self.assertEqual(fit_ride.read(ride_file(header_size=12)), ROW)

    def test_timer_time_when_elapsed_is_invalid(self):
        self.assertEqual(fit_ride.read(ride_file(elapsed_ms=0xFFFFFFFF))["duration_s"], 530)

    def test_big_endian_definition(self):
        self.assertEqual(fit_ride.read(ride_file(big=True)), ROW)

    def test_compressed_timestamp_header(self):
        s = fit_time(START)
        w = FitWriter()
        w.define(0, 0, [(0, ENUM)]).data(0, {0: 4})
        w.define(1, 20, [(253, UINT32), (7, UINT16)]).data(1, {253: s + 540, 7: 150})
        sess = [(2, UINT32), (7, UINT32), (8, UINT32), (5, ENUM)]
        w.define(2, 18, sess).data(2, {2: s, 7: 540250, 8: 530000, 5: 2}, compressed_offset=(s + 541) & 0x1F)
        # activity: a compressed timestamp past a roll-over of the five-bit offset; local time one hour ahead
        act_ts = s + 541 + 19
        w.define(3, 34, [(5, UINT32), (1, UINT16)])
        w.data(3, {5: act_ts + 3600, 1: 1}, compressed_offset=act_ts & 0x1F)
        self.assertEqual(fit_ride.read(w.build()), dict(ROW, start="2030-01-13T00:00:00+01:00"))

    def test_bad_header_crc(self):
        self.assertEqual(fit_ride.read(ride_file(bad_header_crc=True)), fit_ride.BAD_HEADER_CRC)

    def test_bad_file_crc(self):
        self.assertEqual(fit_ride.read(ride_file(bad_crc=True)), fit_ride.BAD_CRC)

    def test_truncated_file(self):
        data = ride_file()
        for cut in (len(data) - 1, len(data) // 2, 15):
            self.assertEqual(fit_ride.read(data[:cut]), fit_ride.TRUNCATED, cut)

    def test_not_fit(self):
        for data in (b"", b"hello", b"x" * 40, b'{"start": "2030-01-12"}' * 3, None, "text"):
            self.assertEqual(fit_ride.read(data), fit_ride.NOT_FIT, data)

    def test_non_cycling_sport(self):
        self.assertEqual(fit_ride.read(ride_file(sport=1)), fit_ride.NOT_CYCLING)   # running

    def test_no_session_message(self):
        self.assertEqual(fit_ride.read(ride_file(with_session=False)), fit_ride.NO_SESSION)

    def test_zero_duration(self):
        self.assertEqual(fit_ride.read(ride_file(elapsed_ms=0, timer_ms=0)), fit_ride.ZERO_DURATION)
        self.assertEqual(fit_ride.read(ride_file(elapsed_ms=0xFFFFFFFF, timer_ms=0xFFFFFFFF)),
                         fit_ride.ZERO_DURATION)

    def test_developer_fields_are_skipped_by_size(self):
        s = fit_time(START)
        w = FitWriter()
        w.define(0, 0, [(0, ENUM)]).data(0, {0: 4})
        w.define(1, 18, SESSION_FIELDS, dev_fields=[(0, 3, 0), (1, 5, 0)])
        w.data(1, session(), dev=b"\x02" * 8)   # synthetic developer bytes
        w.define(2, 20, [(253, UINT32)], dev_fields=[(0, 2, 0)]).data(2, {253: s + 600}, dev=b"\xff\xff")
        self.assertEqual(fit_ride.read(w.build()), ROW)

    def test_local_timestamp_gives_the_offset(self):
        row = fit_ride.read(ride_file(offset_s=-5 * 3600))
        self.assertEqual(row, dict(ROW, start="2030-01-12T18:00:00-05:00"))
        self.assertEqual(datetime.fromisoformat(row["start"]).timestamp(), fit_time(START) + FIT_EPOCH)

    def test_offset_rounds_to_a_quarter_hour_and_a_huge_one_stays_utc(self):
        self.assertEqual(fit_ride.read(ride_file(offset_s=3600 + 7))["start"], "2030-01-13T00:00:00+01:00")
        self.assertEqual(fit_ride.read(ride_file(offset_s=20 * 3600))["start"], START)

    def test_reasons_are_words(self):
        for why in fit_ride.REASONS:
            self.assertIsInstance(why, str)
            self.assertIsNone(re.search(r"\d", why), why)

    def test_never_raises_on_bad_bytes(self):
        good = ride_file()
        for i in range(len(good)):
            bad = bytearray(good)
            bad[i] ^= 0xFF
            out = fit_ride.read(bytes(bad))
            self.assertTrue(isinstance(out, (dict, str)), i)
        # a valid CRC around garbage records: still a reason, not a traceback
        w = FitWriter()
        w.body += b"\x05\x41\x00" + b"\x7f" * 30
        self.assertIn(fit_ride.read(w.build()), fit_ride.REASONS)

    def test_read_path(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "synthetic.fit"
            p.write_bytes(ride_file())
            self.assertEqual(fit_ride.read_path(p), ROW)
            self.assertEqual(fit_ride.read_path(Path(d) / "missing.fit"), fit_ride.UNREADABLE)

    def test_ride_kind_is_counted_by_default(self):
        self.assertIn(fit_ride.KIND, RIDE_KINDS)


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.state = self.home / "state"
        self.state.mkdir()
        self.rides = self.state / "rides.jsonl"
        self.cfg = self.home / "config.json"
        self.cfg.write_text(json.dumps({"rides_file": "rides.jsonl"}))
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("LIMITLESS_")}
        self.env.update(HOME=str(self.home), LIMITLESS_STATE=str(self.state), LIMITLESS_CONFIG=str(self.cfg))
        self.fit = self.home / "ride.fit"
        self.fit.write_bytes(ride_file(offset_s=-5 * 3600))

    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-I", str(CLI), *args], env=child_env(self.env), cwd=self.home,
                              capture_output=True, text=True, timeout=30)

    def ride_rows(self):
        return StateReader(self.state).ride_rows(today=date(2030, 2, 1), env=self.env, home=self.home)

    def test_usage_errors_exit_two(self):
        self.assertEqual(self.run_cli().returncode, 2)
        self.assertEqual(self.run_cli("--bogus", str(self.fit)).returncode, 2)

    def test_dry_run_writes_nothing(self):
        prior = json.dumps({"start": "2030-01-05T07:00:00+01:00", "duration_s": 600, "kind": "rehit",
                            "source": "synthetic-bike-app"}) + "\n"
        self.rides.write_text(prior)
        before = self.rides.read_bytes()
        r = self.run_cli(str(self.fit))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "ride.fit: would add one ride\nwould add one ride\n")
        self.assertEqual(self.rides.read_bytes(), before)

    def test_dry_run_without_a_rides_file_creates_nothing(self):
        r = self.run_cli(str(self.fit))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.rides.exists())

    def test_write_appends_one_row_that_ride_rows_returns(self):
        self.assertEqual(self.ride_rows(), [])
        r = self.run_cli("--write", str(self.fit))
        self.assertEqual((r.returncode, r.stdout), (0, "ride.fit: added one ride\nadded one ride\n"), r.stderr)
        lines = self.rides.read_text().splitlines()
        self.assertEqual(len(lines), 1)
        row = {"start": "2030-01-12T18:00:00-05:00", "duration_s": 540, "kind": "ride", "source": "carol-fit"}
        self.assertEqual(json.loads(lines[0]), row)
        self.assertEqual(self.ride_rows(), [row])
        self.assertEqual(self.rides.stat().st_mode & 0o777, 0o600)

    def test_second_import_is_deduped(self):
        self.run_cli("--write", str(self.fit))
        before = self.rides.read_bytes()
        # the same instant written in UTC is the same ride
        utc = self.home / "same-ride-utc.fit"
        utc.write_bytes(ride_file())
        r = self.run_cli("--write", str(self.fit), str(utc))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "ride.fit: already in the rides file\n"
                                   "same-ride-utc.fit: already in the rides file\nadded no rides\n")
        self.assertEqual(self.rides.read_bytes(), before)

    def test_same_ride_twice_in_one_run_adds_one(self):
        r = self.run_cli("--write", str(self.fit), str(self.fit))
        self.assertEqual(r.stdout.splitlines()[-1], "added one ride", r.stderr)
        self.assertEqual(len(self.rides.read_text().splitlines()), 1)

    def test_append_only_keeps_existing_bytes(self):
        self.rides.write_text('{"not": "a ride"}\n{"torn"')
        before = self.rides.read_bytes()
        other = self.home / "other.fit"
        other.write_bytes(ride_file(start="2030-01-10T23:00:00Z"))
        r = self.run_cli("--write", str(self.fit), str(other))
        self.assertEqual(r.stdout.splitlines()[-1], "added two rides", r.stderr)
        self.assertTrue(self.rides.read_bytes().startswith(before))
        self.assertEqual(len(self.ride_rows()), 2)

    def test_reasons_in_words_without_digits(self):
        junk = self.home / "notes.fit"
        junk.write_bytes(b"not a fit file at all")
        run = self.home / "run.fit"
        run.write_bytes(ride_file(sport=1))
        missing = self.home / "gone.fit"
        r = self.run_cli(str(junk), str(run), str(missing))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, f"notes.fit: {fit_ride.NOT_FIT}\nrun.fit: {fit_ride.NOT_CYCLING}\n"
                                   f"gone.fit: {fit_ride.UNREADABLE}\nwould add no rides\n")
        self.assertIsNone(re.search(r"\d", r.stdout))

    def test_write_without_a_configured_rides_file_fails_plainly(self):
        self.cfg.write_text("{}")
        r = self.run_cli("--write", str(self.fit))
        self.assertEqual(r.returncode, 1)
        self.assertIn("no rides file set", r.stdout)
        self.assertEqual(sorted(p.name for p in self.state.iterdir()), [])

    def test_json_has_the_numbers(self):
        r = self.run_cli("--json", str(self.fit))
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["written"], False)
        self.assertEqual(out["added"], 1)
        self.assertEqual(out["files"][0]["row"]["duration_s"], 540)
        self.assertEqual(out["files"][0]["status"], "new")
        self.assertFalse(self.rides.exists())


if __name__ == "__main__":
    unittest.main()
