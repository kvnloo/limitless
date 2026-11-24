"""A wake brief that never reached the phone can be read in any Hermes chat (missed_brief).

Missed = today's wake brief row is in kevin-push's log (config push_log, the row titled the wake brief's send
title), today is a wake day, the delivery audit's rule finds no delivered brief today, and the newest brief row
is no older than the wake job's stale_after_s. The state card then says so on a line of its own after the push
reach line; limitless_missed_brief returns the text through tier_audit.gate (digits masked without the raw
opt-in). Read-only: only the gate's content-free audit row is written.

Synthetic state dirs and logs, times in this machine's local zone, a fixed clock, env passed explicitly.
Nothing is run or sent.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import card, delivery_audit, jobs, plugin, tier_audit  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

try:
    from limitless import missed_brief  # noqa: E402
except ImportError:  # RED: the module does not exist yet; each test fails on its own
    missed_brief = None

FIX = Path(__file__).resolve().parent / "fixtures" / "state"
TODAY = date(2030, 1, 15)
LINE = "Today's wake brief did not reach your phone; ask me for it."
TITLE = jobs.WAKE_BRIEF.send_title
BRIEF = "Good morning. Sleep 7 h 20 min (proxy).\nOne decision waiting.\nReply: Yes / Later"
MASKED = "Good morning. Sleep # h # min (proxy).\nOne decision waiting.\nReply: Yes / Later"


def local(day, hour, minute=0):
    return datetime(day.year, day.month, day.day, hour, minute).timestamp()


WAKE = local(TODAY, 7)
SENT_AT = local(TODAY, 7, 30)
NOW = local(TODAY, 8, 30)
HELD = "held (sleep mode)"
RC1 = "log (telegram rc=1)"


def row(at, how, title=TITLE, body=BRIEF):
    return {"at": int(at), "tag": "brief", "cls": "digest", "title": title, "body": body, "how": how}


def iso(t):
    return datetime.fromtimestamp(t).astimezone().isoformat()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "st"
        shutil.copytree(FIX, self.st)
        (self.st / "sleepmode.jsonl").unlink()          # wake events come only from events.jsonl here
        (self.st / "sleepmode-poll.json").unlink()
        self.log = self.st / "push-log.jsonl"
        self.audit = self.root / "audit.jsonl"
        self.cfg = self.root / "config.json"
        self.cfg.write_text(json.dumps({"push_log": "push-log.jsonl"}))
        self.hermes = self.root / "hermes"
        (self.hermes / "profiles" / "intake").mkdir(parents=True)   # the sender is set: no push-reach line
        self.env = {"HOME": str(self.root), "HERMES_HOME": str(self.hermes), "LIMITLESS_STATE": str(self.st),
                    "LIMITLESS_CONFIG": str(self.cfg), "LIMITLESS_AUDIT": str(self.audit)}
        self.r = StateReader(self.st)
        self.wakes(WAKE)

    def wakes(self, *ts):
        (self.st / "events.jsonl").write_text("".join(json.dumps({"event": "wake", "at": iso(t)}) + "\n"
                                                      for t in ts))

    def write_log(self, rows):
        self.log.write_text("".join(json.dumps(r) + "\n" for r in rows))

    def tool(self, now=NOW, raw=False):
        return missed_brief.tool(self.r, now, raw=raw, env=self.env)

    def card(self, now=NOW, today=TODAY, **kw):
        return card.build(self.r, now, today, env=self.env, **kw)

    def snapshot(self):
        out = {}
        for p in sorted(self.root.rglob("*")):
            if p.is_file() and p != self.audit:
                out[str(p.relative_to(self.root))] = (hashlib.sha256(p.read_bytes()).hexdigest(),
                                                      p.stat().st_mtime_ns)
        return out

    @staticmethod
    def bump(p):
        st = p.stat()
        os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 10 ** 9))


class Missed(Base):
    def test_a_held_brief_today_is_missed_on_the_card_and_in_the_tool(self):
        self.write_log([row(SENT_AT, HELD)])
        self.assertIn(LINE, self.card()["lines"])
        res = self.tool()
        self.assertEqual(res["value"]["brief"], MASKED)
        self.assertEqual(res["modality"], "measured")
        self.assertEqual(res["evidence_tier"], "direct")
        self.assertAlmostEqual(res["age_h"], 1.0)
        self.assertEqual(res["value"]["why"], delivery_audit.MISS_SLEEP)

    def test_a_failed_send_is_missed_too_and_the_newest_attempt_is_offered(self):
        self.write_log([row(SENT_AT - 600, RC1, body="old words"), row(SENT_AT, RC1)])
        self.assertEqual(self.tool()["value"]["brief"], MASKED)
        self.assertIn(LINE, self.card()["lines"])

    def test_the_line_comes_after_the_push_reach_line_and_before_the_offers(self):
        (self.hermes / "profiles" / "intake").rmdir()   # the sender is missing: the push-reach line shows
        self.write_log([row(SENT_AT, delivery_audit.NO_SENDER)])
        lines = self.card()["lines"]
        reach = [i for i, ln in enumerate(lines) if ln.startswith("Phone pushes are not reaching you")]
        self.assertEqual(len(reach), 1)
        self.assertEqual(lines[reach[0] + 1], LINE)
        lines = self.card(explain_offer="Explain back: offer. Reply: Voice / Later")["lines"]
        self.assertEqual(lines[-1], "Explain back: offer. Reply: Voice / Later")
        self.assertEqual(lines[-2], LINE)

    def test_the_line_survives_a_full_card_and_holds_no_digit(self):
        self.write_log([row(SENT_AT, HELD)])
        c = self.card()
        self.assertGreaterEqual(len(c["lines"]), card.MAX_LINES)   # sanity: the fixture card is full
        self.assertIn(LINE, c["lines"])
        self.assertEqual(re.findall(r"\d", LINE), [])


class NotMissed(Base):
    def assert_none(self, res):
        self.assertIsNone(res["value"])
        self.assertEqual(res["evidence_tier"], "none")
        self.assertTrue(res["reason"])
        self.assertEqual(re.findall(r"\d", res["reason"]), [])

    def test_a_delivered_brief_is_not_offered(self):
        self.write_log([row(SENT_AT - 600, HELD), row(SENT_AT, "telegram")])
        self.assertNotIn(LINE, self.card()["lines"])
        self.assert_none(self.tool())

    def test_yesterdays_brief_is_not_offered(self):
        y = TODAY - timedelta(days=1)
        self.wakes(local(y, 7))
        self.write_log([row(local(y, 23, 30), HELD)])
        now = local(TODAY, 0, 30)          # an hour after yesterday's brief, but on a new day
        self.assertNotIn(LINE, self.card(now=now)["lines"])
        self.assert_none(self.tool(now=now))

    def test_a_brief_older_than_the_wake_jobs_stale_after_is_not_offered(self):
        self.write_log([row(SENT_AT, HELD)])
        late = SENT_AT + jobs.WAKE_BRIEF.stale_after_s + 60
        self.assertNotIn(LINE, self.card(now=late)["lines"])
        self.assert_none(self.tool(now=late))

    def test_no_wake_today_is_not_offered(self):
        self.wakes(local(TODAY - timedelta(days=1), 7))
        self.write_log([row(SENT_AT, HELD)])
        self.assert_none(self.tool())
        self.assertNotIn(LINE, self.card()["lines"])

    def test_other_titles_never_count_as_a_brief(self):
        self.write_log([row(SENT_AT, HELD, title="Pick one")])
        self.assert_none(self.tool())

    def test_no_push_log_set_is_not_offered(self):
        self.cfg.write_text("{}")
        self.assert_none(self.tool())
        self.assertNotIn(LINE, self.card()["lines"])


class Digits(Base):
    def test_digits_are_masked_without_the_opt_in_and_kept_with_it(self):
        self.write_log([row(SENT_AT, HELD)])
        self.assertEqual(self.tool(raw=False)["value"]["brief"], MASKED)
        self.assertEqual(self.tool(raw=True)["value"]["brief"], BRIEF)

    def test_the_text_goes_through_the_tier_gate(self):
        self.write_log([row(SENT_AT, HELD)])
        seen = []
        real = tier_audit.gate

        def spy(hook, text, opt_in, *a, **k):
            seen.append((hook, text, opt_in))
            return real(hook, text, opt_in, *a, **k)

        with mock.patch.object(tier_audit, "gate", side_effect=spy):
            self.tool()
        self.assertEqual(seen, [(missed_brief.HOOK, MASKED, False)])
        rows = [json.loads(ln) for ln in self.audit.read_text().splitlines()]
        self.assertEqual([r["hook"] for r in rows], [missed_brief.HOOK])
        self.assertNotIn("Good morning", self.audit.read_text())   # content-free

    def test_a_brief_the_gate_drops_is_no_value(self):
        self.write_log([row(SENT_AT, HELD)])
        with mock.patch.object(tier_audit, "gate", return_value=None):
            res = self.tool()
        self.assertIsNone(res["value"])
        self.assertEqual(re.findall(r"\d", res["reason"]), [])


class ReadOnly(Base):
    def test_no_file_but_the_audit_row_changes(self):
        self.write_log([row(SENT_AT, HELD)])
        before = self.snapshot()
        self.assertEqual(self.tool()["value"]["brief"], MASKED)
        self.tool(raw=True)
        self.card()
        card.CardCache().get(self.r, NOW, TODAY, env=self.env)
        h = plugin._handler(plugin.TOOLS["limitless_missed_brief"][1], "limitless_missed_brief")
        with mock.patch.dict(os.environ, self.env, clear=True), \
                mock.patch.object(plugin.time, "time", return_value=NOW):
            res = json.loads(h({}))
        self.assertEqual(res["value"]["brief"], MASKED)
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(self.audit.is_file())
        for ln in self.audit.read_text().splitlines():
            self.assertEqual(set(json.loads(ln)) - set(tier_audit.FIELDS), set())


class Cache(Base):
    def setUp(self):
        super().setUp()
        self.c = card.CardCache()

    def get(self, now=NOW):
        return self.c.get(self.r, now, TODAY, env=self.env)

    def test_a_cache_hit_opens_no_push_log(self):
        self.write_log([row(SENT_AT, HELD)])
        self.assertIn(LINE, self.get())
        real = delivery_audit.read_log
        with mock.patch.object(delivery_audit, "read_log", side_effect=real) as rl:
            self.assertIn(LINE, self.get())
            self.assertIn(LINE, self.get(NOW + 60))
        self.assertEqual(self.c.builds, 1)
        self.assertEqual(rl.call_count, 0)

    def test_a_delivery_landing_rebuilds_without_the_line(self):
        self.write_log([row(SENT_AT, HELD)])
        self.assertIn(LINE, self.get())
        self.write_log([row(SENT_AT, HELD), row(SENT_AT + 60, "telegram")])
        self.bump(self.log)
        self.assertNotIn(LINE, self.get())
        self.assertEqual(self.c.builds, 2)

    def test_the_line_goes_once_the_brief_is_stale(self):
        self.write_log([row(SENT_AT, HELD)])
        self.assertIn(LINE, self.get())
        self.assertNotIn(LINE, self.get(SENT_AT + jobs.WAKE_BRIEF.stale_after_s + 1))

    def test_a_new_wake_event_rebuilds(self):
        self.wakes(local(TODAY - timedelta(days=1), 7))
        self.write_log([row(SENT_AT, HELD)])
        self.assertNotIn(LINE, self.get())
        self.wakes(WAKE)
        self.bump(self.st / "events.jsonl")
        self.assertIn(LINE, self.get())


class Wiring(unittest.TestCase):
    def test_the_tool_is_registered_with_a_read_only_description(self):
        self.assertIn("limitless_missed_brief", plugin.TOOLS)
        desc = plugin.TOOLS["limitless_missed_brief"][0]["description"].lower()
        self.assertIn("read-only", desc)
        self.assertIn("raw opt-in", desc)

    def test_docs_name_the_tool_and_the_line(self):
        repo = Path(__file__).resolve().parents[1]
        doc = (repo / "docs" / "missed-brief.md").read_text()
        self.assertIn("limitless_missed_brief", doc)
        self.assertIn(LINE, doc)
        self.assertIn("`limitless_missed_brief`", (repo / "README.md").read_text())


if __name__ == "__main__":
    unittest.main()
