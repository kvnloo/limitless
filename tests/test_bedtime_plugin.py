"""register(ctx) wires bedtime capture to post_gateway_admission, a real Hermes hook (hermes_cli/plugins.py
VALID_HOOKS), and the hook is inert while bedtime_capture is off (the default). Synthetic state only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from test_plugin import FakeCtx, load_plugin

NOW = 1894708800.0


def iso(t):
    return datetime.fromtimestamp(t, tz=timezone.utc).isoformat()


class Wiring(unittest.TestCase):
    def setUp(self):
        self.mod = load_plugin("hermes_plugins.limitless_bedtime_test")
        self.ctx = FakeCtx()
        self.mod.register(self.ctx)
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.state = root / "state"
        self.state.mkdir()
        (self.state / "sleepmode.jsonl").write_text(
            json.dumps({"at": iso(NOW - 30 * 3600), "on": True}) + "\n"
            + json.dumps({"at": iso(NOW - 20 * 3600), "on": False}) + "\n"
            + json.dumps({"at": iso(NOW - 3600), "on": True}) + "\n")
        (self.state / "sleepmode-poll.json").write_text(json.dumps({"at": iso(NOW - 60), "ok": True}))
        self.cfg = root / "config.json"

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, cfg):
        self.cfg.write_text(json.dumps(cfg))
        hook = self.ctx.hooks["post_gateway_admission"][0]
        env = {"LIMITLESS_STATE": str(self.state), "LIMITLESS_CONFIG": str(self.cfg)}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(time, "time", return_value=NOW):
            return hook(session_key="k", platform="telegram", source={}, message_id="m", text="a synthetic idea")

    def test_one_post_gateway_admission_hook_and_the_card_hook_stay(self):
        self.assertEqual(len(self.ctx.hooks["post_gateway_admission"]), 1)
        # bedtime adds no pre_llm_call of its own: only the card's and the catch-up's are there
        self.assertEqual(sorted(f.__module__.rsplit(".", 1)[-1] for f in self.ctx.hooks["pre_llm_call"]),
                         ["card", "catchup"])

    def test_off_by_default(self):
        self.assertIsNone(self.run_hook({}))
        self.assertFalse((self.state / "captures.jsonl").exists())

    def test_on_and_asleep_is_handled(self):
        self.assertEqual(self.run_hook({"bedtime_capture": "on"}),
                         {"action": "handled", "reply": "Saved for tomorrow."})


if __name__ == "__main__":
    unittest.main()
