"""The morning after: the wake brief gets "Saved last night: N ideas" and the state card a digit-free
"ideas saved last night", counting bedtime captures of the night that ended at the latest wake.
Reuses brief_post.finalize, bin/limitless-brief and card.build: no new sender. Synthetic data only."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import bedtime, brief_post, card  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
NOW = 1894708800.0
H = 3600.0


def iso(t):
    return datetime.fromtimestamp(t, tz=timezone.utc).isoformat()


def write_night(state: Path, now: float, captures=True):
    """Two nights: asleep -40..-28 h (a wake at -28 h), asleep -10..-1 h (this morning's wake at -1 h)."""
    rows = [(-40, True), (-28, False), (-10, True), (-1, False)]
    (state / "sleepmode.jsonl").write_text("".join(json.dumps({"at": iso(now + h * H), "on": on}) + "\n"
                                                   for h, on in rows))
    (state / "sleepmode-poll.json").write_text(json.dumps({"at": iso(now - 60), "ok": True}))
    if captures:
        caps = [(-30, "bedtime"),   # the night before last: not last night
                (-11, "bedtime"),   # last night, before Sleep mode (wind-down)
                (-5, "bedtime"),    # last night, asleep
                (-4, "hermes"),     # a tool capture, not routed at bedtime
                (-0.5, "bedtime")]  # after this wake: tonight's, counted tomorrow
        (state / "captures.jsonl").write_text("".join(
            json.dumps({"at": iso(now + h * H), "text": "a synthetic idea", "source": s}) + "\n" for h, s in caps))


class Count(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.env = {"LIMITLESS_STATE": str(self.state), "LIMITLESS_CONFIG": str(self.state / "none.json")}

    def tearDown(self):
        self.tmp.cleanup()

    def test_counts_bedtime_captures_between_the_last_two_wakes(self):
        write_night(self.state, NOW)
        self.assertEqual(bedtime.saved_last_night(self.state, NOW, env=self.env), 2)

    def test_no_wake_or_no_captures_is_zero(self):
        self.assertEqual(bedtime.saved_last_night(self.state, NOW, env=self.env), 0)
        write_night(self.state, NOW, captures=False)
        self.assertEqual(bedtime.saved_last_night(self.state, NOW, env=self.env), 0)
        self.assertEqual(bedtime.saved_last_night(self.state / "missing", NOW, env=self.env), 0)


class BriefLine(unittest.TestCase):
    def test_line(self):
        self.assertIsNone(brief_post.saved_line(0))
        self.assertIsNone(brief_post.saved_line(None))
        self.assertEqual(brief_post.saved_line(3), "Saved last night: 3 ideas")
        self.assertEqual(brief_post.saved_line(1), "Saved last night: 1 idea")

    def test_finalize_adds_one_line_only_when_some_were_saved(self):
        self.assertEqual(brief_post.finalize("State: synthetic", None, NOW, saved=2),
                         "State: synthetic\nSaved last night: 2 ideas")
        self.assertEqual(brief_post.finalize("State: synthetic", None, NOW, saved=0), "State: synthetic")
        self.assertEqual(brief_post.finalize("State: synthetic", None, NOW), "State: synthetic")


class CardLine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.env = {"LIMITLESS_STATE": str(self.state), "LIMITLESS_CONFIG": str(self.state / "none.json")}

    def tearDown(self):
        self.tmp.cleanup()

    def build(self):
        return card.build(StateReader(self.state), NOW, date(2030, 1, 15), env=self.env)

    def test_card_says_ideas_saved_last_night_without_digits(self):
        write_night(self.state, NOW)
        c = self.build()
        self.assertIn("ideas saved last night", c["lines"])
        self.assertLessEqual(len(c["lines"]), card.MAX_LINES)
        self.assertFalse(any(ch.isdigit() for ch in "ideas saved last night"))

    def test_no_line_without_bedtime_captures(self):
        write_night(self.state, NOW, captures=False)
        self.assertNotIn("ideas saved last night", self.build()["text"])

    def test_the_hook_card_refreshes_when_a_capture_lands(self):
        write_night(self.state, NOW, captures=False)
        hook = card.make_pre_llm_call(env=self.env, clock=lambda: NOW, today=lambda: date(2030, 1, 15))
        self.assertNotIn("ideas saved last night", hook()["context"])
        write_night(self.state, NOW)
        self.assertIn("ideas saved last night", hook()["context"])


FAKE_LOOP = '''
import os
from pathlib import Path
def load_config():
    return {}
def build(cfg, day=None):
    return {"path": "/dev/null", "notif": "State: synthetic"}
def deliver(cfg, title, body, url=None, env=None):
    Path(os.environ["HOME"], "delivered.txt").write_text(body)
    return {"rc": 0, "shown": "telegram"}
'''


class BriefCli(unittest.TestCase):
    def test_send_carries_the_saved_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".local/lib").mkdir(parents=True)
            (home / ".local/lib/limitless_loop.py").write_text(FAKE_LOOP)
            state = home / "state"
            state.mkdir()
            write_night(state, time.time())
            env = dict(os.environ, HOME=str(home), LIMITLESS_STATE=str(state),
                       LIMITLESS_CONFIG=str(home / "none.json"))
            r = subprocess.run([sys.executable, "-I", str(ROOT / "bin" / "limitless-brief"), "send"], env=env,
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual((home / "delivered.txt").read_text(), "State: synthetic\nSaved last night: 2 ideas")


if __name__ == "__main__":
    unittest.main()
