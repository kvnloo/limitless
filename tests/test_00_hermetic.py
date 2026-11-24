"""The suite never reads or writes the host's real Limitless config, state or audit log.

On a host with ~/.config/limitless/config.json (audit_path, state, ...), tests that call the library with the
default env used to append synthetic rows to the real audit log. This module sorts first in discovery, so its
import-time isolation applies to the whole run: HOME points at an empty temp dir and every LIMITLESS_* variable
is dropped.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

for _k in [k for k in os.environ if k.startswith("LIMITLESS_")]:
    del os.environ[_k]
TEST_HOME = Path(tempfile.mkdtemp(prefix="limitless-test-home-"))
os.environ["HOME"] = str(TEST_HOME)
# A test that clears os.environ drops HOME too, and Path.home() then falls back to the passwd entry.
Path.home = classmethod(lambda cls: cls(TEST_HOME))

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
