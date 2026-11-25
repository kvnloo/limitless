"""The doctor's owner beacon paths are the reader's: for the same env and config, doctor._beacon_paths equals
StateReader(<state dir>).owner_beacon_paths (env wins, else the config list; blank and non-string items
skipped; ``~`` expanded; a relative path is in the state dir; an empty env var falls back to config). The
reader here reads the config file, as the tools do inside Hermes. Synthetic paths only, no network."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import doctor  # noqa: E402
from limitless.state_reader import OWNER_BEACONS_CONFIG as KEY, OWNER_BEACONS_ENV as ENV, StateReader  # noqa: E402


class SameAsReader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.home = self.dir / "home"
        self.home.mkdir()
        self.st = self.dir / "state"
        self.other_st = self.dir / "other-state"
        self.cfg_path = self.dir / "config.json"

    def both(self, cfg, **env_extra):
        """(doctor's paths, reader's paths) for cfg written to the config file and the given env."""
        self.cfg_path.write_text(json.dumps(cfg))
        env = {k: v for k, v in os.environ.items() if not k.startswith("LIMITLESS_")}
        env.update(HOME=str(self.home), LIMITLESS_CONFIG=str(self.cfg_path), **env_extra)
        with mock.patch.dict(os.environ, env, clear=True):
            got = doctor._beacon_paths(cfg, env)
            want = StateReader(doctor.state_path(cfg, env)).owner_beacon_paths(env, self.home)
        self.assertEqual(got, want or [], (cfg, env_extra))
        return got

    def test_config_list_skips_blank_and_non_strings_expands_home_and_joins_relative(self):
        items = ["beacons/a.json", str(self.dir / "abs.json"), "", "   ", 7, None, True, ["x"], "~/b.json"]
        got = self.both({"state": str(self.st), KEY: items})
        self.assertEqual(got, [self.st / "beacons/a.json", self.dir / "abs.json", self.home / "b.json"])

    def test_env_wins_over_config(self):
        env_v = os.pathsep.join(["env/a.json", "", str(self.dir / "env-b.json"), "~/env-c.json"])
        got = self.both({"state": str(self.st), KEY: ["cfg.json"]}, **{ENV: env_v})
        self.assertEqual(got, [self.st / "env/a.json", self.dir / "env-b.json", self.home / "env-c.json"])

    def test_env_set_but_empty_falls_back_to_config(self):
        got = self.both({"state": str(self.st), KEY: ["cfg.json"]}, **{ENV: ""})
        self.assertEqual(got, [self.st / "cfg.json"])

    def test_env_of_only_separators_names_nothing(self):
        self.assertEqual(self.both({"state": str(self.st), KEY: ["cfg.json"]}, **{ENV: os.pathsep * 2}), [])

    def test_relative_path_follows_the_state_dir_env(self):
        got = self.both({"state": str(self.st), KEY: ["rel.json"]}, LIMITLESS_STATE=str(self.other_st))
        self.assertEqual(got, [self.other_st / "rel.json"])

    def test_relative_path_in_the_default_state_dir(self):
        with mock.patch.object(Path, "home", return_value=self.home):
            got = self.both({KEY: ["rel.json"]})
        self.assertEqual(got, [self.home / ".local/state/limitless/rel.json"])

    def test_nothing_set_or_not_a_list_names_nothing(self):
        for cfg in ({}, {KEY: []}, {KEY: [""]}, {KEY: "beacons/a.json"}, {KEY: {"a": 1}}, {KEY: None}):
            self.assertEqual(self.both(dict(cfg, state=str(self.st))), [], cfg)


class TheDoctorsOwnCfgAndEnv(unittest.TestCase):
    """report() hands the doctor the config it read and owner_beacon_row may get an env: the paths come from
    those, never from a second read of the config file or from os.environ."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.st = self.dir / "state"
        self.file_cfg = self.dir / "config.json"
        self.file_cfg.write_text(json.dumps({"state": str(self.dir / "file-state"), KEY: ["from-file.json"]}))
        base = {k: v for k, v in os.environ.items() if not k.startswith("LIMITLESS_")}
        self.os_env = dict(base, LIMITLESS_CONFIG=str(self.file_cfg), **{ENV: str(self.dir / "os-env.json")})
        self.env = dict(base, LIMITLESS_CONFIG=str(self.file_cfg))

    def paths(self, cfg, env):
        with mock.patch.dict(os.environ, self.os_env, clear=True):
            return doctor._beacon_paths(cfg, env)

    def test_the_cfg_it_is_given_not_the_config_file(self):
        cfg = {"state": str(self.st), KEY: ["given.json"]}
        self.assertEqual(self.paths(cfg, self.env), [self.st / "given.json"])
        self.assertEqual(self.paths({"state": str(self.st)}, self.env), [])

    def test_the_env_it_is_given_not_os_environ(self):
        cfg = {"state": str(self.st), KEY: ["given.json"]}
        env = dict(self.env, LIMITLESS_STATE=str(self.dir / "env-state"), **{ENV: "env.json"})
        self.assertEqual(self.paths(cfg, env), [self.dir / "env-state" / "env.json"])


if __name__ == "__main__":
    unittest.main()
