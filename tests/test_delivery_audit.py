"""delivery_audit: a read-only audit of kevin-push's own log (log.jsonl), pure over parsed rows.

Rows are in the shape bin/kevin-push writes, one per decision: {"at", "tag", "cls", "title", "body", "how"};
"how" is "telegram" only on a real delivery. Synthetic rows, a fixed clock, UTC. Nothing is written or sent.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
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
        out = run([row(0), "nope", {"at": None, "how": "telegram"}, {"at": row(0)["at"], "how": 3},
                   {"at": 1e30, "how": "telegram"}, {"at": float("nan"), "how": "telegram"}], skipped=2)
        self.assertEqual(out["delivered"], 1)
        self.assertEqual(out["skipped"], 7)

    def test_read_log_returns_none_for_a_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(da.read_log(Path(d) / "absent.jsonl"))
            p = Path(d) / "log.jsonl"
            p.write_text(json.dumps(row(0)) + "\nbroken\n")
            self.assertEqual(da.read_log(p), ([row(0)], 1))


class Cap(unittest.TestCase):
    def test_default_cap_is_the_send_gates_own(self):
        self.assertEqual(da.push_cap({}), send_gate.DAILY_CAP)
        self.assertEqual(run([row(0)])["cap"], send_gate.DAILY_CAP)

    def test_config_push_cap_is_read_and_bad_values_fall_back(self):
        self.assertEqual(da.push_cap({"push_cap": 3}), 3)
        for bad in (0, -1, True, "4", 2.5, None, [3]):
            self.assertEqual(da.push_cap({"push_cap": bad}), send_gate.DAILY_CAP, bad)
        self.assertEqual(da.push_cap(None), send_gate.DAILY_CAP)

    def test_days_over_the_cap(self):
        cap = send_gate.DAILY_CAP
        out = run([row(0)] * (cap + 1) + [row(1)] * cap + [row(2, how="log")] * (cap + 3))
        self.assertTrue(day(out, 0)["over_cap"])
        self.assertFalse(day(out, 1)["over_cap"])
        self.assertFalse(day(out, 2)["over_cap"])
        self.assertEqual(out["over_cap_days"], [TODAY.isoformat()])
        self.assertEqual(out["labels"]["push"], "over the push limit on some days")

    def test_a_lower_configured_cap_is_used(self):
        out = run([row(0)] * 3, cap=2)
        self.assertEqual(out["over_cap_days"], [TODAY.isoformat()])

    def test_within_the_limit_every_day(self):
        out = run([row(n) for n in range(7)])
        self.assertEqual(out["over_cap_days"], [])
        self.assertEqual(out["labels"]["push"], "within the push limit every day this week")

    def test_within_the_limit_on_the_logged_days_only(self):
        self.assertEqual(run([row(0)])["labels"]["push"], "within the push limit on every logged day")


class WakeBrief(unittest.TestCase):
    def wake(self, *ago):
        return [TODAY - timedelta(days=n) for n in ago]

    def test_brief_delivered_on_every_wake_day(self):
        out = run([brief(0), brief(1)], wake_days=self.wake(0, 1))
        self.assertEqual((out["wake"]["wake_days"], out["wake"]["brief_delivered"]), (2, 2))
        self.assertTrue(day(out, 0)["brief"])
        self.assertEqual(out["labels"]["brief"], "brief reached you on every wake day")

    def test_a_held_or_failed_brief_is_not_delivered(self):
        out = run([brief(0), brief(1, how="held (sleep mode)"), brief(2, how="log (telegram rc=1)"), brief(3)],
                  wake_days=self.wake(0, 1, 2, 3))
        self.assertEqual(out["wake"]["brief_delivered"], 2)
        self.assertFalse(day(out, 1)["brief"])
        self.assertEqual(out["labels"]["brief"], "brief reached you on some wake days")

    def test_most_wake_days(self):
        out = run([brief(0), brief(1), row(2)], wake_days=self.wake(0, 1, 2))
        self.assertEqual(out["labels"]["brief"], "brief reached you on most wake days")
        self.assertAlmostEqual(out["wake"]["brief_share"], 2 / 3)

    def test_no_brief_on_any_wake_day(self):
        out = run([row(0)], wake_days=self.wake(0))
        self.assertEqual(out["labels"]["brief"], "brief did not reach you on any wake day")

    def test_a_wake_day_with_no_log_rows_is_unknown(self):
        out = run([brief(0)], wake_days=self.wake(0, 1))
        self.assertIsNone(day(out, 1)["brief"])
        self.assertEqual((out["wake"]["wake_days"], out["wake"]["unknown_wake_days"]), (1, 1))
        self.assertEqual(out["labels"]["brief"], "brief reached you on every wake day")

    def test_no_wake_days_known_is_unknown(self):
        for wd in (None, [], self.wake(30)):
            out = run([brief(0)], wake_days=wd)
            self.assertEqual(out["labels"]["brief"], "brief: unknown, no wake days known", wd)
            self.assertIsNone(out["wake"]["brief_share"])
        self.assertIsNone(day(run([brief(0)]), 0)["wake_day"])

    def test_wake_days_may_be_iso_strings_and_bad_ones_are_ignored(self):
        out = run([brief(0)], wake_days=[TODAY.isoformat(), "someday", 7, None])
        self.assertEqual(out["wake"]["wake_days"], 1)

    def test_a_brief_on_a_day_that_was_no_wake_day_does_not_count(self):
        out = run([brief(0), row(1)], wake_days=self.wake(1))
        self.assertEqual(out["wake"]["brief_delivered"], 0)


class ActionLine(unittest.TestCase):
    def test_a_delivery_without_a_reply_line_is_counted(self):
        out = run([row(0), row(0, body=f"Decision: keep the loop\n{WHY}"), brief(0)])
        self.assertEqual(out["no_action"], 2)
        self.assertEqual(day(out, 0)["no_action"], 2)
        self.assertEqual(out["labels"]["action"], "some pushes had no reply line")

    def test_message_shapes_reply_line_counts(self):
        bodies = ["Keep it?\nReply: Keep / Drop\n" + WHY, "Asks\nA1: one\nReply in any bot chat with the id\n" + WHY,
                  "Keep it?\nReply: Yes / No / Later"]
        out = run([row(0, body=b) for b in bodies])
        self.assertEqual(out["no_action"], 0)
        self.assertEqual(out["labels"]["action"], "every push had a reply line")

    def test_only_deliveries_are_judged(self):
        out = run([row(0, how="log", body="fyi"), row(0, how="held (sleep mode)", body="later")])
        self.assertEqual(out["no_action"], 0)
        self.assertEqual(out["labels"]["action"], "")

    def test_a_body_cut_by_the_log_is_unknown_not_missing(self):
        long = "Head\n" + "x " * 1200 + "\nReply: Yes / No"
        cut = long[:da.LOG_BODY_CHARS]
        out = run([row(0, body=cut), row(0, body=None)])
        self.assertEqual((out["no_action"], out["action_unknown"]), (0, 1))
        self.assertEqual(out["labels"]["action"], "every push with a known body had a reply line")


class Labels(unittest.TestCase):
    def test_the_label_joins_the_clauses_in_words(self):
        out = run([brief(0), row(0)], wake_days=[TODAY])
        self.assertEqual(out["label"]["label"], "within the push limit on every logged day; "
                                                "brief reached you on every wake day; some pushes had no reply line; "
                                                "complaints: unknown, " + da.NO_DB_COMPLAINTS)
        self.assertEqual(out["label"]["tier"], "T1")

    def test_digit_walk_over_every_label(self):
        cap = send_gate.DAILY_CAP
        cases = [[], [row(0)], [row(n) for n in range(7)], [row(0)] * (cap + 1), [brief(0), row(0, how="log")],
                 [row(0, body="x" * da.LOG_BODY_CHARS)], ["junk"]]
        seen = set()
        for rows in cases:
            for wd in (None, [TODAY], [TODAY - timedelta(days=n) for n in range(7)]):
                for d in (1, 7, 14):
                    out = run(rows, wake_days=wd, days=d)
                    words = [out["label"]["label"], *out.get("labels", {}).values()]
                    for w in words:
                        self.assertFalse(any(c.isdigit() for c in w), (w, rows, wd))
                        seen.add(w)
        seen.add(da.NO_LOG)
        self.assertFalse(any(c.isdigit() for w in seen for c in w))
        self.assertIn("unknown: no push log set", seen)

    def test_audit_is_pure(self):
        rows = [row(0), brief(1)]
        before = json.dumps(rows)
        with tempfile.TemporaryDirectory() as d:
            cwd = os.getcwd()
            os.chdir(d)
            try:
                run(rows, wake_days=[TODAY])
            finally:
                os.chdir(cwd)
            self.assertEqual(os.listdir(d), [])
        self.assertEqual(json.dumps(rows), before)


class RealShape(unittest.TestCase):
    """Rows written by bin/kevin-push itself (fake transport on PATH, temp HOME): nothing reaches a phone."""

    def test_rows_kevin_push_writes_are_audited(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            fakebin = home / "fakebin"
            fakebin.mkdir()
            hermes = fakebin / "hermes"
            hermes.write_text("#!/bin/sh\nexit 0\n")
            hermes.chmod(hermes.stat().st_mode | stat.S_IEXEC)
            env = dict(os.environ, HOME=str(home), PATH=f"{fakebin}:{os.environ['PATH']}",
                       LIMITLESS_SLEEPMODE=str(home / "none.jsonl"), LIMITLESS_STATE=str(home / "st"),
                       LIMITLESS_CONFIG=str(home / "none.json"))
            cli = ROOT / "bin" / "kevin-push"
            for tag, title, body, cls in [("x", "Pick one", "Keep the loop?\nReply: Yes / No", "decision"),
                                          ("x", "Note", "fyi", "report"),
                                          ("asks", "Asks waiting on you", "A1: one", "decision"),
                                          ("limitless", jobs.WAKE_BRIEF.send_title, "Good morning.", "report")]:
                r = subprocess.run([sys.executable, "-I", str(cli), tag, title, body], timeout=30,
                                   env=child_env(dict(env, CIRCADIAN_CLASS=cls)), capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)
            got = da.read_log(home / ".local/state/kevin-push/log.jsonl")
        rows, skipped = got
        self.assertEqual(skipped, 0)
        self.assertEqual(set(rows[0]), {"at", "tag", "cls", "title", "body", "how"})
        when = datetime.fromtimestamp(rows[0]["at"]).date()
        out = da.audit(rows, wake_days=[when], today=when)
        self.assertEqual(out["days"][-1]["delivered"], 2)
        self.assertEqual(out["wake"]["brief_delivered"], 1)
        self.assertEqual(out["no_action"], 1)       # the wake brief has no reply line


class Constants(unittest.TestCase):
    def test_delivered_is_the_word_jobs_runner_reads(self):
        self.assertEqual(da.DELIVERED, jobs_runner.DELIVERED)


if __name__ == "__main__":
    unittest.main()
