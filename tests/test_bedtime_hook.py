"""The post_gateway_admission hook: with bedtime_capture on, an admitted owner message in an asleep or
wind_down window is written through capture.capture and answered "Saved for tomorrow." (the agent turn is
skipped); everything else, and any error, passes the message through untouched. Synthetic state only."""
import json
import logging
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import bedtime, capture  # noqa: E402

NOW = 1894708800.0
H = 3600.0
IDEA = "an idea for the synthetic widget demo"
HANDLED = {"action": "handled", "reply": "Saved for tomorrow."}


def iso(t):
    return datetime.fromtimestamp(t, tz=timezone.utc).isoformat()


class Home:
    def __init__(self, window="asleep", cfg=None):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.state = root / "state"
        self.state.mkdir()
        cfg = {"bedtime_capture": "on"} if cfg is None else cfg
        (root / "config.json").write_text(json.dumps(cfg))
        self.env = {"LIMITLESS_STATE": str(self.state), "LIMITLESS_CONFIG": str(root / "config.json"),
                    "LIMITLESS_AUDIT": str(root / "audit.jsonl")}
        self.audit = root / "audit.jsonl"
        rows = [{"at": iso(NOW - 30 * H), "on": True}, {"at": iso(NOW - 20 * H), "on": False}]
        if window == "asleep":
            rows.append({"at": iso(NOW - 2 * H), "on": True})
        else:  # awake, two hours since the wake event: peak by default
            rows = [{"at": iso(NOW - 10 * H), "on": True}, {"at": iso(NOW - 2 * H), "on": False}]
        (self.state / "sleepmode.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        (self.state / "sleepmode-poll.json").write_text(json.dumps({"at": iso(NOW - 60), "ok": True}))
        if window == "wind_down":
            att = root / "attention.json"
            att.write_text(json.dumps({"block": None, "queue": [], "resume": {"saved": NOW - 600}}))
            self.env["LIMITLESS_GLIDE_ATTENTION"] = str(att)

    def hook(self):
        return bedtime.make_post_gateway_admission(env=self.env, clock=lambda: NOW)

    def captures(self):
        p = self.state / capture.FILE
        return [json.loads(ln) for ln in p.read_text().splitlines()] if p.exists() else []

    def close(self):
        self.tmp.cleanup()


def call(hook, text):
    return hook(session_key="agent:main:telegram:dm:x", platform="telegram", source={"platform": "telegram"},
                message_id="m1", text=text)


class Hook(unittest.TestCase):
    def setUp(self):
        self.homes = []

    def tearDown(self):
        for h in self.homes:
            h.close()

    def home(self, *a, **kw):
        h = Home(*a, **kw)
        self.homes.append(h)
        return h

    def test_asleep_captures_through_the_one_store_and_replies(self):
        h = self.home("asleep")
        self.assertEqual(call(h.hook(), IDEA), HANDLED)
        rows = h.captures()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["text"], IDEA)
        self.assertEqual(rows[0]["source"], bedtime.SOURCE)
        self.assertEqual(sorted(p.name for p in h.state.iterdir()),
                         ["captures.jsonl", "sleepmode-poll.json", "sleepmode.jsonl"])  # no new journal

    def test_wind_down_from_glide_captures(self):
        h = self.home("wind_down")
        self.assertEqual(call(h.hook(), IDEA), HANDLED)
        self.assertEqual(len(h.captures()), 1)

    def test_off_by_default_passes_and_writes_nothing(self):
        for cfg in ({}, {"bedtime_capture": "off"}):
            h = self.home("asleep", cfg=cfg)
            self.assertIsNone(call(h.hook(), IDEA))
            self.assertEqual(h.captures(), [])

    def test_awake_passes(self):
        h = self.home("awake")
        self.assertIsNone(call(h.hook(), IDEA))
        self.assertEqual(h.captures(), [])

    def test_urgent_and_commands_pass(self):
        h = self.home("asleep")
        for text in ("urgent: the synthetic build is red", "/stop"):
            self.assertIsNone(call(h.hook(), text))
        self.assertEqual(h.captures(), [])

    def test_configured_urgent_words(self):
        h = self.home("asleep", cfg={"bedtime_capture": "on", "bedtime_urgent_words": ["asap"]})
        self.assertIsNone(call(h.hook(), "asap: look at the demo"))
        self.assertEqual(call(h.hook(), "look at the demo now"), HANDLED)

    def test_a_failed_capture_passes_the_message_through(self):
        h = self.home("asleep")
        self.assertIsNone(call(h.hook(), "x" * (capture.MAX_CHARS + 1)))
        self.assertEqual(h.captures(), [])

    def test_any_error_fails_open(self):
        h = self.home("asleep")
        with mock.patch.object(bedtime, "window_class", side_effect=RuntimeError("boom")):
            self.assertIsNone(call(h.hook(), IDEA))
        with mock.patch.object(bedtime.capture, "capture", side_effect=OSError("disk")):
            self.assertIsNone(call(h.hook(), IDEA))
        self.assertIsNone(h.hook()())  # a payload without text
        self.assertEqual(h.captures(), [])

    def test_the_text_is_never_logged_or_audited(self):
        h = self.home("asleep")
        seen = []

        class Grab(logging.Handler):
            def emit(self, record):
                seen.append(record.getMessage())

        root = logging.getLogger()
        grab, level = Grab(level=logging.DEBUG), root.level
        root.addHandler(grab)
        root.setLevel(logging.DEBUG)
        try:
            call(h.hook(), IDEA)
            with mock.patch.object(bedtime.capture, "capture", side_effect=OSError(IDEA)):
                call(h.hook(), IDEA)
        finally:
            root.removeHandler(grab)
            root.setLevel(level)
        self.assertFalse([m for m in seen if "synthetic widget" in m], seen)
        audit = h.audit.read_text() if h.audit.exists() else ""
        self.assertNotIn("synthetic widget", audit)


class Window(unittest.TestCase):
    def test_window_class_from_state(self):
        for name, want in (("asleep", "asleep"), ("wind_down", "wind_down"), ("awake", "peak")):
            h = Home(name)
            try:
                self.assertEqual(bedtime.window_class(h.state, NOW, env=h.env), want, name)
            finally:
                h.close()


if __name__ == "__main__":
    unittest.main()
