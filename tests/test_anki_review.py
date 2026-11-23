"""The week review's Anki line (anki.review_line, words only), last before the Keep / Drop line; empty when
the week is unknown (no collection set, unreadable). Synthetic collections, a fake push, a fixed clock.
"""
import json
import re
import sys
import tempfile
import unittest
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import anki, jobs, jobs_runner  # noqa: E402
from test_anki_reviews import collection  # noqa: E402
from test_flow_week_hooks import FakePush  # noqa: E402

KD = "\nReply: Keep / Drop"
UTC = timezone.utc
NOW = 2_000_000_000.0
TODAY = datetime.fromtimestamp(NOW, UTC).date()


def on(days_ago: int, h: float = 9.0) -> float:
    return datetime.combine(TODAY - timedelta(days=days_ago), time(), tzinfo=UTC).timestamp() + h * 3600


class ReviewLine(unittest.TestCase):
    def test_words_only_and_empty_when_unknown(self):
        self.assertEqual(anki.review_line({"label": anki.t1(anki.SOME)}), "Anki: some reviews this week (measured)")
        self.assertEqual(anki.review_line({"label": anki.t1(anki.NONE)}), "Anki: no reviews this week (measured)")
        self.assertEqual(anki.review_line({"label": anki.t1(anki.MOST)}),
                         "Anki: reviewed most days this week (measured)")
        for w in (None, {}, {"label": anki.t1(anki.UNKNOWN)}, {"label": anki.t1("7 reviews")}, "x"):
            self.assertEqual(anki.review_line(w), "", w)


class Review(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.cfg = self.root / "config.json"
        self.cfg.write_text("{}")
        self.env = {"LIMITLESS_CONFIG": str(self.cfg)}
        self.week_of = TODAY - timedelta(days=6)
        self.habit = {"week_of": self.week_of.isoformat(), "habit": "Synthetic habit",
                      "checkins": {self.week_of.isoformat(): "Done"}}
        (self.st / "habit.json").write_text(json.dumps(self.habit))
        (self.st / "events.jsonl").write_text(json.dumps({"event": "habit_cue", "at": NOW - 60}) + "\n")

    def review(self, env=None):
        push = FakePush()
        rows = jobs_runner.run_once(self.st, NOW, push=push, dry_run=False, env=env or self.env, home=self.root,
                                    tz=UTC)
        self.assertEqual({r["job"]: r for r in rows}["Week review"]["action"], jobs.DELIVER)
        (text,) = [c[1] for c in push.calls if c[0] == "Week review"]
        self.assertTrue(text.endswith(KD), text)
        return text[:-len(KD)].split("\n")

    def test_body_puts_the_anki_line_last_before_the_choices(self):
        text = jobs.week_review_text(self.habit)
        self.assertEqual(jobs_runner.body(jobs.WEEK_REVIEW, self.habit, rides_line="Rides: z.", sleep_line="Sleep: s.",
                                          anki_line="Anki: a."),
                         text + "\nRides: z.\nSleep: s.\nAnki: a." + KD)
        self.assertEqual(jobs_runner.body(jobs.WEEK_REVIEW, self.habit, anki_line=""), text + KD)
        self.assertNotIn("Anki", jobs_runner.body(jobs.HABIT_CHECKIN, self.habit, anki_line="Anki: a."))

    def test_the_review_carries_the_anki_words(self):
        db = collection(self.root / "c.anki2", [on(d) for d in (0, 1, 3, 5)] + [on(9)])
        lines = self.review(dict(self.env, LIMITLESS_ANKI=str(db)))
        self.assertEqual(lines, [jobs.week_review_text(self.habit), "Anki: reviewed most days this week (measured)"])
        self.assertEqual(re.findall(r"\d", lines[-1]), [])

    def test_some_and_none(self):
        db = collection(self.root / "some.anki2", [on(2), on(2, 10)])
        self.assertEqual(jobs_runner.week_anki(self.st, self.habit, dict(self.env, LIMITLESS_ANKI=str(db)),
                                               self.root, UTC, TODAY), "Anki: some reviews this week (measured)")
        db = collection(self.root / "none.anki2", [on(12)])
        line = jobs_runner.week_anki(self.st, self.habit, dict(self.env, LIMITLESS_ANKI=str(db)), self.root, UTC,
                                     TODAY)
        self.assertEqual(line, "Anki: no reviews this week (measured)")
        for bad in ("streak", "missed", "failed", "behind"):
            self.assertNotIn(bad, line)

    def test_unknown_leaves_the_review_unchanged(self):
        self.assertEqual(self.review(), [jobs.week_review_text(self.habit)])            # no collection set
        (self.st / "jobs-sent.jsonl").unlink()
        gone = dict(self.env, LIMITLESS_ANKI=str(self.root / "gone.anki2"))
        self.assertEqual(self.review(gone), [jobs.week_review_text(self.habit)])        # missing file
        self.assertEqual(jobs_runner.week_anki(self.st, None, self.env, self.root, UTC, TODAY), "")   # no week
        self.assertEqual(jobs_runner.week_anki(self.st, self.habit, self.env, self.root, UTC), "")   # no today

    def test_the_collection_is_never_written(self):
        db = collection(self.root / "c.anki2", [on(1)], wal=True)
        before = (db.read_bytes(), db.stat().st_mtime_ns, sorted(p.name for p in self.root.iterdir()))
        self.review(dict(self.env, LIMITLESS_ANKI=str(db)))
        self.assertEqual((db.read_bytes(), db.stat().st_mtime_ns, sorted(p.name for p in self.root.iterdir())),
                         before)


if __name__ == "__main__":
    unittest.main()
