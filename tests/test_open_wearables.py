"""limitless/open_wearables.py: fetch_sleep reads an Open Wearables server's sleep sessions through an injected http
callable and maps them to the sleep_file row shape noop_export writes, with source "open_wearables".

Synthetic JSON only (tests/fixtures/open_wearables). No test touches the network. UTC stands in for the local zone.
"""
import json
import sys
import unittest
from datetime import date, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import noop_export as nx  # noqa: E402
from limitless import open_wearables as ow  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "open_wearables"
UTC = timezone.utc
KEY = "ow-SYNTHETIC-key-7f3a9c"          # a made-up key: it must never surface anywhere
USER = "00000000-0000-4000-8000-0000000000aa"
BASE = "http://ow.example.invalid:8000"


def page(name):
    return (FIX / name).read_bytes()


class Fake:
    """An http callable: answers from a list of (status, body) or exceptions, and records each call."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, url, headers, timeout):
        self.calls.append({"url": url, "headers": dict(headers), "timeout": timeout})
        got = self.answers.pop(0)
        if isinstance(got, BaseException):
            raise got
        return got


def fetch(http, since=date(2030, 1, 1), until=date(2030, 1, 8), **kw):
    return ow.fetch_sleep(BASE, KEY, since, http=http, user=USER, until=until, tz=UTC, **kw)


class Mapping(unittest.TestCase):
    def setUp(self):
        self.http = Fake((200, page("sleep_page1.json")), (200, page("sleep_page2.json")))
        self.got = fetch(self.http)

    def test_rows_have_the_noop_sleep_shape_and_the_open_wearables_source(self):
        self.assertIsNone(self.got["reason"])
        self.assertEqual(self.got["sleep"], [
            {"night": "2030-01-01", "asleep_s": 25200, "source": "open_wearables",
             "start": "2030-01-01T23:00:00Z", "end": "2030-01-02T07:00:00Z"},
            {"night": "2030-01-02", "asleep_s": 23400, "source": "open_wearables",
             "start": "2030-01-03T01:30:00Z", "end": "2030-01-03T08:30:00Z"},
            {"night": "2030-01-06", "asleep_s": 26400, "source": "open_wearables",
             "start": "2030-01-06T22:30:00Z", "end": "2030-01-07T06:30:00Z"},
        ])
        for r in self.got["sleep"]:
            self.assertEqual(set(r), set(nx.sleep_row({"night": "x", "asleep_s": 1, "onset": 0, "end": 1})))

    def test_naps_phones_and_sessions_with_no_asleep_time_are_skipped_and_counted(self):
        self.assertEqual(self.got["skipped"], {"nap": 1, "not_wearable": 1, "no_asleep_time": 1, "not_a_night": 0})

    def test_the_documented_endpoint_header_and_pagination(self):
        first, second = self.http.calls
        u = urlsplit(first["url"])
        self.assertEqual(f"{u.scheme}://{u.netloc}{u.path}", f"{BASE}/api/v1/users/{USER}/events/sleep")
        q = parse_qs(u.query)
        self.assertEqual(q["start_date"], ["2030-01-01"])
        self.assertEqual(q["end_date"], ["2030-01-08"])
        self.assertNotIn("cursor", q)
        self.assertEqual(first["headers"]["X-Open-Wearables-API-Key"], KEY)
        self.assertNotIn("Authorization", first["headers"])
        self.assertEqual(parse_qs(urlsplit(second["url"]).query)["cursor"], ["c2ludGhldGljLXBhZ2UtdHdv"])
        self.assertGreater(first["timeout"], 0)

    def test_a_base_url_that_already_names_the_api_version_is_not_doubled(self):
        http = Fake((200, page("sleep_page2.json")))
        ow.fetch_sleep(BASE + "/api/v1/", KEY, date(2030, 1, 1), http=http, user=USER, until=date(2030, 1, 8))
        self.assertTrue(http.calls[0]["url"].startswith(f"{BASE}/api/v1/users/{USER}/events/sleep?"))


def session(start, end, asleep=None, **kw):
    s = {"id": "00000000-0000-4000-8000-0000000000ff", "start_time": start, "end_time": end,
         "source": {"provider": "polar", "device_type": "watch"}, "duration_seconds": 0,
         "sleep_duration_seconds": asleep, "stages": None, "is_nap": False, "is_final": True}
    s.update(kw)
    return s


def body(*sessions, more=False, cursor=None):
    return json.dumps({"data": list(sessions), "pagination": {"has_more": more, "next_cursor": cursor},
                       "metadata": {}}).encode()


class PerNight(unittest.TestCase):
    def test_the_session_with_the_most_sleep_stands_for_the_night(self):
        got = fetch(Fake((200, body(session("2030-01-01T20:00:00Z", "2030-01-01T21:00:00Z", 3000),
                                    session("2030-01-01T23:00:00Z", "2030-01-02T06:00:00Z", 24000)))))
        self.assertEqual([(r["night"], r["asleep_s"]) for r in got["sleep"]], [("2030-01-01", 24000)])

    def test_not_a_night_when_the_span_or_the_sleep_is_impossible(self):
        got = fetch(Fake((200, body(session("2030-01-02T07:00:00Z", "2030-01-01T23:00:00Z", 3000),
                                    session("2030-01-01T23:00:00Z", "2030-01-03T23:30:00Z", 3000),
                                    session("2030-01-01T23:00:00Z", "2030-01-02T06:00:00Z", 0),
                                    session("not a time", "2030-01-02T06:00:00Z", 3000)))))
        self.assertEqual(got["sleep"], [])
        self.assertEqual(got["skipped"]["not_a_night"], 4)

    def test_time_in_bed_is_never_taken_as_sleep(self):
        got = fetch(Fake((200, body(session("2030-01-01T23:00:00Z", "2030-01-02T06:00:00Z", None,
                                            time_in_bed_seconds=25200, duration_seconds=25200,
                                            efficiency_percent=90.0)))))
        self.assertEqual(got["sleep"], [])
        self.assertEqual(got["skipped"]["no_asleep_time"], 1)

    def test_the_night_follows_the_local_zone(self):
        plus9 = timezone(timedelta(hours=9))
        one = body(session("2030-01-02T05:00:00Z", "2030-01-02T07:00:00Z", 6000))
        got = ow.fetch_sleep(BASE, KEY, date(2030, 1, 1), http=Fake((200, one)), user=USER,
                             until=date(2030, 1, 8), tz=plus9)
        self.assertEqual(got["sleep"][0]["night"], "2030-01-02")   # 14:00 local: that date's evening half
        got = fetch(Fake((200, one)))
        self.assertEqual(got["sleep"][0]["night"], "2030-01-01")   # 05:00 UTC: after midnight, the date before

    def test_pagination_stops_when_a_page_says_more_but_gives_no_cursor(self):
        http = Fake((200, body(session("2030-01-01T23:00:00Z", "2030-01-02T06:00:00Z", 24000), more=True)))
        got = fetch(http)
        self.assertEqual(len(http.calls), 1)
        self.assertEqual(len(got["sleep"]), 1)

    def test_pagination_has_a_page_cap(self):
        answers = [(200, body(more=True, cursor=f"c{i}")) for i in range(ow.MAX_PAGES + 5)]
        http = Fake(*answers)
        got = fetch(http)
        self.assertEqual(len(http.calls), ow.MAX_PAGES)
        self.assertIsNone(got["reason"])


if __name__ == "__main__":
    unittest.main()
