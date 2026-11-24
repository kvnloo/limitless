"""result_tier registers its transform_tool_result hook only on a host that knows that hook name (the
VALID_HOOKS of the host's loaded hermes_cli.plugins module); an older host or a bare fake ctx still loads the
plugin. Synthetic fake modules only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import result_tier as rt  # noqa: E402
from test_plugin import FakeCtx, load_plugin, manifest_list  # noqa: E402


def host(*hooks):
    """A fake loaded host plugins module with these hook names."""
    mod = types.ModuleType("hermes_cli.plugins")
    mod.VALID_HOOKS = set(hooks)
    pkg = types.ModuleType("hermes_cli")
    pkg.plugins = mod
    return mock.patch.dict(sys.modules, {"hermes_cli": pkg, "hermes_cli.plugins": mod})


class Register(unittest.TestCase):
    def test_a_host_that_knows_the_hook_gets_it(self):
        ctx = FakeCtx()
        with host("pre_tool_call", rt.HOOK_NAME):
            rt.register(ctx)
        self.assertEqual(list(ctx.hooks), [rt.HOOK_NAME])
        self.assertEqual(len(ctx.hooks[rt.HOOK_NAME]), 1)
        self.assertTrue(callable(ctx.hooks[rt.HOOK_NAME][0]))

    def test_a_host_without_the_hook_name_gets_nothing(self):
        ctx = FakeCtx()
        with host("pre_tool_call", "post_tool_call"):
            rt.register(ctx)
        self.assertEqual(ctx.hooks, {})

    def test_no_host_module_gets_nothing_and_imports_nothing(self):
        ctx = FakeCtx()
        with mock.patch.dict(sys.modules):
            for m in [m for m in sys.modules if m == "hermes_cli" or m.startswith("hermes_cli.")]:
                del sys.modules[m]
            rt.register(ctx)
            self.assertNotIn("hermes_cli", sys.modules)
        self.assertEqual(ctx.hooks, {})

    def test_a_host_that_raises_never_breaks_registration(self):
        class Raising(FakeCtx):
            def register_hook(self, hook_name, callback, *, hold_stream=False):
                raise RuntimeError("synthetic host failure")
        with host(rt.HOOK_NAME):
            rt.register(Raising())

    def test_odd_host_tables_are_unknown(self):
        for table in (None, "transform_tool_result", 7):
            mod = types.ModuleType("hermes_cli.plugins")
            mod.VALID_HOOKS = table
            with mock.patch.dict(sys.modules, {"hermes_cli.plugins": mod}):
                self.assertFalse(rt.host_knows(rt.HOOK_NAME), table)


class PluginWiring(unittest.TestCase):
    def test_a_fake_ctx_without_the_hook_name_still_loads_every_tool(self):
        ctx = FakeCtx()
        load_plugin().register(ctx)
        self.assertNotIn(rt.HOOK_NAME, ctx.hooks)
        self.assertEqual(sorted(ctx.tools), sorted(manifest_list("provides_tools")))

    def test_on_a_host_that_knows_it_every_manifest_hook_is_registered(self):
        ctx = FakeCtx()
        with host(*manifest_list("provides_hooks")):
            load_plugin().register(ctx)
        self.assertEqual(sorted(ctx.hooks), sorted(manifest_list("provides_hooks")))
        self.assertEqual(len(ctx.hooks[rt.HOOK_NAME]), 1)


if __name__ == "__main__":
    unittest.main()
