"""Where the work-app and feed-app lists come from: env, then config, then apps.json (a reply).

One shared helper (apps_reply.lists_for); flow_week.work_apps, feeds_evidence.feed_apps and the feed reflex
all read through it. Synthetic app names only.
"""
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import apps_reply, feed_reflex, feeds_evidence, flow_week  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
W, F = apps_reply.WORK, apps_reply.FEED
NOW = 2_000_000_000.0


class Lists(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.st = self.home / "state"
        self.st.mkdir()
        self.cfg_path = self.home / "config.json"
        self.env = {"LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(self.cfg_path)}

    def tearDown(self):
        self.tmp.cleanup()

    def cfg(self, **kv):
        self.cfg_path.write_text(json.dumps(kv))

    def reply(self, text):
        apps_reply.ingest(self.st, [(NOW - 60, text)], NOW, dry_run=False)

    def both(self, env=None):
        env = dict(self.env, **(env or {}))
        return flow_week.work_apps(env, self.home), feeds_evidence.feed_apps(env, self.home)

    def test_nothing_set_is_empty(self):
        self.assertEqual(self.both(), ((), ()))
        self.assertEqual(apps_reply.lists_for({}, self.st, self.env), {W: ((), None), F: ((), None)})

    def test_apps_json_is_read_when_env_and_config_are_unset(self):
        self.reply("work apps: editor, terminal\nfeed apps: scrollerapp")
        self.assertEqual(self.both(), (("editor", "terminal"), ("scrollerapp",)))
        self.assertEqual(apps_reply.lists_for({}, self.st, self.env),
                         {W: (("editor", "terminal"), apps_reply.REPLY), F: (("scrollerapp",), apps_reply.REPLY)})

    def test_config_beats_apps_json(self):
        self.reply("work apps: reply-editor\nfeed apps: reply-feed")
        self.cfg(flow_work_apps=["cfg-editor"], feed_apps="cfg-feed, cfg-clip")
        self.assertEqual(self.both(), (("cfg-editor",), ("cfg-feed", "cfg-clip")))
        got = apps_reply.lists_for(json.loads(self.cfg_path.read_text()), self.st, self.env)
        self.assertEqual((got[W][1], got[F][1]), (apps_reply.CONFIG, apps_reply.CONFIG))

    def test_config_per_list_the_other_from_the_reply(self):
        self.reply("work apps: reply-editor\nfeed apps: reply-feed")
        self.cfg(flow_work_apps=["cfg-editor"])
        self.assertEqual(self.both(), (("cfg-editor",), ("reply-feed",)))

    def test_env_beats_config_and_apps_json(self):
        self.reply("work apps: reply-editor\nfeed apps: reply-feed")
        self.cfg(flow_work_apps=["cfg-editor"], feed_apps=["cfg-feed"])
        self.assertEqual(self.both({"LIMITLESS_FLOW_WORK_APPS": "env-editor", "LIMITLESS_FEED_APPS": "env-feed"}),
                         (("env-editor",), ("env-feed",)))

    def test_an_empty_config_list_falls_through_to_the_reply(self):
        self.reply("work apps: reply-editor")
        self.cfg(flow_work_apps=[])
        self.assertEqual(self.both()[0], ("reply-editor",))

    def test_a_cleared_reply_list_is_unset(self):
        self.reply("work apps: editor")
        apps_reply.ingest(self.st, [(NOW - 30, "work apps: none")], NOW, dry_run=False)
        self.assertEqual(self.both()[0], ())

    def test_a_broken_apps_json_is_unset(self):
        (self.st / apps_reply.APPS_FILE).write_text("{not json")
        self.assertEqual(self.both(), ((), ()))
        (self.st / apps_reply.APPS_FILE).write_text(json.dumps({W: "editor", F: [3, " ", "ok"]}))
        self.assertEqual(self.both(), ((), ("ok",)))

    def test_the_state_dir_from_config_finds_apps_json(self):
        self.reply("feed apps: scrollerapp")
        self.cfg(state=str(self.st))
        env = {"LIMITLESS_CONFIG": str(self.cfg_path)}
        self.assertEqual(feeds_evidence.feed_apps(env, self.home), ("scrollerapp",))

    def test_the_feed_reflex_reads_a_reply_list(self):
        self.reply("feed apps: scrollerapp")
        got = feed_reflex.from_settings({}, self.st, NOW - 86400, NOW, env={})
        self.assertNotEqual(got["label"], feed_reflex.UNKNOWN_PREFIX + feed_reflex.NO_FEEDS)
        self.assertNotIn("scrollerapp", json.dumps(got))

    def test_the_feed_reflex_config_beats_a_reply_list(self):
        self.reply("feed apps: scrollerapp")
        self.assertEqual(apps_reply.lists_for({"feed_apps": ["cfg-feed"]}, self.st, {})[F],
                         (("cfg-feed",), apps_reply.CONFIG))


class OneHelper(unittest.TestCase):
    def test_no_module_reads_the_list_keys_itself(self):
        pat = re.compile(r"\.get\(\s*(feeds_evidence\.CONFIG_KEY|feeds_evidence\.ENV_KEY|WORK_CONFIG|WORK_ENV|"
                         r"\"feed_apps\"|\"flow_work_apps\"|\"LIMITLESS_FEED_APPS\"|\"LIMITLESS_FLOW_WORK_APPS\")")
        hits = [p.name for p in sorted((ROOT / "limitless").glob("*.py"))
                if p.name != "apps_reply.py" and pat.search(p.read_text(encoding="utf-8"))]
        src = (ROOT / "limitless" / "feeds_evidence.py").read_text(encoding="utf-8")
        if re.search(r"\.get\(\s*(CONFIG_KEY|ENV_KEY)\)", src):
            hits.append("feeds_evidence.py")
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
