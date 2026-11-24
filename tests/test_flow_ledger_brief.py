"""The flow-ledger line in the wake brief: "Yesterday's work: <label>." when known, nothing when unknown.

Words only, through tier_audit.gate; no new push or job. Synthetic ActivityWatch DBs, a fixed clock, UTC as the
local zone (the CLI test uses this machine's zone and clock).
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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from limitless import brief_post, jobs, jobs_runner  # noqa: E402
from test_flow_week import make_db  # noqa: E402
from test_naps_brief import FAKE_LOOP  # noqa: E402

UTC = timezone.utc
DS = datetime(2033, 5, 17, tzinfo=UTC).timestamp()
NOW = DS + 86400.0 + 8 * 3600.0
M, H = 60.0, 3600.0
LINE = "Yesterday's work: two long blocks, one with a feed leak; one item landed."


def block(at, minutes=100, feed=False):
    mid = at + 40 * M
    return [(at, mid, "editor"), (mid, mid + 2 * M, "feed" if feed else "chat"), (mid + 2 * M, at + minutes * M, "editor")]


class State(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        (self.st / "lanes" / "done").mkdir(parents=True)
        self.db = self.st / "aw.db"
        self.cfg = self.root / "config.json"
        self.cfg.write_text(json.dumps({"aw_db": "aw.db", "flow_work_apps": ["editor"], "feed_apps": ["feed"],
                                        "work_queue_dir": "lanes"}))
        self.audit = self.root / "audit.jsonl"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg), "LIMITLESS_AUDIT": str(self.audit)}

    def done(self, mtime):
        p = self.st / "lanes" / "done" / "synthetic-lane.md"
        p.write_text("synthetic\n")
        os.utime(p, (mtime, mtime))

    def line(self, now=NOW):
        return jobs_runner.brief_flow_ledger(self.st, now, self.env, self.root, UTC)

    def audited(self):
        return [json.loads(ln) for ln in self.audit.read_text().splitlines()] if self.audit.exists() else []


class BriefLine(State):
    def test_yesterdays_work_in_words(self):
        make_db(self.db, spans=block(DS + 9 * H) + block(DS + 13 * H, feed=True))
        self.done(DS + 15 * H)
        self.assertEqual(self.line(), LINE)
        self.assertEqual(re.findall(r"\d", self.line()), [])
        for bad in ("editor", "synthetic", "chat"):
            self.assertNotIn(bad, self.line())

    def test_no_long_blocks(self):
        make_db(self.db, spans=block(DS + 9 * H, minutes=20))
        self.assertEqual(self.line(), "Yesterday's work: no long blocks; nothing landed.")

    def test_unknown_is_no_line(self):
        self.assertEqual(self.line(), "")                                   # no DB
        make_db(self.db, spans=block(DS - 30 * H))
        self.assertEqual(self.line(), "")                                   # no activity yesterday
        make_db(self.st / "b.db", spans=block(DS + 9 * H))
        self.cfg.write_text(json.dumps({"aw_db": "b.db"}))
        self.assertEqual(self.line(), "")                                   # no work apps
        self.assertEqual(self.audited(), [])                                # nothing to gate: nothing recorded

    def test_a_broken_state_is_no_line(self):
        self.db.mkdir()
        self.assertEqual(self.line(), "")
        self.assertEqual(jobs_runner.brief_flow_ledger(self.root / "missing", NOW, self.env, self.root, UTC), "")

    def test_the_line_passes_the_tier_audit_gate(self):
        make_db(self.db, spans=block(DS + 9 * H))
        self.line()
        (row,) = self.audited()
        self.assertEqual((row["hook"], row["tier"], row["digits"], row["blocked"]),
                         ("brief:flow_ledger", "T1", 0, False))

    def test_finalize_adds_the_line_only_when_given(self):
        self.assertEqual(brief_post.finalize("State: synthetic", None, NOW, work=LINE), "State: synthetic\n" + LINE)
        self.assertEqual(brief_post.finalize("State: synthetic", None, NOW, work=""), "State: synthetic")
        out = brief_post.finalize("State: synthetic", None, NOW, overnight="Overnight: one done", work=LINE,
                                  naps="Naps yesterday: none (phone Sleep mode)").splitlines()
        self.assertEqual(out[1:], ["Overnight: one done", LINE, "Naps yesterday: none (phone Sleep mode)"])

    def test_no_new_push_or_job(self):
        self.assertEqual(sorted(jobs.SPECS), sorted(s.name for s in (jobs.WAKE_BRIEF, jobs.NAP, jobs.MIQ,
                                                                     jobs.HABIT_CHECKIN, jobs.WEEK_REVIEW,
                                                                     jobs.BREAK_NUDGE)))
        make_db(self.db, spans=block(DS + 9 * H))
        rows = jobs_runner.run_once(self.st, NOW, push=None, dry_run=True, env=self.env, home=self.root, tz=UTC)
        self.assertFalse(any("ledger" in r["job"].lower() or "yesterday" in r["job"].lower() for r in rows))


class BriefCli(unittest.TestCase):
    def test_send_adds_the_work_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".local/lib").mkdir(parents=True)
            (home / ".local/lib/limitless_loop.py").write_text(FAKE_LOOP)
            st = home / ".local/state/limitless"
            st.mkdir(parents=True)
            yesterday = date.fromtimestamp(_time.time()) - timedelta(days=1)
            ds = datetime.combine(yesterday, datetime.min.time()).timestamp()
            make_db(st / "aw.db", spans=block(ds + 9 * H))
            (home / ".config/limitless").mkdir(parents=True)
            (home / ".config/limitless/config.json").write_text(json.dumps({"aw_db": "aw.db",
                                                                             "flow_work_apps": ["editor"]}))
            env = {k: v for k, v in os.environ.items() if not k.startswith("LIMITLESS_")}
            env["HOME"] = str(home)
            r = subprocess.run([sys.executable, "-I", str(ROOT / "bin" / "limitless-brief"), "send"], env=child_env(env),
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual((home / "delivered.txt").read_text(),
                             "State: synthetic\nYesterday's work: one long block, feed leaks unknown.")


if __name__ == "__main__":
    unittest.main()
