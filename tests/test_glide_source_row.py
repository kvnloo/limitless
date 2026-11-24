"""glide_provider.source_status and the doctor's `glide source` row. Synthetic attention files only."""
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
from limitless import glide_provider as gp  # noqa: E402

NOW = 1894708800.0
M, H = 60.0, 3600.0
HINT = "set glide_attention to Glide's <profile>/glide/attention.json"
OLD = {"block": None, "queue": [], "resume": None, "nudged": ""}   # what an older Glide writes: no wind_down key


def newer(**kw):
    return dict(OLD, wind_down=None, **kw)


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        p = mock.patch.dict(os.environ, {}, clear=True)
        p.start()
        self.addCleanup(p.stop)

    def file(self, data, name="attention.json"):
        p = self.home / name
        p.write_text(data if isinstance(data, str) else json.dumps(data))
        return str(p)

    def with_config(self, path):
        cfg = self.home / ".config" / "limitless" / "config.json"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(json.dumps({gp.CONFIG_KEY: path}))

    def status(self, data=None, env=None, now=NOW):
        env = {gp.ENV_KEY: self.file(data)} if env is None else env
        return gp.source_status(env, self.home, now)


class SourceStatus(Case):
    def test_the_words_are_the_eight_the_doctor_prints(self):
        self.assertEqual(gp.SOURCE_STATUSES, (
            "not configured", "file missing", "unreadable", "older Glide (no wind-down event key)",
            "ok: wind-down open", "ok: wind-down ended", "ok: no wind-down yet", "ok: focus block running"))
        for s in gp.SOURCE_STATUSES:
            self.assertNotRegex(s, r"\d")

    def test_not_configured_without_env_or_config_key(self):
        self.assertEqual(self.status(env={}), "not configured")
        self.assertEqual(self.status(env={gp.ENV_KEY: ""}), "not configured")
        self.with_config("")
        self.assertEqual(self.status(env={}), "not configured")

    def test_file_missing(self):
        self.assertEqual(self.status(env={gp.ENV_KEY: str(self.home / "nope.json")}), "file missing")

    def test_unreadable(self):
        self.assertEqual(self.status("{not json"), "unreadable")
        self.assertEqual(self.status([1, 2]), "unreadable")             # not an object
        self.assertEqual(self.status(env={gp.ENV_KEY: str(self.home)}), "unreadable")   # a dir
        p = self.home / "bytes.json"
        p.write_bytes(b"\xff\xfe\x00{")
        self.assertEqual(self.status(env={gp.ENV_KEY: str(p)}), "unreadable")

    def test_older_glide_has_no_wind_down_key(self):
        self.assertEqual(self.status(OLD), "older Glide (no wind-down event key)")
        old = dict(OLD, resume={"saved": NOW - H, "night": "2030-01-14"})
        self.assertEqual(self.status(old), "older Glide (no wind-down event key)")

    def test_a_malformed_key_reads_as_absent_as_the_reader_does(self):
        for bad in ("yes", {"started": "soon"}, {"started": NOW + H}, {"started": NOW - H, "ended": NOW - 2 * H}):
            self.assertEqual(self.status(dict(OLD, wind_down=bad)), "older Glide (no wind-down event key)", bad)

    def test_no_wind_down_yet(self):
        self.assertEqual(self.status(newer()), "ok: no wind-down yet")

    def test_wind_down_open(self):
        for by in ("nudge", "manual", "other"):
            ev = {"started": NOW - H, "by": by, "ended": None}
            self.assertEqual(self.status(newer(wind_down=ev)), "ok: wind-down open", by)
        ev = {"started": NOW - H, "by": "nudge", "ended": NOW + M}   # ends later
        self.assertEqual(self.status(newer(wind_down=ev)), "ok: wind-down open")

    def test_wind_down_ended(self):
        ev = {"started": NOW - H, "by": "nudge", "ended": NOW - M}
        self.assertEqual(self.status(newer(wind_down=ev)), "ok: wind-down ended")
        ev = {"started": NOW - gp.WIND_DOWN_MAX_S - M, "by": "nudge", "ended": None}   # past the cap
        self.assertEqual(self.status(newer(wind_down=ev)), "ok: wind-down ended")

    def test_a_running_focus_block_wins(self):
        block = {"start": NOW - M, "end": NOW + H, "minutes": 60}
        ev = {"started": NOW - H, "by": "nudge", "ended": None}
        self.assertEqual(self.status(newer(block=block, wind_down=ev)), "ok: focus block running")
        self.assertEqual(self.status(dict(OLD, block=block)), "ok: focus block running")
        over = {"start": NOW - 2 * H, "end": NOW - H, "minutes": 60}
        self.assertEqual(self.status(newer(block=over)), "ok: no wind-down yet")

    def test_env_wins_over_config_as_from_config_does(self):
        good = self.file(newer(), "good.json")
        missing = str(self.home / "gone.json")
        self.with_config(good)
        self.assertEqual(self.status(env={}), "ok: no wind-down yet")
        self.assertEqual(self.status(env={gp.ENV_KEY: missing}), "file missing")
        self.assertEqual(self.status(env={gp.ENV_KEY: ""}), "ok: no wind-down yet")   # empty env falls back
        self.with_config(missing)
        self.assertEqual(self.status(env={gp.ENV_KEY: good}), "ok: no wind-down yet")
        self.assertEqual(gp.GlideProvider.from_config({gp.ENV_KEY: good}, self.home).path, good)

    def test_never_raises_and_reads_no_clock(self):
        ev = {"started": NOW - H, "by": "nudge", "ended": None}
        path = self.file(newer(wind_down=ev))
        with mock.patch("time.time", side_effect=AssertionError("clock read")):
            for now in (None, "soon", float("nan"), True):
                self.assertIn(gp.source_status({gp.ENV_KEY: path}, self.home, now), gp.SOURCE_STATUSES, now)
            self.assertIn(gp.source_status({gp.ENV_KEY: 7}, self.home, NOW), gp.SOURCE_STATUSES)
            self.assertIn(gp.source_status(None, self.home, NOW), gp.SOURCE_STATUSES)
            self.assertEqual(gp.source_status({gp.ENV_KEY: "\0bad"}, self.home, NOW), "unreadable")

    def test_nothing_written(self):
        path = self.file(newer())
        before = sorted((p.name, p.stat().st_mtime_ns) for p in self.home.iterdir())
        gp.source_status({gp.ENV_KEY: path}, self.home, NOW)
        self.assertEqual(sorted((p.name, p.stat().st_mtime_ns) for p in self.home.iterdir()), before)


