"""The FIT import's brief line: after a write pass of the FIT import job added rides, the next delivered wake brief
says so once ("Imported two bike rides from your CAROL exports."), through the tier audit gate; marked told only
after a real delivery, like the apps-set line. fit_ingest_job.brief_fit_rides / brief_fit_rides_told,
brief_post.finalize and bin/limitless-brief end to end. Words only: never a file name, never a digit.

Every FIT file here is SYNTHETIC, built by the tiny writer in tests/test_fit_ride.py from made-up values; synthetic
runs.jsonl rows, a temp config and HOME and a fake limitless_loop; nothing real. Nothing here sends, pushes or
starts a process other than the CLI under test with its fake delivery.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from limitless import brief_post, fit_ingest_job, fit_ride, jobs_runner, message_shape  # noqa: E402
from test_fit_drop_ingest import Base as DropBase, H, NOW, start, sync  # noqa: E402
from test_fit_ride import ride_file  # noqa: E402  (the synthetic FIT writer)

TWO = "Imported two bike rides from your CAROL exports."
ONE = "Imported one bike ride from your CAROL exports."
THREE = "Imported three bike rides from your CAROL exports."
MANY = "Imported more than twenty bike rides from your CAROL exports."
TOLD = "fit-rides-told.json"
CLI = ROOT / "bin" / "limitless-brief"
IMPORT_CLI = ROOT / "bin" / "limitless-import-fit"

FAKE_LOOP = '''
import json, os
from pathlib import Path
def load_config():
    return {}
def build(cfg, day=None):
    return {"path": "/dev/null", "notif": "State: synthetic"}
def deliver(cfg, title, body, url=None, env=None):
    if os.environ.get("FAKE_FAIL"):
        return {"rc": 1, "shown": "log"}
    if os.environ.get("FAKE_HELD"):
        return {"rc": 0, "shown": "held"}
    with open(Path(os.environ["HOME"], "delivered.txt"), "a") as f:
        f.write(body + "\\n---\\n")
    return {"rc": 0, "shown": "telegram"}
'''


class Base(DropBase):
    def setUp(self):
        super().setUp()
        self.audit = self.dir / "audit.jsonl"
        self.env["LIMITLESS_AUDIT"] = str(self.audit)
        self.n = 0

    def add(self, k=1):
        """``k`` new synthetic rides in the drop folder."""
        for _ in range(k):
            self.n += 1
            self.drop(f"ride-{self.n}.fit", start=start(self.n))

    def sync_pass(self, now, mode="write"):
        """One sync row just before ``now`` and one ingest pass of limitless-jobs over it."""
        self.config(fit_ingest=mode)
        self.runs(sync(now - 60))
        self.once(now, ingest=True)

    def line(self, now):
        return fit_ingest_job.brief_fit_rides(self.st, now, self.env, self.dir)

    def told(self, now):
        return fit_ingest_job.brief_fit_rides_told(self.st, now, self.env, self.dir)


class Line(Base):
    def test_dry_run_never_produces_the_line(self):
        self.add(2)
        self.sync_pass(NOW, mode="dry_run")
        self.assertIn("would add two rides", self.load_mark()["said"])
        self.assertEqual(self.line(NOW + H), "")
        self.config(fit_ingest="write")                # a dry run left nothing to tell, even in write mode now
        self.assertEqual(self.line(NOW + H), "")
        self.assertFalse(self.told(NOW + H))
        self.assertFalse((self.st / TOLD).exists())

    def test_a_dry_run_of_limitless_jobs_never_produces_the_line(self):
        self.add(2)
        self.config(fit_ingest="write")
        self.runs(sync(NOW - 60))
        self.once(NOW, dry_run=True)
        self.assertEqual(self.line(NOW + H), "")

    def test_a_write_that_adds_two_gives_the_line_in_words(self):
        self.add(2)
        self.sync_pass(NOW)
        self.assertEqual(len(self.ride_rows()), 2)
        got = self.line(NOW + H)
        self.assertEqual(got, TWO)
        self.assertNotRegex(got, r"\d")

    def test_through_the_gate_hook_brief_fit_rides(self):
        self.add(2)
        self.sync_pass(NOW)
        self.line(NOW + H)
        row = json.loads(self.audit.read_text().splitlines()[-1])
        self.assertEqual((row["hook"], row["digits"], row["blocked"]), ("brief:fit_rides", 0, False))

    def test_the_mark_records_what_was_added_in_words_and_an_epoch(self):
        self.add(2)
        self.sync_pass(NOW)
        m = self.load_mark()
        self.assertEqual(m["added_at"], NOW)
        self.assertEqual(m["added"], "two rides")
        self.assertEqual(stat.S_IMODE(self.mark.stat().st_mode), 0o600)

    def test_building_it_is_read_only(self):
        self.add(2)
        self.sync_pass(NOW)
        self.assertEqual(self.line(NOW + H), TWO)
        self.assertEqual(self.line(NOW + 2 * H), TWO)
        self.assertFalse((self.st / TOLD).exists())

    def test_a_write_pass_with_nothing_new_writes_no_line(self):
        self.sync_pass(NOW)
        self.assertEqual(self.load_mark()["said"], "nothing new")
        self.assertEqual(self.line(NOW + H), "")

    def test_only_duplicates_is_no_line(self):
        self.add(1)
        fit_ride.run(sorted(self.drop_dir.iterdir()), self.rides, write=True)    # imported by hand first
        self.sync_pass(NOW)
        self.assertIn("one file already in the rides file", self.load_mark()["said"])
        self.assertEqual(self.line(NOW + H), "")

    def test_a_later_pass_with_nothing_new_keeps_it_to_tell(self):
        self.add(2)
        self.sync_pass(NOW)
        self.sync_pass(NOW + H)
        self.assertEqual(self.load_mark()["said"], "nothing new")
        self.assertEqual(self.line(NOW + 2 * H), TWO)

    def test_two_passes_before_a_brief_add_up(self):
        self.add(2)
        self.sync_pass(NOW)
        self.add(1)
        self.sync_pass(NOW + H)
        self.assertEqual(self.line(NOW + 2 * H), THREE)

    def test_more_than_twenty_is_capped_in_words(self):
        self.add(21)                                   # twenty per pass: two passes
        self.sync_pass(NOW)
        self.assertEqual(self.load_mark()["added"], "twenty rides")
        self.sync_pass(NOW + H)
        self.assertEqual(len(self.ride_rows()), 21)
        got = self.line(NOW + 2 * H)
        self.assertEqual(got, MANY)
        self.assertNotRegex(got, r"\d")

    def test_write_mode_only(self):
        self.add(2)
        self.sync_pass(NOW)
        for mode in ("dry_run", "off", None):
            self.config(fit_ingest=mode)
            self.assertEqual(self.line(NOW + H), "", mode)
            self.assertFalse(self.told(NOW + H), mode)

    def test_a_pass_in_the_future_of_now_is_not_told(self):
        self.add(2)
        self.sync_pass(NOW)
        self.assertEqual(self.line(NOW - H), "")

    def test_unreadable_state_is_no_line_and_never_raises(self):
        self.add(2)
        self.sync_pass(NOW)
        self.assertEqual(fit_ingest_job.brief_fit_rides(self.dir / "nowhere", NOW, self.env, self.dir), "")
        self.assertFalse(fit_ingest_job.brief_fit_rides_told(self.dir / "nowhere", NOW, self.env, self.dir))
        self.mark.write_text("{not json")
        self.assertEqual(self.line(NOW + H), "")


class Told(Base):
    def test_delivered_marks_it_told_and_it_is_not_said_again(self):
        self.add(2)
        self.sync_pass(NOW)
        self.assertEqual(self.line(NOW + H), TWO)
        self.assertTrue(self.told(NOW + H))
        m = self.st / TOLD
        self.assertEqual(json.loads(m.read_text()), {"told": NOW, "told_at": NOW + H})
        self.assertEqual(stat.S_IMODE(m.stat().st_mode), 0o600)
        self.assertEqual([p.name for p in self.st.iterdir() if p.name.endswith(".tmp")], [])
        self.assertEqual(self.line(NOW + 2 * H), "")
        self.assertFalse(self.told(NOW + 2 * H))
        self.sync_pass(NOW + 3 * H)                    # a later sync with nothing new
        self.assertEqual(self.line(NOW + 4 * H), "")

    def test_held_keeps_it_for_the_next_brief(self):
        self.add(2)
        self.sync_pass(NOW)
        self.assertEqual(self.line(NOW + H), TWO)      # built, never told (held or failed send)
        self.assertEqual(self.line(NOW + 2 * H), TWO)

    def test_a_later_pass_adding_one_more_is_a_new_line_for_that_one(self):
        self.add(2)
        self.sync_pass(NOW)
        self.assertTrue(self.told(NOW + H))
        self.add(1)
        self.sync_pass(NOW + 2 * H)
        self.assertEqual(self.load_mark()["added"], "one ride")
        self.assertEqual(self.line(NOW + 3 * H), ONE)
        self.assertTrue(self.told(NOW + 3 * H))
        self.assertEqual(json.loads((self.st / TOLD).read_text()), {"told": NOW + 2 * H, "told_at": NOW + 3 * H})
        self.assertEqual(self.line(NOW + 4 * H), "")

    def test_the_told_mark_is_epochs_only(self):
        self.add(2)
        self.sync_pass(NOW)
        self.told(NOW + H)
        data = json.loads((self.st / TOLD).read_text())
        self.assertEqual(sorted(data), ["told", "told_at"])
        self.assertTrue(all(isinstance(v, float) for v in data.values()))

    def test_rides_imported_by_hand_do_not_count(self):
        self.config(fit_ingest="write")
        p = self.dir / "by-hand.fit"
        p.write_bytes(ride_file(start=start(9)))
        r = subprocess.run([sys.executable, "-I", str(IMPORT_CLI), "--write", str(p)],
                           env=child_env(dict(self.env, HOME=str(self.dir))), capture_output=True, text=True,
                           timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.ride_rows()), 1)
        self.assertEqual(self.line(NOW + H), "")
        self.sync_pass(NOW)                            # the job's pass finds nothing new in its folder
        self.assertEqual(self.line(NOW + H), "")


class Finalize(unittest.TestCase):
    def test_the_line_goes_after_the_apps_set_line_and_before_the_ask(self):
        out = brief_post.finalize("State: synthetic", None, NOW, outage="Not recording: wearable.",
                                  apps_set="Work app list set from your reply.", fit_rides=TWO,
                                  apps_ask="Reply with this:\nwork apps: a\nfeed apps: b")
        self.assertEqual(out.splitlines()[1:4], ["Not recording: wearable.", "Work app list set from your reply.",
                                                 TWO])
        self.assertEqual(out.splitlines()[4], "Reply with this:")

    def test_nothing_else_changes_without_it(self):
        kw = dict(overnight="Overnight: a few done.", naps="Naps yesterday: none.", outage="Not recording: x.")
        self.assertEqual(brief_post.finalize("State: synthetic", None, NOW, fit_rides="", **kw),
                         brief_post.finalize("State: synthetic", None, NOW, **kw))

    def test_message_shape_keeps_a_short_brief_as_it_is(self):
        body = f"State: synthetic\n{TWO}"
        self.assertEqual(message_shape.shape("Wake-up brief", body), body)


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
        self.added_at = time.time() - H
        self.pass_mark(self.added_at, "two rides")
        self.audit = self.home / "audit.jsonl"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("LIMITLESS_", "KEVIN_PUSH"))}
        self.env.update(HOME=str(self.home), LIMITLESS_AUDIT=str(self.audit))

    def config(self, mode):
        self.cfg.write_text(json.dumps({"rides_file": "rides.jsonl", "fit_drop_dir": "drop", "fit_ingest": mode}))

    def pass_mark(self, at, added):
        """The mark a synthetic FIT import write pass leaves after adding rides."""
        (self.st / fit_ingest_job.MARK).write_text(json.dumps(
            {"row_at": at - 60, "ran_at": at, "read_to": at - 600, "mode": "write", "said": f"added {added}",
             "added_at": at, "added": added}))

    def run_cli(self, *args, **extra):
        return subprocess.run([sys.executable, "-I", str(CLI), *args], env=child_env(dict(self.env, **extra)),
                              capture_output=True, text=True, timeout=60)

    def sent(self):
        p = self.home / "delivered.txt"
        return [b.strip() for b in p.read_text().split("---") if b.strip()] if p.exists() else []

    def told(self):
        p = self.st / TOLD
        return json.loads(p.read_text()) if p.exists() else None

    def test_send_says_it_once(self):
        for _ in range(2):
            r = self.run_cli("send")
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.sent(), [f"State: synthetic\n{TWO}", "State: synthetic"])
        self.assertEqual(self.told()["told"], self.added_at)

    def test_a_failed_send_keeps_it_untold(self):
        r = self.run_cli("send", FAKE_FAIL="1")
        self.assertEqual(json.loads(r.stdout)["notify_rc"], 1)
        self.assertIsNone(self.told())
        self.run_cli("send")
        self.assertEqual(self.sent(), [f"State: synthetic\n{TWO}"])
        self.assertIsNotNone(self.told())

    def test_a_held_send_keeps_it_for_the_next_brief(self):
        r = self.run_cli("send", FAKE_HELD="1")
        self.assertEqual(json.loads(r.stdout)["notify_rc"], 1)
        self.assertIsNone(self.told())
        self.run_cli("send")
        self.assertEqual(self.sent(), [f"State: synthetic\n{TWO}"])

    def test_a_later_pass_is_told_again(self):
        self.run_cli("send")
        self.pass_mark(time.time() - 60, "one ride")
        self.run_cli("send")
        self.run_cli("send")
        self.assertEqual(self.sent(), [f"State: synthetic\n{TWO}", f"State: synthetic\n{ONE}", "State: synthetic"])

    def test_build_previews_without_marking(self):
        r = self.run_cli("build")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(json.loads(r.stdout)["notif_text"].endswith(TWO))
        self.assertIsNone(self.told())
        self.assertEqual(self.sent(), [])

    def test_dry_run_mode_never_produces_the_line(self):
        self.config("dry_run")
        self.run_cli("send")
        self.assertEqual(self.sent(), ["State: synthetic"])
        self.assertIsNone(self.told())

    def test_with_the_import_off_the_brief_is_unchanged(self):
        self.config("off")
        r = self.run_cli("build")
        self.assertEqual(json.loads(r.stdout)["notif_text"], "State: synthetic")
        self.run_cli("send")
        self.assertEqual(self.sent(), ["State: synthetic"])
        self.assertIsNone(self.told())
        self.assertFalse(self.audit.exists() and "brief:fit_rides" in self.audit.read_text())


if __name__ == "__main__":
    unittest.main()
