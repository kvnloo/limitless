"""bin/limitless-app-candidates: prints the ready-to-send reply lines (or --json), writes nothing, sends nothing.

Synthetic phone DBs and desktop export files only (well-known public app ids, made-up app names).
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))

from limitless import app_candidates as ac  # noqa: E402
from test_app_candidates_tool import desktop_export, listing, phone_db  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "limitless-app-candidates"
M, H = 60.0, 3600.0


class Cli(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.st = self.dir / "state"
        self.st.mkdir()

    def env(self, **cfg):
        cfg.setdefault("state", str(self.st))
        p = self.dir / "config.json"
        p.write_text(json.dumps(cfg))
        keep = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "SYSTEMROOT")}
        return dict(keep, LIMITLESS_CONFIG=str(p), LIMITLESS_STATE=str(self.st), HOME=str(self.dir))

    def data(self):
        now = time.time()   # the CLI reads the real clock: the synthetic week ends just before it
        t = now - 2 * 86400
        phone_db(self.st / "aw.db", [(t, t + 90 * M, "Instagram", "com.instagram.android"),
                                     (t + 2 * H, t + 2 * H + 20 * M, "Reddit", "com.reddit.frontpage")])
        desktop_export(self.st / "desk.json", [(now - 6 * H, now - 2 * H, "Code"), (now - 2 * H, now - H, "kitty")])

    def run_cli(self, env, *args):
        return subprocess.run([sys.executable, "-I", str(BIN), *args], env=child_env(env), capture_output=True, text=True,
                              timeout=60)

    def test_prints_the_reply_lines(self):
        self.data()
        r = self.run_cli(self.env(aw_db="aw.db", desktop_aw_export="desk.json", feed_apps=["zqscroller"]))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "work apps: code, kitty\nfeed apps: instagram, reddit, zqscroller\n")
        self.assertEqual(r.stderr, "")

    def test_json(self):
        self.data()
        r = self.run_cli(self.env(aw_db="aw.db", desktop_aw_export="desk.json"), "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual(got["label"], ac.BOTH)
        self.assertEqual(got["reply"], "work apps: code, kitty\nfeed apps: instagram, reddit")
        self.assertEqual([e["name"] for e in got["work"]], ["code", "kitty"])
        self.assertEqual(got["work"][0]["seconds"], 4 * H)
        self.assertEqual(got["sources"], ["phone", "desktop"])
        self.assertEqual(set(got), {"label", "reply", "work", "feed", "other", "sources", "max_n", "total_s", "why"})

    def test_unknown_prints_no_reply_and_a_plain_reason(self):
        r = self.run_cli(self.env())
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "")
        self.assertEqual(r.stderr, f"limitless-app-candidates: unknown: {ac.NO_SOURCE}\n")
        r = self.run_cli(self.env(), "--json")
        got = json.loads(r.stdout)
        self.assertEqual((got["label"], got["reply"], got["work"], got["feed"]),
                         ("unknown: " + ac.NO_SOURCE, "", None, None))

    def test_nothing_is_written(self):
        self.data()
        env = self.env(aw_db="aw.db", desktop_aw_export="desk.json", flow_work_apps=["zqeditor"])
        before, repo_before = listing(self.dir), listing(ROOT / "bin")
        self.assertEqual(self.run_cli(env).returncode, 0)
        self.assertEqual(self.run_cli(env, "--json").returncode, 0)
        self.assertEqual(listing(self.dir), before)
        self.assertEqual(listing(ROOT / "bin"), repo_before)

    def test_help_says_it_only_suggests(self):
        r = self.run_cli(self.env(), "--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("never writes", r.stdout)


if __name__ == "__main__":
    unittest.main()
