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


if __name__ == "__main__":
    unittest.main()
