"""Scorecard measured rows three (habit loop), four (evidence loop) and seven (privacy).

scorecard.measured_audits reads them from what the plugin already writes: the stop rule's loop rows and the
locks and receipts in predictions.jsonl, the kept habit files, and the tier audit log. Synthetic fixtures only
(invented habits, synthetic ledgers and a synthetic audit log). Fixed clock, UTC.
"""
import json
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import prediction, scorecard as sc, stop_rule, tier_audit, tools  # noqa: E402

UTC = timezone.utc
NOW = 2_000_000_000.0
TODAY = datetime.fromtimestamp(NOW, UTC).date()
DAY = 86400
DIGIT = re.compile(r"\d")

# The public ROADMAP wording of the three rows, as the brief defines them.
ROW3 = "Habit loop: 4 weekly cycles"
ROW4 = "Evidence loop: >=2 locked N-of-1 experiments with outcome receipts"
ROW7 = "Privacy: no raw health data above T1, 0 leaks"
ROW3_DEF = ("a cycle is one habit week with a confirmed start and a Keep or Drop decision row; met when the last "
            "four habit weeks each closed with a decision; not met when a finished week has no decision; unknown "
            "when no habit week was ever started")
ROW4_DEF = ("count locked predictions with a judged receipt (supports, contradicts or inconclusive, not pending); "
            "met at two or more; not met when a lock exists but fewer than two are judged; unknown when none was "
            "ever locked")
ROW7_DEF = ("tier_audit.check over the configured audit log for the last seven days; met when the log has rows and "
            "nothing digit-bearing went out without the opt-in; not met when one went out; unknown when no audit "
            "log is set or it has no rows in the window")

HEADER = "| # | Criterion | Status | Evidence (latest) | Weeks green |\n|---|---|---|---|---|\n"


def table(status=None):
    """A NORTH-STAR-shaped synthetic table: rows one to seven, all green unless ``status`` says otherwise."""
    names = {1: "Loop uptime", 2: "Delivery", 3: ROW3, 4: ROW4, 5: "Capture triage", 6: "Review held", 7: ROW7}
    status = status or {}
    return HEADER + "".join(f"| {n} | {names[n]} | {status.get(n, 'green')} | synthetic | 1 |\n" for n in names)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.env = {"LIMITLESS_CONFIG": str(self.root / "none.json")}
        self.cfg = {}

    # --- habit weeks -------------------------------------------------------------------------------------------
    def week(self, weeks_ago, decision=None, current=False):
        """A started synthetic habit week ``weeks_ago`` weeks before this one (habit.json when ``current``, else
        the kept habit-<week_of>.json), with its loop row when ``decision`` is Keep or Drop."""
        start = TODAY - timedelta(days=7 * weeks_ago)
        habit = {"habit": "Synthetic stretch", "week_of": start.isoformat(), "start": None, "checkins": {}}
        name = "habit.json" if current else f"habit-{start.isoformat()}.json"
        (self.st / name).write_text(json.dumps(habit))
        if decision:
            stop_rule.record_loop(self.st, habit, decision, start.isoformat(), now=NOW)
        return start

    # --- locks and receipts ------------------------------------------------------------------------------------
    def lock(self, weeks_ago, verdict=None):
        """A synthetic locked prediction for a week ``weeks_ago`` back, with a receipt of ``verdict`` if given."""
        week = (TODAY - timedelta(days=7 * weeks_ago)).isoformat()
        locked_at = f"{week}T00:00:00+00:00"
        rows = [{"kind": "prediction", "week_of": week, "text": "More done days", "metric": "logged",
                 "direction": "at_least 1 of 2", "falsifier": None, "lag_days": 0, "locked_at": locked_at}]
        if verdict:
            rows.append({"kind": "receipt", "week_of": week, "locked_at": locked_at, "verdict": verdict,
                         "reason": "synthetic", "outcome": None, "at": locked_at})
        for r in rows:
            prediction._append(self.st, r)

    # --- the tier audit log ------------------------------------------------------------------------------------
    def audit_log(self, *kinds, age_days=1):
        """A synthetic audit log, one row per kind: allowed (no digit), blocked (a digit, stopped), opted (a digit
        under the opt-in) or leaked (a digit that went out without the opt-in)."""
        at = NOW - age_days * DAY
        text = {"allowed": "words only", "blocked": "digit 1", "opted": "digit 2", "leaked": "digit 3"}
        rows = []
        for k in kinds:
            ev = tier_audit.event("hook:synthetic", text[k], k == "opted", now=at)
            if k == "leaked":
                ev["blocked"] = False     # a bug path: a digit-bearing result that went out unstopped
            rows.append(ev)
        path = self.root / "audit.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        self.cfg["audit_path"] = str(path)
        return path

    def audits(self):
        return {row["n"]: (row, a) for row, a in sc.measured_audits(self.st, self.cfg, NOW, UTC, env=self.env,
                                                                     home=self.root)}

    def row(self, n):
        return self.audits()[n][0]


