"""jobs_runner.run_once: job verdicts from the state dir, sends only through push. Synthetic data only.

NOW is an arbitrary epoch; only differences between times matter. Nothing here reads the clock.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import jobs, jobs_runner  # noqa: E402

NOW = 2_000_000_000.0
H = 3600.0


def write_rows(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


class FakePush:
    def __init__(self, result="telegram"):
        self.result, self.calls = result, []

    def __call__(self, title, body):
        self.calls.append((title, body))
        return self.result


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        # No config and no Glide file: the window comes from Sleep mode and unlocks only.
        self.env = {"LIMITLESS_CONFIG": str(self.root / "no-config.json")}

    def tearDown(self):
        self.tmp.cleanup()

    def awake_after_night(self, off_ago_h=0.2):
        write_rows(self.st / "sleepmode.jsonl", [{"at": NOW - 8.5 * H, "on": True},
                                                 {"at": NOW - off_ago_h * H, "on": False}])
        (self.st / "sleepmode-poll.json").write_text(json.dumps({"at": NOW - 60, "ok": True}))
        write_rows(self.st / "unlocks.jsonl", [{"at": NOW - 120}])

    def once(self, now=NOW, **kw):
        kw.setdefault("env", self.env)
        kw.setdefault("home", self.root)
        return jobs_runner.run_once(self.st, now, **kw)

    def by_job(self, rows):
        return {r["job"]: r for r in rows}

    def sent_rows(self):
        p = self.st / "jobs-sent.jsonl"
        return [json.loads(ln) for ln in p.read_text().splitlines()] if p.exists() else []


class DryRun(Base):
    def test_one_plain_row_per_spec(self):
        self.awake_after_night()
        rows = self.once()
        self.assertEqual(len(rows), len(jobs.SPECS))
        for r in rows:
            self.assertEqual(set(r), {"job", "action", "reason"})
            self.assertIn(r["action"], jobs.ACTIONS)
            self.assertNotIn("_", r["job"], "job is plain words, not an id")
        self.assertEqual(self.by_job(rows)["Wake-up brief"]["action"], jobs.DELIVER)
        self.assertEqual(self.by_job(rows)["Back from nap"]["action"], jobs.NOT_TRIGGERED)

    def test_dry_run_is_the_default_and_never_pushes_or_writes(self):
        self.awake_after_night()
        before = sorted(p.name for p in self.st.iterdir())
        push = FakePush()
        rows = self.once(push=push)
        self.assertEqual(self.by_job(rows)["Wake-up brief"]["action"], jobs.DELIVER)
        self.assertEqual(push.calls, [])
        self.assertEqual(sorted(p.name for p in self.st.iterdir()), before)

    def test_empty_state_dir_is_not_triggered_everywhere(self):
        rows = self.once()
        self.assertEqual({r["action"] for r in rows}, {jobs.NOT_TRIGGERED})


class Send(Base):
    def test_deliver_pushes_and_logs_sent_only_on_telegram(self):
        self.awake_after_night()
        push = FakePush("telegram")
        rows = self.once(push=push, dry_run=False)
        self.assertEqual([t for t, _ in push.calls], ["Wake-up brief"])
        self.assertTrue(push.calls[0][1].strip())
        self.assertEqual(self.by_job(rows)["Wake-up brief"]["action"], jobs.DELIVER)
        trig = NOW - 0.2 * H
        self.assertEqual(self.sent_rows(), [jobs.sent_entry(jobs.WAKE_BRIEF, trig, NOW)])

    def test_log_only_push_is_not_sent(self):
        self.awake_after_night()
        for result in ("log", "log (telegram rc=1)", "held (sleep mode)", False, None, ""):
            push = FakePush(result)
            rows = self.once(push=push, dry_run=False)
            self.assertEqual(len(push.calls), 1, result)
            self.assertEqual(self.sent_rows(), [], result)
            row = self.by_job(rows)["Wake-up brief"]
            self.assertEqual(row["action"], jobs.HOLD, result)
            self.assertIn("not delivered", row["reason"])

    def test_push_that_raises_is_not_sent(self):
        self.awake_after_night()

        def boom(title, body):
            raise OSError("no kevin-push")
        rows = self.once(push=boom, dry_run=False)
        self.assertEqual(self.sent_rows(), [])
        self.assertEqual(self.by_job(rows)["Wake-up brief"]["action"], jobs.HOLD)

    def test_true_counts_as_delivered(self):
        self.awake_after_night()
        self.once(push=FakePush(True), dry_run=False)
        self.assertEqual(len(self.sent_rows()), 1)

    def test_only_deliver_verdicts_push(self):
        # Sleep mode on with a live poll: asleep, every triggered job holds, nothing is pushed.
        write_rows(self.st / "sleepmode.jsonl", [{"at": NOW - 9 * H, "on": True}, {"at": NOW - 1 * H, "on": False},
                                                 {"at": NOW - 0.1 * H, "on": True}])
        (self.st / "sleepmode-poll.json").write_text(json.dumps({"at": NOW - 60, "ok": True}))
        push = FakePush()
        rows = self.once(push=push, dry_run=False)
        self.assertEqual(push.calls, [])
        self.assertNotIn(jobs.DELIVER, {r["action"] for r in rows})
        self.assertEqual(self.sent_rows(), [])


class Idempotent(Base):
    def test_two_runs_send_once_per_trigger(self):
        self.awake_after_night()
        push = FakePush()
        first = self.once(push=push, dry_run=False)
        second = self.once(push=push, dry_run=False, now=NOW + 300)
        self.assertEqual(len(push.calls), 1)
        self.assertEqual(len(self.sent_rows()), 1)
        self.assertEqual(self.by_job(first)["Wake-up brief"]["action"], jobs.DELIVER)
        row = self.by_job(second)["Wake-up brief"]
        self.assertEqual(row["action"], jobs.DROP)
        self.assertIn("already spoke once", row["reason"])

    def test_failed_push_then_good_push_sends_once(self):
        self.awake_after_night()
        self.once(push=FakePush("log"), dry_run=False)
        push = FakePush()
        self.once(push=push, dry_run=False, now=NOW + 300)
        self.once(push=push, dry_run=False, now=NOW + 600)
        self.assertEqual(len(push.calls), 1)
        self.assertEqual(len(self.sent_rows()), 1)

    def test_a_new_trigger_sends_again(self):
        self.awake_after_night()
        push = FakePush()
        self.once(push=push, dry_run=False)
        # The next day: Sleep mode on for a night, then off again.
        later = NOW + 24 * H
        write_rows(self.st / "sleepmode.jsonl", [{"at": NOW - 8.5 * H, "on": True}, {"at": NOW - 0.2 * H, "on": False},
                                                 {"at": later - 8 * H, "on": True}, {"at": later - 0.1 * H, "on": False}])
        (self.st / "sleepmode-poll.json").write_text(json.dumps({"at": later - 60, "ok": True}))
        self.once(push=push, dry_run=False, now=later)
        self.once(push=push, dry_run=False, now=later + 300)
        self.assertEqual(len(push.calls), 2)
        self.assertEqual(len(self.sent_rows()), 2)


class EventsAndWindow(Base):
    def glide(self, data):
        path = self.root / "attention.json"
        path.write_text(json.dumps(data))
        self.env["LIMITLESS_GLIDE_ATTENTION"] = str(path)

    def test_events_jsonl_wakes_the_habit_check_in_with_its_habit(self):
        self.awake_after_night()
        (self.st / "habit.json").write_text(json.dumps({"habit": "Stretch for two minutes", "checkins": {}}))
        write_rows(self.st / "events.jsonl", [{"event": "habit_cue", "at": NOW - 60},
                                              {"event": "not_an_event", "at": NOW - 30},
                                              {"event": "habit_cue", "at": "not a time"}, ["junk"]])
        push = FakePush()
        rows = self.once(push=push, dry_run=False)
        self.assertEqual(self.by_job(rows)["Habit check-in"]["action"], jobs.DELIVER)
        bodies = dict(push.calls)
        self.assertIn("Stretch for two minutes", bodies["Habit check-in"])
        self.assertIn("Done, No or Skip", bodies["Habit check-in"])

    def test_wind_down_job_needs_the_glide_wind_down_window(self):
        self.awake_after_night()
        write_rows(self.st / "events.jsonl", [{"event": "wind_down", "at": NOW - 60}])
        self.assertEqual(self.by_job(self.once())["MIQ for tonight?"]["action"], jobs.HOLD)
        self.glide({"block": None, "resume": {"saved": NOW - 120}})
        self.assertEqual(self.by_job(self.once())["MIQ for tonight?"]["action"], jobs.DELIVER)

    def test_glide_focus_block_holds_every_ask(self):
        self.awake_after_night()
        self.glide({"block": {"start": NOW - 600, "end": NOW + 600, "minutes": 20}})
        push = FakePush()
        row = self.by_job(self.once(push=push, dry_run=False))["Wake-up brief"]
        self.assertEqual(row["action"], jobs.HOLD)
        self.assertIn("focus block", row["reason"])
        self.assertEqual(push.calls, [])

    def test_glide_path_from_config(self):
        self.awake_after_night()
        write_rows(self.st / "events.jsonl", [{"event": "wind_down", "at": NOW - 60}])
        att = self.root / "attention.json"
        att.write_text(json.dumps({"resume": {"saved": NOW - 120}}))
        cfg = self.root / "config.json"
        cfg.write_text(json.dumps({"glide_attention": str(att)}))
        self.env["LIMITLESS_CONFIG"] = str(cfg)
        self.assertEqual(self.by_job(self.once())["MIQ for tonight?"]["action"], jobs.DELIVER)

    def test_asleep_holds_even_when_glide_knows_a_window(self):
        write_rows(self.st / "sleepmode.jsonl", [{"at": NOW - 9 * H, "on": True}, {"at": NOW - 1 * H, "on": False},
                                                 {"at": NOW - 0.1 * H, "on": True}])
        (self.st / "sleepmode-poll.json").write_text(json.dumps({"at": NOW - 60, "ok": True}))
        # A habit cue after Sleep mode went on: triggered, not expired, but the person is asleep.
        write_rows(self.st / "events.jsonl", [{"event": "habit_cue", "at": NOW - 60}])
        self.glide({"resume": {"saved": NOW - 0.5 * H}})
        row = self.by_job(self.once())["Habit check-in"]
        self.assertEqual(row["action"], jobs.HOLD)
        self.assertIn("asleep", row["reason"])


if __name__ == "__main__":
    unittest.main()
