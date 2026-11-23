"""The Open Wearables reader drops demo rows (limitless/mock_guard.py): every session of a seed user (the user
record's ``first_name`` carries the seed generator's ``[SEED:`` mark) and any session whose source device matches
the cited demo id shapes or config ``mock_device_patterns``. Only demo rows is "no wearable data", recorded as a
failed run so the doctor never calls it live. All-real input reads exactly as before.

Synthetic JSON only; the http callable is injected, so nothing touches the network.
"""
import io
import json
import sys
import tempfile
import unittest
from datetime import date, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import doctor, mock_guard as mg, open_wearables as ow  # noqa: E402
from limitless.state_reader import StateReader, config  # noqa: E402

UTC = timezone.utc
KEY = "ow-SYNTHETIC-key-7f3a9c"
USER = "00000000-0000-4000-8000-0000000000aa"
BASE = "http://ow.example.invalid:8000"
TODAY = date(2030, 1, 8)
NOW = 1893456000.0


def session(start, end, asleep, **src):
    s = {"provider": "polar", "device_type": "watch"}
    s.update(src)
    return {"id": "00000000-0000-4000-8000-0000000000ff", "start_time": start, "end_time": end,
            "source": s, "sleep_duration_seconds": asleep, "stages": None, "is_nap": False}


REAL1 = session("2030-01-01T23:00:00Z", "2030-01-02T06:00:00Z", 24000)
REAL2 = session("2030-01-02T23:00:00Z", "2030-01-03T06:00:00Z", 23000)
DEMO1 = session("2030-01-03T23:00:00Z", "2030-01-04T06:00:00Z", 25000, device_id="demo-band-a")
DEMO2 = session("2030-01-04T23:00:00Z", "2030-01-05T06:00:00Z", 25000, device="sim-band-c")


def sleep_body(*sessions):
    return json.dumps({"data": list(sessions), "pagination": {"has_more": False}, "metadata": {}}).encode()


def user_body(first_name):
    return json.dumps({"id": USER, "created_at": "2030-01-01T00:00:00Z", "first_name": first_name}).encode()


class Server:
    """Answers the sleep list and the user record by path; records each URL."""

    def __init__(self, sessions, first_name="Synthetic", user_status=200):
        self.sessions, self.first_name, self.user_status, self.calls = sessions, first_name, user_status, []

    def __call__(self, url, headers, timeout):
        self.calls.append(url)
        assert headers[ow.HEADER] == KEY
        if "/events/sleep" in url:
            return 200, sleep_body(*self.sessions)
        if url.split("?")[0].endswith(f"/api/v1/users/{USER}"):
            return self.user_status, user_body(self.first_name) if self.user_status == 200 else b""
        return 404, b""


def fetch(http, **kw):
    return ow.fetch_sleep(BASE, KEY, date(2030, 1, 1), http=http, user=USER, until=TODAY, tz=UTC, **kw)


