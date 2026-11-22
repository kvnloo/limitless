"""Day 7: three synthetic replies (Done, No, Skip) to three check-ins give "1 of 2 logged days"."""
import json
import os
import sys
import tempfile
import unittest
from datetime import date, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import habit_replies, jobs, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

D1 = 1894363200.0            # 2030-01-11 12:00 UTC, the synthetic week's first day
DAY_S = 24 * 3600.0


class DaySeven(unittest.TestCase):
    def test_done_no_skip_give_one_of_two_logged_days(self):
        with tempfile.TemporaryDirectory() as d:
            st = Path(d)
            (st / "habit.json").write_text(json.dumps({"week_of": "2030-01-11", "habit": "Synthetic habit",
                                                       "start": "Synthetic two-minute start"}))
            sent = []
            for i, reply in enumerate(["Done", "No", "Skip"]):
                t = D1 + i * DAY_S
                sent.append(jobs.sent_entry(jobs.HABIT_CHECKIN, t - jobs.HABIT_CUE_AFTER_S, t))
                (st / "jobs-sent.jsonl").write_text("".join(json.dumps(r) + "\n" for r in sent))
                habit_replies.ingest(st, [(t + 300, reply)], t + 3600, tz=timezone.utc)
            v = tools.habit(StateReader(st), D1 + 6 * DAY_S, date(2030, 1, 17))["value"]
        self.assertEqual(v["day"], 7)
        self.assertEqual([x["checkin"] for x in v["days"][:3]], ["Done", "No", "Skipped"])
        self.assertEqual(v["logged"], "1 of 2 logged days")


if __name__ == "__main__":
    unittest.main()
