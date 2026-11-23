"""/limitless mode [brainstorm|pm|copilot|focused|off]: sets or reads mode.json; never sends. Synthetic only."""
import os
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import modes  # noqa: E402
from test_plugin import FakeCtx, load_plugin  # noqa: E402


class CommandCtx(FakeCtx):
    """FakeCtx plus the host's slash-command API (hermes_cli/plugins_context.py register_command)."""

    def __init__(self):
        super().__init__()
        self.commands = {}

    def register_command(self, name, handler, description="", args_hint="", argument_mode=None):
        self.commands[name] = {"handler": handler, "description": description, "args_hint": args_hint}


def _no_send(*a, **k):
    raise AssertionError("a mode must never send or run anything")


class Command(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.st = Path(self.tmp.name)

    def run_(self, raw):
        with mock.patch.object(subprocess, "run", _no_send), mock.patch.object(subprocess, "Popen", _no_send), \
                mock.patch.object(urllib.request, "urlopen", _no_send), \
                mock.patch.object(socket.socket, "connect", _no_send):
            out = modes.command(raw, self.st)
        self.assertIsInstance(out, str)
        self.assertFalse(any(c.isdigit() for c in out), out)
        return out

    def test_read_with_no_mode(self):
        self.assertEqual(self.run_("mode"), "mode: none (the card as usual)")
        self.assertFalse((self.st / "mode.json").exists())

    def test_set_each_mode_then_read_it(self):
        for m in modes.MODES:
            self.assertEqual(self.run_(f"mode {m}"), f"mode set: {modes.line(m)}")
            self.assertEqual(modes.load(self.st), m)
            self.assertEqual(self.run_("mode"), f"mode: {modes.line(m)}")

    def test_off_returns_to_none(self):
        self.run_("mode focused")
        self.assertEqual(self.run_("mode off"), "mode off: the card as usual")
        self.assertEqual(modes.load(self.st), "none")
        self.assertEqual(self.run_("  MODE   Off  "), "mode off: the card as usual")

    def test_case_and_spaces(self):
        self.run_("  Mode   PM ")
        self.assertEqual(modes.load(self.st), "pm")

    def test_anything_else_is_usage_and_changes_nothing(self):
        self.run_("mode pm")
        for raw in ("", "   ", "mode sprint", "mode pm now", "focus", "modes", None, "status"):
            self.assertEqual(self.run_(raw), modes.USAGE, raw)
            self.assertEqual(modes.load(self.st), "pm")

    def test_only_mode_json_is_written(self):
        for raw in ("mode", "mode focused", "mode", "mode off", "mode sprint"):
            self.run_(raw)
        self.assertEqual(sorted(p.name for p in self.st.iterdir()), ["mode.json"])

    def test_an_unwritable_state_dir_says_so_and_never_raises(self):
        out = modes.command("mode pm", self.st / "absent")
        self.assertEqual(out, "mode not set: the state dir cannot be written")
        self.assertNotIn(str(self.st), out)


class Plugin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ctx = CommandCtx()
        self.mod = load_plugin()
        self.mod.register(self.ctx)

    def test_registers_the_limitless_slash_command(self):
        c = self.ctx.commands["limitless"]
        self.assertIn("mode", c["args_hint"])
        self.assertIn("presentation", c["description"])
        for m in modes.MODES + ("off",):
            self.assertIn(m, c["args_hint"])

    def test_handler_sets_the_mode_in_the_configured_state_dir(self):
        h = self.ctx.commands["limitless"]["handler"]
        with mock.patch.dict(os.environ, {"LIMITLESS_STATE": self.tmp.name}, clear=True):
            self.assertEqual(h("mode copilot"), f"mode set: {modes.line('copilot')}")
            self.assertEqual(h("mode"), f"mode: {modes.line('copilot')}")
        self.assertEqual(modes.load(self.tmp.name), "copilot")

    def test_handler_never_raises(self):
        h = self.ctx.commands["limitless"]["handler"]
        loaded = sys.modules[self.mod.__name__ + ".limitless.modes"]   # the plugin's own copy of modes
        with mock.patch.object(loaded, "command", side_effect=RuntimeError("boom")):
            self.assertEqual(h("mode pm"), "mode not set: the state dir cannot be written")

    def test_no_tool_is_added_and_a_host_without_commands_still_registers(self):
        self.assertNotIn("limitless_mode", self.ctx.tools)
        plain = FakeCtx()
        load_plugin().register(plain)
        self.assertEqual(sorted(plain.tools), sorted(self.ctx.tools))


if __name__ == "__main__":
    unittest.main()
