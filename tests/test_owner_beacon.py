"""Owner beacons: a content-free {"at": ISO UTC, "v": 1} file, written on another machine, read as one more
source by owner_messages.newest_user_message. Synthetic data only."""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import catchup, tools  # noqa: E402
from limitless import owner_messages as om  # noqa: E402
from limitless.state_reader import OWNER_BEACONS_CONFIG, OWNER_BEACONS_ENV, StateReader  # noqa: E402
from test_owner_messages import CONTENT, H, NOW, make_db  # noqa: E402


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds")


def beacon(path, t, **extra):
    path.write_text(json.dumps(dict({"at": iso(t), "v": 1}, **extra)))
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.db = make_db(self.dir / "here.db", [("s-cli", "user", CONTENT, NOW - 30 * H)])

    def tearDown(self):
        self.tmp.cleanup()


class Paths(Base):
    def setUp(self):
        super().setUp()
        self.state = self.dir / "state"
        self.state.mkdir()
        self.home = self.dir / "home"
        self.reader = StateReader(self.state)

    def cfg(self, obj):
        p = self.dir / "config.json"
        p.write_text(json.dumps(obj))
        return {"LIMITLESS_CONFIG": str(p)}

    def test_names(self):
        self.assertEqual((OWNER_BEACONS_ENV, OWNER_BEACONS_CONFIG), ("LIMITLESS_OWNER_BEACONS", "owner_beacons"))

    def test_env_split_on_pathsep_relative_in_state_dir(self):
        env = {OWNER_BEACONS_ENV: os.pathsep.join([str(self.dir / "a.json"), "", "rel/b.json"])}
        self.assertEqual(self.reader.owner_beacon_paths(env, self.home),
                         [self.dir / "a.json", self.state / "rel/b.json"])

    def test_config_list_and_env_beats_config(self):
        env = self.cfg({OWNER_BEACONS_CONFIG: ["one.json", str(self.dir / "two.json"), 7, ""]})
        self.assertEqual(self.reader.owner_beacon_paths(env, self.home),
                         [self.state / "one.json", self.dir / "two.json"])
        env[OWNER_BEACONS_ENV] = str(self.dir / "env.json")
        self.assertEqual(self.reader.owner_beacon_paths(env, self.home), [self.dir / "env.json"])

    def test_none_set_is_none(self):
        self.assertIsNone(self.reader.owner_beacon_paths({}, self.home))
        for bad in ("one.json", [], {"a": 1}, None):
            self.assertIsNone(self.reader.owner_beacon_paths(self.cfg({OWNER_BEACONS_CONFIG: bad}), self.home))

    def test_beacons_do_not_leak_into_db_paths(self):
        env = {OWNER_BEACONS_ENV: str(self.dir / "a.json")}
        self.assertIsNone(self.reader.owner_db_paths(env, self.home))


