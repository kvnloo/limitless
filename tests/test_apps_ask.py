"""apps_ask.ask_lines: the pre-filled "work apps: / feed apps:" reply for the wake brief, while both lists are
unset, at most once in seven days, the mark written only after a delivery.

Synthetic phone DBs (the ActivityWatch schema) with well-known public app ids only; no real person's data.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from limitless import app_candidates as ac, apps_ask, apps_reply  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from test_app_candidates_tool import phone_db  # noqa: E402

NOW = 1894708800.0
M, H, D = 60.0, 3600.0, 86400.0
REPLY = "work apps: alacritty\nfeed apps: instagram, reddit"
NAMES = ("alacritty", "instagram", "reddit")


def aw_rows(st):
    """A synthetic phone DB two days before NOW: a terminal, two feeds (public ids only)."""
    t = NOW - 2 * D
    phone_db(Path(st) / "aw.db", [(t, t + 60 * M, "Alacritty", "org.example.alacritty"),
                                  (t + 2 * H, t + 2 * H + 50 * M, "Instagram", "com.instagram.android"),
                                  (t + 4 * H, t + 4 * H + 20 * M, "Reddit", "com.reddit.frontpage")])


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.st = self.dir / "state"
        self.st.mkdir()
        p = mock.patch.dict(os.environ, {}, clear=True)   # no list from the real environment
        p.start()
        self.addCleanup(p.stop)

    def env(self, **cfg):
        cfg.setdefault("state", str(self.st))
        cfg.setdefault("aw_db", "aw.db")
        p = self.dir / "config.json"
        p.write_text(json.dumps(cfg))
        self.cfg = cfg
        return {"LIMITLESS_CONFIG": str(p), "LIMITLESS_STATE": str(self.st)}

    def rows(self):
        aw_rows(self.st)

    def lines(self, **cfg):
        env = self.env(**cfg)
        return apps_ask.ask_lines(self.cfg, self.st, NOW, env=env, home=self.dir)


class AskLines(Base):
    def test_two_lines_the_prompt_then_the_reply_exactly(self):
        self.rows()
        self.assertEqual(self.lines(), [apps_ask.PROMPT, REPLY])
        self.assertEqual(apps_ask.PROMPT, "Reply with this to set your app lists (edit freely):")

    def test_the_reply_is_reply_line_unchanged_and_parses_back(self):
        self.rows()
        env = self.env()
        want = ac.reply_line(ac.read_for(StateReader(self.st), NOW, env, self.dir))
        got = apps_ask.ask_lines(self.cfg, self.st, NOW, env=env, home=self.dir)
        self.assertEqual(got[1], want)
        self.assertEqual(apps_reply.parse(got[1]),
                         {apps_reply.WORK: ("alacritty",), apps_reply.FEED: ("instagram", "reddit")})

    def test_a_list_set_in_config_is_no_lines(self):
        self.rows()
        self.assertEqual(self.lines(flow_work_apps=["zqeditor"]), [])
        self.assertEqual(self.lines(feed_apps="zqscroller"), [])

    def test_a_list_set_in_the_env_is_no_lines(self):
        self.rows()
        env = dict(self.env(), LIMITLESS_FEED_APPS="zqscroller")
        self.assertEqual(apps_ask.ask_lines(self.cfg, self.st, NOW, env=env, home=self.dir), [])

    def test_a_list_set_from_a_reply_is_no_lines(self):
        self.rows()
        apps_reply.ingest(self.st, [(NOW - 60, "work apps: zqeditor")], NOW, dry_run=False)
        self.assertEqual(self.lines(), [])

    def test_unknown_candidates_are_no_lines(self):
        self.assertEqual(self.lines(), [])                       # no DB at all
        t = NOW - D
        phone_db(self.st / "aw.db", [(t, t + 5 * M, "Instagram", "com.instagram.android")])   # too little
        self.assertEqual(self.lines(), [])
        phone_db(self.st / "aw.db", [(t, t + 2 * H, "zqnotes", "org.example.zqnotes")])      # none known
        self.assertEqual(self.lines(), [])

    def test_off_is_no_lines(self):
        self.rows()
        for off in (False, "off", "OFF", "false", "no"):
            self.assertEqual(self.lines(apps_ask=off), [], off)
        self.assertEqual(self.lines(apps_ask="on"), [apps_ask.PROMPT, REPLY])
        self.assertEqual(self.lines(apps_ask=True), [apps_ask.PROMPT, REPLY])

    def test_told_five_days_ago_is_no_lines_eight_days_is_lines(self):
        self.rows()
        self.assertTrue(apps_ask.tell(self.st, NOW - 5 * D))
        self.assertEqual(self.lines(), [])
        self.assertTrue(apps_ask.tell(self.st, NOW - 8 * D))
        self.assertEqual(self.lines(), [apps_ask.PROMPT, REPLY])
        self.assertTrue(apps_ask.tell(self.st, NOW - 7 * D))   # seven whole days is not "within" them
        self.assertEqual(self.lines(), [apps_ask.PROMPT, REPLY])

    def test_asking_writes_nothing(self):
        self.rows()
        before = sorted(p.name for p in self.st.iterdir())
        self.assertEqual(len(self.lines()), 2)
        self.assertEqual(sorted(p.name for p in self.st.iterdir()), before)

    def test_a_broken_mark_counts_as_never_told(self):
        self.rows()
        for bad in ("not json", "[]", '{"told": "soon"}', '{"told": true}', '{"told": NaN}'):
            (self.st / apps_ask.MARK_FILE).write_text(bad)
            self.assertEqual(len(self.lines()), 2, bad)


class Mark(Base):
    def test_tell_writes_an_epoch_only_0600(self):
        self.assertTrue(apps_ask.tell(self.st, NOW))
        p = self.st / apps_ask.MARK_FILE
        self.assertEqual(json.loads(p.read_text()), {"told": NOW})
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
        self.assertEqual(apps_ask.told_at(self.st), NOW)
        self.assertEqual([x.name for x in self.st.iterdir() if x.name.endswith(".tmp")], [])

    def test_tell_never_raises(self):
        self.assertFalse(apps_ask.tell(self.dir / "nowhere", NOW))


if __name__ == "__main__":
    unittest.main()
