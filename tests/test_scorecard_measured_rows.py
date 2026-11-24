"""Scorecard measured rows five (foundation), six (flow), eight (integrated) and ten (top items).

scorecard.measured_audits reads them from what the plugin can already see: the sleep coverage audit, the weekly
flow numbers (flow_week), the local integrations (Glide's attention file, the call brief, the asks queue, the
voice MIQ) and an optional ranked ledger. Synthetic fixtures only (invented apps, synthetic sleep rows, synthetic
ActivityWatch rows, synthetic attention, brief, asks and ledger files). Fixed clock, UTC.
"""
import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import scorecard as sc, tier_audit, tools  # noqa: E402

UTC = timezone.utc
NOW = 2_000_000_000.0
TODAY = datetime.fromtimestamp(NOW, UTC).date()
DAY, H = 86400, 3600
DIGIT = re.compile(r"\d")
NS = 1_000_000_000

# The public ROADMAP wording of the four rows, and their definitions as the brief gives them.
ROW5 = "Foundation measured honestly"
ROW6 = "Flow reported weekly (deep-work minutes, feed leak)"
ROW8 = "Integrated (Glide, z0live voice brief, ayo windows, z0 registry)"
ROW10 = "Top-25 ranked items done-verified or dropped"
ROW5_DEF = ("reuse sleep_coverage's own goal: wearable sleep on at least four fifths of nights, its own unknown "
            "rules; never re-implemented")
ROW6_DEF = ("met when the last finished week has a known deep-work amount and a known feed-leak word from flow_week "
            "(phone or desktop ActivityWatch, Glide blocks); not met when work apps are set and the week has data "
            "but either part is unknown; unknown when no work-app list is set or there is no activity data; the "
            "trend is never judged")
ROW8_DEF = ("one sub-check per local integration: Glide attention file readable, call brief written within the "
            "stale window, asks queue configured and readable, voice MIQ sessions configured; z0 registry not "
            "measured here and never live; met only when all four are live; not met when one is configured but "
            "missing or stale; unknown when none is configured")
ROW10_DEF = ("an optional ranked ledger (config ranked_ledger, env LIMITLESS_RANKED_LEDGER), JSONL rows id, status "
             "open built verified dropped, by, evidence; the newest row per id wins; verified counts only with "
             "evidence, dropped only by the owner; met when every id counts; unknown when no ledger is set, it is "
             "missing or has no rows; ids and evidence never in the label")

HEADER = "| # | Criterion | Status | Evidence (latest) | Weeks green |\n|---|---|---|---|---|\n"
NAMES = {1: "Loop uptime", 2: "Delivery", 3: "Habit loop", 4: "Evidence loop", 5: ROW5, 6: ROW6, 7: "Privacy",
         8: ROW8, 9: "Review held", 10: ROW10}
NOTE = "says green but the measurement says not met."
MORE = "More measured rows in limitless_scorecard."


def table(status=None):
    """A NORTH-STAR-shaped synthetic table of ten rows, all green unless ``status`` says otherwise."""
    status = status or {}
    return HEADER + "".join(f"| {n} | {NAMES[n]} | {status.get(n, 'green')} | synthetic | 1 |\n" for n in NAMES)