class Newest(Base):
    def test_a_newer_beacon_wins_and_counts_as_one_source(self):
        b = beacon(self.dir / "other.json", NOW - 2 * H)
        out = om.newest_user_message([self.db], NOW, beacons=[b])
        self.assertEqual(out, {"at": iso(NOW - 2 * H), "age_h": 2.0, "sources_read": 2, "sources_failed": 0})

    def test_an_older_beacon_does_not_beat_the_db(self):
        b = beacon(self.dir / "other.json", NOW - 50 * H)
        out = om.newest_user_message([self.db], NOW, beacons=[b])
        self.assertEqual((out["at"], out["sources_read"]), (iso(NOW - 30 * H), 2))

    def test_beacons_alone(self):
        a, b = beacon(self.dir / "a.json", NOW - 5 * H), beacon(self.dir / "b.json", NOW - 4 * H)
        out = om.newest_user_message(None, NOW, beacons=[a, b])
        self.assertEqual((out["at"], out["age_h"], out["sources_read"]), (iso(NOW - 4 * H), 4.0, 2))

    def test_z_suffix_and_offset_are_accepted(self):
        p = self.dir / "z.json"
        p.write_text(json.dumps({"at": "2030-01-15T10:00:00Z", "v": 1}))
        self.assertEqual(om.newest_user_message([], NOW, beacons=[p])["age_h"], 2.0)
        p.write_text(json.dumps({"at": "2030-01-15T11:00:00+01:00", "v": 1}))
        self.assertEqual(om.newest_user_message([], NOW, beacons=[p])["age_h"], 2.0)

    def test_unreadable_or_malformed_beacons_fail_and_never_raise(self):
        bad = {
            "gone.json": None,
            "empty.json": "",
            "text.json": "not json",
            "list.json": json.dumps([iso(NOW)]),
            "no_at.json": json.dumps({"v": 1}),
            "no_v.json": json.dumps({"at": iso(NOW - H)}),
            "v2.json": json.dumps({"at": iso(NOW - H), "v": 2}),
            "vtrue.json": json.dumps({"at": iso(NOW - H), "v": True}),
            "num.json": json.dumps({"at": NOW - H, "v": 1}),
            "garbage_at.json": json.dumps({"at": "yesterday", "v": 1}),
            "naive.json": json.dumps({"at": "2030-01-15T10:00:00", "v": 1}),
            "huge.json": json.dumps({"at": iso(NOW - H), "v": 1, "pad": "x" * (om.BEACON_MAX_BYTES + 1)}),
            "binary.json": b"\xff\xfe\x00",
        }
        paths = []
        for name, body in bad.items():
            p = self.dir / name
            if isinstance(body, bytes):
                p.write_bytes(body)
            elif body is not None:
                p.write_text(body)
            paths.append(p)
        paths += [self.dir, "", None, 7]
        out = om.newest_user_message([self.db], NOW, beacons=paths)
        self.assertEqual(out["at"], iso(NOW - 30 * H))
        self.assertEqual((out["sources_read"], out["sources_failed"]), (1, len(paths)))

    def test_a_beacon_from_the_future_beyond_skew_fails(self):
        far = beacon(self.dir / "far.json", NOW + om.SKEW_S + 60)
        near = beacon(self.dir / "near.json", NOW + om.SKEW_S - 60)
        out = om.newest_user_message([self.db], NOW, beacons=[far])
        self.assertEqual((out["at"], out["sources_read"], out["sources_failed"]), (iso(NOW - 30 * H), 1, 1))
        out = om.newest_user_message([], NOW, beacons=[near])
        self.assertEqual((out["age_h"], out["sources_read"]), (0.0, 1))

    def test_until_ignores_a_newer_beacon_but_it_was_read(self):
        b = beacon(self.dir / "b.json", NOW - 60)   # this turn's own message, relayed
        out = om.newest_user_message([self.db], NOW, until=NOW - 120, beacons=[b])
        self.assertEqual((out["at"], out["sources_read"], out["sources_failed"]), (iso(NOW - 30 * H), 2, 0))
        out = om.newest_user_message([self.db], NOW, until=NOW - 30, beacons=[b])
        self.assertEqual(out["at"], iso(NOW - 60))

    def test_unknown_stays_unknown(self):
        self.assertEqual(om.newest_user_message(None, NOW, beacons=None),
                         {"at": None, "age_h": None, "sources_read": 0, "sources_failed": 0})
        self.assertEqual(om.newest_user_message([], NOW), om.newest_user_message([], NOW, beacons=[]))

    def test_a_stale_beacon_is_just_an_old_timestamp(self):
        b = beacon(self.dir / "old.json", NOW - 400 * H)
        out = om.newest_user_message(None, NOW, beacons=[b])
        self.assertEqual((out["at"], out["age_h"], out["sources_failed"]), (iso(NOW - 400 * H), 400.0, 0))

    def test_no_extra_beacon_field_leaks(self):
        b = beacon(self.dir / "b.json", NOW - H, note=CONTENT)
        out = om.newest_user_message(None, NOW, beacons=[b])
        self.assertEqual(sorted(out), ["age_h", "at", "sources_failed", "sources_read"])
        self.assertNotIn("synthetic", json.dumps(out))


