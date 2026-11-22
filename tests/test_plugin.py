"""The repo root is a Hermes directory plugin: plugin.yaml + __init__.py exposing register(ctx).

Loaded the way hermes_cli/plugins_loader.py loads one (spec_from_file_location with the plugin dir as
the package path, module name hermes_plugins.<slug>), against a fake ctx: Hermes is not needed.
"""
import importlib.util
import re
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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


if __name__ == "__main__":
    unittest.main()
