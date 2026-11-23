"""The loop row: after the person replies Keep or Drop to the week review (habit_replies.decide), ONE row per
week goes to the existing prediction ledger (predictions.jsonl): {week_of, habit, prediction, outcome, rule
verdict, decision}. Nothing is written before the reply, a dry run writes nothing, and a week never gets a
second row. Synthetic data only; nothing sends."""
import json
import os
import stat
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import habit_replies, prediction, stop_rule  # noqa: E402

UTC = timezone.utc
H = 3600.0
REVIEW_AT = 2_000_000_000.0                       # the week review send, on day seven
TODAY = datetime.fromtimestamp(REVIEW_AT, UTC).date()
START = TODAY - timedelta(days=6)
WEEK_OF = START.isoformat()


class Loop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Path(self.tmp.name)
        self.pj = self.st / prediction.PREDICTIONS_FILE
        self.write_habit("most_done", "Done", "Done", "Skipped", "No")
        (self.st / "jobs-sent.jsonl").write_text(json.dumps({"t": REVIEW_AT, "k": "x", "job": "week_review"}) + "\n")

    def tearDown(self):
        self.tmp.cleanup()

    def write_habit(self, rule, *answers):
        h = {"habit": "Synthetic habit", "week_of": WEEK_OF, "at": "2033-05-11T07:00:00+00:00",
             "checkins": {(START + timedelta(days=i)).isoformat(): a for i, a in enumerate(answers)}}
        if rule:
            h["stop_rule"] = rule
        (self.st / "habit.json").write_text(json.dumps(h))

    def decide(self, replies, dry_run=False, now=REVIEW_AT + 2 * H):
        return habit_replies.decide(self.st, replies, now, dry_run=dry_run, tz=UTC)

    def loops(self):
        return [r for r in prediction.rows(self.st) if r.get("kind") == stop_rule.LOOP]

    def test_nothing_is_written_before_the_reply(self):
        self.decide([])
        self.decide([(REVIEW_AT - 60, "Keep")])            # before the review
        self.decide([(REVIEW_AT + 60, "maybe")])           # not Keep or Drop
        self.assertFalse(self.pj.exists())
        self.assertEqual(stop_rule.loop_rows(self.st), [])

    def test_a_dry_run_writes_nothing(self):
        self.decide([(REVIEW_AT + 60, "Keep")], dry_run=True)
        self.assertFalse(self.pj.exists())

    def test_keep_writes_one_row_with_the_loop_fields(self):
        self.decide([(REVIEW_AT + 60, "Keep")])
        (row,) = self.loops()
        self.assertEqual({k: row[k] for k in ("week_of", "habit", "prediction", "outcome", "rule", "verdict",
                                             "decision")},
                         {"week_of": WEEK_OF, "habit": "Synthetic habit", "prediction": "none", "outcome": "unknown",
                          "rule": "most_done", "verdict": "keep", "decision": "Keep"})
        self.assertEqual(stat.S_IMODE(self.pj.stat().st_mode), 0o600)

    def test_the_reply_decides_never_the_rule(self):
        self.write_habit("any_done", "No", "No")
        self.decide([(REVIEW_AT + 60, "Keep")])
        (row,) = self.loops()
        self.assertEqual((row["verdict"], row["decision"]), ("drop", "Keep"))
        self.assertEqual(json.loads((self.st / "habit.json").read_text())["decision"], "Keep")

    def test_one_row_per_week_however_often_it_runs(self):
        self.decide([(REVIEW_AT + 60, "Keep")])
        self.decide([(REVIEW_AT + 60, "Keep"), (REVIEW_AT + 120, "Drop")])
        h = json.loads((self.st / "habit.json").read_text())
        self.assertIsNone(stop_rule.record_loop(self.st, h, "Drop", "2033-05-18T00:00:00+00:00"))
        self.assertEqual(len(self.loops()), 1)
        self.assertEqual(self.loops()[0]["decision"], "Keep")

    def test_unknown_stays_unknown_and_never_drop(self):
        self.write_habit("most_done", "Skipped", "Skipped")
        self.decide([(REVIEW_AT + 60, "Drop")])
        (row,) = self.loops()
        self.assertEqual((row["verdict"], row["decision"]), ("unknown", "Drop"))
        self.write_habit(None, "Done")
        self.assertEqual(stop_rule.loop_row(self.st, json.loads((self.st / "habit.json").read_text()), "Keep",
                                            None)["verdict"], "unknown")

    def test_the_locked_prediction_and_its_receipt_are_named(self):
        self.write_habit("most_done")
        prediction.lock(self.st, WEEK_OF, "Synthetic prediction", "logged", "at_least 3 of 7", write=True,
                        today=START, now=REVIEW_AT - 7 * 24 * H)
        self.write_habit("most_done", "Done", "Done", "Done", "No")
        prediction.receipt(self.st, WEEK_OF, write=True, today=TODAY + timedelta(days=1), now=REVIEW_AT + H)
        before = self.pj.read_text().splitlines()
        self.decide([(REVIEW_AT + 60, "Keep")])
        (row,) = self.loops()
        self.assertEqual((row["prediction"], row["outcome"], row["outcome_modality"]),
                         ("prediction locked", "supports", "self_report"))
        self.assertEqual(self.pj.read_text().splitlines()[:len(before)], before)     # append-only
        self.assertIsNotNone(prediction.locked(self.st, WEEK_OF))
        self.assertIsNotNone(prediction.receipt_for(self.st, WEEK_OF))

    def test_loop_rows_are_one_per_week_oldest_first(self):
        other = {"habit": "Older synthetic habit", "week_of": (START - timedelta(days=7)).isoformat(), "checkins": {}}
        stop_rule.record_loop(self.st, other, "Drop", "2033-05-11T00:00:00+00:00")
        self.decide([(REVIEW_AT + 60, "Keep")])
        with open(self.pj, "a", encoding="utf-8") as f:
            f.write(json.dumps(dict(self.loops()[-1], decision="Drop")) + "\n")   # a stray second row is not read
        self.assertEqual([(r["week_of"], r["decision"]) for r in stop_rule.loop_rows(self.st)],
                         [(other["week_of"], "Drop"), (WEEK_OF, "Keep")])


if __name__ == "__main__":
    unittest.main()
