"""limitless_app_candidates: read both ActivityWatch sources from config, propose the lists, write nothing.

Synthetic phone DBs (the ActivityWatch schema) and synthetic desktop export files only: well-known public
app ids and made-up app names; no real person's data.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from limitless import app_candidates as ac, aw_desktop, doctor, plugin, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from test_flow_week import NS, SCHEMA  # noqa: E402

NOW = 1894708800.0
M, H, D = 60.0, 3600.0, 86400.0
FIXTURE_NAMES = ("instagram", "com.instagram.android", "reddit", "com.reddit.frontpage", "zqnotes",
                 "org.example.zqnotes", "code", "alacritty", "firefox", "zqeditor", "zqscroller")


def phone_db(path, spans):
    """``spans``: (start_s, end_s, app, package) app-in-foreground rows in a synthetic phone DB."""
    Path(path).unlink(missing_ok=True)   # a test may build the same synthetic DB again
    con = sqlite3.connect(str(path))
    con.executescript(SCHEMA)
    con.execute("INSERT INTO buckets VALUES (1, 'w', 'currentwindow', 'test', 'test-host', '', '{}')")
    for s, e, app, pkg in spans:
        con.execute("INSERT INTO events(bucketrow, starttime, endtime, data) VALUES (1, ?, ?, ?)",
                    (int(s * NS), int(e * NS), json.dumps({"app": app, "package": pkg})))
    con.commit()
    con.close()


def _ev(s, e, **data):
    return {"timestamp": datetime.fromtimestamp(s, timezone.utc).isoformat(), "duration": e - s, "data": data}


def desktop_export(path, wins):
    """A synthetic aw-server export: ``wins`` (start_s, end_s, app), all of it not-afk time."""
    lo, hi = min(w[0] for w in wins), max(w[1] for w in wins)
    b = {"aw-watcher-window_desk": {"id": "aw-watcher-window_desk", "type": "currentwindow", "hostname": "desk",
                                    "events": [_ev(s, e, app=a, title="a synthetic title") for s, e, a in wins]},
         "aw-watcher-afk_desk": {"id": "aw-watcher-afk_desk", "type": "afkstatus", "hostname": "desk",
                                 "events": [_ev(lo, hi, status="not-afk")]}}
    Path(path).write_text(json.dumps({"buckets": b}))


def listing(root):
    return sorted((str(p.relative_to(root)), p.stat().st_size, p.stat().st_mtime_ns) for p in Path(root).rglob("*"))


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.st = self.dir / "state"
        self.st.mkdir()
        self.reader = StateReader(self.st)
        aw_desktop._HOLD.clear()
        self.addCleanup(aw_desktop._HOLD.clear)

    def env(self, **cfg):
        cfg.setdefault("state", str(self.st))
        p = self.dir / "config.json"
        p.write_text(json.dumps(cfg))
        return {"LIMITLESS_CONFIG": str(p), "LIMITLESS_STATE": str(self.st)}

    def phone(self):
        t = NOW - 3 * D
        phone_db(self.st / "aw.db", [(t, t + 90 * M, "Instagram", "com.instagram.android"),
                                     (t + 2 * H, t + 2 * H + 20 * M, "Reddit", "com.reddit.frontpage"),
                                     (t + 3 * H, t + 3 * H + 40 * M, "zqnotes", "org.example.zqnotes"),
                                     (NOW - 9 * D, NOW - 8 * D, "Reddit", "com.reddit.frontpage")])  # too old

    def desktop(self):
        t = NOW - 10 * H   # ends two hours before NOW: fresh
        desktop_export(self.st / "desk.json", [(t, t + 4 * H, "Code"), (t + 4 * H, t + 5 * H, "Alacritty"),
                                               (t + 5 * H, t + 8 * H, "firefox")])

    def both(self, **cfg):
        self.phone()
        self.desktop()
        return self.env(aw_db="aw.db", desktop_aw_export="desk.json", **cfg)


class ReadFor(Base):
    def test_phone_and_desktop_rows_over_the_last_week(self):
        got = ac.read_for(self.reader, NOW, self.both())
        self.assertEqual(ac.reply_line(got), "work apps: code, alacritty\nfeed apps: instagram, reddit")
        self.assertEqual(got["feed"][1]["seconds"], 20 * M)   # the row from nine days ago is not read
        self.assertEqual([e["name"] for e in got["other"]], ["firefox", "zqnotes"])
        self.assertEqual(got["sources"], ["phone", "desktop"])
        self.assertEqual(got["label"], ac.BOTH)

    def test_the_config_lists_are_kept(self):
        got = ac.read_for(self.reader, NOW, self.both(flow_work_apps=["zqeditor"], feed_apps="zqscroller, Reddit"))
        self.assertEqual(ac.reply_line(got), "work apps: code, alacritty, zqeditor\n"
                                             "feed apps: instagram, Reddit, zqscroller")
        self.assertEqual([e["kept"] for e in got["feed"]], [False, True, True])

    def test_the_env_lists_are_kept_too(self):
        env = dict(self.both(), LIMITLESS_FLOW_WORK_APPS="zqeditor", LIMITLESS_FEED_APPS="zqscroller")
        got = ac.read_for(self.reader, NOW, env)
        self.assertIn("zqeditor", ac.reply_line(got))
        self.assertIn("zqscroller", ac.reply_line(got))

    def test_app_candidates_max_from_config(self):
        got = ac.read_for(self.reader, NOW, self.both(app_candidates_max=1))
        self.assertEqual(ac.reply_line(got), "work apps: code\nfeed apps: instagram")
        self.assertEqual(got["max_n"], 1)
        for bad in (0, -2, "three", True, 1.5):
            self.assertEqual(ac.read_for(self.reader, NOW, self.both(app_candidates_max=bad))["max_n"], ac.MAX_N)

    def test_either_source_alone_is_enough(self):
        self.phone()
        got = ac.read_for(self.reader, NOW, self.env(aw_db="aw.db"))
        self.assertEqual(ac.reply_line(got), "feed apps: instagram, reddit")
        self.assertEqual(got["sources"], ["phone"])
        self.desktop()
        got = ac.read_for(self.reader, NOW, self.env(desktop_aw_export="desk.json"))
        self.assertEqual(ac.reply_line(got), "work apps: code, alacritty")
        self.assertEqual(got["sources"], ["desktop"])

    def test_an_unreadable_source_does_not_hide_the_other(self):
        self.desktop()
        got = ac.read_for(self.reader, NOW, self.env(aw_db="missing.db", desktop_aw_export="desk.json"))
        self.assertEqual(got["sources"], ["desktop"])
        self.assertEqual(got["label"], ac.WORK_ONLY)

    def test_no_source_set_is_unknown(self):
        got = ac.read_for(self.reader, NOW, self.env(feed_apps=["reddit"]))
        self.assertIsNone(got["work"])
        self.assertEqual(got["label"], "unknown: " + ac.NO_SOURCE)

    def test_no_readable_source_is_unknown_with_its_reason(self):
        got = ac.read_for(self.reader, NOW, self.env(aw_db="missing.db"))
        self.assertEqual(got["label"], "unknown: " + ac.blocks.NO_DB)
        got = ac.read_for(self.reader, NOW, self.env(desktop_aw_export="missing.json"))
        self.assertEqual(got["label"], "unknown: " + aw_desktop.NO_EXPORT)

    def test_an_empty_week_is_unknown(self):
        phone_db(self.st / "aw.db", [])
        got = ac.read_for(self.reader, NOW, self.env(aw_db="aw.db"))
        self.assertEqual(got["label"], "unknown: " + ac.NO_ROWS)


class Tool(Base):
    def call(self, env, raw=False):
        return tools.app_candidates(self.reader, NOW, raw=raw, env=env)

    def test_words_only_without_the_raw_opt_in(self):
        out = self.call(self.both(feed_apps=["zqscroller"]))
        self.assertEqual(set(out) - {"label"}, {"value", "modality", "age_h", "evidence_tier"})
        self.assertEqual(out["modality"], "proxy")
        self.assertEqual(out["label"], {"tier": "T1", "modality": "proxy", "label": ac.BOTH})
        self.assertEqual(out["value"], {"label": ac.BOTH, "work": "two apps", "feed": "three apps, one kept"})
        text = json.dumps(out).casefold()
        self.assertNotRegex(json.dumps(out["value"]), r"\d")
        for n in FIXTURE_NAMES:
            self.assertNotRegex(text, r"\b" + re.escape(n) + r"\b", n)
        self.assertIsNotNone(out["age_h"])

    def test_the_reply_and_the_lists_only_with_the_raw_opt_in(self):
        v = self.call(self.both(), raw=True)["value"]
        self.assertEqual(v["reply"], "work apps: code, alacritty\nfeed apps: instagram, reddit")
        self.assertEqual(v["work"][0], {"name": "code", "seconds": 4 * H, "kept": False})
        self.assertEqual([e["name"] for e in v["other"]], ["firefox", "zqnotes"])
        self.assertEqual(v["sources"], ["phone", "desktop"])
        self.assertEqual(v["label"], ac.BOTH)

    def test_unknown_is_no_value_with_a_reason_never_empty_lists(self):
        for env in (self.env(), self.env(aw_db="missing.db")):
            out = self.call(env, raw=True)
            self.assertIsNone(out["value"])
            self.assertTrue(out["reason"].startswith("app candidates unknown: "), out)
            self.assertTrue(out["label"]["label"].startswith("unknown: "))
            self.assertNotRegex(out["reason"] + out["label"]["label"], r"\d")

    def test_nothing_is_written(self):
        env = self.both(flow_work_apps=["zqeditor"])
        before = listing(self.dir)
        self.call(env)
        self.call(env, raw=True)
        with mock.patch.dict(os.environ, env, clear=True), mock.patch("time.time", return_value=NOW):
            json.loads(plugin._handler(plugin.TOOLS["limitless_app_candidates"][1], "limitless_app_candidates")({}))
        self.assertEqual(listing(self.dir), before)

    def test_the_plugin_handler_follows_the_raw_opt_in(self):
        env = self.both()
        h = plugin._handler(plugin.TOOLS["limitless_app_candidates"][1], "limitless_app_candidates")
        with mock.patch.dict(os.environ, env, clear=True), mock.patch("time.time", return_value=NOW):
            plain = json.loads(h({}))
        with mock.patch.dict(os.environ, dict(env, LIMITLESS_RAW_IN_PROMPT="1"), clear=True), \
                mock.patch("time.time", return_value=NOW):
            raw = json.loads(h({}))
        self.assertNotIn("reply", plain["value"])
        self.assertIn("instagram", raw["value"]["reply"])


class Doctor(Base):
    def row(self, env):
        with mock.patch.dict(os.environ, env, clear=True):
            return doctor.tool_row("limitless_app_candidates", NOW)

    def test_the_doctor_reason_has_no_digit_and_no_app_name(self):
        for env in (self.both(feed_apps=["zqscroller"]), self.env(), self.env(aw_db="missing.db"),
                    self.env(desktop_aw_export="missing.json")):
            r = self.row(env)
            self.assertEqual(r["name"], "tool limitless_app_candidates")
            self.assertNotRegex(r["reason"], r"\d")
            for n in FIXTURE_NAMES:
                self.assertNotRegex(r["reason"].casefold(), r"\b" + re.escape(n) + r"\b", (r, n))
            self.assertNotIn(r["reason"], ac.WORDS)   # never the value

    def test_the_doctor_lists_the_tool_and_writes_nothing(self):
        env = self.both()
        before = listing(self.dir)
        r = self.row(env)
        self.assertEqual(r["status"], doctor.LIVE)
        self.assertEqual(listing(self.dir), before)
        self.assertIn("limitless_app_candidates", doctor.manifest_tools())


if __name__ == "__main__":
    unittest.main()
