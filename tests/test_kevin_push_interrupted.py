"""bin/kevin-push names a send a killed push left behind: a sent.json row still marked ``pending`` after
send_gate.PENDING_UNKNOWN_S (twice the sender's timeout) loses the mark and gets ``"unknown": true``, inside the
same locked read the push decides on. The row stays: it still counts for the daily cap and the dedupe, since its
delivery is unknown, not failed. A pending row younger than the limit belongs to a push still running and is
left alone. A push that was only slow, not killed, and settles after its row was renamed still settles its own row:
a delivery leaves a plain delivered row, a failed send removes it.

A fake `hermes` on PATH answers at once; a temp HOME and state dir, synthetic titles only; nothing is sent.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import fcntl
import importlib.machinery
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import send_gate  # noqa: E402

CLI = ROOT / "bin" / "kevin-push"


class KevinPushInterrupted(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        fakebin = self.home / "fakebin"
        fakebin.mkdir()
        hermes = fakebin / "hermes"
        # copies sent.json as it is during the send, counts its calls, exits 0
        hermes.write_text("#!/bin/sh\n"
                          "cp \"$HOME/.local/state/kevin-push/sent.json\" \"$HOME/sent-during.json\" 2>/dev/null\n"
                          "echo called >> \"$HOME/hermes-calls\"\n"
                          "exit 0\n")
        hermes.chmod(hermes.stat().st_mode | stat.S_IEXEC)
        state = self.home / "state"
        state.mkdir()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("KEVIN_PUSH_")}
        self.env.update(HOME=str(self.home), PATH=f"{fakebin}:{os.environ['PATH']}", LIMITLESS_STATE=str(state),
                        LIMITLESS_SLEEPMODE=str(self.home / "none.jsonl"), CIRCADIAN_CLASS="decision")
        self.st = self.home / ".local/state/kevin-push"
        self.st.mkdir(parents=True)
        self.now = time.time()
        self.old = {"t": self.now - send_gate.PENDING_UNKNOWN_S - 60,
                    "k": send_gate.key("Synthetic old", "A made-up choice"), "pending": "aaaa"}
        self.fresh = {"t": self.now - 5, "k": send_gate.key("Synthetic fresh", "Another made-up choice"),
                      "pending": "bbbb"}

    def write_sent(self, rows):
        (self.st / "sent.json").write_text(json.dumps(rows))

    def sent(self):
        return json.loads((self.st / "sent.json").read_text())

    def calls(self):
        p = self.home / "hermes-calls"
        return p.read_text().count("called") if p.exists() else 0

    def start(self, title, body):
        return subprocess.Popen([sys.executable, "-I", str(CLI), "x", title, body], env=child_env(self.env),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def push(self, title, body):
        p = self.start(title, body)
        out, err = p.communicate(timeout=60)
        self.assertEqual(p.returncode, 0, err)
        return out.strip()

    def row(self, rows, k):
        got = [r for r in rows if r.get("k") == k]
        self.assertEqual(len(got), 1, rows)
        return got[0]

    def test_an_old_pending_row_becomes_unknown_and_a_fresh_one_is_left_alone(self):
        self.write_sent([self.old, self.fresh])
        self.assertEqual(self.push("Pick one", "Synthetic choice A"), "kevin-push: telegram")
        rows = self.sent()
        self.assertEqual(len(rows), 3, rows)
        old = self.row(rows, self.old["k"])
        self.assertEqual(old, {"t": self.old["t"], "k": self.old["k"], "unknown": True})
        self.assertEqual(self.row(rows, self.fresh["k"]), self.fresh)
        # written with the reservation, i.e. inside the locked read, before the sender ran
        during = json.loads((self.home / "sent-during.json").read_text())
        self.assertEqual(self.row(during, self.old["k"]).get("unknown"), True, during)

    def test_the_unknown_row_still_counts_for_dedupe(self):
        self.write_sent([self.old])
        self.assertEqual(self.push("Synthetic old", "A made-up choice"), "kevin-push: log (duplicate)")
        self.assertEqual(self.calls(), 0)
        self.assertEqual(self.sent(), [{"t": self.old["t"], "k": self.old["k"], "unknown": True}])

    def test_the_unknown_row_still_counts_for_the_cap(self):
        rows = [{"t": self.now - 600 - i, "k": f"synthetic{i:02d}"} for i in range(send_gate.DAILY_CAP - 1)]
        self.write_sent(rows + [self.old])
        self.assertEqual(self.push("Pick one", "Synthetic choice A"), "kevin-push: log (daily cap)")
        self.assertEqual(self.calls(), 0)
        self.assertEqual(self.sent(), rows + [{"t": self.old["t"], "k": self.old["k"], "unknown": True}])

    def test_the_mark_is_changed_only_once_the_push_holds_the_lock(self):
        self.write_sent([self.old])
        lock = open(self.st / "sent.json.lock", "a")
        self.addCleanup(lock.close)
        fcntl.flock(lock, fcntl.LOCK_EX)
        p = self.start("Pick one", "Synthetic choice A")
        try:
            with self.assertRaises(subprocess.TimeoutExpired):
                p.wait(timeout=2)
            self.assertEqual(self.sent(), [self.old], "nothing is rewritten before the lock is held")
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
        out, err = p.communicate(timeout=60)
        self.assertEqual(p.returncode, 0, err)
        self.assertEqual(self.row(self.sent(), self.old["k"]).get("unknown"), True)


def load_kevin_push(st):
    """bin/kevin-push as a module, its sent.json and lock pointed at ``st`` (a temp dir)."""
    loader = importlib.machinery.SourceFileLoader("kevin_push_under_test", str(CLI))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    mod.ST, mod.SENT, mod.LOCK = st, st / "sent.json", st / "sent.json.lock"
    return mod


class SlowPushSettlesItsOwnRow(unittest.TestCase):
    """A push that was only slow (stopped, swapped out), not killed, settles after the next push renamed its row
    unknown: the row is still its own. Synthetic clock: every time is an offset from T0, nothing is sent."""

    T0 = 1_900_000_000.0

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.kp = load_kevin_push(Path(tmp.name))
        self.k = send_gate.key("Synthetic slow", "A made-up choice")
        self.other = {"t": self.T0 - 600, "k": send_gate.key("Synthetic other", "Another made-up choice")}
        # the slow push's reservation, as main() writes it under the lock
        self.kp.SENT.write_text(json.dumps([self.other, {"t": self.T0, "k": self.k, "pending": "slowtoken"}]))
        # the next push's locked read, past PENDING_UNKNOWN_S: the slow push's row is renamed unknown
        later = self.T0 + send_gate.PENDING_UNKNOWN_S + 60
        with self.kp.sent_lock():
            self.kp.SENT.write_text(json.dumps(self.kp.name_unknown(self.kp.read_sent(later), later)))
        renamed = self.mine()
        self.assertIs(renamed.get("unknown"), True, renamed)
        self.assertNotIn("pending", renamed)

    def rows(self):
        return json.loads(self.kp.SENT.read_text())

    def mine(self):
        got = [r for r in self.rows() if r.get("k") == self.k]
        return got[0] if len(got) == 1 else got

    def test_a_delivery_after_the_rename_leaves_a_plain_delivered_row(self):
        self.kp.settle(self.T0, "slowtoken", True)
        self.assertEqual(self.rows(), [self.other, {"t": self.T0, "k": self.k}])

    def test_a_failed_send_after_the_rename_removes_the_row(self):
        self.kp.settle(self.T0, "slowtoken", False)
        self.assertEqual(self.rows(), [self.other])

    def test_another_push_settling_leaves_the_renamed_row_unknown(self):
        self.kp.settle(self.T0, "othertoken", True)
        self.assertIs(self.mine().get("unknown"), True)


if __name__ == "__main__":
    unittest.main()
