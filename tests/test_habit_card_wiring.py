"""The habit code calls habit_card for its three card operations: jobs.record_checkin (record), jobs.week_logged
(week_number) and stop_rule.verdict (verdict_inputs). Synthetic data only."""
import os
import sys
import unittest
from datetime import date, timedelta
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import habit_card, jobs, stop_rule  # noqa: E402

START = date(2030, 1, 7)


def week(*answers):
    return {"habit": "Synthetic habit", "week_of": START.isoformat(),
            "checkins": {(START + timedelta(days=i)).isoformat(): a for i, a in enumerate(answers) if a}}


class Wiring(unittest.TestCase):
    def test_record_checkin_records_through_the_card(self):
        with mock.patch.object(habit_card, "record", wraps=habit_card.record) as rec:
            jobs.record_checkin(week(), START.isoformat(), "Done")
        rec.assert_called_once()

    def test_week_logged_counts_through_the_card(self):
        with mock.patch.object(habit_card, "week_number", wraps=habit_card.week_number) as wn:
            self.assertEqual(jobs.week_logged(week("Done", "No", "Skipped")), (1, 2))
        wn.assert_called_once()

    def test_the_stop_rule_reads_the_cards_verdict_inputs(self):
        with mock.patch.object(habit_card, "verdict_inputs", wraps=habit_card.verdict_inputs) as vi:
            self.assertEqual(stop_rule.verdict(week("Done", "Done", "No"), "most_done"), "keep")
        vi.assert_called_once()

    def test_the_week_card_state_holds_only_done_and_no(self):
        h = week("Done", "Skipped", None, "No")
        synced = {(START + timedelta(days=2)).isoformat(): "met", (START + timedelta(days=3)).isoformat(): "met"}
        self.assertEqual(jobs.week_card_state(h, synced),
                         {"checkins": {START.isoformat(): "Done", (START + timedelta(days=2)).isoformat(): "Done",
                                       (START + timedelta(days=3)).isoformat(): "No"}})
        self.assertEqual(jobs.week_card_state({}, synced), {"checkins": {}})

    def test_skip_still_writes_the_skipped_marker_into_habit_json(self):
        self.assertEqual(jobs.record_checkin(week("Done"), START.isoformat(), "skip")["checkins"],
                         {START.isoformat(): "Skipped"})

    def test_habit_card_imports_nothing_else_from_limitless(self):
        src = open(habit_card.__file__, encoding="utf-8").read()
        self.assertNotIn("from .", src.replace("from .envelope", ""))
        self.assertNotIn("import limitless", src)


if __name__ == "__main__":
    unittest.main()
