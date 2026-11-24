"""Where the owner's session stores are: $LIMITLESS_OWNER_DBS (os.pathsep-separated) or config "owner_dbs" (a
list; a relative path is in the state dir). None set means the input is missing, never zero. Synthetic only."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import owner_messages as om  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402


class Paths(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.state = self.dir / "state"
        self.state.mkdir()
        self.home = self.dir / "home"   # no config file here
        self.reader = StateReader(self.state)

    def tearDown(self):
        self.tmp.cleanup()

    def cfg(self, obj) -> dict:
        p = self.dir / "config.json"
        p.write_text(json.dumps(obj))
        return {"LIMITLESS_CONFIG": str(p)}

    def test_env_list_split_on_pathsep(self):
        env = {om.ENV_KEY: os.pathsep.join([str(self.dir / "a.db"), "", "rel/b.db"])}
        self.assertEqual(self.reader.owner_db_paths(env, self.home), [self.dir / "a.db", self.state / "rel/b.db"])

    def test_config_list_relative_is_in_the_state_dir(self):
        env = self.cfg({om.CONFIG_KEY: ["one.db", str(self.dir / "two.db"), 7, ""]})
        self.assertEqual(self.reader.owner_db_paths(env, self.home), [self.state / "one.db", self.dir / "two.db"])

    def test_env_beats_config(self):
        env = dict(self.cfg({om.CONFIG_KEY: ["one.db"]}), **{om.ENV_KEY: str(self.dir / "env.db")})
        self.assertEqual(self.reader.owner_db_paths(env, self.home), [self.dir / "env.db"])

    def test_none_set_is_none_not_an_empty_list(self):
        self.assertIsNone(self.reader.owner_db_paths({}, self.home))
        self.assertIsNone(self.reader.owner_db_paths({om.ENV_KEY: os.pathsep}, self.home))
        for bad in ("one.db", [], {"a": 1}, None):
            self.assertIsNone(self.reader.owner_db_paths(self.cfg({om.CONFIG_KEY: bad}), self.home), bad)


if __name__ == "__main__":
    unittest.main()
