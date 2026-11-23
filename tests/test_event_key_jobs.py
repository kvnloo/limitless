"""jobs_runner.event_key for the MIQ and nap jobs equals the `once` run_once passes to push.

MIQ's trigger is a wind_down event (events.jsonl); it is delivered only in the wind-down window,
which the Glide provider opens from attention.json (path from the env or from config.json).
The nap's trigger is a Sleep-mode off after a short on. Synthetic data only. NOW is an arbitrary
epoch; only differences between times matter. Nothing sends: the push is a fake.
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import jobs, jobs_runner  # noqa: E402

NOW = 2_000_000_000.0
H = 3600.0
UTC = timezone.utc


def night(at):
    """The MIQ night key for an event with no wake before it: the event's own UTC date."""
    return f"miq:{datetime.fromtimestamp(at, UTC).date().isoformat()}"


def write_rows(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


class OncePush:
    def __init__(self, result="telegram"):
        self.result, self.calls = result, []

    def __call__(self, title, body, once=None):
        self.calls.append((title, body, once))
        return self.result


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.att = self.root / "attention.json"
        self.env = {"LIMITLESS_CONFIG": str(self.root / "no-config.json")}

    def tearDown(self):
        self.tmp.cleanup()

    def key(self, job, now=NOW):
        return jobs_runner.event_key(self.st, now, job=job, env=self.env, home=self.root, tz=UTC)

    def pushed(self, spec, now=NOW):
        push = OncePush()
        jobs_runner.run_once(self.st, now, push=push, dry_run=False, env=self.env, home=self.root, tz=UTC)
        return [c[2] for c in push.calls if c[0] == spec.send_title]

    def assert_same(self, spec, expect_at, now=NOW):
        k = self.key(spec.name, now)
        self.assertEqual(k, night(expect_at) if spec.name == jobs.MIQ.name else f"{spec.name}:{int(expect_at)}")
        self.assertEqual(self.pushed(spec, now), [k])


class MiqKey(Base):
    def glide_wind_down(self, saved):
        self.att.write_text(json.dumps({"block": None, "queue": [], "resume": {"saved": saved}, "nudged": ""}))

    def test_wind_down_event_with_the_glide_window_from_the_env(self):
        at = NOW - 90
        write_rows(self.st / "events.jsonl", [{"event": "wind_down", "at": at}])
        self.glide_wind_down(NOW - 120)
        self.env["LIMITLESS_GLIDE_ATTENTION"] = str(self.att)
        self.assert_same(jobs.MIQ, at)

    def test_wind_down_event_with_the_glide_window_from_config(self):
        at = NOW - 0.5 * H
        write_rows(self.st / "events.jsonl", [{"event": "wind_down", "at": "2033-05-18T03:03:20Z"}])
        self.glide_wind_down(NOW - 0.5 * H)
        cfg = self.root / "config.json"
        cfg.write_text(json.dumps({"glide_attention": str(self.att)}))
        self.env["LIMITLESS_CONFIG"] = str(cfg)
        self.assertEqual(at, 2_000_000_000.0 - 1800)   # the ISO time above is NOW - 0.5 h
        self.assert_same(jobs.MIQ, at)

    def test_the_latest_wind_down_event_is_the_key(self):
        later = NOW - 300
        write_rows(self.st / "events.jsonl", [{"event": "wind_down", "at": NOW - 2 * H},
                                              {"event": "wind_down", "at": later}])
        self.glide_wind_down(NOW - 600)
        self.env["LIMITLESS_GLIDE_ATTENTION"] = str(self.att)
        self.assert_same(jobs.MIQ, later)

    def test_polls_of_one_wind_down_share_the_key(self):
        at = NOW - 90
        write_rows(self.st / "events.jsonl", [{"event": "wind_down", "at": at}])
        self.glide_wind_down(NOW - 120)
        self.env["LIMITLESS_GLIDE_ATTENTION"] = str(self.att)
        self.assertEqual({self.key("miq", NOW + d) for d in (0, 300, 900)}, {night(at)})

    def test_without_the_glide_window_the_event_still_has_its_key_but_nothing_is_pushed(self):
        at = NOW - 90
        write_rows(self.st / "events.jsonl", [{"event": "wind_down", "at": at}])
        self.assertEqual(self.key("miq"), night(at))
        self.assertEqual(self.pushed(jobs.MIQ), [])

    def test_no_wind_down_event_no_key(self):
        self.glide_wind_down(NOW - 120)
        self.env["LIMITLESS_GLIDE_ATTENTION"] = str(self.att)
        self.assertIsNone(self.key("miq"))
        self.assertEqual(self.pushed(jobs.MIQ), [])


class NapKey(Base):
    def test_nap_end_event(self):
        off = NOW - 300
        write_rows(self.st / "sleepmode.jsonl", [{"at": off - 0.5 * H, "on": True}, {"at": off, "on": False}])
        (self.st / "sleepmode-poll.json").write_text(json.dumps({"at": NOW - 60, "ok": True}))
        self.assert_same(jobs.NAP, off)

    def test_nap_after_a_night_is_the_nap_not_the_wake(self):
        wake, off = NOW - 6 * H, NOW - 600
        write_rows(self.st / "sleepmode.jsonl", [{"at": wake - 8 * H, "on": True}, {"at": wake, "on": False},
                                                 {"at": off - 1 * H, "on": True}, {"at": off, "on": False}])
        (self.st / "sleepmode-poll.json").write_text(json.dumps({"at": NOW - 60, "ok": True}))
        write_rows(self.st / "unlocks.jsonl", [{"at": NOW - 120}])
        self.assert_same(jobs.NAP, off)

    def test_a_long_sleep_is_not_a_nap(self):
        write_rows(self.st / "sleepmode.jsonl", [{"at": NOW - 8.5 * H, "on": True}, {"at": NOW - 300, "on": False}])
        (self.st / "sleepmode-poll.json").write_text(json.dumps({"at": NOW - 60, "ok": True}))
        self.assertIsNone(self.key("nap"))
        self.assertEqual(self.pushed(jobs.NAP), [])


if __name__ == "__main__":
    unittest.main()
