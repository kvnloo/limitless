"""Static guard: every test module loads the isolation, and every child process a test starts gets its HOME.

test_00_hermetic only isolates a full `discover` run, and only in-process. A single-file run
(`discover -s tests -p test_x.py`) never imports it, and a child interpreter started with an env= that lacks
HOME falls back to the passwd entry, which is the real home with the real config and audit log. So:

- every tests/test_*.py must import hermetic_env as its first statement (after the docstring and any
  `from __future__` import), before anything can read a config;
- every subprocess call anywhere under tests/ must pass env= built by hermetic_env.child_env(...).
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import ast
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from hermetic_env import TEST_HOME, child_env

TESTS = Path(__file__).resolve().parent
SPAWN = {"run", "Popen", "call", "check_call", "check_output"}  # subprocess.* that take env=
NO_ENV = {"getoutput", "getstatusoutput"}  # subprocess.* that cannot take env=
OS_SPAWN = ("system", "popen", "exec", "spawn", "posix_spawn", "fork")
ASYNC_SPAWN = {"create_subprocess_exec", "create_subprocess_shell"}


def _is_child_env(node):
    return isinstance(node, ast.Call) and (
        (isinstance(node.func, ast.Name) and node.func.id == "child_env")
        or (isinstance(node.func, ast.Attribute) and node.func.attr == "child_env"))


def spawn_problems(src, name="<src>"):
    """Every process-starting call in `src` whose env= is not a direct hermetic_env.child_env(...) call."""
    tree = ast.parse(src)
    mods = {"subprocess": "subprocess", "os": "os", "asyncio": "asyncio"}  # local name -> module
    funcs = {}  # local name -> (module, attr) for `from subprocess import run`
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name in ("subprocess", "os", "asyncio"):
                    mods[a.asname or a.name] = a.name
        elif isinstance(n, ast.ImportFrom) and n.module in ("subprocess", "os", "asyncio"):
            for a in n.names:
                funcs[a.asname or a.name] = (n.module, a.name)
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in mods:
            mod, attr = mods[f.value.id], f.attr
        elif isinstance(f, ast.Name) and f.id in funcs:
            mod, attr = funcs[f.id]
        else:
            continue
        where = f"{name}:{n.lineno} {mod}.{attr}"
        if (mod == "subprocess" and attr in NO_ENV) or (mod == "os" and attr.startswith(OS_SPAWN)):
            out.append(f"{where}: cannot pass env=child_env(...); use subprocess.run")
        elif (mod == "subprocess" and attr in SPAWN) or (mod == "asyncio" and attr in ASYNC_SPAWN):
            env = [k.value for k in n.keywords if k.arg == "env"]
            if not env:
                out.append(f"{where}: no env=; pass env=child_env(...)")
            elif not _is_child_env(env[0]):
                out.append(f"{where}: env={ast.get_source_segment(src, env[0])} is not child_env(...)")
    return out


def first_statement_problem(src, name="<src>"):
    """None when the module's first real statement imports hermetic_env, else why not."""
    body = ast.parse(src).body
    i = 0
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        i = 1
    while i < len(body) and isinstance(body[i], ast.ImportFrom) and body[i].module == "__future__":
        i += 1
    if i < len(body):
        s = body[i]
        if isinstance(s, ast.Import) and any(a.name == "hermetic_env" for a in s.names):
            return None
        if isinstance(s, ast.ImportFrom) and s.module == "hermetic_env" and not s.level:
            return None
        return f"{name}:{s.lineno}: first statement is not `import hermetic_env`"
    return f"{name}: no statements, so no `import hermetic_env`"


