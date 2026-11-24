"""The suite never reads or writes the host's real Limitless config, state or audit log.

On a host with ~/.config/limitless/config.json (audit_path, state, ...), tests that call the library with the
default env used to append synthetic rows to the real audit log. The isolation lives in tests/hermetic_env.py,
which every test module imports first (test_hermetic_guard enforces it): HOME points at an empty temp dir and
every LIMITLESS_* variable is dropped. This module checks the result.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from hermetic_env import TEST_HOME

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import state_reader, tier_audit  # noqa: E402


class Hermetic(unittest.TestCase):
    def test_the_host_config_is_not_visible(self):
        self.assertEqual(state_reader.config(), {})

    def test_the_audit_log_is_off(self):
        self.assertIsNone(tier_audit.audit_path())

    def test_home_is_an_empty_temp_dir(self):
        self.assertFalse((Path.home() / ".config/limitless/config.json").exists())

    def test_a_cleared_environment_still_never_reaches_the_real_home(self):
        # Many tests patch os.environ with clear=True; without HOME, Path.home() falls back to the passwd entry,
        # which is the real home with the real config.
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(Path.home(), TEST_HOME)
            self.assertEqual(state_reader.config(), {})
            self.assertIsNone(tier_audit.audit_path())


if __name__ == "__main__":
    unittest.main()
