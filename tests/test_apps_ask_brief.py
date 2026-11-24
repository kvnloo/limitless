"""The app-lists ask in the wake brief: jobs_runner.brief_apps_ask / brief_apps_ask_told, brief_post.finalize and
bin/limitless-brief end to end. It rides the brief through the tier audit gate (the existing send path); never a
push of its own. The mark is written only after a real delivery.

Synthetic phone DBs, a temp config and HOME, a fake limitless_loop; nothing real.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from limitless import apps_ask, brief_post, jobs_runner  # noqa: E402
from test_app_candidates_tool import phone_db  # noqa: E402
from test_apps_ask import NAMES, REPLY  # noqa: E402
from test_outage_brief import FAKE_LOOP  # noqa: E402

M, H, D = 60.0, 3600.0, 86400.0
NOW = 1894708800.0
ASK = apps_ask.PROMPT + "\n" + REPLY


def aw_rows(st, now):
    t = now - 2 * D
    phone_db(Path(st) / "aw.db", [(t, t + 60 * M, "Alacritty", "org.example.alacritty"),
                                  (t + 2 * H, t + 2 * H + 50 * M, "Instagram", "com.instagram.android"),
                                  (t + 4 * H, t + 4 * H + 20 * M, "Reddit", "com.reddit.frontpage")])


class Runner(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.cfg_path = self.root / "config.json"
        self.audit = self.root / "audit.jsonl"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg_path), "LIMITLESS_AUDIT": str(self.audit),
                    "LIMITLESS_STATE": str(self.st)}
        p = mock.patch.dict(os.environ, {}, clear=True)
        p.start()
        self.addCleanup(p.stop)
        aw_rows(self.st, NOW)

    def config(self, **cfg):
        cfg.setdefault("state", str(self.st))
        cfg.setdefault("aw_db", "aw.db")
        self.cfg_path.write_text(json.dumps(cfg))

    def ask(self, now=NOW):
        return jobs_runner.brief_apps_ask(self.st, now, self.env, self.root)

    def test_the_ask_text_through_the_gate_hook_brief_apps_ask(self):
        self.config()
        self.assertEqual(self.ask(), ASK)
        row = json.loads(self.audit.read_text().splitlines()[-1])
        self.assertEqual((row["hook"], row["digits"], row["blocked"], row["lines"]), ("brief:apps_ask", 0, False, 3))
        for n in NAMES:
            self.assertNotIn(n, self.audit.read_text())       # the audit row: counts and a hash only

    def test_asking_writes_no_mark_told_does(self):
        self.config()
        self.assertEqual(self.ask(), ASK)
        self.assertEqual(self.ask(), ASK)                     # not told yet: still asked
        self.assertFalse((self.st / apps_ask.MARK_FILE).exists())
        self.assertTrue(jobs_runner.brief_apps_ask_told(self.st, NOW, self.env, self.root))
        self.assertEqual(json.loads((self.st / apps_ask.MARK_FILE).read_text()), {"told": NOW})
        self.assertEqual(self.ask(NOW + 5 * D), "")
        self.assertEqual(self.ask(NOW + 8 * D), "")           # eight days on there are no rows left in the window
        aw_rows(self.st, NOW + 8 * D)
        self.assertEqual(self.ask(NOW + 8 * D), ASK)

    def test_off_and_set_lists_are_no_text_and_told_writes_nothing(self):
        for cfg in ({"apps_ask": "off"}, {"flow_work_apps": ["zqeditor"]}):
            self.config(**cfg)
            self.assertEqual(self.ask(), "", cfg)
            self.assertFalse(jobs_runner.brief_apps_ask_told(self.st, NOW, self.env, self.root), cfg)
            self.assertFalse((self.st / apps_ask.MARK_FILE).exists(), cfg)

    def test_a_name_with_a_digit_is_blocked_by_the_gate(self):
        t = NOW - D
        phone_db(self.st / "aw.db", [(t, t + 2 * H, "iTerm2", "com.example.iterm2"),
                                     (t + 3 * H, t + 4 * H, "Instagram", "com.instagram.android")])
        self.config()
        self.assertEqual(self.ask(), "")
        self.assertTrue(json.loads(self.audit.read_text().splitlines()[-1])["blocked"])

    def test_unreadable_state_is_no_text(self):
        self.config()
        self.assertEqual(jobs_runner.brief_apps_ask(self.root / "nowhere", NOW, {}, self.root / "nohome"), "")

    def test_finalize_adds_it_last_only_when_given(self):
        out = brief_post.finalize("State: synthetic", None, NOW, outage="Not recording: wearable.", apps_ask=ASK)
        self.assertEqual(out.splitlines()[-3:], ASK.splitlines())
        self.assertEqual(out.splitlines()[-4], "Not recording: wearable.")
        self.assertEqual(brief_post.finalize("State: synthetic", None, NOW, apps_ask=""), "State: synthetic")


class Cli(unittest.TestCase):
    """bin/limitless-brief: send carries the ask once (marked only after a real delivery); build only previews."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        lib = self.home / ".local/lib"
        lib.mkdir(parents=True)
        (lib / "limitless_loop.py").write_text(FAKE_LOOP)
        (self.home / ".local/state/kevin-push").mkdir(parents=True)
        self.st = self.home / ".local/state/limitless"
        self.st.mkdir(parents=True)
        cfg = self.home / ".config/limitless"
        cfg.mkdir(parents=True)
        (cfg / "config.json").write_text(json.dumps({"aw_db": "aw.db"}))
        import time
        aw_rows(self.st, time.time())
        self.audit = self.home / "audit.jsonl"
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("LIMITLESS_", "KEVIN_PUSH"))}
        self.env.update(HOME=str(self.home), LIMITLESS_AUDIT=str(self.audit))

    def run_cli(self, *args, **extra):
        return subprocess.run([sys.executable, "-I", str(CLI), *args], env=child_env(dict(self.env, **extra)),
                              capture_output=True, text=True, timeout=60)

    def sent(self):
        p = self.home / "delivered.txt"
        return [b.strip() for b in p.read_text().split("---") if b.strip()] if p.exists() else []

    def test_send_asks_once(self):
        for _ in range(3):
            r = self.run_cli("send")
            self.assertEqual(r.returncode, 0, r.stderr)
        got = self.sent()
        self.assertEqual(len(got), 3)
        self.assertEqual(got[0].splitlines()[-3:], ASK.splitlines())
        self.assertEqual(got[1], "State: synthetic")
        self.assertEqual(got[2], "State: synthetic")
        mark = (self.st / apps_ask.MARK_FILE).read_text()
        self.assertEqual(sorted(json.loads(mark)), ["told"])
        for n in NAMES:
            self.assertNotIn(n, mark)
            self.assertNotIn(n, self.audit.read_text())

    def test_a_failed_send_keeps_it_for_the_next_brief(self):
        self.run_cli("send", FAKE_FAIL="1")
        self.assertFalse((self.st / apps_ask.MARK_FILE).exists())
        self.run_cli("send")
        self.assertEqual(self.sent()[0].splitlines()[-3:], ASK.splitlines())
        self.assertTrue((self.st / apps_ask.MARK_FILE).exists())

    def test_build_previews_without_marking(self):
        r = self.run_cli("build")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(json.loads(r.stdout)["notif_text"].endswith(ASK))
        self.assertFalse((self.st / apps_ask.MARK_FILE).exists())

    def test_off_in_config_is_no_ask(self):
        (self.home / ".config/limitless/config.json").write_text(json.dumps({"aw_db": "aw.db", "apps_ask": "off"}))
        self.run_cli("send")
        self.assertEqual(self.sent(), ["State: synthetic"])
        self.assertFalse((self.st / apps_ask.MARK_FILE).exists())


CLI = ROOT / "bin" / "limitless-brief"

if __name__ == "__main__":
    unittest.main()
