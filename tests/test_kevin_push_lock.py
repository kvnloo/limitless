"""bin/kevin-push reads sent.json, decides and reserves its send under one lock, so two pushes on one tick
cannot both take the last slot of the daily cap, and neither write loses the other's send.

A fake `hermes` on PATH sleeps briefly before it answers, so two pushes started together are both past
their cap check before either send returns; without the lock both would send. A temp HOME and state dir,
synthetic titles only; nothing is sent.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
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
# the fake transport's delay: longer than a child's start-up, so both pushes have read sent.json before
# either send returns
DELAY_S = "1"


class KevinPushLock(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        fakebin = self.home / "fakebin"
        fakebin.mkdir()
        hermes = fakebin / "hermes"
        # copies sent.json as it is during the send, sleeps, counts its calls, exits $FAKE_HERMES_RC
        hermes.write_text("#!/bin/sh\n"
                          "cp \"$HOME/.local/state/kevin-push/sent.json\" \"$HOME/sent-during.json\" 2>/dev/null\n"
                          "sleep ${FAKE_HERMES_DELAY:-0}\n"
                          "echo called >> \"$HOME/hermes-calls\"\n"
                          "exit ${FAKE_HERMES_RC:-0}\n")
        hermes.chmod(hermes.stat().st_mode | stat.S_IEXEC)
        state = self.home / "state"
        state.mkdir()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("KEVIN_PUSH_")}
        self.env.update(HOME=str(self.home), PATH=f"{fakebin}:{os.environ['PATH']}", LIMITLESS_STATE=str(state),
                        LIMITLESS_SLEEPMODE=str(self.home / "none.jsonl"), CIRCADIAN_CLASS="decision",
                        FAKE_HERMES_DELAY=DELAY_S)
        self.st = self.home / ".local/state/kevin-push"
        self.st.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def prefill(self, n):
        now = time.time()
        rows = [{"t": now - 600 - i, "k": f"synthetic{i:02d}"} for i in range(n)]
        (self.st / "sent.json").write_text(json.dumps(rows))
        return rows

    def start(self, title, body, **env):
        return subprocess.Popen([sys.executable, "-I", str(CLI), "x", title, body],
                                env=child_env(self.env, **env), stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)

    def calls(self):
        p = self.home / "hermes-calls"
        return p.read_text().count("called") if p.exists() else 0

    def sent(self):
        return json.loads((self.st / "sent.json").read_text())

    def test_two_pushes_on_one_tick_take_the_last_cap_slot_once(self):
        self.prefill(send_gate.DAILY_CAP - 1)
        procs = [self.start("Pick one", "Synthetic choice A"), self.start("Pick two", "Synthetic choice B")]
        outs = [p.communicate(timeout=60) for p in procs]
        for p, (_, err) in zip(procs, outs):
            self.assertEqual(p.returncode, 0, err)
        said = sorted(out.strip() for out, _ in outs)
        self.assertEqual(self.calls(), 1, said)
        self.assertEqual(said, ["kevin-push: log (daily cap)", "kevin-push: telegram"])
        rows = self.sent()
        self.assertEqual(len(rows), send_gate.DAILY_CAP, rows)
        self.assertEqual(sum(1 for r in rows if not r["k"].startswith("synthetic")), 1, rows)

    def test_a_failed_send_leaves_sent_json_without_its_reservation(self):
        rows = self.prefill(send_gate.DAILY_CAP - 1)
        p = self.start("Pick one", "Synthetic choice A", FAKE_HERMES_RC="1", FAKE_HERMES_DELAY="0",
                       KEVIN_PUSH_ONCE="synthetic_event:1999990000")
        out, err = p.communicate(timeout=60)
        self.assertEqual(p.returncode, 0, err)
        self.assertEqual(out.strip(), "kevin-push: log (telegram rc=1)")
        self.assertEqual(self.calls(), 1)
        during = json.loads((self.home / "sent-during.json").read_text())
        self.assertEqual(len(during), send_gate.DAILY_CAP, "the slot is reserved while the send runs")
        self.assertEqual([r for r in during if r.get("pending")][0].get("once"), "synthetic_event:1999990000")
        self.assertEqual(self.sent(), rows, "a failed send uses no cap slot and claims no event key")


if __name__ == "__main__":
    unittest.main()
