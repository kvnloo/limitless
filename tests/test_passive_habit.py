"""Passive habit days: the older loop's per-day rows, read as measured evidence (a proxy), never a check-in.

Synthetic rows only. The file is the config key ``passive_habit_file`` (relative = the state dir); none by
default, and no file or no rows is unknown, never "0 of 0".
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import card, catchup, jobs, jobs_runner, tools, weekly_target  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402


def row(day, met, **kw):
    r = {"day": day, "wake": "07:00", "feedMinFirstHour": 0.0, "firstApp": "synthetic", "firstCat": "tool",
         "minToFirstFeed": None, "met": met}
    r.update(kw)
    return r


class Setup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.cfg = self.root / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg), "LIMITLESS_STATE": str(self.st)}

    def tearDown(self):
        self.tmp.cleanup()

    def configure(self, name="passive.jsonl"):
        self.cfg.write_text(json.dumps({"passive_habit_file": name}))

    def write_rows(self, rows, name="passive.jsonl", extra=""):
        p = Path(name) if Path(name).is_absolute() else self.st / name
        p.write_text("".join(json.dumps(r) + "\n" for r in rows) + extra)
        return p


class PassiveDays(Setup):
    def test_no_file_configured_is_empty(self):
        self.write_rows([row("2030-01-14", True)])
        self.assertEqual(StateReader(self.st).passive_habit_days(self.env), [])

    def test_relative_path_is_in_the_state_dir(self):
        self.configure("passive.jsonl")
        self.write_rows([row("2030-01-14", True), row("2030-01-15", False)])
        got = StateReader(self.st).passive_habit_days(self.env)
        self.assertEqual([(r["day"], r["met"]) for r in got], [("2030-01-14", True), ("2030-01-15", False)])
        self.assertEqual(StateReader(self.st).passive_habit_file(self.env), self.st / "passive.jsonl")

    def test_absolute_path(self):
        p = self.root / "elsewhere.jsonl"
        self.configure(str(p))
        self.write_rows([row("2030-01-14", True)], name=str(p))
        self.assertEqual(len(StateReader(self.st).passive_habit_days(self.env)), 1)

    def test_malformed_rows_are_ignored(self):
        self.configure()
        self.write_rows([row("2030-01-10", True), row("2030-01-11", "yes"), row("2030-13-01", True),
                         row("not a day", False), row(20300112, True), {"met": True}, row("2030-01-13", None),
                         row("20300114", True), row("2030-01-15", False)],
                        extra="{broken json\n[1, 2]\n")
        got = StateReader(self.st).passive_habit_days(self.env)
        self.assertEqual([r["day"] for r in got], ["2030-01-10", "2030-01-15"])

    def test_one_row_per_day_the_last_wins_sorted(self):
        self.configure()
        self.write_rows([row("2030-01-15", False), row("2030-01-14", True), row("2030-01-15", True)])
        got = StateReader(self.st).passive_habit_days(self.env)
        self.assertEqual([(r["day"], r["met"]) for r in got], [("2030-01-14", True), ("2030-01-15", True)])

    def test_missing_file_or_bad_config_is_empty(self):
        self.configure("nope.jsonl")
        self.assertEqual(StateReader(self.st).passive_habit_days(self.env), [])
        self.cfg.write_text(json.dumps({"passive_habit_file": 7}))
        self.assertIsNone(StateReader(self.st).passive_habit_file(self.env))
        self.assertEqual(StateReader(self.st).passive_habit_days(self.env), [])

    def test_reading_writes_nothing(self):
        self.configure()
        self.write_rows([row("2030-01-15", True)])
        before = sorted(p.name for p in self.st.iterdir())
        StateReader(self.st).passive_habit_days(self.env)
        self.assertEqual(sorted(p.name for p in self.st.iterdir()), before)


TODAY = date(2030, 1, 15)
NOW = 1894708800.0          # 2030-01-15 noon UTC, as tests/test_habit.py


def days_back(n):
    return (TODAY - timedelta(days=n)).isoformat()


class WithPassive(Setup):
    def passive(self, mets, start_back=None):
        """One row per day ending today; ``mets`` oldest first."""
        start_back = len(mets) - 1 if start_back is None else start_back
        self.configure()
        self.write_rows([row(days_back(start_back - i), m) for i, m in enumerate(mets)])

    def habit_file(self, **h):
        (self.st / "habit.json").write_text(json.dumps(h))

    def run_tool(self):
        return tools.habit(StateReader(self.st), NOW, TODAY, self.env)


class NoConfirmedWeek(WithPassive):
    def test_passive_field_and_label_when_no_week(self):
        self.passive([True, True, True, True, True, True, False])
        out = self.run_tool()
        p = out["value"]["passive"]
        self.assertEqual({k: p[k] for k in ("days_measured", "days_met", "modality")},
                         {"days_measured": 7, "days_met": 6, "modality": "proxy"})
        self.assertEqual(out["label"]["label"], "habit not started; phone data shows the first hour mostly feed-free")
        self.assertEqual(out["label"]["tier"], "T1")
        self.assertEqual(out["modality"], "proxy")
        self.assertIsNone(out["value"]["habit"])

    def test_wording_comes_from_counts(self):
        cases = {(True,) * 7: "mostly feed-free", (True, True, True, True, False, False, False): "about half",
                 (True, False, False, False, False, False, False): "rarely feed-free",
                 (True, True, False): "mostly feed-free", (True, False, False): "rarely feed-free"}
        for mets, want in cases.items():
            self.passive(list(mets))
            word = self.run_tool()["label"]["label"]
            self.assertTrue(word.startswith("habit not started; phone data shows the first hour"), word)
            self.assertIn(want, word)
            self.assertFalse(any(c.isdigit() for c in word), word)

    def test_under_three_days_is_not_enough_phone_data(self):
        self.passive([True, True])
        out = self.run_tool()
        self.assertEqual(out["label"]["label"], "habit not started; not enough phone data")
        self.assertEqual(out["value"]["passive"]["days_measured"], 2)

    def test_only_the_last_seven_days_count(self):
        self.passive([True, True, True, True], start_back=10)   # days ten to seven back: all outside
        out = self.run_tool()
        self.assertIsNone(out["value"])
        self.assertNotIn("passive", json.dumps(out))
        self.passive([True] * 9)                                # nine days: only seven count
        self.assertEqual(self.run_tool()["value"]["passive"]["days_measured"], 7)

    def test_a_past_week_is_no_confirmed_week(self):
        self.habit_file(week_of="2030-01-01", habit="synthetic habit", checkins={})
        self.passive([True] * 5)
        out = self.run_tool()
        self.assertEqual(out["value"]["passive"]["days_met"], 5)
        self.assertTrue(out["label"]["label"].startswith("habit not started"))

    def test_never_writes_never_done_never_starts(self):
        self.passive([True] * 7)
        before = sorted(p.name for p in self.st.iterdir())
        out = self.run_tool()
        self.assertEqual(sorted(p.name for p in self.st.iterdir()), before)
        self.assertFalse((self.st / "habit.json").exists())
        for k in ("days", "counts", "today", "logged", "day"):
            self.assertNotIn(k, out["value"])
        self.assertNotIn("Done", json.dumps(out))
        self.assertEqual(jobs.habit_week_gate(StateReader(self.st).habit(), TODAY).reason, jobs.NO_WEEK)


class UnknownIsNotZero(WithPassive):
    def test_no_file_configured(self):
        self.write_rows([row(days_back(0), True)])     # present but not configured
        out = self.run_tool()
        self.assertIsNone(out["value"])
        self.assertIn("habit.json", out["reason"])
        self.assertNotIn("passive", json.dumps(out))

    def test_configured_but_no_rows(self):
        self.configure()
        self.write_rows([{"day": "junk"}])
        out = self.run_tool()
        self.assertIsNone(out["value"])
        self.assertNotIn("passive", json.dumps(out))
        self.assertNotIn("of", (out.get("label") or {}).get("label", ""))

    def test_confirmed_week_without_rows_has_no_passive_field(self):
        self.habit_file(week_of=days_back(2), habit="synthetic habit", checkins={days_back(1): "Done"})
        self.assertNotIn("passive", self.run_tool()["value"])
        self.configure("nope.jsonl")
        self.assertNotIn("passive", self.run_tool()["value"])


class ConfirmedWeek(WithPassive):
    def setUp(self):
        super().setUp()
        self.checkins = {days_back(4): "Done", days_back(3): "No", days_back(1): "Done"}
        self.habit_file(week_of=days_back(4), habit="synthetic habit", start="one small step", checkins=self.checkins)
        self.plain = self.run_tool()

    def test_passive_sits_beside_the_taps_never_merged(self):
        self.passive([True] * 7)                       # two of them before week_of
        out = self.run_tool()
        for k in ("days", "counts", "today", "logged", "day", "habit"):
            self.assertEqual(out["value"][k], self.plain["value"][k], k)
        self.assertEqual(out["modality"], self.plain["modality"])
        p = out["value"]["passive"]
        self.assertEqual((p["days_measured"], p["days_met"], p["modality"]), (5, 5, "proxy"))
        self.assertEqual(p["label"]["label"], "phone data shows the first hour mostly feed-free")
        self.assertEqual(p["label"]["tier"], "T1")
        self.assertNotIn("label", out)                 # the age label is the handler's, as before

    def test_week_review_keeps_the_tapped_number_and_adds_a_line(self):
        self.passive([False] * 7)
        h = StateReader(self.st).habit()
        line = jobs_runner.week_passive(self.st, h, self.env)
        self.assertEqual(line, "Phone data (a proxy, not a check-in): the first hour rarely feed-free.")
        text = jobs_runner.body(jobs.WEEK_REVIEW, h, synced={}, passive=line, flow="Flow: synthetic.")
        self.assertEqual(text.split("\n"), [jobs.week_review_text(h, {}), weekly_target.REVIEW_ON_THE_WAY, line, "Flow: synthetic.",
                                                "Reply: Keep / Drop"])
        self.assertIn("2 of 3 logged days", text.split("\n")[0])
        self.assertEqual(jobs.week_logged(h, {}), (2, 3))

    def test_week_review_without_rows_is_unchanged(self):
        h = StateReader(self.st).habit()
        self.assertEqual(jobs_runner.week_passive(self.st, h, self.env), "")
        self.assertEqual(jobs_runner.body(jobs.WEEK_REVIEW, h, synced={}, passive=""),
                         jobs.week_review_text(h, {}) + "\n" + weekly_target.REVIEW_ON_THE_WAY + "\nReply: Keep / Drop")


class CardAndCatchup(WithPassive):
    def card_habit_line(self):
        c = card.build(StateReader(self.st), NOW, TODAY, env=self.env)
        return [ln for ln in c["lines"] if ln.startswith("habit")][0]

    def catchup_habit_line(self):
        c = catchup.build(StateReader(self.st), NOW, NOW - 3 * 86400, env=self.env, today=TODAY)
        return [ln for ln in c["lines"] if ln.startswith("habit")][0]

    def test_card_no_week(self):
        self.assertEqual(self.card_habit_line(), "habit: none set this week")
        self.passive([True] * 7)
        self.assertEqual(self.card_habit_line(),
                         "habit: none set this week; phone data shows the first hour mostly feed-free")

    def test_card_confirmed_week(self):
        self.habit_file(week_of=days_back(2), habit="synthetic habit", checkins={days_back(0): "Done"})
        self.passive([True, False, False])
        self.assertEqual(self.card_habit_line(),
                         "habit this week: synthetic habit; today Done; phone data shows the first hour rarely feed-free")

    def test_catchup_lines(self):
        self.assertEqual(self.catchup_habit_line(), "habit week: unknown")
        self.passive([True, True, True, False, False, False])
        self.assertEqual(self.catchup_habit_line(),
                         "habit week: unknown; phone data shows the first hour feed-free about half the time")
        self.habit_file()
        self.assertEqual(self.catchup_habit_line(),
                         "habit week: none started; phone data shows the first hour feed-free about half the time")
        self.habit_file(week_of=days_back(2), habit="synthetic habit", checkins={days_back(0): "Done"})
        self.assertEqual(self.catchup_habit_line(),
                         "habit week: running, today Done; phone data shows the first hour rarely feed-free")

    def test_a_week_too_young_for_phone_data(self):
        self.habit_file(week_of=days_back(1), habit="synthetic habit", checkins={days_back(0): "Done"})
        self.passive([True] * 7)                       # only two of them are in the week
        self.assertEqual(self.card_habit_line(), "habit this week: synthetic habit; today Done; not enough phone data")

    def test_lines_stay_digit_free(self):
        self.passive([True] * 7)
        for ln in (self.card_habit_line(), self.catchup_habit_line()):
            self.assertFalse(any(c.isdigit() for c in ln), ln)


class FakePush:
    def __init__(self):
        self.calls = []

    def __call__(self, title, body, once=None):
        self.calls.append((title, body, once))
        return "telegram"


class WeekReviewSend(WithPassive):
    def test_the_sent_review_has_the_tapped_number_then_the_phone_line(self):
        day7 = datetime.fromtimestamp(NOW, timezone.utc).date()
        week_of = day7 - timedelta(days=6)
        self.habit_file(week_of=week_of.isoformat(), habit="Synthetic habit",
                        checkins={week_of.isoformat(): "Done", (day7 - timedelta(days=1)).isoformat(): "No"})
        self.configure()
        self.write_rows([row((week_of + timedelta(days=i)).isoformat(), True) for i in range(7)])
        (self.st / "events.jsonl").write_text(json.dumps({"event": "habit_cue", "at": NOW - 60}) + "\n")
        push = FakePush()
        jobs_runner.run_once(self.st, NOW, push=push, dry_run=False, env=self.env, home=self.root, tz=timezone.utc)
        bodies = [b for t, b, _ in push.calls if t == "Week review"]
        self.assertEqual(bodies, ["Synthetic habit: 1 of 2 logged days this week.\n"
                                  "habit: on the way\n"
                                  "Phone data (a proxy, not a check-in): the first hour mostly feed-free.\n"
                                  "Reply: Keep / Drop"])
        self.assertEqual(json.loads((self.st / "habit.json").read_text())["checkins"],
                         {week_of.isoformat(): "Done", (day7 - timedelta(days=1)).isoformat(): "No"})


if __name__ == "__main__":
    unittest.main()
