"""limitless.context_packet: the state card as one data-free context packet for other long-horizon agents.
Synthetic fixtures only (tests/fixtures/state); never a real person's data."""
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import card, context_packet as cp  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures" / "state"
NOW = 1894708800.0
TODAY = date(2030, 1, 15)
ROW_KEYS = {"key", "words", "modality", "evidence_tier", "age_words"}


def no_config(d) -> dict:
    """An environment that reads no host config (a config path that does not exist)."""
    return {"LIMITLESS_CONFIG": str(Path(d) / "absent-config.json")}


def strings(v, path="$"):
    """Every (path, string) in v: dict keys and values, list items, recursively."""
    if isinstance(v, str):
        yield path, v
    elif isinstance(v, dict):
        for k, x in v.items():
            yield f"{path}.<key>", k
            yield from strings(x, f"{path}.{k}")
    elif isinstance(v, (list, tuple)):
        for i, x in enumerate(v):
            yield from strings(x, f"{path}[]")


def numbers(v):
    """Every non-bool int or float anywhere in v."""
    if isinstance(v, bool) or v is None:
        return []
    if isinstance(v, (int, float)):
        return [v]
    if isinstance(v, dict):
        return [n for x in v.values() for n in numbers(x)]
    if isinstance(v, (list, tuple)):
        return [n for x in v for n in numbers(x)]
    return []


def snapshot(d: Path):
    return sorted((str(p.relative_to(d)), p.stat().st_mtime_ns, p.stat().st_size) for p in d.rglob("*"))


class Shape(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.env = no_config(self.tmp)
        self.p = cp.packet(FIX, NOW, TODAY, env=self.env)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_top_level_keys(self):
        self.assertEqual(set(self.p), {"schema", "generated_at", "rows", "window", "asks"})
        self.assertEqual(self.p["schema"], "limitless.context/1")
        self.assertEqual(self.p["generated_at"], "2030-01-15T12:00:00Z")

    def test_rows_are_the_card_items(self):
        items = card.build(StateReader(FIX), NOW, TODAY, env=self.env)["items"]
        self.assertEqual([r["key"] for r in self.p["rows"]], list(items))
        for r in self.p["rows"]:
            self.assertEqual(set(r), ROW_KEYS)
            self.assertEqual(r["evidence_tier"], items[r["key"]]["evidence_tier"])
            self.assertEqual(r["modality"], items[r["key"]]["modality"])

    def test_words_match_the_card(self):
        rows = {r["key"]: r for r in self.p["rows"]}
        self.assertEqual(rows["sleep"]["words"], "short")
        self.assertEqual(rows["readiness"]["words"], "low")
        self.assertEqual(rows["habit_today"]["words"], "Done")
        self.assertEqual(self.p["window"], "peak")
        self.assertEqual(self.p["asks"], cp.ASKS_WAITING)

    def test_age_in_words(self):
        for r in self.p["rows"]:
            self.assertIsInstance(r["age_words"], str)
            self.assertTrue(r["age_words"])

    def test_a_missing_part_says_unknown_and_why(self):
        rows = {r["key"]: r for r in self.p["rows"]}
        self.assertTrue(rows["owner_message"]["words"].startswith("unknown"), rows["owner_message"])
        self.assertEqual(rows["owner_message"]["evidence_tier"], "none")

    def test_no_asks_says_so(self):
        st = Path(self.tmp) / "st"
        shutil.copytree(FIX, st)
        (st / "asks-latest.json").unlink()
        self.assertEqual(cp.packet(st, NOW, TODAY, env=self.env)["asks"], cp.NO_ASKS)

    def test_json_serialisable(self):
        self.assertEqual(json.loads(json.dumps(self.p)), self.p)


class DigitFree(unittest.TestCase):
    """Zero digits anywhere except generated_at and schema: every string (keys too) and no number at all."""

    def assert_digit_free(self, p):
        self.assertEqual(numbers(p), [])
        hits = [(path, s) for path, s in strings(p) if re.search(r"\d", s)
                and path not in ("$.generated_at", "$.schema")]
        self.assertEqual(hits, [])

    def test_fixture(self):
        with tempfile.TemporaryDirectory() as d:
            self.assert_digit_free(cp.packet(FIX, NOW, TODAY, env=no_config(d)))

    def test_owner_message_time_never_leaks(self):
        # the owner envelope's value is an ISO time: only its T1 label may reach the packet
        with tempfile.TemporaryDirectory() as d:
            beacon = Path(d) / "beacon.json"
            beacon.write_text(json.dumps({"at": "2030-01-14T22:00:00+00:00", "v": 1}))
            env = dict(no_config(d), LIMITLESS_OWNER_BEACONS=str(beacon))
            p = cp.packet(FIX, NOW, TODAY, env=env)
            owner = {r["key"]: r for r in p["rows"]}["owner_message"]
            self.assertNotEqual(owner["evidence_tier"], "none", owner)
            self.assert_digit_free(p)

    def test_digit_in_a_free_text_reason_is_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            st = Path(d) / "st"
            shutil.copytree(FIX, st)
            h = json.loads((st / "habit.json").read_text())
            h["week_of"] = "2029-12-03"   # an old week: the habit item's reason names that date
            (st / "habit.json").write_text(json.dumps(h))
            items = card.build(StateReader(st), NOW, TODAY, env=no_config(d))["items"]
            self.assertRegex(items["habit_today"]["reason"], r"\d")   # sanity: the reason has a digit
            p = cp.packet(st, NOW, TODAY, env=no_config(d))
            self.assert_digit_free(p)
            self.assertEqual({r["key"]: r for r in p["rows"]}["habit_today"]["words"], cp.UNKNOWN)

    def test_missing_state_dir(self):
        with tempfile.TemporaryDirectory() as d:
            p = cp.packet(Path(d) / "nowhere", NOW, TODAY, env=no_config(d))
            self.assert_digit_free(p)
            self.assertEqual(p["schema"], "limitless.context/1")


class RawFlagIgnored(unittest.TestCase):
    def test_raw_opt_in_changes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            env = no_config(d)
            plain = cp.packet(FIX, NOW, TODAY, env=env)
            raw = cp.packet(FIX, NOW, TODAY, env=dict(env, LIMITLESS_RAW_IN_PROMPT="1"))
            self.assertEqual(raw, plain)
            self.assertEqual(numbers(raw), [])
            self.assertNotIn("raw", json.dumps(raw))

    def test_the_card_itself_still_honours_it(self):
        # sanity: the flag does change the card, so the test above really holds the packet to T1
        self.assertIn("raw", card.build(StateReader(FIX), NOW, TODAY, raw=True)["items"]["sleep"])


class ReadOnly(unittest.TestCase):
    def test_packet_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            st = Path(d) / "st"
            shutil.copytree(FIX, st)
            before, home = snapshot(st), snapshot(Path(d))
            cp.packet(st, NOW, TODAY, env=no_config(d))
            self.assertEqual(snapshot(st), before)
            self.assertEqual(snapshot(Path(d)), home)


if __name__ == "__main__":
    unittest.main()