class Wiring(Base):
    def setUp(self):
        super().setUp()
        self.st = self.dir / "state"
        self.st.mkdir()
        self.b = beacon(self.dir / "other.json", NOW - 3 * H)
        self.env = {"LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(self.dir / "none.json")}

    def test_last_seen_uses_beacons_with_dbs(self):
        env = dict(self.env, LIMITLESS_OWNER_DBS=str(self.db), LIMITLESS_OWNER_BEACONS=str(self.b))
        self.assertEqual(catchup.last_seen(StateReader(self.st), NOW, env, self.dir), NOW - 3 * H)

    def test_last_seen_uses_beacons_without_dbs(self):
        env = dict(self.env, LIMITLESS_OWNER_BEACONS=str(self.b))
        self.assertEqual(catchup.last_seen(StateReader(self.st), NOW, env, self.dir), NOW - 3 * H)

    def test_last_seen_skips_this_turns_beacon(self):
        fresh = beacon(self.dir / "fresh.json", NOW - 30)
        env = dict(self.env, LIMITLESS_OWNER_DBS=str(self.db), LIMITLESS_OWNER_BEACONS=str(fresh))
        self.assertEqual(catchup.last_seen(StateReader(self.st), NOW, env, self.dir), NOW - 30 * H)

    def test_hook_stays_quiet_when_a_beacon_shows_recent_activity(self):
        env = dict(self.env, LIMITLESS_OWNER_DBS=str(self.db))
        hook = catchup.make_pre_llm_call(env=env, clock=lambda: NOW, home=self.dir)
        self.assertIsNotNone(hook())                       # the DB alone: away for a day
        env[OWNER_BEACONS_ENV] = str(self.b)
        hook = catchup.make_pre_llm_call(env=env, clock=lambda: NOW, home=self.dir)
        self.assertIsNone(hook())                          # the other machine wrote three hours ago

    def test_catchup_tool_with_beacons_only(self):
        env = dict(self.env, LIMITLESS_OWNER_BEACONS=str(self.b))
        out = catchup.tool(StateReader(self.st), NOW, env, self.dir)
        self.assertEqual(out["age_h"], 3.0)
        self.assertEqual(out["value"]["label"]["label"], catchup.NOT_AWAY)

    def test_catchup_tool_unknown_names_both_settings(self):
        out = catchup.tool(StateReader(self.st), NOW, self.env, self.dir)
        self.assertIsNone(out["value"])
        self.assertIn("LIMITLESS_OWNER_DBS", out["reason"])
        self.assertIn("LIMITLESS_OWNER_BEACONS", out["reason"])

    def test_owner_message_with_beacons_only(self):
        env = dict(self.env, LIMITLESS_OWNER_BEACONS=str(self.b))
        out = tools.owner_message(StateReader(self.st), NOW, env, self.dir)
        self.assertEqual((out["value"], out["age_h"]), (iso(NOW - 3 * H), 3.0))
        self.assertEqual(out["sources"], {"read": 1, "failed": 0})
        self.assertEqual(out["label"]["label"], "quiet for a while")  # three hours: over OWNER_RECENT_H

    def test_owner_message_failed_beacon_reason_never_echoes_a_path(self):
        env = dict(self.env, LIMITLESS_OWNER_BEACONS=str(self.dir / "gone.json"))
        out = tools.owner_message(StateReader(self.st), NOW, env, self.dir)
        self.assertIsNone(out["value"])
        self.assertIn("could not be read", out["reason"])
        self.assertEqual(out["sources"], {"read": 0, "failed": 1})
        self.assertNotIn(str(self.dir), json.dumps(out))

    def test_owner_message_unknown_names_both_settings(self):
        out = tools.owner_message(StateReader(self.st), NOW, self.env, self.dir)
        self.assertIsNone(out["value"])
        self.assertIn("LIMITLESS_OWNER_DBS", out["reason"])
        self.assertIn("LIMITLESS_OWNER_BEACONS", out["reason"])


if __name__ == "__main__":
    unittest.main()
