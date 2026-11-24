"""Row two's complaints where they show: the scorecard's measured row two, limitless_delivery and the doctor's
delivery row. Words only (no digit) outside the raw opt-in; complaints unknown keeps the goal unknown.

Synthetic kevin-push logs, a synthetic quiet state and the synthetic session DB fixture only; a fixed clock,
UTC. Nothing is written or sent.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from limitless import delivery_audit as da, doctor, quiet, scorecard as sc, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from hermes_db_fixture import make_db  # noqa: E402
from test_scorecard_measured import H, HEADER, NOW, TODAY, UTC, Fixture, noon  # noqa: E402

DIGIT = re.compile(r"\d")
NONE_WORDS, SOME_WORDS = "no complaints this week", "some pushes drew a quiet or stop request"


def first_push_at():
    """The first plain push of today in Fixture.pushes(): the wake event four hours before noon, plus two minutes."""
    return noon(TODAY) - 4 * H + 120


class Wired(Fixture):
    def hermes(self, messages=()):
        make_db(self.st / "state.db", list(messages), started=NOW - 30 * 86400)
        self.cfg["hermes_db"] = "state.db"

    def row2(self):
        return self.by_n()[sc.DELIVERY_ROW]


class ScorecardRow(Wired):
    def test_a_full_week_with_no_complaint_is_met_and_says_so(self):
        self.pushes()
        self.hermes([("user", "thanks", first_push_at() + 60)])
        m = self.row2()
        self.assertEqual(m["goal"], "met")
        self.assertTrue(m["label"].endswith("; " + NONE_WORDS), m["label"])

    def test_no_reply_source_is_unknown_never_met(self):
        self.pushes()
        m = self.row2()
        self.assertEqual(m["goal"], "unknown")
        self.assertIn("complaints: unknown, " + da.NO_DB_COMPLAINTS, m["label"])
        self.assertNotIn(NONE_WORDS, m["label"])

    def test_an_unreadable_db_is_unknown(self):
        self.pushes()
        self.cfg["hermes_db"] = "absent.db"
        m = self.row2()
        self.assertEqual(m["goal"], "unknown")
        self.assertIn("complaints: unknown, " + da.DB_UNREADABLE, m["label"])

    def test_a_stop_after_a_push_is_not_met_with_one_note_on_a_green_row(self):
        self.pushes()
        self.hermes([("user", "Stop.", first_push_at() + 300)])
        m = self.row2()
        self.assertEqual(m["goal"], "not met")
        self.assertIn(SOME_WORDS, m["label"])
        rows = sc.parse(HEADER + "| 2 | Delivery | green | synthetic | 1 |\n")
        lines = sc.measured_lines(rows, [m])
        self.assertEqual(lines, ["Measured: delivery: " + m["label"],
                                 "Row Delivery says green but the measurement says not met."])

    def test_a_snooze_the_quiet_ingest_recorded_this_week_is_not_met(self):
        self.pushes()
        self.hermes()
        quiet.write(self.st, quiet.SNOOZED, NOW - 2 * 86400)
        self.assertEqual(self.row2()["goal"], "not met")
        quiet.write(self.st, quiet.SNOOZED, NOW - 9 * 86400)
        self.assertEqual(self.row2()["goal"], "met")

    def test_the_row_has_no_digit_and_never_the_reply_text(self):
        marker = "synthetic marker words"
        for msgs in ((), [("user", "stop " + marker, first_push_at() + 60)], [("user", marker, NOW - H)]):
            self.pushes()
            if (self.st / "state.db").exists():
                (self.st / "state.db").unlink()
            self.hermes(msgs)
            m = self.row2()
            self.assertIsNone(DIGIT.search(m["label"]), m)
            self.assertNotIn(marker, json.dumps(m))

    def test_raw_counts_carry_the_complaints(self):
        self.pushes()
        self.hermes([("user", "too much", first_push_at() + 60)])
        out = tools.scorecard(self.root / "absent.md", NOW, state_dir=self.st, cfg=self.cfg, tz=UTC, raw=True,
                              env=self.env, home=self.root)
        got = {m["n"]: m for m in out["measured"]}[sc.DELIVERY_ROW]["counts"]["complaints"]
        self.assertEqual(got, {"known": True, "quiet": 0, "stop": 1, "total": 1, "why": None})


class DeliveryTool(Wired):
    def call(self, raw=False):
        (self.root / "config.json").write_text(json.dumps(self.cfg))
        env = {"LIMITLESS_CONFIG": str(self.root / "config.json")}
        return tools.delivery(StateReader(self.st), NOW, raw=raw, env=env, home=self.root, tz=UTC)

    def test_the_tool_label_carries_the_complaints_word(self):
        self.pushes()
        self.hermes()
        res = self.call()
        self.assertTrue(res["label"]["label"].endswith(NONE_WORDS))
        self.assertEqual(set(res["value"]), {"label"})
        self.assertIsNone(DIGIT.search(json.dumps(res["value"])))

    def test_counts_only_with_the_raw_opt_in(self):
        self.pushes()
        self.hermes([("user", "stop", first_push_at() + 60)])
        v = self.call(raw=True)["value"]
        self.assertEqual(v["complaints"]["stop"], 1)
        self.assertIn("complaints", tools.DELIVERY_RAW_KEYS)


class DoctorRow(Wired):
    def setUp(self):
        super().setUp()
        p = mock.patch.dict(os.environ, {"LIMITLESS_CONFIG": str(self.root / "none.json"), "TZ": "UTC"},
                            clear=True)
        p.start()
        self.addCleanup(p.stop)

    def row(self):
        r = doctor.delivery_row(StateReader(self.st), self.cfg, NOW, tz=UTC)
        self.assertEqual((r["name"], r["kind"]), (doctor.DELIVERY_ROW, "source"))
        self.assertIsNone(DIGIT.search(r["reason"]), r)
        return r

    def test_no_push_log_is_off(self):
        self.assertEqual((self.row()["status"], self.row()["reason"]), (doctor.OFF, da.NO_LOG_REASON))

    def test_met_is_live_with_the_words(self):
        self.pushes()
        self.hermes()
        r = self.row()
        self.assertEqual(r["status"], doctor.LIVE)
        self.assertTrue(r["reason"].endswith(NONE_WORDS), r)

    def test_unknown_complaints_are_missing(self):
        self.pushes()
        r = self.row()
        self.assertEqual(r["status"], doctor.MISSING)
        self.assertIn("complaints: unknown, " + da.NO_DB_COMPLAINTS, r["reason"])

    def test_a_complaint_is_stale_with_the_words(self):
        self.pushes()
        self.hermes([("user", "too much!", first_push_at() + 60)])
        r = self.row()
        self.assertEqual(r["status"], doctor.STALE)
        self.assertIn(SOME_WORDS, r["reason"])

    def test_the_row_sits_right_after_the_uptime_row(self):
        cfg = dict(self.cfg, state=str(self.st))
        names = [r["name"] for r in doctor.report(cfg, NOW)]
        self.assertEqual(names[names.index(doctor.UPTIME_ROW) + 1], doctor.DELIVERY_ROW)


if __name__ == "__main__":
    unittest.main()
