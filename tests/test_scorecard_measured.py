"""Scorecard measured rows: north-star rows one (loop uptime) and two (delivery) as the audits measured them.

scorecard.measured reads the uptime audit of the state dir's runs.jsonl and the delivery audit of
kevin-push's log; the weekly block cites both in words beside the hand status. Synthetic fixtures only: an
invented NORTH-STAR-shaped table, a synthetic runs.jsonl and a synthetic push log. Fixed clock, UTC.
"""
import json
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import delivery_audit, jobs, scorecard as sc, tier_audit, tools, uptime_audit  # noqa: E402

UTC = timezone.utc
NOW = 2_000_000_000.0
TODAY = datetime.fromtimestamp(NOW, UTC).date()
H = 3600
HEADER = "| # | Criterion | Status | Evidence (latest) | Weeks green |\n|---|---|---|---|---|\n"
DIGIT = re.compile(r"\d")
FIELDS = {"value", "modality", "age_h", "evidence_tier"}


def table(uptime="green", delivery="green", rest="amber"):
    return (HEADER + f"| 1 | Loop uptime | {uptime} | synthetic | 2 |\n| 2 | Delivery | {delivery} | synthetic | 1 |\n"
            f"| 3 | Capture triage | {rest} | synthetic | 0 |\n| 4 | Review held | red | synthetic | 0 |\n")


def noon(day):
    return datetime(day.year, day.month, day.day, 12, tzinfo=UTC).timestamp()


def run_row(day, stale=()):
    at = datetime.fromtimestamp(noon(day), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"at": at, "inputs": ("stale " + ",".join(stale)).strip()}


