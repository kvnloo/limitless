"""result_tier registers its transform_tool_result hook unless the host's loaded hermes_cli.plugins module
lists VALID_HOOKS without that name (an older host). With no host module loaded at all (a bare fake ctx, or
`hermes plugins validate`'s isolated capability probe) it registers, because the plugin's requires_hermes floor
already guarantees the hook wherever Hermes loads it. It never imports the host. Synthetic fake modules only."""
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

    def test_no_host_module_still_gets_it_and_imports_nothing(self):
        # the validator's capability probe imports nothing from Hermes: the declared hook must still register there
        ctx = FakeCtx()
        with mock.patch.dict(sys.modules):
            for m in [m for m in sys.modules if m == "hermes_cli" or m.startswith("hermes_cli.")]:
                del sys.modules[m]
            rt.register(ctx)
            self.assertNotIn("hermes_cli", sys.modules)
        self.assertEqual(list(ctx.hooks), [rt.HOOK_NAME])
        self.assertEqual(len(ctx.hooks[rt.HOOK_NAME]), 1)

    def test_a_host_module_with_an_unreadable_table_gets_nothing(self):
        # a loaded host whose VALID_HOOKS we cannot read is treated like an older host: no hook
        for table in (None, "transform_tool_result", 7):
            ctx = FakeCtx()
            mod = types.ModuleType("hermes_cli.plugins")
            mod.VALID_HOOKS = table
            with mock.patch.dict(sys.modules, {"hermes_cli.plugins": mod}):
                rt.register(ctx)
            self.assertEqual(ctx.hooks, {}, table)

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
    def test_a_bare_fake_ctx_gets_every_manifest_hook_and_tool(self):
        # what `hermes plugins validate` sees: every declared hook is registered, so the manifest matches
        ctx = FakeCtx()
        with mock.patch.dict(sys.modules):
            for m in [m for m in sys.modules if m == "hermes_cli" or m.startswith("hermes_cli.")]:
                del sys.modules[m]
            load_plugin().register(ctx)
        self.assertEqual(sorted(ctx.hooks), sorted(manifest_list("provides_hooks")))
        self.assertEqual(sorted(ctx.tools), sorted(manifest_list("provides_tools")))

    def test_an_older_host_still_loads_every_tool_without_the_hook(self):
        ctx = FakeCtx()
        with host(*(h for h in manifest_list("provides_hooks") if h != rt.HOOK_NAME)):
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