class EveryTestModuleLoadsTheIsolation(unittest.TestCase):
    def test_every_test_module_imports_hermetic_env_first(self):
        bad = [p for f in sorted(TESTS.glob("test_*.py"))
               for p in [first_statement_problem(f.read_text(), f.name)] if p]
        self.assertEqual(bad, [], "\n".join(bad))

    def test_the_rule_catches_a_late_or_missing_import(self):
        self.assertIsNone(first_statement_problem('"""doc"""\nimport hermetic_env\nimport os\n'))
        self.assertIsNone(first_statement_problem("from __future__ import annotations\nimport hermetic_env\n"))
        self.assertIsNotNone(first_statement_problem("import os\nimport hermetic_env\n"))
        self.assertIsNotNone(first_statement_problem('"""doc"""\nimport os\n'))
        self.assertIsNotNone(first_statement_problem(""))


class EveryChildProcessGetsTheTestHome(unittest.TestCase):
    def test_every_subprocess_call_under_tests_uses_child_env(self):
        bad = [p for f in sorted(TESTS.rglob("*.py")) if "__pycache__" not in f.parts
               for p in spawn_problems(f.read_text(), str(f.relative_to(TESTS)))]
        self.assertEqual(bad, [], "\n".join(bad))

    def test_the_rule_catches_each_shape(self):
        ok = ("import subprocess\nfrom hermetic_env import child_env\nimport hermetic_env\n"
              "subprocess.run(['x'], env=child_env())\nsubprocess.Popen(['x'], env=hermetic_env.child_env(e))\n")
        self.assertEqual(spawn_problems(ok), [])
        for src in ("import subprocess\nsubprocess.run(['x'])\n",
                    "import subprocess\nsubprocess.run(['x'], env={'PATH': ''})\n",
                    "import subprocess\nsubprocess.check_output(['x'], env=self.env)\n",
                    "import subprocess as sp\nsp.Popen(['x'], env=env)\n",
                    "from subprocess import run\nrun(['x'])\n",
                    "from subprocess import check_output as co\nco(['x'], env=dict(os.environ))\n",
                    "import subprocess\nsubprocess.getoutput('x')\n",
                    "import os\nos.system('x')\n",
                    "import os\nos.execvpe('x', ['x'], {})\n",
                    "import asyncio\nasyncio.create_subprocess_exec('x')\n"):
            self.assertEqual(len(spawn_problems(src)), 1, src)


class ChildEnv(unittest.TestCase):
    def test_a_cleared_environment_still_gives_the_child_the_test_home(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(child_env()["HOME"], str(TEST_HOME))
        self.assertEqual(child_env({"PATH": "/x"})["HOME"], str(TEST_HOME))
        self.assertEqual(child_env({"HOME": ""})["HOME"], str(TEST_HOME))

    def test_a_home_the_test_chose_is_kept_and_extras_apply(self):
        env = child_env({"HOME": "/tmp/zq-own-home", "A": "1"}, B="2")
        self.assertEqual((env["HOME"], env["A"], env["B"]), ("/tmp/zq-own-home", "1", "2"))

    def test_the_base_is_copied_not_changed(self):
        base = {"PATH": "/x"}
        child_env(base, B="2")
        self.assertEqual(base, {"PATH": "/x"})

    @unittest.skipUnless(hermetic_env._passwd_home(), "no passwd entry")
    def test_the_passwd_home_is_refused(self):
        with self.assertRaises(RuntimeError):
            child_env({"HOME": hermetic_env._passwd_home()})

    def test_a_real_child_with_a_cleared_env_sees_the_test_home(self):
        code = "import os, pathlib; print(pathlib.Path.home()); print(os.path.expanduser('~/a'))"
        r = subprocess.run([sys.executable, "-I", "-c", code], env=child_env({}), capture_output=True, text=True,
                           timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.split(), [str(TEST_HOME), str(TEST_HOME / "a")])

    def test_in_process_tilde_never_reaches_the_passwd_home_with_home_unset(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(Path.home(), TEST_HOME)
            self.assertEqual(Path("~/a").expanduser(), TEST_HOME / "a")
            self.assertEqual(os.path.expanduser("~/a"), str(TEST_HOME / "a"))
            self.assertEqual(os.path.expanduser("~"), str(TEST_HOME))
        self.assertEqual(Path("/abs/~x").expanduser(), Path("/abs/~x"))


if __name__ == "__main__":
    unittest.main()
