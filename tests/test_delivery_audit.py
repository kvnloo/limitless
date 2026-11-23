"""delivery_audit: a read-only audit of kevin-push's own log (log.jsonl), pure over parsed rows.

Rows are in the shape bin/kevin-push writes, one per decision: {"at", "tag", "cls", "title", "body", "how"};
"how" is "telegram" only on a real delivery. Synthetic rows, a fixed clock, UTC. Nothing is written or sent.
"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import delivery_audit as da, jobs, jobs_runner, send_gate  # noqa: E402

UTC = timezone.utc
NOW = 2_000_000_000.0
TODAY = datetime.fromtimestamp(NOW, UTC).date()
WHY = "Why now: you are awake and this fits any moment"
HOW = {"log": "log", "fold": "folded (brief line)", "hold": "held (sleep mode)", "duplicate": "log (duplicate)",
       "cap": "log (daily cap)", "drop": "log (dropped)"}


def row(days_ago=0, how="telegram", title="Pick one", body=None, tag="x", cls="decision", hour=9):
    """One log.jsonl row as bin/kevin-push writes it: at (whole epoch seconds), tag, cls, title, body, how."""
    at = int(datetime(TODAY.year, TODAY.month, TODAY.day, hour, tzinfo=UTC).timestamp()) - days_ago * 86400
    if body is None:
        body = f"Keep the loop?\nReply: Yes / No\n{WHY}" if how == "telegram" else "Keep the loop?\nReply: Yes / No"
    return {"at": at, "tag": tag, "cls": cls, "title": title, "body": body, "how": how}


def brief(days_ago=0, how="telegram"):
    return row(days_ago, how, title=jobs.WAKE_BRIEF.send_title, tag="limitless",
               body=f"Good morning.\nSleep: unknown\nWhy now: you woke up", hour=7)


def run(rows, **kw):
    kw.setdefault("today", TODAY)
    kw.setdefault("tz", UTC)
    return da.audit(rows, **kw)


def day(out, days_ago):
    iso = (TODAY - timedelta(days=days_ago)).isoformat()
    return next(d for d in out["days"] if d["day"] == iso)


class Deliveries(unittest.TestCase):
    def test_counts_real_telegram_deliveries_per_day(self):
        out = run([row(0), row(0), row(1)])
        self.assertEqual(len(out["days"]), 7)
        self.assertEqual([d["day"] for d in out["days"]][-1], TODAY.isoformat())
        self.assertEqual(day(out, 0)["delivered"], 2)
        self.assertEqual(day(out, 1)["delivered"], 1)
        self.assertEqual(out["delivered"], 3)

    def test_held_folded_dropped_and_logged_rows_never_count_as_delivered(self):
        rows = [row(0, how=h) for h in list(HOW.values()) + ["log (telegram rc=1)",
                                                            f"log ({send_gate.ONCE_DROP})", "log (quiet: on)"]]
        out = run(rows)
        self.assertEqual(day(out, 0)["delivered"], 0)
        self.assertEqual(day(out, 0)["rows"], len(rows))
        self.assertEqual(out["delivered"], 0)

    def test_a_day_with_no_rows_is_unknown_not_zero(self):
        out = run([row(0, how="log")])
        self.assertEqual(day(out, 0)["delivered"], 0)
        for n in range(1, 7):
            self.assertIsNone(day(out, n)["delivered"], n)
            self.assertIsNone(day(out, n)["over_cap"], n)
        self.assertEqual(out["known_days"], 1)

    def test_rows_outside_the_window_are_not_counted(self):
        out = run([row(7), row(30), row(-1)])
        self.assertEqual(out["delivered"], 0)
        self.assertEqual(out["known_days"], 0)

    def test_days_is_the_window_length(self):
        self.assertEqual(len(run([row(0)], days=3)["days"]), 3)

    def test_without_today_the_newest_row_dates_the_window(self):
        out = da.audit([row(2), row(3)], tz=UTC)
        self.assertEqual(out["days"][-1]["day"], (TODAY - timedelta(days=2)).isoformat())

    def test_no_rows_at_all_is_unknown_everywhere(self):
        out = da.audit([], tz=UTC)
        self.assertEqual(out["days"], [])
        self.assertEqual(out["known_days"], 0)
        self.assertTrue(out["label"]["label"].startswith("unknown"))


class Parsing(unittest.TestCase):
    def test_corrupt_and_partial_lines_are_skipped_and_counted(self):
        good = json.dumps(row(0))
        text = "\n".join([good, "{not json", "[1, 2]", json.dumps({"at": "soon", "how": "telegram"}),
                          json.dumps({"tag": "x", "how": "telegram"}), json.dumps({"at": row(0)["at"]}),
                          json.dumps(dict(row(0), at=True)), "", good[: len(good) // 2], good]) + "\n"
        rows, skipped = da.parse_lines(text)
        self.assertEqual(len(rows), 2)
        self.assertEqual(skipped, 7)

    def test_audit_skips_and_counts_bad_rows_it_is_given(self):
        out = run([row(0), "nope", {"at": None, "how": "telegram"}, {"at": row(0)["at"], "how": 3}], skipped=2)
        self.assertEqual(out["delivered"], 1)
        self.assertEqual(out["skipped"], 5)

    def test_read_log_returns_none_for_a_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(da.read_log(Path(d) / "absent.jsonl"))
            p = Path(d) / "log.jsonl"
            p.write_text(json.dumps(row(0)) + "\nbroken\n")
            self.assertEqual(da.read_log(p), ([row(0)], 1))


if __name__ == "__main__":
    unittest.main()
