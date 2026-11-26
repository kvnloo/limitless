"""limitless.push_sender inside Hermes: no profile's .env or config.yaml is opened (plugin-catalog rule 11).

Hermes imports the plugin as ``hermes_plugins.<slug>``; that copy of push_sender answers readiness from the
profile's existence alone, so a ready profile becomes a maybe (``unknown: ...``) and nothing reads its token.
The CLIs import ``limitless`` itself and keep the presence read (the other push_sender tests). Synthetic homes only.
"""
from hermetic_env import TEST_HOME  # noqa: F401  first import: isolates HOME, see tests/hermetic_env.py
import builtins
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import push_sender as cli_copy  # noqa: E402

SOURCE = Path(cli_copy.__file__)
TOKEN = "SYNTHETICTOKENzz-value-never-shown"


def host_copy():
    """push_sender loaded under the name Hermes' plugin loader gives it."""
    spec = importlib.util.spec_from_file_location("hermes_plugins.limitless.limitless.push_sender", SOURCE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class InHost(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "hermes"
        home = self.root / "profiles" / "sender-a"
        home.mkdir(parents=True)
        (home / ".env").write_text(f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_HOME_CHANNEL=made-up-chat\n")
        (home / "config.yaml").write_text("")
        self.cfg = {"push_profile": "sender-a", "push_to": "telegram"}
        self.env = {"HERMES_HOME": str(self.root)}

    def test_the_cli_copy_reads_presence_and_calls_it_ready(self):
        self.assertTrue(cli_copy.READ_PROFILE_FILES)
        self.assertEqual(cli_copy.readiness(self.cfg, self.env, self.root), cli_copy.READY)

    def test_the_host_copy_never_opens_the_profile_files(self):
        ps = host_copy()
        self.assertFalse(ps.READ_PROFILE_FILES)
        real_open = builtins.open
        opened = []

        def watch(path, *a, **k):
            opened.append(str(path))
            return real_open(path, *a, **k)

        with mock.patch("builtins.open", side_effect=watch), \
                mock.patch.object(Path, "read_text", side_effect=AssertionError("read a profile file")), \
                mock.patch.object(Path, "read_bytes", side_effect=AssertionError("read a profile file")):
            words = ps.readiness(self.cfg, self.env, self.root)
            cands = ps.candidates(self.cfg, self.env, self.root, probed=False)
        self.assertEqual(words, ps.NOT_READ_IN_HOST)
        self.assertTrue(words.startswith(ps.UNKNOWN_PREFIX))
        self.assertFalse([p for p in opened if p.endswith((".env", "config.yaml"))], opened)
        self.assertIn("sender-a", ps.maybe_names(cands))
        self.assertEqual(ps.ready_names(cands), [])
        self.assertNotIn(TOKEN, repr(cands))

    def test_a_missing_profile_is_still_missing_in_the_host(self):
        ps = host_copy()
        cfg = dict(self.cfg, push_profile="nobody")
        self.assertEqual(ps.readiness(cfg, self.env, self.root), ps.MISSING)


if __name__ == "__main__":
    unittest.main()
