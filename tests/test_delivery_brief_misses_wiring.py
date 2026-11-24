"""The missed-brief reason where it shows: limitless_delivery and the doctor's delivery row append the most common
miss reason when the goal is not met; the scorecard's measured row two line is unchanged and keeps its length.

Synthetic kevin-push logs and the synthetic session DB fixture only; a fixed clock, UTC. Nothing is written or
sent.
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

from limitless import delivery_audit as da, doctor, jobs, scorecard as sc, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from hermes_db_fixture import make_db  # noqa: E402
from test_scorecard_measured import HEADER, NOW, UTC, Fixture  # noqa: E402

DIGIT = re.compile(r"\d")
CLAUSE = "; most common miss: held while Sleep mode was on"


class Missed(Fixture):
    def setUp(self):
        super().setUp()
        p = mock.patch.dict(os.environ, {"LIMITLESS_CONFIG": str(self.root / "none.json"), "TZ": "UTC"},
                            clear=True)
        p.start()
        self.addCleanup(p.stop)

    def week(self, held=(), quiet=()):
        """Fixture.pushes() with the wake brief of the newest days ``held`` held by Sleep mode (``quiet``: dropped
        by the quiet setting), counted back from the newest brief before NOW (today's wake event is after the
        fixed clock, so today is not a wake day yet); complaints known and none."""
        self.pushes()
        log = self.st / "push-log.jsonl"
        rows = [json.loads(ln) for ln in log.read_text().splitlines()]
        briefs = [r for r in rows if r["title"] == jobs.WAKE_BRIEF.send_title and r["at"] <= NOW][::-1]
        for k in held:
            briefs[k]["how"] = "held (sleep mode)"
        for k in quiet:
            briefs[k]["how"] = "log (quiet: on)"
        log.write_text("".join(json.dumps(r) + "\n" for r in rows))
        make_db(self.st / "state.db", [], started=NOW - 30 * 86400)
        self.cfg["hermes_db"] = "state.db"

    def tool(self, raw=False):
        (self.root / "config.json").write_text(json.dumps(self.cfg))
        env = {"LIMITLESS_CONFIG": str(self.root / "config.json")}
        return tools.delivery(StateReader(self.st), NOW, raw=raw, env=env, home=self.root, tz=UTC)

    def doctor_row(self):
        return doctor.delivery_row(StateReader(self.st), self.cfg, NOW, tz=UTC)


class ToolResult(Missed):
    def test_not_met_by_a_missed_brief_appends_the_most_common_reason(self):
        self.week(held=(0, 1), quiet=(2,))
        res = self.tool()
        self.assertTrue(res["label"]["label"].endswith(CLAUSE), res["label"])
        self.assertEqual(res["value"]["label"], res["label"]["label"])
        self.assertIsNone(DIGIT.search(json.dumps(res["value"])))

    def test_met_has_no_miss_clause(self):
        self.week()
        res = self.tool()
        self.assertNotIn("most common miss", res["label"]["label"])
        self.assertTrue(res["label"]["label"].endswith("no complaints this week"))

    def test_raw_carries_the_counts_per_reason(self):
        self.week(held=(0,), quiet=(1,))
        v = self.tool(raw=True)["value"]
        self.assertIn("misses", tools.DELIVERY_RAW_KEYS)
        self.assertEqual(v["misses"]["reasons"][da.MISS_SLEEP], 1)
        self.assertEqual(v["misses"]["reasons"][da.MISS_QUIET], 1)
        self.assertEqual(v["misses"]["missed"], 2)

    def test_a_tie_is_broken_by_the_fixed_list_order(self):
        self.week(held=(1,), quiet=(0,))
        self.assertTrue(self.tool()["label"]["label"].endswith(CLAUSE))


class DoctorRow(Missed):
    def test_stale_with_the_most_common_miss_reason(self):
        self.week(quiet=(0, 3))
        r = self.doctor_row()
        self.assertEqual(r["status"], doctor.STALE)
        self.assertTrue(r["reason"].endswith("; most common miss: held by the quiet setting"), r)
        self.assertIsNone(DIGIT.search(r["reason"]), r)

    def test_live_has_no_miss_clause(self):
        self.week()
        r = self.doctor_row()
        self.assertEqual(r["status"], doctor.LIVE)
        self.assertNotIn("most common miss", r["reason"])


class ScorecardRow(Missed):
    def test_row_two_line_is_unchanged_and_within_the_length_rule(self):
        self.week(held=(0, 1, 2))
        m = self.by_n()[sc.DELIVERY_ROW]
        self.assertEqual(m["goal"], "not met")
        self.assertNotIn("most common miss", m["label"])
        self.assertNotIn("\n", m["label"])
        rows = sc.parse(HEADER + "| 2 | Delivery | green | synthetic | 1 |\n")
        lines = sc.measured_lines(rows, self.measured())
        self.assertLessEqual(len(lines), sc.MAX_LINES - 1)
        self.assertIn("Measured: delivery: " + m["label"], lines)


if __name__ == "__main__":
    unittest.main()