class HabitLoop(Fixture):
    def test_row_three_is_the_habit_loop(self):
        m = self.row(3)
        self.assertEqual(m["criterion_words"], "habit loop")
        self.assertEqual(set(m), {"n", "criterion_words", "label", "goal"})

    def test_no_week_ever_started_is_unknown(self):
        m, a = self.audits()[3]
        self.assertEqual(m["goal"], "unknown")
        self.assertTrue(m["label"].startswith("unknown: "), m)
        self.assertIsNone(a)

    def test_four_decided_weeks_in_a_row_are_met(self):
        for k, d in ((4, "Keep"), (3, "Drop"), (2, "Keep"), (1, "Keep")):
            self.week(k, d)
        m, a = self.audits()[3]
        self.assertEqual(m["goal"], "met")
        self.assertEqual(m["label"], sc.HABIT_MET)
        self.assertEqual(a["recent_closed"], 4)

    def test_a_finished_week_with_no_decision_is_not_met(self):
        for k, d in ((5, "Keep"), (4, "Keep"), (3, None), (2, "Keep"), (1, "Keep")):
            self.week(k, d)
        m = self.row(3)
        self.assertEqual((m["goal"], m["label"]), ("not met", sc.HABIT_OPEN))

    def test_an_old_undecided_week_before_four_closed_ones_does_not_count(self):
        for k, d in ((6, None), (4, "Keep"), (3, "Keep"), (2, "Drop"), (1, "Keep")):
            self.week(k, d)
        self.assertEqual(self.row(3)["goal"], "met")

    def test_fewer_than_four_closed_weeks_is_not_met(self):
        self.week(2, "Keep")
        self.week(1, "Drop")
        m = self.row(3)
        self.assertEqual((m["goal"], m["label"]), ("not met", sc.HABIT_FEW))

    def test_the_running_week_never_counts_against_the_cycles(self):
        for k in (4, 3, 2, 1):
            self.week(k, "Keep")
        self.week(0, None, current=True)                # days one to seven: still running, undecided
        self.assertEqual(self.row(3)["goal"], "met")

    def test_skipped_and_unanswered_days_never_count_against_a_cycle(self):
        for k in (4, 3, 2, 1):
            start = self.week(k, "Keep")
            kept = self.st / f"habit-{start.isoformat()}.json"
            h = json.loads(kept.read_text())
            h["checkins"] = {start.isoformat(): "Skipped", (start + timedelta(days=1)).isoformat(): "No"}
            kept.write_text(json.dumps(h))
        self.assertEqual(self.row(3)["goal"], "met")

    def test_only_a_running_week_is_not_met_never_unknown(self):
        self.week(0, None, current=True)
        self.assertEqual(self.row(3)["goal"], "not met")

    def test_a_broken_habit_file_and_ledger_are_unknown_not_a_traceback(self):
        (self.st / "habit.json").write_text("{not json")
        (self.st / "predictions.jsonl").write_bytes(b"\xff\xfe{torn\n")
        m = self.row(3)
        self.assertEqual(m["goal"], "unknown")

    def test_label_has_no_digit(self):
        for setup in (lambda: None, lambda: self.week(3, None), lambda: [self.week(k, "Keep") for k in (2, 1, 4)]):
            setup()
            self.assertIsNone(DIGIT.search(self.row(3)["label"]))


class EvidenceLoop(Fixture):
    def test_row_four_is_the_evidence_loop(self):
        self.assertEqual(self.row(4)["criterion_words"], "evidence loop")

    def test_no_lock_ever_is_unknown_never_met(self):
        m, a = self.audits()[4]
        self.assertEqual((m["goal"], m["label"]), ("unknown", "unknown: no experiment locked"))
        self.assertIsNone(a)

    def test_two_judged_receipts_are_met(self):
        self.lock(3, "supports")
        self.lock(2, "contradicts")
        m, a = self.audits()[4]
        self.assertEqual((m["goal"], m["label"]), ("met", sc.EVIDENCE_MET))
        self.assertEqual((a["locked"], a["judged"]), (2, 2))

    def test_inconclusive_is_judged(self):
        self.lock(3, "inconclusive")
        self.lock(2, "supports")
        self.assertEqual(self.row(4)["goal"], "met")

    def test_locks_with_pending_or_no_receipt_are_not_met(self):
        self.lock(3, "supports")
        self.lock(2, "pending")
        self.lock(1)
        m, a = self.audits()[4]
        self.assertEqual((m["goal"], m["label"]), ("not met", sc.EVIDENCE_FEW))
        self.assertEqual((a["locked"], a["judged"]), (3, 1))

    def test_one_lock_without_a_receipt_is_not_met(self):
        self.lock(1)
        self.assertEqual(self.row(4)["goal"], "not met")

    def test_a_receipt_for_another_lock_is_not_this_ones(self):
        self.lock(3)
        week = (TODAY - timedelta(days=21)).isoformat()
        prediction._append(self.st, {"kind": "receipt", "week_of": week, "locked_at": "not this lock",
                                     "verdict": "supports"})
        self.lock(2, "supports")
        self.assertEqual(self.audits()[4][1]["judged"], 1)

    def test_loop_rows_are_not_locks(self):
        self.week(1, "Keep")
        self.assertEqual(self.row(4)["goal"], "unknown")

    def test_a_torn_ledger_is_read_around(self):
        self.lock(3, "supports")
        with open(self.st / "predictions.jsonl", "a") as f:
            f.write("{torn\n[1, 2]\n")
        self.lock(2, "supports")
        self.assertEqual(self.row(4)["goal"], "met")

    def test_label_has_no_digit(self):
        for setup in (lambda: None, lambda: self.lock(1), lambda: self.lock(2, "supports"),
                      lambda: self.lock(3, "supports")):
            setup()
            self.assertIsNone(DIGIT.search(self.row(4)["label"]))


if __name__ == "__main__":
    unittest.main()