def push_row(at, how="telegram", title="Pick one", body="Keep it?\nReply: Yes / No"):
    return {"at": int(at), "tag": "x", "cls": "decision", "title": title, "body": body, "how": how}


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.env = {"LIMITLESS_CONFIG": str(self.root / "none.json")}
        self.cfg = {}

    def runs(self, stale_days=0, days=28):
        """``days`` synthetic sync days ending today; the newest ``stale_days`` list the wearable as stale."""
        rows = [run_row(TODAY - timedelta(days=k), ("wearable",) if k < stale_days else ())
                for k in range(days - 1, -1, -1)]
        (self.st / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def pushes(self, per_day=1, briefs=True, days=7, body="Keep it?\nReply: Yes / No"):
        """A synthetic kevin-push log over ``days`` days ending today, a wake event each day."""
        rows, wakes = [], []
        for k in range(days - 1, -1, -1):
            t = noon(TODAY - timedelta(days=k)) - 4 * H
            wakes.append({"event": "wake", "at": t})
            if briefs:
                rows.append(push_row(t + 60, title=jobs.WAKE_BRIEF.send_title, body="Morning\nReply: ok"))
            rows += [push_row(t + 120 + i, body=body) for i in range(per_day)]
        (self.st / "push-log.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        (self.st / "events.jsonl").write_text("".join(json.dumps(w) + "\n" for w in wakes))
        self.cfg["push_log"] = "push-log.jsonl"

    def measured(self, **kw):
        return sc.measured(self.st, self.cfg, NOW, UTC, env=self.env, home=self.root, **kw)

    def by_n(self, **kw):
        return {m["n"]: m for m in self.measured(**kw)}


class Measured(Fixture):
    def test_measured_rows_in_order_with_the_brief_shape(self):
        got = self.measured()
        self.assertEqual([m["n"] for m in got], [1, 2, 3])
        self.assertEqual([m["criterion_words"] for m in got],
                         ["loop uptime", "delivery", "habit loop"])
        for m in got:
            self.assertEqual(set(m), {"n", "criterion_words", "label", "goal"})

    def test_missing_logs_are_the_audits_own_unknown_words(self):
        m = self.by_n()
        self.assertEqual(m[1]["goal"], uptime_audit.GOAL_UNKNOWN)
        self.assertEqual(m[1]["label"], "unknown: " + uptime_audit.NO_LOG_REASON)
        self.assertEqual(m[2]["goal"], "unknown")
        self.assertEqual(m[2]["label"], delivery_audit.NO_LOG)

    def test_missing_state_dir_is_unknown_not_an_error(self):
        got = sc.measured(self.root / "nowhere", None, NOW, UTC, env=self.env, home=self.root)
        self.assertEqual([m["goal"] for m in got], ["unknown"] * 3)

    def test_unreadable_push_log_and_a_quiet_week_are_unknown(self):
        self.cfg["push_log"] = "absent.jsonl"
        self.assertEqual(self.by_n()[2]["label"], "unknown: " + delivery_audit.UNREADABLE_REASON)
        (self.st / "absent.jsonl").write_text(json.dumps(push_row(NOW - 30 * 86400)) + "\n")
        self.assertEqual(self.by_n()[2], {"n": 2, "criterion_words": "delivery", "goal": "unknown",
                                          "label": delivery_audit.UNKNOWN_ROWS})

    def test_uptime_fresh_every_day_is_met_from_the_audit(self):
        self.runs()
        m = self.by_n()[1]
        self.assertEqual(m["goal"], uptime_audit.GOAL_MET)
        self.assertIn(uptime_audit.GOAL_WORDS[uptime_audit.GOAL_MET], m["label"])

    def test_uptime_stale_for_a_week_is_not_met(self):
        self.runs(stale_days=7)
        m = self.by_n()[1]
        self.assertEqual(m["goal"], uptime_audit.GOAL_NOT_MET)
        self.assertIn(uptime_audit.GOAL_WORDS[uptime_audit.GOAL_NOT_MET], m["label"])

    def test_uptime_with_too_few_known_days_is_unknown(self):
        self.runs(days=3)
        m = self.by_n()[1]
        self.assertEqual((m["goal"], m["label"]), ("unknown", "unknown: " + uptime_audit.FEW_KNOWN_REASON))

    def test_delivery_every_day_within_cap_with_briefs_is_met(self):
        self.pushes()
        m = self.by_n()[2]
        self.assertEqual(m["goal"], "met")
        for words in (delivery_audit.WITHIN_ALL, delivery_audit.BRIEF_ALL, delivery_audit.ACTION_ALL):
            self.assertIn(words, m["label"])

    def test_delivery_over_the_cap_is_not_met(self):
        self.pushes(per_day=1)
        self.cfg["push_cap"] = 1      # the brief plus one push is two deliveries a day
        m = self.by_n()[2]
        self.assertEqual(m["goal"], "not met")
        self.assertIn(delivery_audit.OVER, m["label"])

    def test_delivery_brief_missed_or_no_reply_line_is_not_met(self):
        self.pushes(briefs=False)
        self.assertEqual(self.by_n()[2]["goal"], "not met")
        self.pushes(body="Just a note\nnothing to answer")
        self.assertEqual(self.by_n()[2]["goal"], "not met")

    def test_delivery_without_wake_days_is_unknown_never_met(self):
        self.pushes()
        (self.st / "events.jsonl").unlink()
        self.assertEqual(self.by_n()[2]["goal"], "unknown")

    def test_labels_have_no_digit(self):
        for setup in (lambda: None, lambda: self.runs(stale_days=3), lambda: self.pushes(per_day=2)):
            setup()
            for m in self.measured():
                self.assertIsNone(DIGIT.search(m["label"]), m)
                self.assertIsNone(DIGIT.search(m["criterion_words"]), m)

    def test_measured_reads_only(self):
        self.runs()
        self.pushes()
        before = sorted((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in self.st.iterdir())
        self.measured()
        self.assertEqual(sorted((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in self.st.iterdir()),
                         before)


class Block(Fixture):
    def block(self, md, measured=None):
        rows = sc.parse(md)
        m = self.measured() if measured is None else measured
        return sc.weekly_block(sc.summary(rows), sc.measured_lines(rows, m))

    def test_measured_lines_follow_the_summary_and_keep_the_cap(self):
        self.runs()
        lines = self.block(table()).splitlines()
        self.assertEqual(lines[0], sc.WEEKLY_TITLE)
        self.assertEqual(len(lines), 1 + sc.MAX_LINES)
        self.assertEqual(lines[1:4], ["- 2 green, 1 amber, 1 red of 4", "- not all green yet", "- Review held: red"])
        self.assertEqual(lines[4], "- Measured: loop uptime: " + self.by_n()[1]["label"])
        self.assertEqual(lines[5], "- Measured: delivery: " + delivery_audit.NO_LOG)

    def test_measured_lines_replace_the_lowest_priority_summary_lines(self):
        summary = sc.summary(sc.parse(table()))
        self.assertEqual(len(summary), 4)
        block = sc.weekly_block(summary, sc.measured_lines(sc.parse(table()), self.measured()))
        self.assertNotIn("Capture triage", block)     # the fourth summary line gave way
        self.assertIn("Review held: red", block)

    def test_missing_logs_read_unknown_in_words(self):
        block = self.block(table())
        self.assertIn("- Measured: loop uptime: unknown: " + uptime_audit.NO_LOG_REASON, block)
        self.assertIn("- Measured: delivery: unknown: no push log set", block)

    def test_measured_words_keep_met_and_not_met(self):
        self.runs(stale_days=7)
        self.pushes()
        block = self.block(table(uptime="amber", delivery="amber"))
        self.assertIn("uptime goal not met", block)
        self.assertNotIn("says green", block)

    def test_green_hand_status_with_a_not_met_measurement_adds_one_note(self):
        self.runs(stale_days=7)
        block = self.block(table(uptime="green"))
        note = "- Row Loop uptime says green but the measurement says not met."
        self.assertEqual(block.splitlines().count(note), 1)
        self.assertEqual(block.count("says green"), 1)
        self.assertEqual(block.splitlines()[-2:], [note, "- Measured: delivery: " + delivery_audit.NO_LOG])

    def test_both_rows_green_and_not_met_give_one_note_each(self):
        self.runs(stale_days=7)
        self.pushes(briefs=False)
        lines = self.block(table()).splitlines()
        self.assertEqual(len(lines), 1 + sc.MAX_LINES)
        self.assertEqual(sum("says green but the measurement says not met." in ln for ln in lines), 2)
        self.assertIn("- Row Delivery says green but the measurement says not met.", lines)
        self.assertEqual(lines[1], "- 2 green, 1 amber, 1 red of 4")

    def test_no_note_when_unknown_or_met_or_not_green(self):
        self.assertNotIn("says green", self.block(table()))                       # unknown
        self.runs()
        self.pushes()
        self.assertNotIn("says green", self.block(table()))                       # met
        self.runs(stale_days=7)
        self.assertNotIn("says green", self.block(table(uptime="red")))           # not met, hand red

    def test_no_digit_in_any_added_line(self):
        for setup in (lambda: None, lambda: self.runs(stale_days=7), lambda: self.pushes(briefs=False)):
            setup()
            rows = sc.parse(table())
            for ln in sc.measured_lines(rows, self.measured()):
                self.assertIsNone(DIGIT.search(ln), ln)

    def test_a_criterion_name_with_digits_is_masked_in_the_note(self):
        md = HEADER + "| 1 | Loop uptime 95 (of 28 days) | green | synthetic | 1 |\n"
        m = [{"n": 1, "criterion_words": "loop uptime", "label": "uptime goal not met", "goal": "not met"}]
        lines = sc.measured_lines(sc.parse(md), m)
        self.assertEqual(lines[1], "Row Loop uptime # says green but the measurement says not met.")

    def test_statuses_are_never_changed(self):
        self.runs(stale_days=7)
        rows = sc.parse(table())
        before = [dict(r) for r in rows]
        sc.measured_lines(rows, self.measured())
        self.assertEqual(rows, before)
        self.runs()
        self.pushes()
        rows = sc.parse(table(uptime="red", delivery="amber"))
        self.assertIn("- Loop uptime: red", sc.weekly_block(sc.summary(rows), sc.measured_lines(rows, self.measured())))

    def test_without_measured_lines_the_block_is_unchanged(self):
        summary = sc.summary(sc.parse(table()))
        self.assertEqual(sc.weekly_block(summary), sc.weekly_block(summary, []))
        self.assertEqual(sc.weekly_block([], []), "")

    def test_measured_lines_alone_still_make_a_block(self):
        block = sc.weekly_block([], sc.measured_lines([], self.measured()))
        self.assertEqual(block.splitlines()[0], sc.WEEKLY_TITLE)
        self.assertEqual(len(block.splitlines()), 3)


class ToolField(Fixture):
    def card(self, md):
        p = self.root / "scorecard.md"
        p.write_text(md)
        return p

    def tool(self, md=None, raw=False, path=None):
        p = self.card(md if md is not None else table()) if path is None else path
        return tools.scorecard(p, NOW, state_dir=self.st, cfg=self.cfg, tz=UTC, raw=raw, env=self.env,
                               home=self.root)

    def test_measured_field_carries_t1_labels_and_goals(self):
        self.runs(stale_days=7)
        out = self.tool()
        self.assertEqual([m["n"] for m in out["measured"]], [1, 2, 3])
        want = {m["n"]: m for m in self.measured()}
        for m in out["measured"]:
            self.assertEqual(m["label"], {"label": want[m["n"]]["label"], "tier": "T1", "modality": "measured"})
            self.assertEqual(m["goal"], want[m["n"]]["goal"])
            self.assertEqual(m["criterion_words"], want[m["n"]]["criterion_words"])
            self.assertNotIn("counts", m)

    def test_envelope_shape_and_value_are_unchanged(self):
        out = self.tool()
        self.assertTrue(FIELDS <= set(out))
        self.assertEqual(out["modality"], "self_report")
        self.assertEqual(out["value"], sc.summary(sc.parse(table())))

    def test_disagreement_note_on_the_row(self):
        self.runs(stale_days=7)
        m = {x["n"]: x for x in self.tool()["measured"]}
        self.assertEqual(m[1]["note"], "Row Loop uptime says green but the measurement says not met.")
        self.assertNotIn("note", m[2])
        self.assertNotIn("note", self.tool(table(uptime="amber"))["measured"][0])

    def test_no_digit_outside_the_raw_opt_in(self):
        self.runs(stale_days=3)
        self.pushes(per_day=2)
        got = self.tool()["measured"]
        self.assertTrue(all(set(m) <= {"n", "criterion_words", "label", "goal", "note"} for m in got))
        text = json.dumps([[m["label"]["label"], m["criterion_words"], m["goal"], m.get("note", "")] for m in got])
        self.assertIsNone(DIGIT.search(text), text)

    def test_counts_only_with_the_raw_opt_in(self):
        self.runs(stale_days=3)
        self.pushes()
        m = {x["n"]: x for x in self.tool(raw=True)["measured"]}
        self.assertEqual(set(m[1]["counts"]), set(tools.UPTIME_RAW_KEYS))
        self.assertEqual(m[1]["counts"]["window_days"], 28)
        self.assertEqual(set(m[2]["counts"]), set(tools.DELIVERY_RAW_KEYS))
        self.assertEqual(m[2]["counts"]["known_days"], 7)

    def test_raw_with_no_log_has_no_counts(self):
        for m in self.tool(raw=True)["measured"]:
            self.assertNotIn("counts", m)
            self.assertEqual(m["goal"], "unknown")

    def test_missing_scorecard_still_measures(self):
        self.runs()
        out = self.tool(path=self.root / "absent.md")
        self.assertIsNone(out["value"])
        self.assertEqual(out["evidence_tier"], "none")
        self.assertEqual(out["measured"][0]["goal"], "met")
        self.assertNotIn("note", out["measured"][0])

    def test_passes_tier_audit(self):
        self.runs(stale_days=7)
        self.pushes(briefs=False)
        out = self.tool()
        words = tier_audit.labels(out)
        self.assertEqual(words, [m["label"]["label"] for m in out["measured"]])
        audit = self.root / "audit.jsonl"
        got = tier_audit.audit_result("tool:limitless_scorecard", out, False, env={"LIMITLESS_AUDIT": str(audit)},
                                      home=self.root, now=NOW)
        self.assertEqual(got, out)
        (line,) = [json.loads(ln) for ln in audit.read_text().splitlines()]
        self.assertEqual((line["tier"], line["blocked"], line["digits"]), ("T1", False, 0))


if __name__ == "__main__":
    unittest.main()
