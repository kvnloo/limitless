"""The jobs runner feeds ActivityWatch unlocks and app spans to the screen-event wake proxy.

Synthetic DBs only (built with tests/test_aw_reader.make_db). NOW is an arbitrary epoch; only
differences between times matter.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from limitless import jobs, jobs_runner, wake_proxy  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from test_aw_reader import make_db  # noqa: E402

NOW = 2_000_000_000.0
H = 3600.0
NIGHT = [NOW - 9 * H, NOW - 0.5 * H]     # an evening unlock, a quiet gap of hours, an unlock


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.db = self.st / "aw.db"
        self.env = {"LIMITLESS_CONFIG": str(self.root / "no-config.json")}

    def tearDown(self):
        self.tmp.cleanup()

    def rows(self, env):
        return {r["job"]: r for r in jobs_runner.run_once(self.st, NOW, env=env, home=self.root)}


class AwDbPath(Base):
    def test_none_when_not_configured(self):
        self.assertIsNone(StateReader(self.st).aw_db_path(env=self.env, home=self.root))

    def test_from_env(self):
        env = dict(self.env, LIMITLESS_AW_DB=str(self.db))
        self.assertEqual(StateReader(self.st).aw_db_path(env=env, home=self.root), self.db)

    def test_from_config_relative_to_state_dir(self):
        cfg = self.root / "config.json"
        cfg.write_text(json.dumps({"aw_db": "aw.db"}))
        env = {"LIMITLESS_CONFIG": str(cfg)}
        self.assertEqual(StateReader(self.st).aw_db_path(env=env, home=self.root), self.db)

    def test_env_wins_over_config(self):
        cfg = self.root / "config.json"
        cfg.write_text(json.dumps({"aw_db": "other.db"}))
        env = {"LIMITLESS_CONFIG": str(cfg), "LIMITLESS_AW_DB": str(self.db)}
        self.assertEqual(StateReader(self.st).aw_db_path(env=env, home=self.root), self.db)


class RunnerUsesAwWakes(Base):
    def test_aw_unlocks_trigger_the_wake_brief_without_sleep_mode(self):
        make_db(self.db, unlocks=NIGHT)
        env = dict(self.env, LIMITLESS_AW_DB=str(self.db))
        wake = self.rows(env)["Wake-up brief"]
        self.assertNotEqual(wake["action"], jobs.NOT_TRIGGERED, wake)

    def test_aw_from_config_key(self):
        make_db(self.db, unlocks=NIGHT[:1], spans=[(NIGHT[1], NIGHT[1] + 60, "reader")])
        cfg = self.root / "config.json"
        cfg.write_text(json.dumps({"aw_db": str(self.db)}))
        wake = self.rows({"LIMITLESS_CONFIG": str(cfg)})["Wake-up brief"]
        self.assertNotEqual(wake["action"], jobs.NOT_TRIGGERED, wake)

    def test_no_db_configured_is_unchanged(self):
        make_db(self.db, unlocks=NIGHT)                 # present on disk but not configured
        wake = self.rows(self.env)["Wake-up brief"]
        self.assertEqual(wake["action"], jobs.NOT_TRIGGERED, wake)

    def test_configured_but_missing_db_is_unchanged(self):
        env = dict(self.env, LIMITLESS_AW_DB=str(self.root / "absent.db"))
        self.assertEqual(self.rows(env), self.rows(self.env))

    def test_screen_and_aw_rows_deduped(self):
        make_db(self.db, unlocks=NIGHT)
        (self.st / "screen-events.jsonl").write_text(
            "".join(json.dumps({"ts": t * 1000, "type": "KEYGUARD_HIDDEN", "pkg": "p"}) + "\n" for t in NIGHT))
        env = dict(self.env, LIMITLESS_AW_DB=str(self.db))
        rows = jobs_runner.person_rows(StateReader(self.st), env=env, home=self.root)
        self.assertEqual(sorted((wake_proxy._ts_s(r), r["type"]) for r in rows),
                         [(t, "KEYGUARD_HIDDEN") for t in NIGHT])
        wakes = [e for e in jobs_runner.events(StateReader(self.st), env=env, home=self.root)
                 if e["event"] == "wake"]
        self.assertEqual(len(wakes), 1)


if __name__ == "__main__":
    unittest.main()
