"""Job owners: a job another sender owns is never pushed by run_once; the wake brief goes through its
own builder (bin/limitless-brief) instead of a placeholder. Synthetic data only; nothing sends.

NOW is an arbitrary epoch; only differences between times matter. Nothing here reads the clock.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import jobs, jobs_runner, send_gate  # noqa: E402

NOW = 2_000_000_000.0
H = 3600.0
OWN = "sent by its own sender"


def write_rows(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


class FakePush:
    def __init__(self, result="telegram"):
        self.result, self.calls = result, []

    def __call__(self, title, body, once=None):
        self.calls.append((title, body, once))
        return self.result


class FakeBrief:
    """Stands in for `limitless-brief send`: counts calls, reports what it is told to."""

    def __init__(self, result="telegram"):
        self.result, self.calls = result, 0

    def __call__(self):
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.env = {"LIMITLESS_CONFIG": str(self.root / "no-config.json")}

    def tearDown(self):
        self.tmp.cleanup()

    def awake_after_night(self):
        write_rows(self.st / "sleepmode.jsonl", [{"at": NOW - 8.5 * H, "on": True}, {"at": NOW - 0.2 * H, "on": False}])
        (self.st / "sleepmode-poll.json").write_text(json.dumps({"at": NOW - 60, "ok": True}))
        write_rows(self.st / "unlocks.jsonl", [{"at": NOW - 120}])

    def back_from_nap(self):
        write_rows(self.st / "sleepmode.jsonl", [{"at": NOW - 12 * H, "on": True}, {"at": NOW - 3 * H, "on": False},
                                                 {"at": NOW - 1 * H, "on": True}, {"at": NOW - 0.1 * H, "on": False}])
        (self.st / "sleepmode-poll.json").write_text(json.dumps({"at": NOW - 60, "ok": True}))
        write_rows(self.st / "unlocks.jsonl", [{"at": NOW - 120}])

    def config(self, cfg):
        p = self.root / "config.json"
        p.write_text(json.dumps(cfg))
        self.env["LIMITLESS_CONFIG"] = str(p)

    def once(self, now=NOW, **kw):
        kw.setdefault("env", self.env)
        kw.setdefault("home", self.root)
        return {r["job"]: r for r in jobs_runner.run_once(self.st, now, **kw)}

    def sent_rows(self):
        p = self.st / "jobs-sent.jsonl"
        return [json.loads(ln) for ln in p.read_text().splitlines()] if p.exists() else []


class ExternalJobsConfig(Base):
    def ext(self):
        return jobs_runner.external_jobs(env=self.env, home=self.root)

    def test_default_is_empty(self):
        self.assertEqual(self.ext(), [])

    def test_env_comma_list(self):
        self.env["LIMITLESS_EXTERNAL_JOBS"] = " wake_brief, nap ,,"
        self.assertEqual(self.ext(), ["wake_brief", "nap"])

    def test_config_list(self):
        self.config({"external_jobs": ["nap"]})
        self.assertEqual(self.ext(), ["nap"])

    def test_env_wins_over_config(self):
        self.config({"external_jobs": ["nap"]})
        self.env["LIMITLESS_EXTERNAL_JOBS"] = "wake_brief"
        self.assertEqual(self.ext(), ["wake_brief"])

    def test_bad_config_is_empty(self):
        for v in ("wake_brief", 3, None, {"wake_brief": True}):
            self.config({"external_jobs": v})
            self.assertEqual(self.ext(), [], v)
        self.config({"external_jobs": ["nap", 7, "", None]})
        self.assertEqual(self.ext(), ["nap"])


class ExternalJobs(Base):
    def test_external_wake_brief_is_never_pushed_or_logged(self):
        self.awake_after_night()
        push, brief = FakePush(), FakeBrief()
        row = self.once(push=push, brief=brief, dry_run=False, external=["wake_brief"])["Wake-up brief"]
        self.assertEqual(push.calls, [])
        self.assertEqual(brief.calls, 0)
        self.assertEqual(self.sent_rows(), [])
        self.assertFalse((self.st / jobs_runner.SENT_LOG).exists())
        self.assertEqual(row["action"], jobs.DELIVER, "the verdict is still computed")
        self.assertIn(OWN, row["reason"])

    def test_external_from_env_and_config(self):
        self.awake_after_night()
        for setup in ({"LIMITLESS_EXTERNAL_JOBS": "wake_brief,nap"}, None):
            if setup is None:
                self.env.pop("LIMITLESS_EXTERNAL_JOBS")
                self.config({"external_jobs": ["wake_brief", "nap"]})
            else:
                self.env.update(setup)
            push = FakePush()
            rows = self.once(push=push, dry_run=False)
            self.assertEqual(push.calls, [], setup)
            self.assertEqual(self.sent_rows(), [], setup)
            self.assertIn(OWN, rows["Wake-up brief"]["reason"])
            self.assertIn(OWN, rows["Back from nap"]["reason"])

    def test_external_nap_is_never_pushed_other_jobs_unchanged(self):
        self.back_from_nap()
        push = FakePush()
        rows = self.once(push=push, dry_run=False, external=["nap"])
        self.assertEqual(push.calls, [])
        self.assertEqual(rows["Back from nap"]["action"], jobs.DELIVER)
        self.assertIn(OWN, rows["Back from nap"]["reason"])
        self.assertEqual(self.sent_rows(), [])
        for job in ("Wake-up brief", "MIQ for tonight?", "Habit check-in"):
            self.assertNotIn(OWN, rows[job]["reason"])

    def test_a_job_not_listed_still_sends(self):
        self.awake_after_night()
        push = FakePush()
        rows = self.once(push=push, dry_run=False, external=["nap"])
        self.assertEqual([c[0] for c in push.calls], ["Wake-up brief"])
        self.assertEqual(len(self.sent_rows()), 1)
        self.assertNotIn(OWN, rows["Wake-up brief"]["reason"])
        self.assertIn(OWN, rows["Back from nap"]["reason"])

    def test_empty_default_is_todays_behavior(self):
        self.awake_after_night()
        push = FakePush()
        rows = self.once(push=push, dry_run=False)
        self.assertEqual([c[0] for c in push.calls], ["Wake-up brief"])
        self.assertTrue(all(OWN not in r["reason"] for r in rows.values()))


class WakeBriefSender(Base):
    def test_brief_sends_the_wake_brief_not_the_placeholder(self):
        self.awake_after_night()
        push, brief = FakePush(), FakeBrief("telegram")
        row = self.once(push=push, brief=brief, dry_run=False)["Wake-up brief"]
        self.assertEqual(brief.calls, 1)
        self.assertEqual(push.calls, [], "the placeholder text is never pushed")
        self.assertEqual(row["action"], jobs.DELIVER)
        self.assertEqual(self.sent_rows(), [jobs.sent_entry(jobs.WAKE_BRIEF, NOW - 0.2 * H, NOW)])
        again = self.once(now=NOW + 300, push=push, brief=brief, dry_run=False)["Wake-up brief"]
        self.assertEqual(brief.calls, 1)
        self.assertEqual(again["action"], jobs.DROP)

    def test_failed_brief_sends_nothing_and_holds(self):
        self.awake_after_night()
        for result in ("limitless-brief failed (exit 1)", "log (telegram rc=1)", False, None,
                       OSError("no limitless-brief")):
            push, brief = FakePush(), FakeBrief(result)
            row = self.once(push=push, brief=brief, dry_run=False)["Wake-up brief"]
            self.assertEqual(brief.calls, 1, result)
            self.assertEqual(push.calls, [], f"no placeholder fallback: {result!r}")
            self.assertEqual(self.sent_rows(), [], result)
            self.assertEqual(row["action"], jobs.HOLD, result)
            self.assertIn("not delivered", row["reason"])

    def test_brief_once_drop_is_a_drop(self):
        self.awake_after_night()
        push = FakePush()
        row = self.once(push=push, brief=FakeBrief(f"log ({send_gate.ONCE_DROP})"), dry_run=False)["Wake-up brief"]
        self.assertEqual(row["action"], jobs.DROP)
        self.assertEqual(push.calls, [])
        self.assertEqual(self.sent_rows(), [])

    def test_dry_run_never_calls_brief(self):
        self.awake_after_night()
        brief = FakeBrief()
        self.once(push=FakePush(), brief=brief)
        self.assertEqual(brief.calls, 0)

    def test_brief_is_for_the_wake_brief_only(self):
        self.back_from_nap()
        push, brief = FakePush(), FakeBrief()
        self.once(push=push, brief=brief, dry_run=False)
        self.assertEqual(brief.calls, 0)
        self.assertEqual([c[0] for c in push.calls], ["Back from nap"])


if __name__ == "__main__":
    unittest.main()
