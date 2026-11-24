"""strength.habit_claim / habit_strength: a habit's rung read from the prediction ledger (predictions.jsonl:
prediction and receipt rows written by prediction.lock and prediction.receipt, loop rows by stop_rule), read-only.
Synthetic ledgers only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import re
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import prediction, strength  # noqa: E402

NOW = 1894708800.0           # 2030-01-15T12:00:00Z
W1 = date(2030, 1, 15)
W2 = W1 + timedelta(days=14)
W3 = W1 + timedelta(days=28)
HABIT = "Synthetic walk after lunch"
OTHER = "Synthetic other habit"
MOSTLY_DONE = ("Done", "Done", "Done", "Done", "Done", "No", "Done")
MOSTLY_NO = ("No", "No", "No", "No", "Done", "No", "No")
TWO_DAYS = ("Done", "Done", None, None, None, None, None)


class Ledger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.st = Path(self.tmp.name)

    def week(self, start, answers, name=HABIT, judge=True):
        """A kept habit-<week>.json, a locked logged-days prediction and (after day seven) its receipt."""
        checkins = {(start + timedelta(days=i)).isoformat(): a for i, a in enumerate(answers) if a}
        (self.st / f"habit-{start.isoformat()}.json").write_text(
            json.dumps({"habit": name, "week_of": start.isoformat(), "checkins": checkins}))
        r = prediction.lock(self.st, start.isoformat(), "Synthetic prediction: most days done", "logged",
                            "at_least 4 of 7", write=True, today=start, now=NOW)
        self.assertEqual(r["action"], prediction.LOCKED, r)
        if judge:
            r = prediction.receipt(self.st, start.isoformat(), write=True, today=start + timedelta(days=7), now=NOW)
            self.assertEqual(r["action"], prediction.WROTE, r)
            return r["receipt"]["verdict"]

    def rung(self, habit=HABIT, week_of=None):
        out = strength.habit_strength(self.st, habit, week_of)
        self.assertEqual(re.findall(r"\d", out["words"] + out["why"]), [], out)
        return out

    def test_empty_ledger_has_no_rung(self):
        self.assertIsNone(self.rung()["rung"])
        self.assertEqual(strength.habit_claim(self.st, HABIT)["weeks"], [])

    def test_one_supported_week_is_preregistered(self):
        self.assertEqual(self.week(W1, MOSTLY_DONE), prediction.SUPPORTS)
        out = self.rung()
        self.assertEqual(out["rung"], "preregistered")
        self.assertEqual(out["words"], "preregistered: one locked week supported it")

    def test_two_separate_supported_weeks_are_repeated(self):
        self.week(W1, MOSTLY_DONE)
        self.week(W2, MOSTLY_DONE)
        self.assertEqual(self.rung()["words"], "repeated: two locked weeks supported it")

    def test_another_habits_weeks_do_not_count(self):
        self.week(W1, MOSTLY_DONE)
        self.week(W2, MOSTLY_DONE, name=OTHER)
        self.assertEqual(self.rung()["rung"], "preregistered")
        self.assertEqual(self.rung(OTHER)["rung"], "preregistered")
        self.assertEqual(self.rung("  synthetic WALK after lunch ")["rung"], "preregistered")

    def test_contradicted_never_climbs(self):
        self.assertEqual(self.week(W1, MOSTLY_NO), prediction.CONTRADICTS)
        self.assertEqual(self.week(W2, MOSTLY_NO), prediction.CONTRADICTS)
        out = self.rung()
        self.assertIsNone(out["rung"])
        self.assertIn("two locked weeks did not", out["words"])

    def test_fewer_than_three_logged_days_is_inconclusive_and_never_climbs(self):
        self.assertEqual(self.week(W1, TWO_DAYS), prediction.INCONCLUSIVE)
        self.assertEqual(self.week(W2, TWO_DAYS), prediction.INCONCLUSIVE)
        self.assertIsNone(self.rung()["rung"])
        self.week(W3, MOSTLY_DONE)
        self.assertEqual(self.rung()["words"], "preregistered: one locked week supported it, two locked weeks did not")

    def test_a_locked_week_without_a_receipt_is_pending_and_never_climbs(self):
        self.week(W1, MOSTLY_DONE)
        self.week(W2, MOSTLY_DONE, judge=False)
        self.assertEqual(self.rung()["rung"], "preregistered")
        weeks = strength.habit_claim(self.st, HABIT)["weeks"]
        self.assertEqual([w["verdict"] for w in weeks], ["supports", "pending"])

    def test_never_replicated_from_the_ledger(self):
        for i in range(6):
            self.week(W1 + timedelta(days=14 * i), MOSTLY_DONE)
        out = self.rung()
        self.assertEqual(out["rung"], "repeated")
        self.assertNotIn("citation", strength.habit_claim(self.st, HABIT))

    def test_a_loop_row_names_the_habit_when_the_week_file_is_gone(self):
        self.week(W1, MOSTLY_DONE)
        (self.st / f"habit-{W1.isoformat()}.json").unlink()
        with open(self.st / prediction.PREDICTIONS_FILE, "a") as f:
            f.write(json.dumps({"kind": "loop", "week_of": W1.isoformat(), "habit": HABIT,
                                "prediction": "prediction locked", "outcome": "supports"}) + "\n")
        self.assertEqual(self.rung()["rung"], "preregistered")

    def test_an_unnamed_week_counts_only_for_itself(self):
        self.week(W1, MOSTLY_DONE)
        self.week(W2, MOSTLY_DONE)
        for w in (W1, W2):
            (self.st / f"habit-{w.isoformat()}.json").unlink()
        self.assertIsNone(self.rung()["rung"])
        self.assertEqual(self.rung(None, W2.isoformat())["rung"], "preregistered")

    def test_a_torn_ledger_line_is_skipped(self):
        self.week(W1, MOSTLY_DONE)
        with open(self.st / prediction.PREDICTIONS_FILE, "a") as f:
            f.write('{"kind": "receipt", "week_of": \n')
        self.assertEqual(self.rung()["rung"], "preregistered")

    def test_read_only(self):
        self.week(W1, MOSTLY_DONE)
        self.week(W2, MOSTLY_NO)
        before = sorted((p.name, p.read_bytes()) for p in self.st.iterdir())
        self.rung()
        strength.habit_claim(self.st, HABIT)
        self.assertEqual(sorted((p.name, p.read_bytes()) for p in self.st.iterdir()), before)

    def test_no_state_dir(self):
        out = strength.habit_strength(self.st / "nowhere", HABIT)
        self.assertIsNone(out["rung"])


if __name__ == "__main__":
    unittest.main()
