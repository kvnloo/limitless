"""The break nudge: one soft message per long focus block, through the same gates as every push.

Synthetic data only: a made-up work app in a synthetic ActivityWatch DB, epoch times picked for the test.
Nothing reads the clock and nothing sends: push is a fake that records its calls.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import blocks, decision_window as dw, jobs, jobs_runner, send_gate  # noqa: E402
from test_flow_week import make_db  # noqa: E402

NOW = 2_000_000_000.0
M, H = 60.0, 3600.0
SPEC = jobs.BREAK_NUDGE
TITLE = SPEC.send_title


def ev(start, end, thr=90 * M):
    return {"event": "long_block", "at": start + thr, "block_start": start, "block_end": end}


def anytime():
    return dw.WindowState("anytime", source="test")


class Spec(unittest.TestCase):
    def test_spec_is_event_triggered_and_listed(self):
        self.assertIs(jobs.SPECS["break_nudge"], SPEC)
        self.assertEqual((SPEC.trigger_event, SPEC.window_class, SPEC.max_per_window), ("long_block", "anytime", 1))
        self.assertIn("long_block", jobs.EVENTS)
        self.assertFalse(SPEC.focus_holds)
        self.assertTrue(jobs.WAKE_BRIEF.focus_holds)

    def test_the_gap_default_matches_blocks(self):
        self.assertEqual(jobs.BLOCK_GAP_S, blocks.GAP_S)

    def test_card_is_plain_words(self):
        card = jobs.to_schedule_card(SPEC)
        self.assertEqual(card["speaks"], "when a focus block runs long, at most once")
        for v in card.values():
            self.assertNotRegex(v, r"_|\d")


class Fire(unittest.TestCase):
    def fire(self, events, state=None, sent=(), now=NOW):
        return jobs.should_fire(SPEC, events, state if state is not None else anytime(), list(sent), now)

    def test_a_block_past_the_threshold_delivers(self):
        v = self.fire([ev(NOW - 100 * M, NOW - M)])
        self.assertEqual(v.action, jobs.DELIVER)
        self.assertEqual(v.trigger_at, NOW - 10 * M)

    def test_an_open_glide_focus_block_does_not_hold_it(self):
        glide = dw.WindowState("peak", since="focus_start", source="glide", hold_asks=True)
        self.assertEqual(self.fire([ev(NOW - 100 * M, NOW - M)], glide).action, jobs.DELIVER)
        # every other job is still held by the focus block
        wake = jobs.should_fire(jobs.WAKE_BRIEF, [{"event": "wake", "at": NOW - 600}], glide, [], NOW)
        self.assertEqual(wake.action, jobs.HOLD)

    def test_asleep_holds(self):
        self.assertEqual(self.fire([ev(NOW - 100 * M, NOW - M)], {"cls": "asleep"}).action, jobs.HOLD)

    def test_the_daily_cap_still_applies(self):
        sent = [{"t": NOW - (i + 1) * 60, "k": f"k{i}"} for i in range(send_gate.DAILY_CAP)]
        v = self.fire([ev(NOW - 100 * M, NOW - M)], sent=sent)
        self.assertEqual(v.action, jobs.HOLD)
        self.assertIn("daily cap", v.reason)

    def test_once_per_block(self):
        e = ev(NOW - 100 * M, NOW - M)
        sent = [jobs.sent_entry(SPEC, e["at"], NOW - 5 * M)]
        self.assertEqual(self.fire([e], sent=sent).action, jobs.DROP)
        # the next long block speaks again
        e2 = ev(NOW + 3 * H, NOW + 5 * H)
        self.assertEqual(self.fire([e, e2], sent=sent, now=NOW + 5 * H).action, jobs.DELIVER)


class BreakVerdict(unittest.TestCase):
    def verdict(self, e, now=NOW):
        v = jobs.should_fire(SPEC, [e], anytime(), [], now)
        return jobs.break_verdict(v, [e], now, gap_s=10 * M)

    def test_still_going_says_so(self):
        v = self.verdict(ev(NOW - 100 * M, NOW - M))
        self.assertEqual(v.action, jobs.DELIVER)
        self.assertTrue(v.reason.startswith("your focus block has run past its usual length"), v.reason)

    def test_just_ended_says_so(self):
        v = self.verdict(ev(NOW - 130 * M, NOW - 20 * M))
        self.assertEqual(v.action, jobs.DELIVER)
        self.assertTrue(v.reason.startswith("a long focus block just ended"), v.reason)

    def test_ended_a_while_ago_drops(self):
        v = self.verdict(ev(NOW - 5 * H, NOW - 2 * H))
        self.assertEqual(v.action, jobs.DROP)
        self.assertIn("a late message is noise", v.reason)

    def test_why_now_line_is_digit_free(self):
        for e in (ev(NOW - 100 * M, NOW - M), ev(NOW - 130 * M, NOW - 20 * M)):
            line = send_gate.why_line(self.verdict(e).reason)
            self.assertNotRegex(line, r"\d")
            self.assertIn("focus block", line)

    def test_other_verdicts_pass_through(self):
        nt = jobs.Verdict(jobs.NOT_TRIGGERED, "no long focus block event yet")
        self.assertEqual(jobs.break_verdict(nt, [], NOW), nt)
        held = jobs.Verdict(jobs.HOLD, "asleep: holds until wake", NOW - 10 * M)
        self.assertEqual(jobs.break_verdict(held, [ev(NOW - 100 * M, NOW - M)], NOW), held)

    def test_block_start_from_the_event(self):
        e = ev(NOW - 100 * M, NOW - M)
        self.assertEqual(jobs.block_start([e], e["at"]), NOW - 100 * M)
        self.assertEqual(jobs.block_start([{"event": "long_block", "at": NOW}], NOW), NOW)


def write_rows(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


class FakePush:
    def __init__(self, result="telegram"):
        self.result, self.calls = result, []

    def __call__(self, title, body, once=None, why=None):
        self.calls.append({"title": title, "body": body, "once": once, "why": why})
        return self.result


class Runner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.db = self.root / "aw.db"
        self.cfg = self.root / "config.json"
        self.config(flow_work_apps=["editor"])
        self.env = {"LIMITLESS_CONFIG": str(self.cfg), "LIMITLESS_AW_DB": str(self.db)}

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, **kw):
        self.cfg.write_text(json.dumps(kw))

    def work(self, start, end, gap_app=None):
        spans = [(start, end, "editor")]
        if gap_app:
            mid = (start + end) / 2
            spans = [(start, mid, "editor"), (mid, mid + 3 * M, gap_app), (mid + 3 * M, end, "editor")]
        make_db(self.db, spans=spans)

    def run_once(self, now=NOW, **kw):
        kw.setdefault("env", self.env)
        kw.setdefault("home", self.root)
        return {r["job"]: r for r in jobs_runner.run_once(self.st, now, **kw)}[TITLE]

    def sent(self):
        p = self.st / jobs_runner.SENT_LOG
        return [json.loads(ln) for ln in p.read_text().splitlines()] if p.exists() else []

    def test_dry_run_lists_it_and_sends_nothing(self):
        self.work(NOW - 100 * M, NOW - M, gap_app="scroller")
        push = FakePush()
        row = self.run_once(push=push)
        self.assertEqual(row["action"], jobs.DELIVER, row)
        self.assertEqual(push.calls, [])
        self.assertEqual(self.sent(), [])

    def test_send_once_per_block_with_the_block_key(self):
        start = NOW - 100 * M
        self.work(start, NOW - M)
        push = FakePush()
        row = self.run_once(push=push, dry_run=False)
        self.assertEqual(row["action"], jobs.DELIVER, row)
        self.assertEqual(len(push.calls), 1)
        call = push.calls[0]
        self.assertEqual(call["title"], TITLE)
        self.assertEqual(call["once"], f"break:{int(start)}")
        self.assertEqual(call["body"], jobs_runner.BREAK_BODY)
        self.assertNotRegex(send_gate.why_line(call["why"]), r"\d")
        self.assertEqual([s["job"] for s in self.sent()], ["break_nudge"])
        again = self.run_once(now=NOW + 5 * M, push=push, dry_run=False)
        self.assertEqual(again["action"], jobs.DROP)
        self.assertEqual(len(push.calls), 1)

    def test_event_key_is_the_block_key(self):
        start = NOW - 100 * M
        self.work(start, NOW - M)
        k = jobs_runner.event_key(self.st, NOW, job="break_nudge", env=self.env, home=self.root)
        self.assertEqual(k, f"break:{int(start)}")

    def test_body_is_one_soft_line_with_no_digits_or_durations(self):
        b = jobs_runner.body(SPEC)
        self.assertEqual(b, jobs_runner.BREAK_BODY)
        self.assertEqual(b, "Long focus block; a short break now keeps the next one good")
        self.assertEqual(len(b.splitlines()), 1)
        self.assertNotRegex(b, r"(?i)\d|\b(min|minute|hour|second|score)s?\b")

    def test_a_short_block_does_not_trigger(self):
        self.work(NOW - 60 * M, NOW - M)
        self.assertEqual(self.run_once()["action"], jobs.NOT_TRIGGERED)

    def test_break_after_min_from_config(self):
        self.work(NOW - 60 * M, NOW - M)
        self.config(flow_work_apps=["editor"], break_after_min=45)
        self.assertEqual(self.run_once()["action"], jobs.DELIVER)

    def test_no_work_apps_is_unknown_not_quiet(self):
        self.work(NOW - 100 * M, NOW - M)
        self.config()
        row = self.run_once()
        self.assertEqual(row["action"], jobs.NOT_TRIGGERED)
        self.assertIn("focus blocks unknown", row["reason"])
        self.assertIn("flow_work_apps", row["reason"])

    def test_no_aw_db_is_unknown(self):
        row = self.run_once(env={"LIMITLESS_CONFIG": str(self.cfg)})
        self.assertEqual(row["action"], jobs.NOT_TRIGGERED)
        self.assertIn("focus blocks unknown", row["reason"])

    def test_just_ended_delivers_and_long_ago_drops(self):
        self.work(NOW - 130 * M, NOW - 20 * M)
        self.assertEqual(self.run_once()["action"], jobs.DELIVER)
        self.assertEqual(self.run_once(now=NOW + 2 * H)["action"], jobs.DROP)

    def test_an_open_glide_block_does_not_hold_it(self):
        self.work(NOW - 100 * M, NOW - M)
        att = self.root / "attention.json"
        att.write_text(json.dumps({"block": {"start": NOW - 100 * M, "end": NOW + H, "minutes": 160}}))
        self.env["LIMITLESS_GLIDE_ATTENTION"] = str(att)
        self.assertEqual(self.run_once()["action"], jobs.DELIVER)

    def sleep_mode_on(self, at):
        write_rows(self.st / "sleepmode.jsonl", [{"at": at, "on": True}])
        (self.st / "sleepmode-poll.json").write_text(json.dumps({"at": NOW - 60, "ok": True}))

    def test_sleep_mode_on_holds_it(self):
        self.work(NOW - 100 * M, NOW - M)
        self.sleep_mode_on(NOW - 2 * H)              # on before the block reached its length: held, not sent
        row = self.run_once()
        self.assertEqual(row["action"], jobs.HOLD)
        self.assertIn("asleep", row["reason"])

    def test_sleep_mode_on_after_the_trigger_drops_it(self):
        self.work(NOW - 100 * M, NOW - M)
        self.sleep_mode_on(NOW - 5 * M)              # Sleep mode went on after it: the nudge expired
        row = self.run_once()
        self.assertEqual(row["action"], jobs.DROP)
        self.assertIn("expired", row["reason"])

    def test_quiet_drops_it(self):
        self.work(NOW - 100 * M, NOW - M)
        push = FakePush("log (quiet: off until you reply on)")
        row = self.run_once(push=push, dry_run=False)
        self.assertEqual(row["action"], jobs.DROP)
        self.assertIn("quiet", row["reason"])
        self.assertEqual(self.sent(), [])


if __name__ == "__main__":
    unittest.main()
