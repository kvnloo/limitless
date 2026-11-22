"""Scorecard: the hand-kept north-star Markdown table -> rows -> a 5-line weekly-review block.

Synthetic fixtures only (tests/fixtures/scorecard/): invented criteria, no real person's data.
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import scorecard as sc  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "scorecard"
HEADER = "| # | Criterion | Status | Evidence (latest) | Weeks green |\n|---|---|---|---|---|\n"


def table(*rows):
    return HEADER + "".join(r + "\n" for r in rows)


class Parse(unittest.TestCase):
    def test_fixture_parses_all_ten_rows(self):
        rows = sc.parse((FIX / "scorecard.md").read_text())
        self.assertEqual(len(rows), 10)
        self.assertEqual(rows[0], {"n": 1, "criterion": "Loop uptime", "status": "green", "weeks_green": 3})
        self.assertEqual(rows[3], {"n": 4, "criterion": "Habit logging", "status": "red", "weeks_green": 0})
        self.assertEqual([r["n"] for r in rows], list(range(1, 11)))

    def test_rows_carry_no_evidence(self):
        for r in sc.parse((FIX / "scorecard.md").read_text()):
            self.assertEqual(set(r), {"n", "criterion", "status", "weeks_green"})
            self.assertNotIn("sentinel", str(r))

    def test_no_table_is_empty(self):
        self.assertEqual(sc.parse(""), [])
        self.assertEqual(sc.parse("# Scorecard\n\nNothing here yet.\n"), [])
        self.assertEqual(sc.parse("| a | b |\n|---|---|\n| 1 | 2 |\n"), [])

    def test_header_without_rows_is_empty(self):
        self.assertEqual(sc.parse(HEADER), [])

    def test_malformed_rows_are_skipped(self):
        rows = sc.parse(table(
            "| 1 | Loop uptime | green | ok | 2 |",
            "| x | Bad number | green | ok | 2 |",
            "| 3 | Bad weeks | green | ok | many |",
            "| 4 | Too few cells | green |",
            "| 5 | Too | many | cells | 1 | 2 |",
            "| 6 |  | green | no criterion | 1 |",
            "| 7 | Delivery | amber | ok | 0 |",
        ))
        self.assertEqual([r["n"] for r in rows], [1, 7])

    def test_unknown_status_reads_unknown(self):
        rows = sc.parse(table("| 1 | Loop uptime | blue | ok | 0 |", "| 2 | Delivery |  | ok | 0 |"))
        self.assertEqual([r["status"] for r in rows], ["unknown", "unknown"])

    def test_status_case_and_spacing_are_normalised(self):
        rows = sc.parse(table("|  1  |  Loop uptime  |  Green  | ok |  3  |", "|2|Delivery|AMBER|ok|0|"))
        self.assertEqual(rows, [{"n": 1, "criterion": "Loop uptime", "status": "green", "weeks_green": 3},
                                {"n": 2, "criterion": "Delivery", "status": "amber", "weeks_green": 0}])

    def test_table_ends_at_the_first_non_table_line(self):
        rows = sc.parse(table("| 1 | Loop uptime | green | ok | 3 |") + "\nprose\n| 2 | Delivery | red | ok | 0 |\n")
        self.assertEqual([r["n"] for r in rows], [1])

    def test_rows_without_outer_pipes_still_parse(self):
        rows = sc.parse("# | Criterion | Status | Evidence (latest) | Weeks green\n---|---|---|---|---\n"
                        "1 | Loop uptime | red | ok | 0\n")
        self.assertEqual(rows, [{"n": 1, "criterion": "Loop uptime", "status": "red", "weeks_green": 0}])


if __name__ == "__main__":
    unittest.main()
