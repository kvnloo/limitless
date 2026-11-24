"""The apps-set line in the wake brief: jobs_runner.brief_apps_set / brief_apps_set_told, brief_post.finalize and
bin/limitless-brief end to end. After the apps ingest wrote the app lists from the person's reply, the next
delivered brief says so once ("Work and feed app lists set from your reply."), through the tier audit gate; the
same write is never told twice, a later write is told again. Words only: never an app name or a count.

Synthetic runs.jsonl rows, the synthetic session DB of tests/hermes_db_fixture.py, a temp config and HOME and a
fake limitless_loop; nothing real. Nothing here sends, pushes or starts a process.
"""
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from limitless import apps_reply, brief_post, jobs_runner, message_shape  # noqa: E402
from hermes_db_fixture import make_db  # noqa: E402
from test_apps_ingest_job import H, NAMES, NOW, PRIVATE, UTC, sync  # noqa: E402
from test_outage_brief import FAKE_LOOP  # noqa: E402

BOTH = "Work and feed app lists set from your reply."
WORK_ONLY = "Work app list set from your reply."
FEED_ONLY = "Feed app list set from your reply."
REPLY_BOTH = "Work apps: editor, terminal\nfeed apps: scrollerapp"
SET_MARK = "apps-set.json"
CLI = ROOT / "bin" / "limitless-brief"


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.st = self.dir / "state"
        self.st.mkdir()
        self.cfg_path = self.dir / "config.json"
        self.audit = self.dir / "audit.jsonl"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg_path), "LIMITLESS_STATE": str(self.st),
                    "LIMITLESS_AUDIT": str(self.audit)}
        p = mock.patch.dict(os.environ, {}, clear=True)
        p.start()
        self.addCleanup(p.stop)
        self.reply(REPLY_BOTH, NOW - 2 * H)

    def reply(self, text, at):
        db = self.st / "hermes.db"
        if db.exists():
            db.unlink()
        make_db(db, [("user", PRIVATE, at - H), ("user", text, at)], started=at - 2 * H)

    def config(self, **kw):
        cfg = {"hermes_db": "hermes.db"}
        cfg.update(kw)
        self.cfg_path.write_text(json.dumps({k: v for k, v in cfg.items() if v is not None}))

    def runs(self, *rows):
        (self.st / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def once(self, now=NOW, dry_run=False):
        return jobs_runner.run_once(self.st, now, push=None, dry_run=dry_run, env=self.env, home=self.dir, tz=UTC)

    def ingest(self, now=NOW, mode="write"):
        """One sync row just before ``now`` and one pass of limitless-jobs over it."""
        self.config(apps_ingest=mode)
        self.runs(sync(now - 60))
        self.once(now)

    def line(self, now=NOW):
        return jobs_runner.brief_apps_set(self.st, now, self.env, self.dir)

    def told(self, now=NOW):
        return jobs_runner.brief_apps_set_told(self.st, now, self.env, self.dir)

    def assertWordsOnly(self, text):
        self.assertNotRegex(text, r"\d")
        for n in NAMES + (PRIVATE,):
            self.assertNotIn(n, text)


class Line(Base):
    def test_after_a_write_the_line_names_the_lists_set(self):
        self.ingest()
        self.assertEqual(self.line(NOW + H), BOTH)

    def test_through_the_gate_hook_brief_apps_set(self):
        self.ingest()
        self.assertEqual(self.line(NOW + H), BOTH)
        row = json.loads(self.audit.read_text().splitlines()[-1])
        self.assertEqual((row["hook"], row["digits"], row["blocked"]), ("brief:apps_set", 0, False))

    def test_words_only_no_digit_and_no_app_name(self):
        self.ingest()
        got = self.line(NOW + H)
        self.assertTrue(got)
        self.assertWordsOnly(got)
        for f in (self.audit, self.st / jobs_runner.APPS_MARK):     # epochs and a hash there, never a name
            for n in NAMES + (PRIVATE,):
                self.assertNotIn(n, f.read_text())

    def test_one_list_says_which(self):
        self.reply("work apps: editor", NOW - 2 * H)
        self.ingest()
        self.assertEqual(self.line(NOW + H), WORK_ONLY)
        self.reply("feed apps: scrollerapp", NOW + 2 * H)
        self.ingest(NOW + 3 * H)
        self.assertEqual(self.line(NOW + 4 * H), FEED_ONLY)

    def test_read_only_the_line_is_not_told_by_building_it(self):
        self.ingest()
        self.assertEqual(self.line(NOW + H), BOTH)
        self.assertEqual(self.line(NOW + 2 * H), BOTH)
        self.assertFalse((self.st / SET_MARK).exists())

    def test_nothing_before_any_write(self):
        self.config(apps_ingest="write")
        self.assertEqual(self.line(), "")
        self.runs(sync(NOW - 60))
        self.assertEqual(self.line(), "")              # a sync it has not run after yet

    def test_dry_run_mode_never_produces_the_line(self):
        self.ingest(mode="dry_run")
        self.assertEqual(jobs_runner.load_apps_mark(self.st)["action"], "would write")
        self.assertEqual(self.line(NOW + H), "")

    def test_a_dry_run_of_limitless_jobs_never_produces_the_line(self):
        self.config(apps_ingest="write")
        self.runs(sync(NOW - 60))
        self.once(dry_run=True)
        self.assertEqual(self.line(NOW + H), "")

    def test_a_write_then_dry_run_config_is_no_line(self):
        self.ingest()
        self.config(apps_ingest="dry_run")
        self.assertEqual(self.line(NOW + H), "")
        self.config(apps_ingest="off")
        self.assertEqual(self.line(NOW + H), "")

    def test_a_later_run_with_nothing_new_keeps_the_write_to_tell(self):
        self.ingest()
        self.runs(sync(NOW - 60), sync(NOW + H))
        self.once(NOW + 2 * H)
        self.assertEqual(jobs_runner.load_apps_mark(self.st)["action"], "nothing")
        self.assertEqual(self.line(NOW + 3 * H), BOTH)

    def test_unreadable_state_is_no_line(self):
        self.ingest()
        self.assertEqual(jobs_runner.brief_apps_set(self.dir / "nowhere", NOW, self.env, self.dir), "")
        (self.st / jobs_runner.APPS_MARK).write_text("{not json")
        self.assertEqual(self.line(NOW + H), "")


if __name__ == "__main__":
    unittest.main()
