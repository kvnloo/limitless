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
    """A synthetic ActivityWatch DB (a fresh file): ``spans`` are (start_s, end_s, app) app-in-foreground spans."""
    if path.exists():
        path.unlink()
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


class Flow(Fixture):
    WORK, FEED = "synthetic-editor", "synthetic-scroller"

    def activity(self, days_ago=3, db="aw.db"):
        """A synthetic AW DB: an hour of the work app then half an hour of the feed app ``days_ago`` days back."""
        aw_db(self.st / db, [(local(days_ago, 9), local(days_ago, 10), self.WORK),
                             (local(days_ago, 10), local(days_ago, 10.5), self.FEED)])
        self.set(aw_db=db)

    def glide(self, days_ago=3):
        """A synthetic Glide attention file whose focus block covers the AW rows' morning."""
        path = self.root / "attention.json"
        path.write_text(json.dumps({"block": {"start": local(days_ago, 8.5), "end": local(days_ago, 11),
                                              "minutes": 150}, "queue": [], "resume": None, "nudged": ""}))
        self.set(glide_attention=str(path))

    def full(self):
        self.activity()
        self.glide()
        self.set(flow_work_apps=[self.WORK], feed_apps=[self.FEED])

    def test_row_six_is_flow(self):
        m = self.row(6)
        self.assertEqual(m["criterion_words"], "flow")
        self.assertEqual(set(m), {"n", "criterion_words", "label", "goal"})

    def test_no_work_apps_set_is_unknown_even_with_data(self):
        self.activity()
        self.glide()
        self.set(feed_apps=[self.FEED])
        m, a = self.audits()[6]
        self.assertEqual((m["goal"], m["label"]), ("unknown", "unknown: no work apps set"))
        self.assertIsNone(a)

    def test_work_apps_from_env_config_or_apps_json_all_count(self):
        self.activity()
        self.env["LIMITLESS_FLOW_WORK_APPS"] = self.WORK
        self.assertNotEqual(self.row(6)["goal"], "unknown")
        del self.env["LIMITLESS_FLOW_WORK_APPS"]
        (self.st / "apps.json").write_text(json.dumps({"work_apps": [self.WORK]}))
        self.assertNotEqual(self.row(6)["goal"], "unknown")
        (self.st / "apps.json").unlink()
        self.set(flow_work_apps=self.WORK)
        self.assertNotEqual(self.row(6)["goal"], "unknown")

    def test_no_activity_data_is_unknown(self):
        self.set(flow_work_apps=[self.WORK])
        m, a = self.audits()[6]                       # no AW DB set at all
        self.assertEqual(m["goal"], "unknown")
        self.assertTrue(m["label"].startswith("unknown: "), m)
        self.activity(days_ago=20)                    # data, but none in the last finished week
        self.assertEqual(self.row(6)["goal"], "unknown")
        self.activity(days_ago=0)                     # today only: the running day is not a finished week
        self.assertEqual(self.row(6)["goal"], "unknown")

    def test_deep_work_and_feed_leak_known_is_met(self):
        self.full()
        m, a = self.audits()[6]
        self.assertEqual(m["goal"], "met")
        self.assertEqual(m["label"], "deep work and feed leak measured for the last finished week")
        self.assertEqual((a["deep_min"], a["feed_leak_min"], a["days_with_data"]), (60.0, 30.0, 1))
        self.assertEqual(a["label"]["label"], m["label"])

    def test_feed_leak_unknown_is_not_met_and_says_why(self):
        self.activity()
        self.set(flow_work_apps=[self.WORK], feed_apps=[self.FEED])
        m = self.row(6)                               # no Glide block: the leak has nothing to be inside
        self.assertEqual(m["goal"], "not met")
        self.assertEqual(m["label"], "deep work measured but feed leak unknown for the last finished week: "
                                     "no focus blocks")
        self.glide()
        self.set(feed_apps=[])
        m = self.row(6)
        self.assertEqual(m["goal"], "not met")
        self.assertTrue(m["label"].endswith("no feed apps set"), m)

    def test_a_broken_activity_db_is_unknown_not_a_traceback(self):
        self.set(flow_work_apps=[self.WORK], aw_db="aw.db")
        (self.st / "aw.db").write_bytes(b"not a database at all")
        self.assertEqual(self.row(6)["goal"], "unknown")
        self.full()
        (self.root / "attention.json").write_text("{\"block\": ")    # a torn Glide file: no block, no traceback
        self.assertEqual(self.row(6)["goal"], "not met")

    def test_the_trend_is_never_judged(self):
        self.full()
        self.set(aw_db="trend.db")
        aw_db(self.st / "trend.db", [(local(10, 9), local(10, 12), self.WORK), (local(3, 9), local(3, 9.25), self.WORK),
                                     (local(3, 10), local(3, 10.5), self.FEED)])   # far less than the week before
        m = self.row(6)
        self.assertEqual(m["goal"], "met")
        for word in ("up", "down", "same", "better", "worse", "score", "good", "bad", "less", "more"):
            self.assertNotIn(word, m["label"].split(), m)

    def test_label_has_no_digit(self):
        for setup in (lambda: None, self.activity, lambda: self.set(flow_work_apps=[self.WORK]), self.full):
            setup()
            self.assertIsNone(DIGIT.search(self.row(6)["label"]), self.row(6))


