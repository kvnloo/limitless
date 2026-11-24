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


class Told(Base):
    def test_told_marks_the_write_and_the_line_is_gone(self):
        self.ingest()
        self.assertEqual(self.line(NOW + H), BOTH)
        self.assertTrue(self.told(NOW + H))
        m = self.st / SET_MARK
        self.assertEqual(json.loads(m.read_text()), {"told": NOW, "told_at": NOW + H})   # the write's ran_at
        self.assertEqual(stat.S_IMODE(m.stat().st_mode), 0o600)
        self.assertEqual([p.name for p in self.st.iterdir() if p.name.endswith(".tmp")], [], "no temp file left")
        self.assertEqual(self.line(NOW + 2 * H), "")

    def test_the_same_write_is_never_told_twice(self):
        self.ingest()
        self.assertTrue(self.told(NOW + H))
        self.assertFalse(self.told(NOW + 2 * H))
        self.assertEqual(json.loads((self.st / SET_MARK).read_text())["told_at"], NOW + H)
        self.runs(sync(NOW - 60), sync(NOW + 3 * H))       # a later sync with no new reply
        self.once(NOW + 4 * H)
        self.assertEqual(self.line(NOW + 5 * H), "")

    def test_a_second_write_later_is_told_again(self):
        self.ingest()
        self.assertTrue(self.told(NOW + H))
        self.reply("feed apps: otherfeedapp", NOW + 2 * H)
        self.ingest(NOW + 3 * H)
        self.assertEqual(self.line(NOW + 4 * H), FEED_ONLY)
        self.assertNotIn("otherfeedapp", self.line(NOW + 4 * H))
        self.assertTrue(self.told(NOW + 4 * H))
        self.assertEqual(json.loads((self.st / SET_MARK).read_text()), {"told": NOW + 3 * H, "told_at": NOW + 4 * H})
        self.assertEqual(self.line(NOW + 5 * H), "")

    def test_nothing_to_tell_writes_no_mark(self):
        self.config(apps_ingest="write")
        self.assertFalse(self.told())
        self.ingest(mode="dry_run")
        self.assertFalse(self.told(NOW + H))
        self.assertFalse((self.st / SET_MARK).exists())

    def test_the_mark_is_epochs_only(self):
        self.ingest()
        self.told(NOW + H)
        text = (self.st / SET_MARK).read_text()
        self.assertEqual(sorted(json.loads(text)), ["told", "told_at"])
        for n in NAMES + (PRIVATE, "work", "feed"):
            self.assertNotIn(n, text)

    def test_unreadable_state_never_raises(self):
        self.assertFalse(jobs_runner.brief_apps_set_told(self.dir / "nowhere", NOW, self.env, self.dir))


class Finalize(unittest.TestCase):
    def test_the_line_goes_before_the_apps_ask_and_after_the_outage_line(self):
        out = brief_post.finalize("State: synthetic", None, NOW, outage="Not recording: wearable.",
                                  apps_set=BOTH, apps_ask="Reply with this:\nwork apps: a\nfeed apps: b")
        self.assertEqual(out.splitlines()[1:3], ["Not recording: wearable.", BOTH])
        self.assertEqual(out.splitlines()[3], "Reply with this:")
        self.assertEqual(brief_post.finalize("State: synthetic", None, NOW, apps_set=""), "State: synthetic")

    def test_message_shape_keeps_the_line(self):
        body = brief_post.finalize("State: synthetic", None, NOW, overnight="Overnight: a few done.",
                                   work="Yesterday's work: two long blocks.", naps="Naps yesterday: none.",
                                   outage="Not recording: wearable.", apps_set=BOTH)
        body = "\n".join([body.splitlines()[0]] + [f"Line {w}." for w in ("one", "two", "three", "four")]
                          + body.splitlines()[1:])
        text, folded, _ = message_shape.fit("Wake-up brief", body)
        self.assertTrue(folded)
        self.assertEqual(text.splitlines()[-1], BOTH)
        self.assertEqual(text.splitlines()[0], "State: synthetic")
        self.assertEqual(message_shape.shape("Wake-up brief", f"State: synthetic\n{BOTH}"), f"State: synthetic\n{BOTH}")


