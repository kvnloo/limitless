"""delivery_audit: kevin-push's "log (no sender profile)" row is a transport failure and its own miss reason.

kevin-push logs that row when its Hermes sender profile cannot exist (push_sender.check BROKEN) and it started
no hermes. The audit counts it in send_failures like "log (telegram rc=N)" (SEND_FAILING wording unchanged)
and words a wake brief missed that way "not sent: the sender profile is missing", right before "logged but
not sent" in MISS_REASONS and MISS_ORDER. Synthetic rows, a fixed clock, UTC; the last test reads a log the
real bin/kevin-push wrote in a temp HOME with a fake hermes on PATH. Nothing is sent.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import delivery_audit as da, jobs, push_sender  # noqa: E402

UTC = timezone.utc
NOW = 2_000_000_000.0
TODAY = datetime.fromtimestamp(NOW, UTC).date()
NO_SENDER = "log (no sender profile)"
MISSING = "not sent: the sender profile is missing"


def row(days_ago=0, how="telegram", title="Pick one", hour=9, tag="x"):
    at = int(datetime(TODAY.year, TODAY.month, TODAY.day, hour, tzinfo=UTC).timestamp()) - days_ago * 86400
    return {"at": at, "tag": tag, "cls": "decision", "title": title, "body": "Keep the loop?\nReply: Yes / No",
            "how": how}


def brief(days_ago=0, how="telegram", hour=7):
    return row(days_ago, how, title=jobs.WAKE_BRIEF.send_title, hour=hour, tag="limitless")


def wake(*days_ago):
    return [TODAY - timedelta(days=n) for n in days_ago]


class TheWords(unittest.TestCase):
    def test_kevin_push_and_the_audit_share_one_how_word(self):
        self.assertEqual(push_sender.NO_SENDER_HOW, NO_SENDER)
        self.assertEqual(da.NO_SENDER, NO_SENDER)

    def test_the_new_reason_sits_right_before_logged_but_not_sent(self):
        self.assertEqual(da.MISS_NO_SENDER, MISSING)
        self.assertEqual(da.MISS_REASONS.index(MISSING) + 1, da.MISS_REASONS.index(da.MISS_LOGGED))
        self.assertEqual(da.MISS_ORDER.index(MISSING) + 1, da.MISS_ORDER.index(da.MISS_LOGGED))
        self.assertFalse(any(c.isdigit() for c in MISSING))

    def test_miss_reason_names_it(self):
        self.assertEqual(da.miss_reason(NO_SENDER), MISSING)
        self.assertEqual(da.miss_reason("log (telegram rc=1)"), da.MISS_LOGGED)   # unchanged


class Misses(unittest.TestCase):
    def test_a_brief_not_sent_for_a_missing_sender_has_its_own_reason(self):
        out = da.brief_misses([brief(0, NO_SENDER)], wake(0), UTC)
        self.assertEqual(out["days"], {TODAY.isoformat(): MISSING})
        self.assertEqual(out["label"], f"missed wake briefs: {MISSING} (all)")

    def test_it_wins_over_logged_but_not_sent_on_the_same_day(self):
        for other in ("log (telegram rc=1)", "log", "folded (brief line)"):
            rows = [brief(0, other, hour=6), brief(0, NO_SENDER, hour=8)]
            with self.subTest(other=other):
                self.assertEqual(da.brief_misses(rows, wake(0), UTC)["days"][TODAY.isoformat()], MISSING)
                self.assertEqual(da.brief_misses(rows[::-1], wake(0), UTC)["days"][TODAY.isoformat()], MISSING)

    def test_the_causes_before_the_transport_still_come_first(self):
        for how, reason in (("held (sleep mode)", da.MISS_SLEEP), ("log (quiet: on)", da.MISS_QUIET),
                            ("log (duplicate)", da.MISS_REPEAT), ("log (daily cap)", da.MISS_GATE)):
            rows = [brief(0, NO_SENDER, hour=6), brief(0, how, hour=8)]
            with self.subTest(how=how):
                self.assertEqual(da.brief_misses(rows, wake(0), UTC)["days"][TODAY.isoformat()], reason)

    def test_a_delivered_brief_that_day_is_still_no_miss(self):
        out = da.brief_misses([brief(0, NO_SENDER, hour=6), brief(0, hour=8)], wake(0), UTC)
        self.assertEqual(out["missed"], 0)

    def test_the_miss_clause_names_it(self):
        a = da.audit([brief(0, NO_SENDER)], wake_days=wake(0), today=TODAY, tz=UTC)
        self.assertEqual(da.miss_clause(a), f"most common miss: {MISSING}")


class SendFailures(unittest.TestCase):
    def test_it_is_a_transport_failure(self):
        self.assertTrue(da.send_failed(row(0, NO_SENDER)))
        self.assertTrue(da.send_failed(row(0, "log (telegram rc=1)")))
        self.assertFalse(da.send_failed(row(0, "log")))

    def test_a_run_of_them_is_worded_send_failing_unchanged(self):
        a = da.audit([row(0, hour=8), row(0, NO_SENDER, hour=9), row(0, NO_SENDER, hour=10)], today=TODAY, tz=UTC)
        self.assertEqual(a["send_failures"], {"failed": 2, "trailing": 2, "failing": True})
        self.assertEqual(a["labels"]["send"], da.SEND_FAILING)
        self.assertEqual(da.SEND_FAILING, "the last pushes failed to send")
        self.assertEqual(da.goal(a), da.GOAL_NOT_MET)

    def test_it_joins_a_run_with_rc_failures(self):
        a = da.audit([row(0, "log (telegram rc=1)", hour=9), row(0, NO_SENDER, hour=10)], today=TODAY, tz=UTC)
        self.assertEqual(a["send_failures"]["trailing"], 2)

    def test_a_delivery_after_it_ends_the_run(self):
        a = da.audit([row(0, NO_SENDER, hour=9), row(0, NO_SENDER, hour=10), row(0, hour=11)], today=TODAY, tz=UTC)
        self.assertEqual(a["send_failures"], {"failed": 2, "trailing": 0, "failing": False})


class Docs(unittest.TestCase):
    def test_the_delivery_audit_doc_names_the_row_the_reason_and_its_place(self):
        text = (ROOT / "docs" / "delivery-audit.md").read_text()
        for word in (f'"{NO_SENDER}"', MISSING, "push_sender.check", "right before logged but"):
            self.assertIn(word, " ".join(text.split()))
        self.assertIn(MISSING, text.split("## A real synthetic run", 1)[1])


class FromTheRealLog(unittest.TestCase):
    def test_a_log_kevin_push_wrote_with_no_sender_profile_reads_as_the_new_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            fakebin = home / "fakebin"
            fakebin.mkdir()
            hermes = fakebin / "hermes"
            hermes.write_text("#!/bin/sh\necho called >> \"$HOME/hermes-calls\"\nexit 0\n")
            hermes.chmod(hermes.stat().st_mode | stat.S_IEXEC)
            (home / "hermes-home").mkdir()                       # a Hermes home with no sender profile
            env = {k: v for k, v in os.environ.items() if not k.startswith("KEVIN_PUSH_")}
            env.update(HOME=str(home), PATH=f"{fakebin}:{os.environ['PATH']}", HERMES_HOME=str(home / "hermes-home"),
                       LIMITLESS_STATE=str(home / "state"), LIMITLESS_CONFIG=str(home / "none.json"),
                       LIMITLESS_SLEEPMODE=str(home / "none.jsonl"), CIRCADIAN_CLASS="report")
            for _ in range(2):
                r = subprocess.run([sys.executable, "-I", str(ROOT / "bin" / "kevin-push"), "limitless",
                                    jobs.WAKE_BRIEF.send_title, "Good morning."],
                                   env=child_env(env), capture_output=True, text=True, timeout=30)
                self.assertEqual(r.stdout.strip(), f"kevin-push: {NO_SENDER}", r.stderr)
            self.assertFalse((home / "hermes-calls").exists())
            rows, skipped = da.read_log(home / ".local/state/kevin-push/log.jsonl")
        days = sorted({datetime.fromtimestamp(r["at"], UTC).date() for r in rows})   # one, or two across midnight
        a = da.audit(rows, days=2, wake_days=days, today=days[-1], tz=UTC)
        self.assertEqual((len(rows), skipped), (2, 0))
        self.assertEqual(a["misses"]["days"], {d.isoformat(): MISSING for d in days})
        self.assertTrue(a["send_failures"]["failing"])


if __name__ == "__main__":
    unittest.main()
