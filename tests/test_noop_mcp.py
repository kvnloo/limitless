"""noop_mcp: the NOOP agent MCP server's spec from config noop_mcp, and whether the result tier filter covers its
tools. The host has no plugin API to register an MCP server, so nothing here registers one, and nothing here ever
starts a process. Synthetic config only."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from limitless import noop_mcp  # noqa: E402

CMD = ["noop-agent-mcp", "--stdio"]
COVER = "mcp__noop__*"


def no_spawn():
    """Every process-starting function patched to raise, for the length of one test."""
    def boom(*a, **k):
        raise AssertionError("a process was started")
    names = [("subprocess", n) for n in ("Popen", "run", "call", "check_call", "check_output")]
    names += [("os", n) for n in ("system", "popen", "posix_spawn", "posix_spawnp", "spawnv", "spawnve", "spawnvp",
                                  "spawnl", "spawnlp", "execv", "execve", "execvp", "fork", "forkpty")]
    mods = {"subprocess": subprocess, "os": os}
    return [mock.patch.object(mods[m], n, boom) for m, n in names if hasattr(mods[m], n)]


class Spawnless(unittest.TestCase):
    def setUp(self):
        for p in no_spawn():
            p.start()
            self.addCleanup(p.stop)


class Spec(Spawnless):
    def test_unset_is_none(self):
        for cfg in ({}, None, {"noop_mcp": None}, {"noop_mcp": {}}, "x"):
            self.assertIsNone(noop_mcp.server_spec(cfg), cfg)

    def test_command_and_env(self):
        spec = noop_mcp.server_spec({"noop_mcp": {"command": CMD, "env": {"NOOP_DB": "/path/to/noop.db"}}})
        self.assertEqual(spec, {"name": "noop", "command": CMD, "env": {"NOOP_DB": "/path/to/noop.db"}})

    def test_env_is_optional_and_a_copy(self):
        raw = {"command": list(CMD)}
        spec = noop_mcp.server_spec({"noop_mcp": raw})
        self.assertEqual(spec, {"name": "noop", "command": CMD, "env": {}})
        spec["command"].append("--more")
        self.assertEqual(raw["command"], CMD)

    def test_a_named_server(self):
        spec = noop_mcp.server_spec({"noop_mcp": {"command": CMD, "name": "health"}})
        self.assertEqual(spec["name"], "health")
        self.assertEqual(noop_mcp.tool_prefix(spec), "mcp__health__")

    def test_malformed_is_none(self):
        for raw in ({"command": []}, {"command": "noop-agent-mcp --stdio"}, {"command": ["", "x"]},
                    {"command": [1]}, {"command": CMD, "env": {"A": 1}}, {"command": CMD, "env": ["A"]},
                    {"command": CMD, "name": ""}, {"command": CMD, "name": 3}, ["noop-agent-mcp"]):
            self.assertIsNone(noop_mcp.server_spec({"noop_mcp": raw}), raw)
        self.assertTrue(noop_mcp.is_set({"noop_mcp": {"command": []}}))
        self.assertFalse(noop_mcp.is_set({}))
        self.assertFalse(noop_mcp.is_set({"noop_mcp": None}))

    def test_prefix_is_the_hosts_mcp_tool_name(self):
        spec = noop_mcp.server_spec({"noop_mcp": {"command": CMD, "name": "noop-agent"}})
        self.assertEqual(noop_mcp.tool_prefix(spec), "mcp__noop_agent__")


class Covered(Spawnless):
    def spec(self, **extra):
        return noop_mcp.server_spec({"noop_mcp": dict({"command": CMD}, **extra)})

    def test_a_server_glob_covers(self):
        for globs in (COVER, [COVER], ["mcp__*"], ["*"], ["limitless_*", "mcp__noop__*"]):
            self.assertTrue(noop_mcp.covered(self.spec(), {"t0_tools": globs}), globs)

    def test_missing_or_partial_globs_do_not(self):
        for globs in (None, [], "", ["mcp__noop__health_snapshot"], ["mcp__noop__sleep_*"], ["mcp__other__*"],
                      ["MCP__NOOP__*"], [3]):
            self.assertFalse(noop_mcp.covered(self.spec(), {"t0_tools": globs}), globs)

    def test_the_prefix_follows_the_name(self):
        self.assertFalse(noop_mcp.covered(self.spec(name="health"), {"t0_tools": [COVER]}))
        self.assertTrue(noop_mcp.covered(self.spec(name="health"), {"t0_tools": ["mcp__health__*"]}))

    def test_no_spec_is_never_covered(self):
        self.assertFalse(noop_mcp.covered(None, {"t0_tools": ["*"]}))


class State(Spawnless):
    def test_each_state(self):
        on = {"command": CMD}
        self.assertEqual(noop_mcp.state({}), noop_mcp.OFF)
        self.assertEqual(noop_mcp.state({"noop_mcp": {"command": []}}), noop_mcp.MALFORMED)
        self.assertEqual(noop_mcp.state({"noop_mcp": on}), noop_mcp.REFUSED)
        self.assertEqual(noop_mcp.state({"noop_mcp": on, "t0_tools": ["mcp__noop__sleep_*"]}), noop_mcp.REFUSED)
        self.assertEqual(noop_mcp.state({"noop_mcp": on, "t0_tools": [COVER]}), noop_mcp.BY_HAND)

    def test_the_plugin_registers_no_mcp_server(self):
        """No host API exists, so plugin.register never calls one, even on a ctx that has such a method."""
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from test_plugin import FakeCtx, load_plugin  # noqa: E402
        calls = []

        class Ctx(FakeCtx):
            def __getattr__(self, name):
                if "mcp" in name.lower():
                    return lambda *a, **k: calls.append(name)
                raise AttributeError(name)

        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "config.json"
            cfg.write_text(json.dumps({"noop_mcp": {"command": CMD}, "t0_tools": [COVER]}))
            with mock.patch.dict(os.environ, {"LIMITLESS_CONFIG": str(cfg)}):
                ctx = Ctx()
                load_plugin().register(ctx)
        self.assertEqual(calls, [])
        self.assertTrue(ctx.tools)


if __name__ == "__main__":
    unittest.main()
