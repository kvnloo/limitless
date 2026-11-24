"""sleep_coverage: wearable, phone-estimate-only and unknown nights over the last weeks (north-star row five).

A night is wearable only from a non-demo wearable row; the phone proxy never counts as wearable. The goal is
judged like uptime_audit: unknown nights never count for it, and fewer than a week of known nights is unknown.
Synthetic rows only, a fixed day, a UTC zone and one fixed non-UTC offset (no DST).
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import os
import re
import sys
import unittest
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import mock_guard, sleep, sleep_coverage as sc  # noqa: E402

UTC = timezone.utc
WEST = timezone(timedelta(hours=-6))      # a fixed offset: no DST
TODAY = date(2030, 1, 29)
H = 3600


def night(ago):
    return (TODAY - timedelta(days=ago)).isoformat()


def wear(ago, **extra):
    r = {"night": night(ago), "asleep_s": 7 * H, "source": "synthetic-band"}
    r.update(extra)
    return r


def gap(ago, start_h=23, hours=8, tz=UTC):
    """A quiet phone span that starts at ``start_h`` local on the evening ``ago`` nights before TODAY."""
    d = TODAY - timedelta(days=ago)
    s = datetime(d.year, d.month, d.day, tzinfo=tz).timestamp() + start_h * H
    return (s, s + hours * H)


def ns(wear_ago=(), gap_ago=(), days=28, tz=UTC):
    return sleep.nights([wear(a) for a in wear_ago], [gap(a, tz=tz) for a in gap_ago], TODAY, days, tz)


def counts(a):
    return a["wearable_nights"], a["proxy_only_nights"], a["unknown_nights"]


class Config(unittest.TestCase):
    def test_defaults_and_bad_values(self):
        self.assertEqual((sc.window_days(None), sc.target(None)), (28, 0.8))
        self.assertEqual((sc.DAYS_CONFIG, sc.TARGET_CONFIG), ("sleep_coverage_days", "sleep_coverage_target"))
        self.assertEqual(sc.window_days({"sleep_coverage_days": 14}), 14)
        self.assertEqual(sc.target({"sleep_coverage_target": 0.9}), 0.9)
        self.assertEqual(sc.target({"sleep_coverage_target": 1}), 1.0)
        for bad in (0, -3, 2.5, True, "28", None, [28]):
            self.assertEqual(sc.window_days({"sleep_coverage_days": bad}), 28, bad)
        for bad in (0, -0.1, 1.5, True, "0.8", float("nan"), float("inf"), None):
            self.assertEqual(sc.target({"sleep_coverage_target": bad}), 0.8, bad)


class Demo(unittest.TestCase):
    def test_demo_marked_rows_are_dropped_and_counted(self):
        rows = [wear(1), wear(2, deviceId="demo-strap"), wear(3, device="Synthetic Band (demo)"),
                wear(4, source="synthetic-demo"), wear(5, source={"device": "demo-ring"}),
                wear(6, first_name="[SEED: synthetic]"), wear(7)]
        real, n = sc.split_demo(rows)
        self.assertEqual([r["night"] for r in real], [night(1), night(7)])
        self.assertEqual(n, 5)

    def test_configured_patterns_are_demo_too(self):
        cfg = {mock_guard.CONFIG: ["sim-*"]}
        real, n = sc.split_demo([wear(1, source="sim-band"), wear(2)], cfg)
        self.assertEqual(([r["night"] for r in real], n), ([night(2)], 1))

    def test_non_rows_are_kept_for_the_reader_to_reject(self):
        self.assertEqual(sc.split_demo([]), ([], 0))
        self.assertEqual(sc.split_demo(None), ([], 0))


class Audit(unittest.TestCase):
    def test_counts_over_the_window(self):
        a = sc.audit(ns(wear_ago=range(1, 25), gap_ago=range(1, 27)))
        self.assertEqual(counts(a), (24, 2, 2))
        self.assertEqual((a["window_nights"], a["known_nights"], a["target"]), (28, 26, 0.8))
        self.assertAlmostEqual(a["wearable_share"], 24 / 28)
        self.assertEqual(a["goal"], "met")
        self.assertEqual(a["label"]["tier"], "T1")

    def test_the_proxy_never_counts_as_wearable(self):
        a = sc.audit(ns(wear_ago=range(1, 4), gap_ago=range(1, 29)))
        self.assertEqual(counts(a), (3, 25, 0))
        self.assertEqual(a["goal"], "not met")
        self.assertEqual(a["label"]["label"],
                         "wearable sleep on few nights, phone estimate on most nights; wearable goal not met")

    def test_whole_night_gaps_are_unknown_not_zero(self):
        a = sc.audit(ns(wear_ago=list(range(1, 11)) + list(range(19, 29)), gap_ago=range(11, 17)))
        self.assertEqual(counts(a), (20, 6, 2))   # nights seventeen and eighteen: nothing at all
        self.assertEqual(a["goal"], "not met")    # even both unknown nights wearable would not reach the target
        a = sc.audit(ns(wear_ago=list(range(1, 21)) + [27, 28]))                 # twenty-two wearable, six unknown
        self.assertEqual(counts(a), (22, 0, 6))
        self.assertEqual(a["goal"], "unknown")
        self.assertEqual(a["label"]["label"], "wearable sleep on most nights, no sleep data on some nights; "
                                              "wearable goal unknown: too many nights with no sleep data")

    def test_unknown_nights_never_count_for_the_goal(self):
        a = sc.audit(ns(wear_ago=range(1, 22)))                                    # three weeks, one unknown
        self.assertEqual(counts(a), (21, 0, 7))
        self.assertEqual(a["goal"], "unknown")
        a = sc.audit(ns(wear_ago=range(1, 23)))                                    # need ceil(28*0.8) = 23
        self.assertEqual(a["goal"], "unknown")
        a = sc.audit(ns(wear_ago=range(1, 24)))
        self.assertEqual(a["goal"], "met")

    def test_fewer_than_a_week_of_known_nights_is_unknown(self):
        a = sc.audit(ns(wear_ago=range(1, 7)))
        self.assertEqual((a["known_nights"], a["goal"], a["label"]["label"]), (6, "unknown", "unknown"))
        a = sc.audit(ns(wear_ago=range(1, 8)))
        self.assertEqual(a["known_nights"], 7)
        self.assertNotEqual(a["label"]["label"], "unknown")

    def test_every_night_wearable(self):
        a = sc.audit(ns(wear_ago=range(1, 29), gap_ago=range(1, 29)))
        self.assertEqual(a["label"]["label"], "wearable sleep on every night; wearable goal met")

    def test_no_wearable_night(self):
        a = sc.audit(ns(gap_ago=range(1, 29)))
        self.assertEqual(a["label"]["label"],
                         "no wearable sleep, phone estimate on every night; wearable goal not met")

    def test_target_and_window_are_arguments(self):
        a = sc.audit(ns(wear_ago=range(1, 13), gap_ago=range(1, 15), days=14), target=0.85)
        self.assertEqual((a["window_nights"], counts(a), a["target"], a["goal"]), (14, (12, 2, 0), 0.85, "met"))
        a = sc.audit(ns(wear_ago=range(1, 12), gap_ago=range(1, 15), days=14), target=0.85)
        self.assertEqual(a["goal"], "not met")

    def test_demo_rows_left_out_say_so_in_words(self):
        a = sc.audit(ns(wear_ago=range(1, 29)), demo=3)
        self.assertEqual(a["demo_rows"], 3)
        self.assertEqual(a["label"]["label"],
                         "wearable sleep on every night; wearable goal met; " + mock_guard.LEFT_OUT)

    def test_about_half_and_some_nights(self):
        a = sc.audit(ns(wear_ago=range(1, 13), gap_ago=range(1, 29)))
        self.assertEqual(a["label"]["label"], "wearable sleep on about half the nights, phone estimate on "
                                              "most nights; wearable goal not met")
        a = sc.audit(ns(wear_ago=range(1, 7), gap_ago=range(1, 29)))
        self.assertEqual(a["label"]["label"], "wearable sleep on some nights, phone estimate on most nights; "
                                              "wearable goal not met")

    def test_a_non_utc_zone_reads_the_proxy_on_its_own_evening(self):
        gaps = [gap(a, start_h=20, tz=WEST) for a in range(1, 29)]    # 20:00 at UTC-6 is 02:00 UTC next day
        here = sc.audit(sleep.nights([], gaps, TODAY, 28, WEST))
        self.assertEqual(counts(here), (0, 28, 0))
        utc = sc.audit(sleep.nights([], gaps, TODAY, 28, UTC))
        self.assertEqual(utc["unknown_nights"], 28)                   # early-morning UTC starts are no night's
        self.assertEqual(utc["label"]["label"], "unknown")

    def test_bad_nights_are_ignored(self):
        a = sc.audit([None, "x", 3] + ns(wear_ago=range(1, 29)))
        self.assertEqual((a["window_nights"], a["wearable_nights"]), (28, 28))
        self.assertEqual(sc.audit([])["label"]["label"], "unknown")
        self.assertEqual(sc.audit(None)["goal"], "unknown")


class Words(unittest.TestCase):
    def test_no_label_has_a_digit(self):
        seen = set()
        for w in range(0, 29, 3):
            for p in range(0, 29 - w, 4):
                for demo in (0, 2):
                    a = sc.audit(ns(wear_ago=range(1, w + 1), gap_ago=range(w + 1, w + p + 1)), demo=demo)
                    seen.add(a["label"]["label"])
                    self.assertEqual(re.findall(r"\d", a["label"]["label"]), [], a["label"])
        self.assertGreater(len(seen), 10)


if __name__ == "__main__":
    unittest.main()