class Integrated(Fixture):
    def glide_file(self, text='{"block": null, "queue": [], "resume": null, "nudged": ""}'):
        path = self.root / "attention.json"
        path.write_text(text)
        self.set(glide_attention=str(path))
        return path

    def brief(self, age_s=600.0, name="call-brief.md"):
        """A synthetic call brief file (config call_brief_file, relative: in the state dir), ``age_s`` old."""
        path = self.st / name
        path.write_text("<!-- limitless call brief; generated: synthetic -->\nTLDR: peak window\n")
        os.utime(path, (NOW - age_s, NOW - age_s))
        self.set(call_brief_file=name)
        return path

    def asks(self, rows=({"id": "a", "title": "Pick one", "cls": "decision"},)):
        path = jsonl(self.root / "asks.jsonl", rows)
        self.set(asks_path=str(path))
        return path

    def voice(self, sessions=True):
        d = self.root / "sessions"
        if sessions:
            d.mkdir(exist_ok=True)
        self.set(voice_miq="dry_run", voice_miq_sessions=str(d))

    def all_live(self):
        self.glide_file()
        self.brief()
        self.asks()
        self.voice()

    def test_row_eight_is_integrated(self):
        m = self.row(8)
        self.assertEqual(m["criterion_words"], "integrated")
        self.assertEqual(set(m), {"n", "criterion_words", "label", "goal"})

    def test_nothing_set_up_is_unknown_never_met(self):
        m, a = self.audits()[8]
        self.assertEqual((m["goal"], m["label"]), ("unknown", "unknown: no local integration set up"))
        self.assertIsNone(a)

    def test_all_four_local_checks_live_is_met(self):
        self.all_live()
        m, a = self.audits()[8]
        self.assertEqual(m["goal"], "met")
        self.assertEqual(m["label"], "Glide, call brief, asks queue and voice MIQ all live")
        self.assertEqual({k: a[k] for k in ("glide", "call_brief", "asks", "voice_miq")},
                         {"glide": "live", "call_brief": "live", "asks": "live", "voice_miq": "live"})
        self.assertEqual((a["live"], a["set_up"], a["checks"]), (4, 4, 4))

    def test_the_z0_registry_is_never_measured_and_never_live(self):
        self.all_live()
        _m, a = self.audits()[8]
        self.assertEqual(a["z0_registry"], "z0 registry: not measured here")
        self.assertEqual(a["live"], 4)
        self.assertNotIn("registry", self.row(8)["label"])

    def test_a_stale_call_brief_is_not_met_and_named(self):
        self.all_live()
        self.brief(age_s=4 * H)
        m, a = self.audits()[8]
        self.assertEqual(m["goal"], "not met")
        self.assertEqual(m["label"], "not live: call brief stale")
        self.assertEqual(a["call_brief"], "stale")
        self.brief(age_s=-H)                          # a future mtime is not fresh either
        self.assertEqual(self.row(8)["label"], "not live: call brief stale")
        self.brief(age_s=2 * H)
        self.assertEqual(self.row(8)["goal"], "met")

    def test_missing_files_are_not_met_and_named_in_order(self):
        self.all_live()
        (self.root / "attention.json").unlink()
        (self.root / "asks.jsonl").unlink()
        (self.st / "call-brief.md").unlink()
        (self.root / "sessions").rmdir()
        m = self.row(8)
        self.assertEqual(m["goal"], "not met")
        self.assertEqual(m["label"], "not live: Glide missing, call brief missing, asks queue missing, voice MIQ "
                                     "missing")

    def test_one_live_and_the_rest_not_set_up_is_not_met(self):
        self.asks()
        m, a = self.audits()[8]
        self.assertEqual(m["goal"], "not met")
        self.assertEqual(m["label"], "not live: Glide not set up, call brief not set up, voice MIQ not set up")
        self.assertEqual((a["live"], a["set_up"]), (1, 1))

    def test_an_unreadable_attention_file_is_missing_not_a_traceback(self):
        self.all_live()
        self.glide_file("{torn")
        self.assertEqual(self.row(8)["label"], "not live: Glide missing")
        self.glide_file("[1, 2]")                     # not an object
        self.assertEqual(self.row(8)["label"], "not live: Glide missing")

    def test_an_empty_asks_queue_is_still_readable_and_a_dir_is_not(self):
        self.all_live()
        self.asks(rows=())
        self.assertEqual(self.row(8)["goal"], "met")
        d = self.root / "asks-dir"
        d.mkdir()
        self.set(asks_path=str(d))
        self.assertEqual(self.row(8)["label"], "not live: asks queue missing")

    def test_env_paths_win_over_config(self):
        self.all_live()
        self.env["LIMITLESS_GLIDE_ATTENTION"] = str(self.root / "absent.json")
        self.env["LIMITLESS_ASKS"] = str(self.root / "absent.jsonl")
        self.assertEqual(self.row(8)["label"], "not live: Glide missing, asks queue missing")

    def test_voice_miq_on_without_a_sessions_dir_is_missing(self):
        self.all_live()
        self.cfg.pop("voice_miq_sessions")
        self.save()
        self.assertEqual(self.row(8)["label"], "not live: voice MIQ missing")
        self.set(voice_miq="off")
        self.assertEqual(self.row(8)["label"], "not live: voice MIQ not set up")

    def test_label_has_no_digit(self):
        for setup in (lambda: None, self.asks, lambda: self.brief(age_s=5 * H), self.all_live):
            setup()
            self.assertIsNone(DIGIT.search(self.row(8)["label"]), self.row(8))


