"""The naps line in the wake brief (brief_post.finalize) and the week review (jobs_runner.body / run_once).

Words only, through tier_audit.gate; nothing when unknown. Synthetic Sleep-mode rows, a fake push, a fixed clock,
UTC as the local zone.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import re
import subprocess
import sys
import tempfile
import time as _time
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from limitless import brief_post, jobs, jobs_runner, naps, weekly_target  # noqa: E402
from test_flow_week_hooks import FakePush  # noqa: E402

UTC = timezone.utc
NOW = 2_000_000_000.0
TODAY = datetime.fromtimestamp(NOW, UTC).date()
KD = "\nReply: Keep / Drop"
DAY_LINE = "Naps yesterday: one short nap, close to the night (phone Sleep mode)"


def rows_for(days_back=1, nap=(20, 0, 20, 40), base=None, local=False):
    """Sleep-mode rows: a night before and after day ``today - days_back`` and one nap in it."""
    base = TODAY if base is None else base
    d = base - timedelta(days=days_back)

    def ts(day, hh, mm=0):
        dt = datetime.combine(day, time(hh, mm))
        return dt.timestamp() if local else dt.replace(tzinfo=UTC).timestamp()
    out = [(ts(d - timedelta(days=1), 23), True), (ts(d, 7), False)]
    if nap:
        out += [(ts(d, nap[0], nap[1]), True), (ts(d, nap[2], nap[3]), False)]
    out += [(ts(d, 23), True), (ts(d + timedelta(days=1), 6), False)]
    return [{"at": t, "on": o} for t, o in out]


class State(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.audit = self.root / "audit.jsonl"
        self.env = {"LIMITLESS_CONFIG": str(self.root / "config.json"), "LIMITLESS_AUDIT": str(self.audit)}

    def sleepmode(self, rows):
        (self.st / "sleepmode.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def audited(self):
        return [json.loads(ln) for ln in self.audit.read_text().splitlines()] if self.audit.exists() else []


class BriefLine(State):
    def test_finalize_adds_the_naps_line_last_only_when_given(self):
        self.assertEqual(brief_post.finalize("State: synthetic", None, NOW, naps=DAY_LINE),
                         "State: synthetic\n" + DAY_LINE)
        self.assertEqual(brief_post.finalize("State: synthetic", None, NOW, naps=""), "State: synthetic")
        self.assertEqual(brief_post.finalize("State: synthetic", None, NOW, saved=2, overnight="Overnight: one done",
                                             naps=DAY_LINE).splitlines()[-1], DAY_LINE)

    def test_brief_naps_words_from_yesterday(self):
        self.sleepmode(rows_for())
        self.assertEqual(jobs_runner.brief_naps(self.st, NOW, self.env, self.root, UTC), DAY_LINE)
        self.sleepmode(rows_for(nap=(12, 0, 12, 30)))
        self.assertEqual(jobs_runner.brief_naps(self.st, NOW, self.env, self.root, UTC),
                         "Naps yesterday: one short nap (phone Sleep mode)")
        self.sleepmode(rows_for(nap=None))
        self.assertEqual(jobs_runner.brief_naps(self.st, NOW, self.env, self.root, UTC),
                         "Naps yesterday: none (phone Sleep mode)")

    def test_unknown_is_no_line(self):
        self.assertEqual(jobs_runner.brief_naps(self.st, NOW, self.env, self.root, UTC), "")
        self.sleepmode(rows_for(days_back=5))
        self.assertEqual(jobs_runner.brief_naps(self.st, NOW, self.env, self.root, UTC), "")
        (self.st / "sleepmode.jsonl").unlink()
        (self.st / "sleepmode.jsonl").mkdir()          # unreadable: unknown, never a traceback
        self.assertEqual(jobs_runner.brief_naps(self.st, NOW, self.env, self.root, UTC), "")

    def test_the_line_passes_the_tier_audit_gate(self):
        self.sleepmode(rows_for())
        jobs_runner.brief_naps(self.st, NOW, self.env, self.root, UTC)
        (row,) = self.audited()
        self.assertEqual((row["hook"], row["tier"], row["digits"], row["blocked"]), ("brief:naps", "T1", 0, False))

    def test_sleep_mode_is_never_written(self):
        self.sleepmode(rows_for())
        p = self.st / "sleepmode.jsonl"
        before = (p.read_bytes(), p.stat().st_mtime_ns)
        jobs_runner.brief_naps(self.st, NOW, self.env, self.root, UTC)
        self.assertEqual((p.read_bytes(), p.stat().st_mtime_ns), before)


class WeekLine(State):
    def setUp(self):
        super().setUp()
        self.week_of = TODAY - timedelta(days=6)
        self.habit = {"week_of": self.week_of.isoformat(), "habit": "Synthetic habit",
                      "checkins": {self.week_of.isoformat(): "Done"}}
        (self.st / "habit.json").write_text(json.dumps(self.habit))
        (self.st / "events.jsonl").write_text(json.dumps({"event": "habit_cue", "at": NOW - 60}) + "\n")

    def review(self):
        push = FakePush()
        rows = jobs_runner.run_once(self.st, NOW, push=push, dry_run=False, env=self.env, home=self.root, tz=UTC)
        self.assertEqual({r["job"]: r for r in rows}["Week review"]["action"], jobs.DELIVER, rows)
        (text,) = [c[1] for c in push.calls if c[0] == "Week review"]
        self.assertTrue(text.endswith(KD), text)
        return text[:-len(KD)].split("\n")

    def test_body_puts_the_naps_line_after_the_sleep_line(self):
        text = jobs_runner.body(jobs.WEEK_REVIEW, self.habit, sleep_line="Sleep: s.", anki_line="Anki: a.",
                                naps_line="Naps this week: none (phone Sleep mode)")
        self.assertEqual(text.split("\n")[-4:-1], ["Sleep: s.", "Naps this week: none (phone Sleep mode)",
                                                   "Anki: a."])
        self.assertNotIn("Naps", jobs_runner.body(jobs.HABIT_CHECKIN, self.habit, naps_line="Naps: n."))
        self.assertNotIn("Naps", jobs_runner.body(jobs.MIQ, self.habit, naps_line="Naps: n."))

    def test_week_naps_helper(self):
        self.sleepmode(rows_for(days_back=3))
        self.assertEqual(jobs_runner.week_naps(self.st, self.env, self.root, TODAY, UTC),
                         "Naps this week: one, close to the night (phone Sleep mode).")
        self.assertEqual(jobs_runner.week_naps(self.st, self.env, self.root), "")       # no today: no clock read
        self.sleepmode(rows_for(days_back=20))
        self.assertEqual(jobs_runner.week_naps(self.st, self.env, self.root, TODAY, UTC), "")

    def test_the_review_carries_the_naps_words(self):
        self.sleepmode(rows_for(days_back=3) + rows_for(days_back=2, nap=(13, 0, 13, 20)))
        lines = self.review()
        self.assertEqual(lines[1:], [weekly_target.REVIEW_ON_THE_WAY,
                                     "Naps this week: a few, some close to the night (phone Sleep mode)."])
        self.assertEqual(re.findall(r"\d", lines[-1]), [])
        hooks = [r["hook"] for r in self.audited()]
        self.assertIn("week_review:naps", hooks)
        self.assertTrue(all(r["blocked"] is False for r in self.audited()))

    def test_no_sleep_mode_leaves_the_review_unchanged(self):
        self.assertEqual(self.review(), [jobs.week_review_text(self.habit), weekly_target.REVIEW_ON_THE_WAY])


FAKE_LOOP = """
import json, os
from pathlib import Path
def load_config():
    return {}
def build(cfg, day=None):
    return {"path": "/dev/null", "notif": "State: synthetic"}
def deliver(cfg, title, body, url=None, env=None):
    Path(os.environ["HOME"], "delivered.txt").write_text(body)
    return {"rc": 0, "shown": "telegram"}
"""


class BriefCli(unittest.TestCase):
    def test_send_adds_the_naps_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".local/lib").mkdir(parents=True)
            (home / ".local/lib/limitless_loop.py").write_text(FAKE_LOOP)
            st = home / ".local/state/limitless"
            st.mkdir(parents=True)
            today = date.fromtimestamp(_time.time())
            (st / "sleepmode.jsonl").write_text("".join(
                json.dumps(r) + "\n" for r in rows_for(nap=(12, 0, 12, 30), base=today, local=True)[:-2]))
            env = {k: v for k, v in os.environ.items() if not k.startswith("LIMITLESS_")}
            env["HOME"] = str(home)
            r = subprocess.run([sys.executable, "-I", str(ROOT / "bin" / "limitless-brief"), "send"], env=child_env(env),
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual((home / "delivered.txt").read_text(),
                             "State: synthetic\nNaps yesterday: one short nap (phone Sleep mode)")


if __name__ == "__main__":
    unittest.main()