class Fetch(unittest.TestCase):
    def test_a_demo_source_device_id_is_dropped_and_counted(self):
        got = fetch(Server([REAL1, DEMO1]))
        self.assertIsNone(got["reason"])
        self.assertEqual([r["night"] for r in got["sleep"]], ["2030-01-01"])
        self.assertEqual(got["skipped"]["demo"], 1)

    def test_a_config_pattern_on_the_source_device_is_dropped(self):
        got = fetch(Server([REAL1, REAL2, DEMO2]), cfg={"mock_device_patterns": ["sim-*"]})
        self.assertEqual(len(got["sleep"]), 2)
        self.assertEqual(got["skipped"]["demo"], 1)
        self.assertEqual(len(fetch(Server([REAL1, REAL2, DEMO2]))["sleep"]), 3)   # without it: read as before

    def test_a_seed_user_is_only_demo_rows(self):
        got = fetch(Server([REAL1, REAL2], first_name="[SEED:42|active] Synthetic"))
        self.assertEqual((got["sleep"], got["reason"]), ([], mg.ONLY_DEMO))
        self.assertEqual(got["skipped"], {"demo": 2})

    def test_only_demo_devices_is_no_wearable_data(self):
        got = fetch(Server([DEMO1]))
        self.assertEqual((got["sleep"], got["reason"]), ([], mg.ONLY_DEMO))

    def test_all_real_reads_exactly_as_before(self):
        got = fetch(Server([REAL1, REAL2]))
        self.assertIsNone(got["reason"])
        self.assertEqual(len(got["sleep"]), 2)
        self.assertEqual(got["skipped"], {"nap": 0, "not_wearable": 0, "no_asleep_time": 0, "not_a_night": 0})

    def test_an_unreadable_user_record_never_fails_the_run(self):
        for status in (404, 500, 401):
            got = fetch(Server([REAL1], user_status=status))
            self.assertIsNone(got["reason"], status)
            self.assertEqual(len(got["sleep"]), 1)

        def broken(url, headers, timeout):
            if "/events/sleep" in url:
                return 200, sleep_body(REAL1)
            raise OSError("synthetic")
        self.assertEqual(len(fetch(broken)["sleep"]), 1)

    def test_no_sessions_never_asks_for_the_user(self):
        http = Server([])
        fetch(http)
        self.assertEqual(len(http.calls), 1)


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.state = self.home / "state"
        self.state.mkdir()
        self.sleep = self.state / "sleep.jsonl"

    def run_cli(self, http, args=(), **cfg):
        c = {"state": str(self.state), "sleep_file": "sleep.jsonl", "open_wearables_export": "write",
             "open_wearables_url": BASE, "open_wearables_user": USER}
        c.update(cfg)
        (self.home / "config.json").write_text(json.dumps(c))
        env = {"LIMITLESS_CONFIG": str(self.home / "config.json"), ow.KEY_ENV: KEY}
        out, err = io.StringIO(), io.StringIO()
        code = ow.main(list(args), env=env, home=self.home, tz=UTC, out=out, err=err, http=http, today=TODAY,
                       now=NOW)
        self.env = env
        return code, out.getvalue(), err.getvalue()

    def doc_row(self):
        return doctor.open_wearables_row(StateReader(self.state), config(self.env, self.home), NOW + 60)

    def test_mixed_says_demo_rows_were_left_out_in_the_output_and_the_doctor_row(self):
        code, out, _ = self.run_cli(Server([REAL1, DEMO1]), ["--write"])
        self.assertEqual(code, 0)
        self.assertIn("some demo rows were left out (one session from a demo or sample device)", out)
        self.assertNotRegex(out, r"\d")
        r = self.doc_row()
        self.assertEqual(r["status"], "live")
        self.assertIn(mg.LEFT_OUT, r["reason"])
        self.assertNotRegex(r["reason"], r"\d")
        self.assertEqual(len(self.sleep.read_text().splitlines()), 1)

    def test_a_dry_run_writes_nothing(self):
        code, out, _ = self.run_cli(Server([REAL1, DEMO1]))
        self.assertEqual(code, 0)
        self.assertIn(mg.LEFT_OUT, out)
        self.assertFalse(self.sleep.exists())

    def test_a_seed_user_writes_nothing_and_the_doctor_row_is_never_live(self):
        code, out, err = self.run_cli(Server([REAL1, REAL2], first_name="[SEED:1|x] Synthetic"), ["--write"])
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(err.strip(), mg.ONLY_DEMO)
        self.assertFalse(self.sleep.exists())
        r = self.doc_row()
        self.assertEqual(r["status"], "stale")
        self.assertIn("no wearable data", r["reason"])
        self.assertNotRegex(r["reason"], r"\d")

    def test_the_config_pattern_comes_from_config_json(self):
        code, _, err = self.run_cli(Server([DEMO2]), ["--write"], mock_device_patterns=["sim-*"])
        self.assertEqual((code, err.strip()), (1, mg.ONLY_DEMO))


if __name__ == "__main__":
    unittest.main()
