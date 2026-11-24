"""delivery_audit's complaints: north-star row two's "0 complaints", from explicit signals only.

A complaint is a quiet, quiet tonight or snooze (off) command recorded inside the audit window (quiet.json as
the quiet ingest wrote it, or the same whole-message command in the Hermes session DB), or a reply whose first
words are "stop" or "too much" sent within delivery_audit.REPLY_GAP_S after a delivered push. Nothing else is
read into it. No reply source set is unknown, never "no complaints". Synthetic rows, a synthetic quiet state
and the synthetic session DB fixture only; a fixed clock, UTC. Nothing is written or sent.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from limitless import delivery_audit as da, jobs, quiet  # noqa: E402
from hermes_db_fixture import make_db  # noqa: E402

UTC = timezone.utc
NOW = 2_000_000_000.0
TODAY = datetime.fromtimestamp(NOW, UTC).date()
MIN = 60


def at(days_ago=0, hour=9):
    return int(datetime(TODAY.year, TODAY.month, TODAY.day, hour, tzinfo=UTC).timestamp()) - days_ago * 86400


def push(t, how="telegram", title="Pick one", body="Keep the loop?\nReply: Yes / No"):
    return {"at": int(t), "tag": "x", "cls": "decision", "title": title, "body": body, "how": how}


def week():
    """A full synthetic week that meets every other check: a brief and one push a day, every wake day known."""
    rows = []
    for n in range(7):
        rows.append(push(at(n, 7), title=jobs.WAKE_BRIEF.send_title, body="Morning\nReply: ok"))
        rows.append(push(at(n, 9)))
    return rows


WAKES = [TODAY - timedelta(days=n) for n in range(7)]


def signals(replies=(), state=None):
    return {"replies": list(replies), "quiet": state, "why": None}


def snooze(t, mode=quiet.SNOOZED):
    return {"mode": mode, "since": quiet.iso(t)}


def run(rows=None, **kw):
    kw.setdefault("today", TODAY)
    kw.setdefault("tz", UTC)
    kw.setdefault("wake_days", WAKES)
    return da.audit(week() if rows is None else rows, **kw)


class Unknown(unittest.TestCase):
    def test_no_reply_source_is_unknown_never_no_complaints(self):
        out = run()
        c = out["complaints"]
        self.assertFalse(c["known"])
        self.assertIsNone(c["total"])
        self.assertEqual(c["why"], da.NO_DB_COMPLAINTS)
        self.assertEqual(out["labels"]["complaints"], "complaints: unknown, " + da.NO_DB_COMPLAINTS)
        self.assertNotIn(da.COMPLAINTS_NONE, out["label"]["label"])

    def test_an_unreadable_source_is_unknown_with_its_reason(self):
        out = run(signals={"replies": None, "quiet": None, "why": da.DB_UNREADABLE})
        self.assertFalse(out["complaints"]["known"])
        self.assertEqual(out["labels"]["complaints"], "complaints: unknown, " + da.DB_UNREADABLE)

    def test_goal_never_met_while_complaints_are_unknown(self):
        self.assertEqual(da.goal(run()), da.GOAL_UNKNOWN)
        self.assertEqual(da.goal(run(signals={"replies": None, "quiet": None, "why": da.DB_UNREADABLE})),
                         da.GOAL_UNKNOWN)

    def test_a_week_with_no_rows_is_never_no_complaints(self):
        out = da.audit([], signals=signals(), tz=UTC)
        self.assertFalse(out["complaints"]["known"])
        self.assertEqual(da.goal(out), da.GOAL_UNKNOWN)


class Quiet(unittest.TestCase):
    def test_none_is_no_complaints_and_the_goal_is_met(self):
        out = run(signals=signals())
        self.assertEqual(out["complaints"], {"known": True, "quiet": 0, "stop": 0, "total": 0, "why": None})
        self.assertEqual(out["labels"]["complaints"], da.COMPLAINTS_NONE)
        self.assertIn("no complaints this week", out["label"]["label"])
        self.assertEqual(da.goal(out), da.GOAL_MET)

    def test_a_snooze_inside_the_window_counts(self):
        out = run(signals=signals(state=snooze(at(2, 10))))
        self.assertEqual((out["complaints"]["quiet"], out["complaints"]["total"]), (1, 1))
        self.assertEqual(out["labels"]["complaints"], "some pushes drew a quiet or stop request")
        self.assertEqual(da.goal(out), da.GOAL_NOT_MET)

    def test_quiet_and_quiet_tonight_count_too(self):
        for mode in (quiet.OFF, quiet.TONIGHT):
            self.assertEqual(run(signals=signals(state=snooze(at(0, 10), mode)))["complaints"]["quiet"], 1, mode)

    def test_a_snooze_outside_the_window_does_not_count(self):
        for t in (at(7, 10), at(30, 10), at(-1, 10)):
            out = run(signals=signals(state=snooze(t)))
            self.assertEqual(out["complaints"]["total"], 0, t)
            self.assertEqual(da.goal(out), da.GOAL_MET)

    def test_on_and_a_broken_state_are_not_a_request(self):
        for state in ({"mode": quiet.ON, "since": quiet.iso(at(1))}, {"mode": quiet.SNOOZED},
                      {"mode": quiet.OFF, "since": "soon"}, {"mode": "loud", "since": quiet.iso(at(1))}):
            self.assertEqual(run(signals=signals(state=state))["complaints"]["quiet"], 0, state)

    def test_a_quiet_command_reply_in_the_window_counts_once_with_its_recorded_state(self):
        t = at(1, 10)
        out = run(signals=signals([(t + 0.4, "Snooze"), (at(3, 12), "quiet tonight.")], state=snooze(t)))
        self.assertEqual(out["complaints"]["quiet"], 2)

    def test_a_quiet_command_must_be_the_whole_message(self):
        out = run(signals=signals([(at(1, 10), "snooze 2h"), (at(1, 11), "on"), (at(1, 12), "keep it quiet")]))
        self.assertEqual(out["complaints"]["total"], 0)


class Stop(unittest.TestCase):
    def test_stop_or_too_much_right_after_a_delivered_push_counts(self):
        for text in ("stop", "Stop.", "STOP!", "too much", "Too much today", "stop sending these"):
            out = run(signals=signals([(at(0, 9) + 5 * MIN, text)]))
            self.assertEqual(out["complaints"]["stop"], 1, text)
            self.assertEqual(da.goal(out), da.GOAL_NOT_MET, text)

    def test_a_stop_long_after_a_push_does_not_count(self):
        out = run(signals=signals([(at(0, 9) + da.REPLY_GAP_S + 1, "stop")]))
        self.assertEqual(out["complaints"]["total"], 0)
        self.assertEqual(da.goal(out), da.GOAL_MET)

    def test_a_stop_before_any_push_does_not_count(self):
        out = run(signals=signals([(at(0, 9) - MIN, "stop")]))
        self.assertEqual(out["complaints"]["stop"], 0)

    def test_stop_inside_a_longer_sentence_does_not_count(self):
        t = at(0, 9) + MIN
        texts = ("please stop", "I can't stop thinking about it", "stopwatch", "not too much", "toomuch", "",
                 "this is too much", None, 7)
        out = run(signals=signals([(t, x) for x in texts]))
        self.assertEqual(out["complaints"]["total"], 0)

    def test_after_a_push_that_was_not_delivered_does_not_count(self):
        rows = week() + [push(at(0, 15), how="held (sleep mode)"), push(at(0, 16), how="log (daily cap)")]
        out = run(rows, signals=signals([(at(0, 15) + MIN, "stop"), (at(0, 16) + MIN, "too much")]))
        self.assertEqual(out["complaints"]["stop"], 0)

    def test_a_stop_outside_the_window_does_not_count(self):
        rows = week() + [push(at(9, 9))]
        out = run(rows, signals=signals([(at(9, 9) + MIN, "stop")]))
        self.assertEqual(out["complaints"]["stop"], 0)

    def test_each_stop_reply_counts(self):
        out = run(signals=signals([(at(0, 9) + MIN, "stop"), (at(1, 9) + MIN, "too much"), ("soon", "stop")]))
        self.assertEqual(out["complaints"]["stop"], 2)

    def test_stop_request_rule(self):
        self.assertTrue(da.stop_request("  Stop  "))
        self.assertTrue(da.stop_request("too   much!!"))
        self.assertFalse(da.stop_request("unstoppable"))
        self.assertFalse(da.stop_request("too"))


class Words(unittest.TestCase):
    def test_message_text_is_never_stored_and_labels_have_no_digit(self):
        marker = "synthetic marker words"
        cases = [None, signals(), signals([(at(0, 9) + MIN, "stop " + marker), (at(0, 9) + MIN, marker)]),
                 signals(state=snooze(at(0))), {"replies": None, "quiet": None, "why": da.DB_UNREADABLE}]
        for sig in cases:
            out = run(signals=sig)
            self.assertNotIn(marker, json.dumps(out))
            for w in (out["label"]["label"], *out["labels"].values()):
                self.assertFalse(any(ch.isdigit() for ch in w), w)

    def test_the_other_checks_still_decide_first(self):
        rows = week() + [push(at(0, 10 + k)) for k in range(da.push_cap({}) + 1)]
        self.assertEqual(da.goal(run(rows)), da.GOAL_NOT_MET)


class Sources(unittest.TestCase):
    """da.signals reads the Hermes session DB (config hermes_db) and quiet.json, read-only."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()

    def files(self):
        return sorted((str(p), p.stat().st_mtime_ns, p.read_bytes()) for p in self.root.rglob("*") if p.is_file())

    def test_no_hermes_db_set_is_unknown(self):
        got = da.signals(self.st, {}, NOW, env={})
        self.assertEqual((got["replies"], got["why"]), (None, da.NO_DB_COMPLAINTS))

    def test_a_missing_or_broken_db_is_unknown(self):
        self.assertEqual(da.signals(self.st, {"hermes_db": "absent.db"}, NOW, env={})["why"], da.DB_UNREADABLE)
        (self.st / "broken.db").write_text("not a database")
        self.assertEqual(da.signals(self.st, {"hermes_db": "broken.db"}, NOW, env={})["why"], da.DB_UNREADABLE)

    def test_the_db_and_the_quiet_state_are_read(self):
        make_db(self.st / "state.db", [("user", "stop", at(0, 9) + MIN), ("assistant", "stop", at(0, 9) + MIN),
                                       ("user", "old", NOW - 30 * 86400)], started=NOW - 40 * 86400)
        quiet.write(self.st, quiet.SNOOZED, at(1, 10))
        before = self.files()
        got = da.signals(self.st, {"hermes_db": "state.db"}, NOW, env={})
        self.assertEqual(got["why"], None)
        self.assertEqual(got["replies"], [(float(at(0, 9) + MIN), "stop")])
        self.assertEqual(got["quiet"]["mode"], quiet.SNOOZED)
        self.assertEqual(self.files(), before)
        out = run(signals=got)
        self.assertEqual((out["complaints"]["quiet"], out["complaints"]["stop"]), (1, 1))

    def test_the_env_db_wins_and_other_sources_are_not_read(self):
        make_db(self.root / "env.db", [("user", "stop", at(0, 9) + MIN)], started=NOW - 86400, source="discord")
        got = da.signals(self.st, {}, NOW, env={"LIMITLESS_HERMES_DB": str(self.root / "env.db")})
        self.assertEqual(got["replies"], [])

    def test_no_quiet_file_is_known_none_but_a_broken_one_is_unknown(self):
        make_db(self.st / "state.db", [], started=NOW - 86400)
        got = da.signals(self.st, {"hermes_db": "state.db"}, NOW, env={})
        self.assertEqual((got["quiet"], got["why"]), (None, None))
        (self.st / quiet.QUIET_FILE).write_text("{broken")
        got = da.signals(self.st, {"hermes_db": "state.db"}, NOW, env={})
        self.assertEqual(got["why"], da.QUIET_UNREADABLE)
        self.assertFalse(run(signals=got)["complaints"]["known"])


if __name__ == "__main__":
    unittest.main()
