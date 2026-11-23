"""The sleep debt words on the state card (card.build, CardCache, the pre_llm_call hook).

Synthetic rows only. One line, the sleep_debt label, right under the sleep and readiness line; none when the
debt is unknown. The card goes through tier_audit.gate like every injection; without the raw opt-in it has no
digit. Nothing is written or sent.
"""
import json
import os
import re
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import card, sleep_debt, tier_audit  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

TODAY = date(2030, 1, 28)
NOW = datetime.combine(TODAY, time(9)).timestamp()
H = 3600
SPAN = sleep_debt.RECENT_NIGHTS + sleep_debt.BASELINE_NIGHTS


def wear(ago, hours):
    return {"night": (TODAY - timedelta(days=ago)).isoformat(), "asleep_s": int(hours * H), "source": "synthetic"}


def screen(ago, hours):
    s = datetime.combine(TODAY - timedelta(days=ago), time(23)).timestamp()
    return [{"ts": int(s * 1000), "type": "KEYGUARD_HIDDEN", "pkg": "synthetic"},
            {"ts": int((s + hours * H) * 1000), "type": "KEYGUARD_HIDDEN", "pkg": "synthetic"}]


def nightly(recent_h, base_h=8.0):
    return [(a, recent_h if a <= sleep_debt.RECENT_NIGHTS else base_h) for a in range(1, SPAN + 1)]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.cfg = self.root / "config.json"
        self.cfg.write_text(json.dumps({"sleep_file": "sleep.jsonl"}))
        self.env = {"LIMITLESS_CONFIG": str(self.cfg), "LIMITLESS_STATE": str(self.st)}

    def wearable(self, recent_h):
        (self.st / "sleep.jsonl").write_text("".join(json.dumps(wear(a, h)) + "\n" for a, h in nightly(recent_h)))

    def phone(self, recent_h):
        rows = [r for a, h in nightly(recent_h) for r in screen(a, h)]
        (self.st / "screen-events.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def build(self, **kw):
        kw.setdefault("peak", None)
        kw.setdefault("light", None)
        return card.build(StateReader(self.st), NOW, TODAY, env=self.env, **kw)

    def hook(self, extra=None):
        env = dict(self.env, **(extra or {}))
        with mock.patch.dict(os.environ, env):
            fn = card.make_pre_llm_call(env=env, clock=lambda: NOW, today=lambda: TODAY)
            return fn()


class Build(Base):
    def test_a_known_debt_is_one_line_under_the_sleep_line(self):
        self.wearable(6)
        lines = self.build()["lines"]
        self.assertEqual(lines.count("a lot of sleep debt"), 1)
        self.assertTrue(lines[2].startswith("sleep "), lines)
        self.assertEqual(lines[3], "a lot of sleep debt")
        self.assertLessEqual(len(lines), card.MAX_LINES)

    def test_wearable_beats_the_phone_on_the_card(self):
        self.wearable(8)
        self.phone(4)
        self.assertIn("little sleep debt", self.build()["lines"])

    def test_all_proxy_says_phone_estimate(self):
        (self.st / "sleep.jsonl").unlink(missing_ok=True)
        self.phone(7)
        self.assertIn("some sleep debt (phone estimate)", self.build()["lines"])

    def test_unknown_is_left_out(self):
        self.wearable(6)
        (self.st / "sleep.jsonl").write_text(json.dumps(wear(1, 5)) + "\n")     # one night: too few
        lines = self.build()["lines"]
        self.assertFalse([ln for ln in lines if "sleep debt" in ln or "too few nights" in ln], lines)

    def test_no_sleep_data_is_left_out_and_the_card_is_unchanged(self):
        plain = self.build()["lines"]
        self.assertFalse([ln for ln in plain if "sleep debt" in ln])
        self.assertEqual(self.build(debt=None)["lines"], plain)

    def test_every_label_as_a_card_line_has_no_digit(self):
        for word in sleep_debt.KNOWN_LABELS:
            text = self.build(debt=word, mask=False)["text"]
            self.assertIn(word, text.splitlines())
            self.assertEqual(re.findall(r"\d", text), [], word)

    def test_a_word_that_is_not_a_debt_label_never_reaches_the_card(self):
        self.assertIsNone(card.debt_line(StateReader(self.root / "nowhere"), NOW, TODAY, self.env))
        with mock.patch.object(card.tools, "sleep_debt", return_value={"value": {"label": "debt of 3 hours"}}):
            self.assertIsNone(card.debt_line(StateReader(self.st), NOW, TODAY, self.env))
        with mock.patch.object(card.tools, "sleep_debt", side_effect=RuntimeError("broken")):
            self.assertIsNone(card.debt_line(StateReader(self.st), NOW, TODAY, self.env))

    def test_a_full_card_still_fits(self):
        self.wearable(6)
        lines = self.build(anki_offer="trough: a short Anki review fits now", peak="post-wake peak: open",
                           light="Light: outdoor light now helps set the day.")["lines"]
        self.assertLessEqual(len(lines), card.MAX_LINES)
        self.assertIn("a lot of sleep debt", lines)


class Hook(Base):
    def test_the_hook_carries_the_line_through_the_gate_with_no_digit(self):
        self.wearable(6)
        log = self.root / "audit.jsonl"
        out = self.hook({tier_audit.ENV_KEY: str(log)})
        self.assertIn("a lot of sleep debt", out["context"].splitlines())
        self.assertEqual(re.findall(r"\d", out["context"]), [])
        (row,) = [json.loads(ln) for ln in log.read_text().splitlines()]
        self.assertEqual((row["hook"], row["tier"], row["blocked"], row["opt_in"]), ("pre_llm_call", "T1", False, False))

    def test_the_card_follows_new_nights(self):
        self.wearable(8)
        env = dict(self.env)
        with mock.patch.dict(os.environ, env):
            fn = card.make_pre_llm_call(env=env, clock=lambda: NOW, today=lambda: TODAY)
            self.assertIn("little sleep debt", fn()["context"].splitlines())
            self.wearable(6)
            self.assertIn("a lot of sleep debt", fn()["context"].splitlines())

    def test_nothing_is_written_or_sent(self):
        self.wearable(6)
        self.phone(8)
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob("*") if p.is_file()}
        with mock.patch("urllib.request.urlopen") as net, mock.patch("subprocess.run") as run:
            self.hook()
        self.assertFalse(net.called or run.called)
        self.assertEqual({p: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.rglob("*") if p.is_file()},
                         before)


if __name__ == "__main__":
    unittest.main()
