"""The repo root is a Hermes directory plugin: plugin.yaml + __init__.py exposing register(ctx).

Loaded the way hermes_cli/plugins_loader.py loads one (spec_from_file_location with the plugin dir as
the package path, module name hermes_plugins.<slug>), against a fake ctx: Hermes is not needed.
"""
import importlib.util
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "state"
CARD = ROOT / "tests" / "fixtures" / "scorecard" / "scorecard.md"
NOW = 1894708800.0  # fixture clock
TOOLS = ["limitless_body", "limitless_capture", "limitless_catchup", "limitless_habit", "limitless_rides",
         "limitless_scorecard", "limitless_state", "limitless_status", "limitless_window"]
FIELDS = {"value", "modality", "age_h", "evidence_tier"}


def body_config(st: Path) -> Path:
    """A config naming a synthetic body file in ``st`` with three visits in each window before NOW."""
    from datetime import date, timedelta
    today = date.fromtimestamp(NOW)
    rows = [{"day": (today - timedelta(days=d)).isoformat(), "bf_pct": 20.0, "method": "synthetic",
             "calibrated": True} for d in (1, 4, 7, 15, 18, 21)]
    (st / "body.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    cfg = st / "body-config.json"
    cfg.write_text(json.dumps({"body_file": "body.jsonl"}))
    return cfg


def rides_config(st: Path) -> Path:
    """A config naming a synthetic rides file in ``st`` with two rides in the week before NOW."""
    from datetime import date, timedelta
    today = date.fromtimestamp(NOW)
    rows = [{"start": f"{(today - timedelta(days=d)).isoformat()}T07:00:00+00:00", "duration_s": 600,
             "kind": "rehit", "source": "synthetic-bike-app"} for d in (1, 4)]
    (st / "rides.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    cfg = st / "rides-config.json"
    cfg.write_text(json.dumps({"rides_file": "rides.jsonl"}))
    return cfg


class FakeCtx:
    def __init__(self):
        self.tools, self.hooks = {}, {}

    def register_tool(self, name, toolset, schema, handler, check_fn=None, requires_env=None,
                      is_async=False, description="", emoji="", override=False):
        self.tools[name] = {"toolset": toolset, "schema": schema, "handler": handler,
                            "description": description}

    def register_hook(self, hook_name, callback, *, hold_stream=False):
        self.hooks.setdefault(hook_name, []).append(callback)


def load_plugin(name="hermes_plugins.limitless_test"):
    if "hermes_plugins" not in sys.modules:
        ns = types.ModuleType("hermes_plugins")
        ns.__path__ = []
        sys.modules["hermes_plugins"] = ns
    for m in [m for m in sys.modules if m == name or m.startswith(name + ".")]:
        del sys.modules[m]
    spec = importlib.util.spec_from_file_location(name, ROOT / "__init__.py",
                                                  submodule_search_locations=[str(ROOT)])
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = name
    mod.__path__ = [str(ROOT)]
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def owner_db(path, at=NOW - 30 * 3600):
    """A synthetic Hermes session store whose only message from the person is at ``at``."""
    con = sqlite3.connect(str(path))
    con.executescript("CREATE TABLE sessions (id TEXT PRIMARY KEY, source TEXT);"
                      "CREATE TABLE messages (session_id TEXT, role TEXT, content TEXT, timestamp REAL NOT NULL);"
                      "CREATE INDEX idx_messages_session ON messages(session_id, timestamp);")
    con.execute("INSERT INTO sessions VALUES ('s', 'cli')")
    con.execute("INSERT INTO messages VALUES ('s', 'user', 'synthetic', ?)", (at,))
    con.commit()
    con.close()
    return path


def manifest_list(key):
    """The YAML list under `key:` in plugin.yaml (stdlib only: simple '  - item' lines)."""
    lines = (ROOT / "plugin.yaml").read_text().splitlines()
    out, inside = [], False
    for ln in lines:
        if re.match(rf"^{key}:\s*$", ln):
            inside = True
        elif inside and re.match(r"^\s+-\s+", ln):
            out.append(re.sub(r"^\s+-\s+", "", ln).strip())
        elif inside and ln.strip():
            inside = False
    return out


class PluginSkeleton(unittest.TestCase):
    def test_manifest_names_the_plugin(self):
        text = (ROOT / "plugin.yaml").read_text()
        self.assertRegex(text, r"(?m)^name:\s*limitless\s*$")
        self.assertRegex(text, r"(?m)^version:\s*\S+")
        self.assertRegex(text, r"(?m)^description:\s*\S+")

    def test_register_runs_against_a_fake_ctx_without_hermes(self):
        mod = load_plugin()
        ctx = FakeCtx()
        mod.register(ctx)
        self.assertNotIn("hermes_cli", sys.modules)

    def test_registrations_match_the_manifest(self):
        ctx = FakeCtx()
        load_plugin().register(ctx)
        self.assertEqual(sorted(ctx.tools), sorted(manifest_list("provides_tools")))
        self.assertEqual(sorted(ctx.hooks), sorted(manifest_list("provides_hooks")))
        for name, t in ctx.tools.items():
            self.assertEqual(t["schema"]["name"], name)
            self.assertEqual(t["toolset"], "limitless")
            self.assertTrue(t["schema"]["description"])

    def test_package_imports_on_its_own(self):
        sys.path.insert(0, str(ROOT))
        try:
            import limitless.plugin as p  # noqa: F401
        finally:
            sys.path.remove(str(ROOT))
        self.assertTrue(callable(p.register))


class Wiring(unittest.TestCase):
    def setUp(self):
        self.ctx = FakeCtx()
        load_plugin().register(self.ctx)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def call(self, name, args=None, env=None):
        env = env or {"LIMITLESS_STATE": str(FIX), "LIMITLESS_SCORECARD": str(CARD)}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(time, "time", return_value=NOW):
            out = self.ctx.tools[name]["handler"](args if args is not None else {}, task_id="t", session_id="s")
        self.assertIsInstance(out, str)
        return json.loads(out)

    def test_the_six_tools_and_the_hook(self):
        self.assertEqual(sorted(self.ctx.tools), TOOLS)
        self.assertEqual(sorted(self.ctx.hooks), ["post_gateway_admission", "pre_llm_call"])

    def test_every_tool_returns_an_envelope(self):
        st = Path(self.tmp.name)
        for name in TOOLS:
            args = {"text": "remember the shed"} if name == "limitless_capture" else {}
            env = {"LIMITLESS_STATE": str(st)} if name == "limitless_capture" else None
            if name == "limitless_catchup":
                env = {"LIMITLESS_STATE": str(FIX), "LIMITLESS_OWNER_DBS": str(owner_db(st / "owner.db"))}
            if name == "limitless_body":   # synthetic visits, three in each two-week window
                env = {"LIMITLESS_STATE": str(st), "LIMITLESS_CONFIG": str(body_config(st))}
            if name == "limitless_rides":   # synthetic rides, two in the last seven days
                env = {"LIMITLESS_STATE": str(st), "LIMITLESS_CONFIG": str(rides_config(st))}
            res = self.call(name, args, env)
            self.assertTrue(FIELDS <= set(res), (name, res))
            self.assertIsNotNone(res["value"], (name, res))

    def test_fixture_values_through_the_handlers(self):
        self.assertEqual(self.call("limitless_window")["value"], "peak")
        self.assertEqual(self.call("limitless_status")["value"]["not_recording"], ["anki", "bike", "scale"])
        self.assertEqual(self.call("limitless_habit")["value"]["today"], "Done")
        self.assertEqual(self.call("limitless_state")["value"]["items"]["readiness"]["value"], "low")

    def test_scorecard_through_the_handler(self):
        res = self.call("limitless_scorecard")
        self.assertEqual(res["modality"], "self_report")
        self.assertEqual(res["value"][:2], ["6 green, 2 amber, 2 red of 10", "not all green yet"])
        res = self.call("limitless_scorecard", env={"LIMITLESS_SCORECARD": "/definitely/not/here.md"})
        self.assertIsNone(res["value"])
        self.assertTrue(res["reason"])

    def test_window_bands_come_from_config(self):
        cfg = Path(self.tmp.name) / "config.json"
        cfg.write_text(json.dumps({"state": str(FIX), "window_bands": {"peak": [6, 8], "trough": [1, 6]}}))
        self.assertEqual(self.call("limitless_window", env={"LIMITLESS_CONFIG": str(cfg)})["value"], "trough")

    def test_handlers_never_raise(self):
        res = self.call("limitless_capture", {"text": 42}, {"LIMITLESS_STATE": self.tmp.name})
        self.assertIsNone(res["value"])
        self.assertTrue(res["reason"])
        res = self.call("limitless_status", None, {"LIMITLESS_STATE": "/definitely/not/here"})
        self.assertIsNone(res["value"])

    def test_capture_schema_requires_text(self):
        params = self.ctx.tools["limitless_capture"]["schema"]["parameters"]
        self.assertEqual(params["required"], ["text"])

    def test_catchup_tool_through_the_handler(self):
        env = {"LIMITLESS_STATE": str(FIX), "LIMITLESS_OWNER_DBS": str(owner_db(Path(self.tmp.name) / "o.db"))}
        res = self.call("limitless_catchup", env=env)
        self.assertEqual(set(res), {"value", "modality", "age_h", "evidence_tier", "label"})
        self.assertEqual(res["label"], {"label": "stale", "tier": "T1", "modality": "messages"})  # last seen 30 h ago
        self.assertEqual(res["value"]["label"], {"label": "away", "tier": "T1", "modality": "messages"})
        self.assertEqual(res["modality"], "messages")
        self.assertTrue(res["value"]["lines"][0].startswith("[limitless] catch-up"))
        self.assertFalse(any(c.isdigit() for c in "".join(res["value"]["lines"])))

    def test_catchup_hook_injects_once_after_the_card(self):
        self.assertEqual(len(self.ctx.hooks["pre_llm_call"]), 2)
        hook = self.ctx.hooks["pre_llm_call"][1]
        env = {"LIMITLESS_STATE": str(FIX), "LIMITLESS_OWNER_DBS": str(owner_db(Path(self.tmp.name) / "o.db"))}
        kw = dict(session_id="s", user_message="hi", conversation_history=[], is_first_turn=True, model="m",
                  platform="cli", sender_id="u")
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(time, "time", return_value=NOW):
            first, second = hook(**kw), hook(**kw)
        self.assertTrue(first["context"].startswith("[limitless] catch-up"), first)
        self.assertIsNone(second)

    def test_hook_injects_the_card(self):
        hook = self.ctx.hooks["pre_llm_call"][0]
        with mock.patch.dict(os.environ, {"LIMITLESS_STATE": str(FIX)}, clear=True), \
                mock.patch.object(time, "time", return_value=NOW):
            out = hook(session_id="s", user_message="hi", conversation_history=[], is_first_turn=True,
                       model="m", platform="cli", sender_id="u")
        self.assertIn("readiness low (imported)", out["context"])


if __name__ == "__main__":
    unittest.main()