def jsonl(path, rows):
    path.write_text("".join((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in rows))
    return path


SCHEMA = """
CREATE TABLE buckets(id INTEGER PRIMARY KEY, name TEXT UNIQUE, type TEXT, client TEXT, hostname TEXT,
                     created TEXT, data TEXT);
CREATE TABLE events(id INTEGER PRIMARY KEY, bucketrow INTEGER REFERENCES buckets(id), starttime INTEGER,
                    endtime INTEGER, data TEXT);
"""


def aw_db(path, spans):
    """A synthetic ActivityWatch DB: ``spans`` are (start_s, end_s, app) app-in-foreground spans."""
    con = sqlite3.connect(str(path))
    try:
        con.executescript(SCHEMA)
        con.execute("INSERT INTO buckets VALUES (1, 'w', 'currentwindow', 'test', 'test-host', '', '{}')")
        for start, end, app in spans:
            con.execute("INSERT INTO events(bucketrow, starttime, endtime, data) VALUES (1, ?, ?, ?)",
                        (int(start * NS), int(end * NS), json.dumps({"app": app, "package": "org.example." + app})))
        con.commit()
    finally:
        con.close()
    return path


def local(days_ago, hour):
    """Epoch seconds of ``hour`` (UTC) on the day ``days_ago`` before TODAY."""
    return datetime.combine(TODAY - timedelta(days=days_ago), time(0), tzinfo=UTC).timestamp() + hour * H


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.config_file = self.root / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.config_file)}
        self.cfg = {}
        self.save()

    def save(self):
        """The host config file holds what ``cfg`` holds (the tool reads one, the readers the other)."""
        self.config_file.write_text(json.dumps(self.cfg))

    def set(self, **kw):
        self.cfg.update(kw)
        self.save()

    def audits(self):
        return {row["n"]: (row, a) for row, a in sc.measured_audits(self.st, self.cfg, NOW, UTC, env=self.env,
                                                                     home=self.root)}

    def row(self, n):
        return self.audits()[n][0]

    def measured(self):
        return [row for row, _a in sc.measured_audits(self.st, self.cfg, NOW, UTC, env=self.env, home=self.root)]

    # --- row five: synthetic wearable sleep ---------------------------------------------------------------------
    def sleep(self, nights):
        """Synthetic wearable sleep rows on ``nights`` (nights ago, one to twenty-eight)."""
        rows = [{"night": (TODAY - timedelta(days=a)).isoformat(), "asleep_s": 7 * H, "source": "synthetic-band"}
                for a in nights]
        jsonl(self.st / "sleep.jsonl", rows)
        self.set(sleep_file="sleep.jsonl")


    def phone(self, nights):
        """Two synthetic unlocks around one quiet span from late evening on each of ``nights``."""
        rows = []
        for a in nights:
            s = local(a, 23)
            rows += [{"ts": int(s * 1000), "type": "KEYGUARD_HIDDEN", "pkg": "synthetic"},
                     {"ts": int((s + 8 * H) * 1000), "type": "KEYGUARD_HIDDEN", "pkg": "synthetic"}]
        jsonl(self.st / "screen-events.jsonl", rows)


class Foundation(Fixture):
    def test_row_five_is_the_foundation(self):
        m, _a = self.audits()[5]
        self.assertEqual(m["criterion_words"], "foundation")
        self.assertEqual(set(m), {"n", "criterion_words", "label", "goal"})

    def test_no_sleep_file_is_unknown_never_met(self):
        m, a = self.audits()[5]
        self.assertEqual(m["goal"], "unknown")
        self.assertTrue(m["label"].startswith("unknown: "), m)
        self.assertIsNone(a)

    def test_wearable_sleep_every_night_is_the_audits_own_met(self):
        self.sleep(range(1, 29))
        m, a = self.audits()[5]
        self.assertEqual(m["goal"], "met")
        self.assertEqual(m["label"], "wearable sleep on every night; wearable goal met")
        self.assertEqual(a["label"]["label"], m["label"])
        self.assertEqual(a["wearable_nights"], 28)

    def test_wearable_sleep_on_few_nights_is_not_met(self):
        self.sleep(range(1, 11))
        self.phone(range(1, 29))           # the phone estimate knows every night: the rest are not wearable
        m, _a = self.audits()[5]
        self.assertEqual(m["goal"], "not met")
        self.assertIn("wearable goal not met", m["label"])

    def test_the_goal_is_sleep_coverages_own(self):
        self.sleep(range(1, 24))         # twenty-three of twenty-eight: just under four fifths
        reader_goal = tools.sleep_coverage_audit(tools.StateReader(self.st), NOW, self.env, self.root, UTC)[0]["goal"]
        self.assertEqual(self.row(5)["goal"], reader_goal)
        self.set(sleep_coverage_target=0.5)
        self.assertEqual(self.row(5)["goal"], "met")

    def test_too_few_known_nights_is_unknown(self):
        self.sleep(range(1, 4))
        m, a = self.audits()[5]
        self.assertEqual(m["goal"], "unknown")
        self.assertTrue(m["label"].startswith("unknown: "), m)

    def test_a_broken_sleep_file_is_unknown_not_a_traceback(self):
        self.set(sleep_file="sleep.jsonl")
        (self.st / "sleep.jsonl").mkdir()
        m, _a = self.audits()[5]
        self.assertEqual(m["goal"], "unknown")
        (self.st / "sleep.jsonl").rmdir()
        (self.st / "sleep.jsonl").write_bytes(b"\xff\xfe{not json\n[1, 2]\n")
        self.assertEqual(self.row(5)["goal"], "unknown")

    def test_label_has_no_digit(self):
        for nights in ((), range(1, 4), range(1, 11), range(1, 29)):
            if nights:
                self.sleep(nights)
            self.assertIsNone(DIGIT.search(self.row(5)["label"]), self.row(5))


