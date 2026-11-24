"""habit_replies.ingest: a Done / No / Skip reply to the habit check-in lands in habit.json. Synthetic data only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import sys
import tempfile
import unittest
from datetime import timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import habit_replies, jobs  # noqa: E402

H = 3600.0
SENT = 1894708800.0          # 2030-01-15 12:00 UTC: a synthetic check-in send
DAY = "2030-01-15"
UTC = timezone.utc
HABIT = {"week_of": "2030-01-11", "habit": "Lights down when wind-down starts", "start": "Dim one lamp",
         "at": "2030-01-11T08:00:00Z", "checkins": {"2030-01-11": "Done"}}


def checkin_row(t):
    return jobs.sent_entry(jobs.HABIT_CHECKIN, t - jobs.HABIT_CUE_AFTER_S, t)


class Ingest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.st = Path(self.tmp.name)
        self.habit(HABIT)
        self.sent([checkin_row(SENT)])

    def tearDown(self):
        self.tmp.cleanup()

    def habit(self, h):
        (self.st / "habit.json").write_text(json.dumps(h))

    def sent(self, rows):
        (self.st / "jobs-sent.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def checkins(self):
        return json.loads((self.st / "habit.json").read_text())["checkins"]

    def ingest(self, replies, now=SENT + 2 * H, **kw):
        return habit_replies.ingest(self.st, replies, now, tz=UTC, **kw)

    def test_done_reply_lands_on_the_check_in_day(self):
        rows = self.ingest([(SENT + 600, "Done")])
        self.assertEqual(self.checkins(), {"2030-01-11": "Done", DAY: "Done"})
        self.assertEqual([(r["day"], r["answer"], r["action"]) for r in rows], [(DAY, "Done", "write")])

    def test_skip_writes_skipped_and_no_writes_no(self):
        self.ingest([(SENT + 60, "skip")])
        self.assertEqual(self.checkins()[DAY], "Skipped")
        self.habit(HABIT)
        self.ingest([(SENT + 60, "NO")])
        self.assertEqual(self.checkins()[DAY], "No")

    def test_first_word_case_punctuation_and_one_emoji_ignored(self):
        for text, want in [("done!", "Done"), ("Done. dimmed the lamp", "Done"), ("Skip✅", "Skipped"),
                           ("no 🙃", "No"), ("Done👍🏽", "Done"), ("  DONE…", "Done"), ("Skip,", "Skipped")]:
            self.habit(HABIT)
            self.ingest([(SENT + 60, text)])
            self.assertEqual(self.checkins().get(DAY), want, text)

    def test_anything_else_is_ignored_never_no(self):
        for text in ["nope", "maybe later", "not today", "✅", "", "   ", "done-ish", "👍👍"]:
            self.habit(HABIT)
            rows = self.ingest([(SENT + 60, text)])
            self.assertNotIn(DAY, self.checkins(), text)
            self.assertEqual([r["action"] for r in rows], ["ignore"], text)

    def test_reply_before_the_send_or_after_the_ask_expires_is_ignored(self):
        stale = jobs.HABIT_STALE_S
        rows = self.ingest([(SENT - 1, "Done"), (SENT, "Done"), (SENT + stale + 1, "Done")], now=SENT + stale + 2)
        self.assertNotIn(DAY, self.checkins())
        self.assertEqual([r["action"] for r in rows], ["ignore"] * 3)

    def test_reply_at_the_last_second_of_the_ask_counts(self):
        self.ingest([(SENT + jobs.HABIT_STALE_S, "Done")], now=SENT + jobs.HABIT_STALE_S)
        self.assertEqual(self.checkins()[DAY], "Done")

    def test_reply_after_now_is_ignored(self):
        self.ingest([(SENT + 2 * H, "Done")], now=SENT + H)
        self.assertNotIn(DAY, self.checkins())

    def test_only_the_latest_check_in_send_counts(self):
        older = SENT - 24 * H
        self.sent([checkin_row(older), {"t": SENT - 2 * H, "k": "x", "job": jobs.WAKE_BRIEF.name}, checkin_row(SENT)])
        self.ingest([(older + 60, "No"), (SENT + 60, "Done")])
        self.assertEqual(self.checkins(), {"2030-01-11": "Done", DAY: "Done"})

    def test_a_send_after_now_is_not_the_latest(self):
        self.sent([checkin_row(SENT), checkin_row(SENT + 24 * H)])
        self.ingest([(SENT + 60, "Done")], now=SENT + H)
        self.assertEqual(self.checkins()[DAY], "Done")

    def test_first_real_tap_wins_within_one_ask(self):
        rows = self.ingest([(SENT + 120, "No"), (SENT + 60, "hmm"), (SENT + 180, "Done")])
        self.assertEqual(self.checkins()[DAY], "No")
        self.assertEqual([r["action"] for r in rows], ["ignore", "write", "keep"])

    def test_never_overwrites_an_answer_already_there(self):
        for prior in ("Done", "No", "Skipped"):
            self.habit(dict(HABIT, checkins={DAY: prior}))
            rows = self.ingest([(SENT + 60, "Skip" if prior != "Skipped" else "Done")])
            self.assertEqual(self.checkins(), {DAY: prior})
            self.assertEqual([r["action"] for r in rows], ["keep"])

    def test_keeps_every_other_key(self):
        h = dict(HABIT, extra={"note": "synthetic"}, cue="wake")
        self.habit(h)
        self.ingest([(SENT + 60, "Done")])
        out = json.loads((self.st / "habit.json").read_text())
        self.assertEqual(out, dict(h, checkins={"2030-01-11": "Done", DAY: "Done"}))

    def test_day_is_the_local_date_of_the_check_in_send(self):
        from datetime import timedelta
        late = 1894751940.0      # 2030-01-15 23:59 UTC
        self.sent([checkin_row(late)])
        habit_replies.ingest(self.st, [(late + 120, "Done")], late + H, tz=timezone(timedelta(hours=2)))
        self.assertEqual(self.checkins().get("2030-01-16"), "Done")
        self.assertNotIn(DAY, self.checkins())

    def test_write_is_atomic_temp_file_and_rename(self):
        calls = []
        real = os.replace

        def spy(src, dst):
            calls.append((Path(src).parent, Path(dst)))
            real(src, dst)
        habit_replies.os.replace = spy
        try:
            self.ingest([(SENT + 60, "Done")])
        finally:
            habit_replies.os.replace = real
        self.assertEqual(calls, [(self.st, self.st / "habit.json")])
        self.assertEqual(sorted(p.name for p in self.st.iterdir()), ["habit.json", "jobs-sent.jsonl"])

    def test_dry_run_writes_nothing(self):
        before = (self.st / "habit.json").read_bytes()
        rows = self.ingest([(SENT + 60, "Done")], dry_run=True)
        self.assertEqual((self.st / "habit.json").read_bytes(), before)
        self.assertEqual([(r["day"], r["answer"], r["action"]) for r in rows], [(DAY, "Done", "would write")])

    def test_no_check_in_sent_writes_nothing(self):
        (self.st / "jobs-sent.jsonl").unlink()
        before = (self.st / "habit.json").read_bytes()
        rows = self.ingest([(SENT + 60, "Done")])
        self.assertEqual((self.st / "habit.json").read_bytes(), before)
        self.assertEqual([r["action"] for r in rows], ["nothing"])
        self.assertIn("no habit check-in", rows[0]["reason"])

    def test_no_habit_json_writes_nothing(self):
        (self.st / "habit.json").unlink()
        rows = self.ingest([(SENT + 60, "Done")])
        self.assertFalse((self.st / "habit.json").exists())
        self.assertEqual([r["action"] for r in rows], ["nothing"])

    def test_no_replies_says_so(self):
        rows = self.ingest([])
        self.assertEqual([r["action"] for r in rows], ["nothing"])
        self.assertIn("no reply", rows[0]["reason"])

    def test_rows_are_plain_words_and_never_echo_the_reply(self):
        rows = self.ingest([(SENT + 60, "Done, synthetic-secret-words"), (SENT + 90, "synthetic-other")])
        for r in rows:
            self.assertEqual(set(r), {"reply_at", "day", "answer", "action", "reason"})
            self.assertNotIn("synthetic", json.dumps(r))
            self.assertIsInstance(r["reason"], str)


if __name__ == "__main__":
    unittest.main()
