"""register(ctx) offers all three of the plugin's skills, limitless:coach, limitless:learn and limitless:chief, to a
host with register_skill, in that order; without it one content-free line in all; one call the host refuses never
stops the others."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from skill_checks import frontmatter  # noqa: E402
from test_coach_register import SkillCtx, _ours  # noqa: E402
from test_learn_register import RefusesOne  # noqa: E402
from test_plugin import FakeCtx, fake_ctx_hooks, load_plugin, manifest_list  # noqa: E402

from limitless import coach_skill  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ALL = ["coach", "learn", "chief"]


class Register(unittest.TestCase):
    def register(self, ctx, skills_dir=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = {"LIMITLESS_CONFIG": str(Path(tmp.name) / "absent.json")}
        mod = load_plugin()
        loaded = sys.modules[mod.__name__ + ".limitless.coach_skill"]   # the plugin's own copy of the module
        with mock.patch.dict(os.environ, env, clear=True), self.assertLogs(level="DEBUG") as cm, \
                mock.patch.object(loaded, "SKILLS_DIR", skills_dir or loaded.SKILLS_DIR):
            logging.getLogger("limitless-chief-test").debug("anchor")   # assertLogs needs one record
            mod.register(ctx)
        return _ours(cm)

    def assert_rest_registered(self, ctx):
        self.assertEqual(sorted(ctx.tools), sorted(manifest_list("provides_tools")))
        self.assertEqual(sorted(ctx.hooks), fake_ctx_hooks())

    def test_the_names_are_coach_learn_chief_with_a_file_each(self):
        self.assertEqual(list(coach_skill.NAMES), ALL)
        p = coach_skill.path("chief")
        self.assertEqual(p.resolve(), (ROOT / "skills" / "chief" / "SKILL.md").resolve())
        self.assertTrue(p.is_file())
        self.assertEqual(frontmatter(p.read_text())[0]["name"], "chief")

    def test_a_host_with_register_skill_gets_all_three_in_order(self):
        ctx = SkillCtx()
        lines = self.register(ctx)
        self.assertEqual([s["name"] for s in ctx.skills], ALL)
        chief = ctx.skills[-1]
        self.assertEqual(chief["description"], frontmatter(chief["path"].read_text())[0]["description"])
        self.assertTrue(chief["description"].startswith("Use when "))
        self.assertEqual([r.getMessage() for r in lines if r.levelno >= logging.WARNING], [])
        self.assert_rest_registered(ctx)

    def test_a_host_without_it_gets_one_line_for_all_three(self):
        ctx = FakeCtx()
        lines = self.register(ctx)
        self.assertEqual([r.getMessage() for r in lines], [coach_skill.NO_HOST])
        self.assert_rest_registered(ctx)

    def test_any_one_refused_call_still_lets_the_other_two_register(self):
        for refused in ALL:
            for exc in (RuntimeError("host refused"), ValueError("bad name"), FileNotFoundError("gone")):
                with self.subTest(refused=refused, exc=type(exc).__name__):
                    ctx = RefusesOne(refused, exc)
                    lines = self.register(ctx)
                    self.assertEqual(ctx.calls, ALL)
                    self.assertEqual([s["name"] for s in ctx.skills], [n for n in ALL if n != refused])
                    self.assertEqual([(r.levelno, r.getMessage()) for r in lines],
                                     [(logging.WARNING, coach_skill.HOST_FAILED)])
                    self.assert_rest_registered(ctx)

    def test_a_missing_chief_file_still_lets_coach_and_learn_register(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for name in ("coach", "learn"):
            d = Path(tmp.name) / name
            d.mkdir()
            (d / "SKILL.md").write_text((ROOT / "skills" / name / "SKILL.md").read_text())
        ctx = SkillCtx()
        lines = self.register(ctx, skills_dir=Path(tmp.name))
        self.assertEqual([s["name"] for s in ctx.skills], ["coach", "learn"])
        self.assertEqual([r.getMessage() for r in lines], [coach_skill.HOST_FAILED])
        self.assert_rest_registered(ctx)


if __name__ == "__main__":
    unittest.main()