class TopItems(Fixture):
    def ledger(self, rows, name="ranked.jsonl"):
        path = jsonl(self.root / name, rows)
        self.set(ranked_ledger=str(path))
        return path

    @staticmethod
    def item(i, status, by="owner", evidence="a synthetic receipt"):
        return {"id": f"item-{i}", "status": status, "by": by, "evidence": evidence}

    def test_row_ten_is_top_items(self):
        m = self.row(10)
        self.assertEqual(m["criterion_words"], "top items")
        self.assertEqual(set(m), {"n", "criterion_words", "label", "goal"})

    def test_no_ledger_set_missing_or_empty_is_unknown(self):
        m, a = self.audits()[10]
        self.assertEqual((m["goal"], m["label"]), ("unknown", "unknown: no ranked ledger set"))
        self.assertIsNone(a)
        self.set(ranked_ledger=str(self.root / "absent.jsonl"))
        self.assertEqual(self.row(10)["label"], "unknown: the ranked ledger is missing or cannot be read")
        self.ledger([])
        self.assertEqual(self.row(10)["label"], "unknown: the ranked ledger has no rows")
        self.ledger(["{torn", "[1, 2]", {"id": "", "status": "verified"}, {"id": "x", "status": "shipped"}])
        self.assertEqual(self.row(10)["goal"], "unknown")

    def test_every_item_verified_with_evidence_or_dropped_by_the_owner_is_met(self):
        self.ledger([self.item(1, "verified"), self.item(2, "dropped", evidence=""), self.item(3, "verified")])
        m, a = self.audits()[10]
        self.assertEqual(m["goal"], "met")
        self.assertEqual(m["label"], "all of the ranked items verified or dropped by the owner")
        self.assertEqual({k: a[k] for k in sc.TOP_RAW_KEYS},
                         {"items": 3, "verified": 2, "owner_dropped": 1, "not_counted": 0, "open": 0})

    def test_verified_without_evidence_and_dropped_by_an_agent_never_count(self):
        self.ledger([self.item(1, "verified", evidence=""), self.item(2, "verified", evidence="   "),
                     self.item(3, "dropped", by="agent"), self.item(4, "verified")])
        m, a = self.audits()[10]
        self.assertEqual(m["goal"], "not met")
        self.assertEqual(m["label"], "some of the ranked items verified or dropped by the owner")   # one of four
        self.assertEqual((a["verified"], a["owner_dropped"], a["not_counted"]), (1, 0, 3))

    def test_the_newest_row_per_id_wins(self):
        self.ledger([self.item(1, "open"), self.item(2, "verified"), self.item(1, "built"), self.item(1, "verified"),
                     self.item(2, "open")])
        m, a = self.audits()[10]
        self.assertEqual(m["goal"], "not met")
        self.assertEqual((a["items"], a["verified"], a["open"]), (2, 1, 1))
        self.assertEqual(m["label"], "some of the ranked items verified or dropped by the owner")
        self.ledger([self.item(1, "verified", evidence=""), self.item(1, "verified")])
        self.assertEqual(self.row(10)["goal"], "met")

    def test_quantity_words(self):
        for done, n, word in ((0, 4, "none"), (1, 10, "few"), (2, 10, "some"), (5, 10, "some"), (6, 10, "most"),
                              (9, 10, "most"), (10, 10, "all")):
            self.ledger([self.item(i, "verified" if i < done else "open") for i in range(n)])
            m = self.row(10)
            self.assertEqual(m["label"], f"{word} of the ranked items verified or dropped by the owner", (done, n))
            self.assertEqual(m["goal"], "met" if done == n else "not met")

    def test_the_env_path_wins_over_config(self):
        self.ledger([self.item(1, "verified")])
        other = jsonl(self.root / "other.jsonl", [self.item(1, "open")])
        self.env["LIMITLESS_RANKED_LEDGER"] = str(other)
        self.assertEqual(self.row(10)["goal"], "not met")

    def test_a_relative_path_is_in_the_state_dir(self):
        jsonl(self.st / "ranked.jsonl", [self.item(1, "verified")])
        self.set(ranked_ledger="ranked.jsonl")
        self.assertEqual(self.row(10)["goal"], "met")

    def test_a_broken_ledger_is_unknown_not_a_traceback(self):
        d = self.root / "ledger-dir"
        d.mkdir()
        self.set(ranked_ledger=str(d))
        self.assertEqual(self.row(10)["goal"], "unknown")
        (self.root / "bin.jsonl").write_bytes(b"\xff\xfe\x00garbage\n")
        self.set(ranked_ledger=str(self.root / "bin.jsonl"))
        self.assertEqual(self.row(10)["goal"], "unknown")

    def test_ids_and_evidence_never_reach_the_label(self):
        self.ledger([{"id": "secret-card-id", "status": "verified", "by": "owner", "evidence": "private receipt text"},
                     {"id": "other-id", "status": "open", "by": "owner", "evidence": ""}])
        for m in self.measured():
            self.assertNotIn("secret-card-id", m["label"])
            self.assertNotIn("private receipt", m["label"])
        _m, a = self.audits()[10]
        self.assertNotIn("secret-card-id", json.dumps(a))
        self.assertNotIn("private receipt", json.dumps(a))

    def test_label_has_no_digit(self):
        for rows in ([], [self.item(1, "open")], [self.item(i, "verified") for i in range(25)]):
            self.ledger(rows)
            self.assertIsNone(DIGIT.search(self.row(10)["label"]), self.row(10))


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