class DoctorRow(Case):
    def row(self, data=None, cfg=None, env=None):
        env = {gp.ENV_KEY: self.file(data)} if env is None else env
        return doctor.glide_source_row(cfg or {}, NOW, env=env)

    def check(self, r, status, reason):
        self.assertEqual((r["name"], r["kind"], r["status"], r["reason"]),
                         (doctor.GLIDE_SOURCE_ROW, "source", status, reason))
        self.assertNotRegex(doctor.text([r]), r"\d")
        self.assertEqual(doctor.text([r]), f"glide source: {status}: {reason}")

    def test_not_configured_names_the_config_key(self):
        self.check(self.row(env={}), doctor.MISSING, "not configured: " + HINT)
        self.assertEqual(doctor.text([self.row(env={})]), "glide source: missing: not configured: " + HINT)

    def test_each_problem_is_missing(self):
        self.check(self.row(env={gp.ENV_KEY: str(self.home / "nope.json")}), doctor.MISSING, "file missing")
        self.check(self.row("{not json"), doctor.MISSING, "unreadable")
        self.check(self.row(OLD), doctor.MISSING, "older Glide (no wind-down event key)")

    def test_each_ok_is_live(self):
        self.check(self.row(newer()), doctor.LIVE, "ok: no wind-down yet")
        self.check(self.row(newer(wind_down={"started": NOW - H, "by": "nudge", "ended": None})),
                   doctor.LIVE, "ok: wind-down open")
        self.check(self.row(newer(wind_down={"started": NOW - H, "by": "manual", "ended": NOW - M})),
                   doctor.LIVE, "ok: wind-down ended")
        self.check(self.row(newer(block={"start": NOW - M, "end": NOW + H, "minutes": 60})),
                   doctor.LIVE, "ok: focus block running")

    def test_the_row_reads_the_doctors_config_with_env_first(self):
        good = self.file(newer(), "good.json")
        self.check(self.row(cfg={gp.CONFIG_KEY: good}, env={}), doctor.LIVE, "ok: no wind-down yet")
        self.check(self.row(cfg={gp.CONFIG_KEY: good}, env={gp.ENV_KEY: str(self.home / "gone.json")}),
                   doctor.MISSING, "file missing")

    def test_every_reason_is_digit_free_and_pathless(self):
        for s in gp.SOURCE_STATUSES + (HINT,):
            self.assertNotRegex(s, r"\d")
        r = self.row(env={gp.ENV_KEY: str(self.home / "nope.json")})
        self.assertNotIn(str(self.home), r["reason"])

    def test_the_report_has_it_right_after_the_sleep_mode_row(self):
        os.environ["LIMITLESS_STATE"] = str(self.home)
        rows = doctor.report({"state": str(self.home)}, NOW)
        names = [r["name"] for r in rows]
        self.assertEqual(names.count(doctor.GLIDE_SOURCE_ROW), 1)
        at = names.index(doctor.GLIDE_SOURCE_ROW)
        self.assertEqual(names[at - 1], doctor.SLEEP_MODE_ROW)
        self.assertEqual(names[at + 1], doctor.LOCAL_LABELER_ROW)
        self.assertEqual(rows[at]["reason"], "not configured: " + HINT)
        self.assertNotIn("source", doctor.STRICT_KINDS)


if __name__ == "__main__":
    unittest.main()