class Cli(unittest.TestCase):
    """bin/limitless-brief: send carries the line once (marked only after a real delivery); build only previews."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        lib = self.home / ".local/lib"
        lib.mkdir(parents=True)
        (lib / "limitless_loop.py").write_text(FAKE_LOOP)
        (self.home / ".local/state/kevin-push").mkdir(parents=True)
        self.st = self.home / ".local/state/limitless"
        self.st.mkdir(parents=True)
        self.cfg = self.home / ".config/limitless/config.json"
        self.cfg.parent.mkdir(parents=True)
        self.config("write")
        from test_apps_ask_brief import aw_rows      # app candidates, so the ask would show while no list is set
        # a day further back: rows span ~4 h from two days before the given time, so late in the evening they
        # would reach yesterday and add the brief's "Yesterday's work" line (a clock-dependent failure)
        aw_rows(self.st, time.time() - 24 * H)
        self.wrote_at = time.time() - H
        self.write(self.wrote_at, ["work", "feed"], {"work_apps": ["editor", "terminal"], "feed_apps": ["scrollerapp"]})
        self.audit = self.home / "audit.jsonl"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("LIMITLESS_", "KEVIN_PUSH"))}
        self.env.update(HOME=str(self.home), LIMITLESS_AUDIT=str(self.audit))

    def config(self, mode):
        self.cfg.write_text(json.dumps({"aw_db": "aw.db", "apps_ingest": mode, "hermes_db": "hermes.db"}))

    def write(self, at, wrote, apps):
        """A synthetic apps-ingest write: the mark limitless-jobs leaves and the apps.json it wrote."""
        (self.st / jobs_runner.APPS_MARK).write_text(json.dumps(
            {"row_at": at - 60, "ran_at": at, "mode": "write", "action": "write", "wrote_at": at, "wrote": wrote}))
        apps_reply.write(self.st, dict(apps, since=apps_reply.iso(at - 60)))

    def run_cli(self, *args, **extra):
        return subprocess.run([sys.executable, "-I", str(CLI), *args], env=dict(self.env, **extra),
                              capture_output=True, text=True, timeout=60)

    def sent(self):
        p = self.home / "delivered.txt"
        return [b.strip() for b in p.read_text().split("---") if b.strip()] if p.exists() else []

    def told(self):
        p = self.st / SET_MARK
        return json.loads(p.read_text()) if p.exists() else None

    def test_send_says_it_once(self):
        for _ in range(2):
            r = self.run_cli("send")
            self.assertEqual(r.returncode, 0, r.stderr)
        got = self.sent()
        self.assertEqual(got, [f"State: synthetic\n{BOTH}", "State: synthetic"])
        self.assertEqual(self.told()["told"], self.wrote_at)
        for n in NAMES:
            self.assertNotIn(n, "\n".join(got))
            self.assertNotIn(n, self.audit.read_text())
        self.assertNotRegex(got[0].splitlines()[-1], r"\d")

    def test_a_failed_send_keeps_it_untold(self):
        r = self.run_cli("send", FAKE_FAIL="1")
        self.assertEqual(json.loads(r.stdout)["notify_rc"], 1)
        self.assertIsNone(self.told())
        self.run_cli("send")
        self.assertEqual(self.sent(), [f"State: synthetic\n{BOTH}"])
        self.assertIsNotNone(self.told())

    def test_a_second_write_later_is_told_again(self):
        self.run_cli("send")
        self.write(time.time() - 60, ["work"], {"work_apps": ["otherworkapp"], "feed_apps": ["scrollerapp"]})
        self.run_cli("send")
        self.run_cli("send")
        self.assertEqual(self.sent(), [f"State: synthetic\n{BOTH}", f"State: synthetic\n{WORK_ONLY}",
                                       "State: synthetic"])

    def test_build_previews_without_marking(self):
        r = self.run_cli("build")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(json.loads(r.stdout)["notif_text"].endswith(BOTH))
        self.assertIsNone(self.told())
        self.assertEqual(self.sent(), [])

    def test_dry_run_mode_never_produces_the_line(self):
        self.config("dry_run")
        self.run_cli("send")
        self.assertEqual(self.sent(), ["State: synthetic"])
        self.assertIsNone(self.told())

    def test_with_a_list_set_the_apps_ask_never_comes_with_it(self):
        self.run_cli("send")
        self.run_cli("send")
        for got in self.sent():
            self.assertNotIn("work apps:", got)
            self.assertNotIn("Reply with this", got)
        self.assertFalse((self.st / "apps-ask.json").exists())

    def test_a_write_that_cleared_both_lists_holds_the_ask_for_that_brief(self):
        self.write(time.time() - 60, ["work", "feed"], {"work_apps": [], "feed_apps": []})
        self.run_cli("send")
        self.run_cli("send")
        first, second = self.sent()
        self.assertEqual(first, f"State: synthetic\n{BOTH}")
        self.assertIn("work apps:", second)              # told: the ask comes back on the next brief
        self.assertNotIn(BOTH, second)


class Doctor(Base):
    def doc_row(self, now):
        from limitless import doctor
        from limitless.state_reader import StateReader, config
        r = doctor.apps_ingest_row(StateReader(self.st), config(self.env, self.dir), now, env=self.env)
        self.assertEqual((r["name"], r["status"]), ("job apps ingest", "live"), r)
        self.assertNotRegex(r["reason"], r"\d")
        self.assertWordsOnly(r["reason"])
        return r["reason"]

    def test_after_a_write_not_told_yet_then_told_in_a_brief(self):
        self.ingest()
        self.assertTrue(self.doc_row(NOW + H).endswith("wrote the app lists; not told yet"))
        self.told(NOW + H)
        self.assertTrue(self.doc_row(NOW + H).endswith("wrote the app lists; told in a brief"))

    def test_a_later_run_with_nothing_new_still_says_whether_the_write_was_told(self):
        self.ingest()
        self.runs(sync(NOW - 60), sync(NOW + H))
        self.once(NOW + 2 * H)
        self.assertTrue(self.doc_row(NOW + 2 * H).endswith("no new apps reply; not told yet"))

    def test_no_write_says_neither(self):
        self.ingest(mode="dry_run")
        reason = self.doc_row(NOW + H)
        self.assertNotIn("told", reason)


if __name__ == "__main__":
    unittest.main()