class Layout(Fixture):
    """The weekly block: the self-reported counts line first, then the measured rows, at most five bullets."""

    def block(self, md, measured=None):
        rows = sc.parse(md)
        m = self.measured() if measured is None else measured
        return sc.weekly_block(sc.summary(rows), sc.measured_lines(rows, m))

    def bullets(self, md, measured=None):
        return [ln[2:] for ln in self.block(md, measured).splitlines() if ln.startswith("- ")]

    def test_the_counts_line_is_always_the_first_bullet(self):
        for status in ({}, {1: "red"}, {n: "red" for n in NAMES}, {5: "amber", 6: "red", 8: "amber"}):
            rows = sc.parse(table(status))
            got = self.bullets(table(status))
            self.assertEqual(got[0], sc.summary(rows)[0])
            self.assertLessEqual(len(got), sc.MAX_LINES)

    def test_measured_rows_follow_in_row_order_and_fold_the_rest(self):
        got = self.bullets(table())
        measured = [ln for ln in got if ln.startswith("Measured: ")]
        words = [ln.split(":")[1].strip() for ln in measured]
        order = [m["criterion_words"] for m in self.measured()]
        self.assertEqual(words, order[:len(words)])
        self.assertEqual(len(got), sc.MAX_LINES)
        self.assertEqual(got[-1], MORE)

    def test_whole_rows_are_kept_with_their_note(self):
        rows = sc.parse(table())
        fake = [{"n": n, "criterion_words": f"row {w}", "label": "synthetic words", "goal": "not met"}
                for n, w in zip(sc.MEASURED_ROWS, "abcdefghij")]
        lines = sc.measured_lines(rows, fake)
        # four lines under the counts line: one whole row with its note, then the fold (never a row cut from
        # its note)
        self.assertEqual(lines, ["Measured: row a: synthetic words", "Row Loop uptime " + NOTE, MORE])
        block = self.bullets(table(), fake)
        self.assertEqual(block[0], sc.summary(rows)[0])
        self.assertEqual(block[-len(lines):], lines)
        self.assertLessEqual(len(block), sc.MAX_LINES)

    def test_few_measured_rows_leave_room_for_the_summary(self):
        rows = sc.parse(table({9: "red"}))
        one = [m for m in self.measured() if m["n"] == sc.UPTIME_ROW]
        got = self.bullets(table({9: "red"}), one)
        summary = sc.summary(rows)
        self.assertEqual(got[0], summary[0])
        self.assertEqual(got[-1], "Measured: loop uptime: " + one[0]["label"])
        self.assertEqual(got[1:-1], summary[1:sc.MAX_LINES - 1])

    def test_no_table_lets_the_measured_lines_make_the_block(self):
        got = self.bullets(HEADER)
        self.assertTrue(got)
        self.assertTrue(all(ln.startswith(("Measured: ", "Row ")) or ln == MORE for ln in got), got)
        self.assertLessEqual(len(got), sc.MAX_LINES)

    def test_no_digit_in_any_bullet_but_the_counts(self):
        for ln in self.bullets(table())[1:]:
            self.assertIsNone(DIGIT.search(ln), ln)


if __name__ == "__main__":
    unittest.main()
