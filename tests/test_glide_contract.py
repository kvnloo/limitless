"""Contract: GlideProvider against the attention.json Glide's own writer produces. Synthetic only.

Pinned to https://github.com/kvnloo/glide ``glide/attention.py`` at main
051b98ca74985194b8afde99b9dc0db81667be5e (the file last changed in 299bc1d). Writers: ``save`` (via
``start_block``, ``stop_block``, ``route``, ``wind_down``, ``take_resume``); reader default: ``load``.

``tests/fixtures/glide/contract.json`` is the file those writers leave at each step, made by running
Glide's real writer on a synthetic anchor with no session database:

    python3 -I tests/test_glide_contract.py --regen <glide checkout>

With ``LIMITLESS_GLIDE_SRC`` set to a Glide checkout, ``LiveWriter`` re-runs the writer and fails on
drift; without it those tests skip (CI has no Glide checkout).
"""
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import flow_week, plugin, tier_audit, wind_down  # noqa: E402
from limitless import glide_provider as gp  # noqa: E402

GOLDEN = ROOT / "tests" / "fixtures" / "glide" / "contract.json"
GLIDE_SHA = "051b98ca74985194b8afde99b9dc0db81667be5e"  # kvnloo/glide main; glide/attention.py at 299bc1d

# Key names in glide/attention.py at GLIDE_SHA (names only).
TOP_KEYS = {"block", "queue", "resume", "nudged"}               # save(); load()'s default on a bad file
BLOCK_KEYS = {"start", "end", "minutes"}                        # start_block(): epoch seconds, int minutes
QUEUE_KEYS = {"title", "body", "cls", "at"}                     # route() while held: epoch seconds
RESUME_KEYS = {"saved", "night", "title", "last_asks", "queued"}  # wind_down(), no session found
RESUME_SESSION_KEYS = {"session_id", "title", "last_asks"}      # _last_session() when one exists
EMPTY = {"block": None, "queue": [], "resume": None, "nudged": ""}

ANCHOR = 1894708800.0
M = 60.0
STEPS = ("missing_load", "after_start_block", "after_route_held", "expired_before_next_event",
         "after_route_post_expiry", "after_stop_block", "after_wind_down", "after_take_resume")


def writer_states(glide_src):
    """Run Glide's real writer (read-only import from a checkout) and return the file after each step."""
    sys.path.insert(0, str(glide_src))
    try:
        from glide import attention as a
    finally:
        sys.path.remove(str(glide_src))
    at = datetime.fromtimestamp(ANCHOR, timezone.utc)
    out = {}
    with tempfile.TemporaryDirectory() as d:
        home = Path(d)
        f = home / "glide" / "attention.json"
        read = lambda: json.loads(f.read_text())  # noqa: E731
        out["missing_load"] = a.load(home)
        a.start_block(home, 50, at)
        out["after_start_block"] = read()
        a.route(home, "Synthetic report", "held during the block", "report", at + timedelta(minutes=10),
                posture=None)
        out["after_route_held"] = read()
        out["expired_before_next_event"] = read()  # the block ran out; nothing rewrote the file yet
        a.route(home, "Synthetic after", "", "report", at + timedelta(minutes=51), posture=None)
        out["after_route_post_expiry"] = read()
        a.start_block(home, 50, at)
        a.stop_block(home, at + timedelta(minutes=5))
        out["after_stop_block"] = read()
        a.wind_down(home, at, force=True, posture=None)
        out["after_wind_down"] = read()
        a.take_resume(home, at + timedelta(days=1))
        out["after_take_resume"] = read()
        f.write_text('{"block": {"start": ')
        out["malformed_load"] = a.load(home)
    return out


def golden():
    return json.loads(GOLDEN.read_text())


def shifted(state, delta):
    """A copy of a writer state with every Glide timestamp moved by ``delta`` seconds."""
    s = json.loads(json.dumps(state))
    if s.get("block"):
        s["block"]["start"] += delta
        s["block"]["end"] += delta
    for item in s.get("queue", []):
        item["at"] += delta
    if s.get("resume"):
        s["resume"]["saved"] += delta
    return s


class Tmp(unittest.TestCase):
    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.addCleanup(self._d.cleanup)
        self.dir = Path(self._d.name)
        self.g = golden()

    def write(self, data, name="attention.json"):
        p = self.dir / name
        p.write_text(data if isinstance(data, str) else json.dumps(data, indent=1))
        return str(p)

    def state(self, step, now):
        return gp.GlideProvider(self.write(self.g["states"][step]), now=now).current()


class Shape(Tmp):
    """The golden file is what the vendored key names say Glide writes."""

    def test_pinned_to_the_same_glide_head(self):
        self.assertEqual(self.g["glide"]["sha"], GLIDE_SHA)
        self.assertEqual(self.g["glide"]["file"], "glide/attention.py")
        self.assertEqual(set(self.g["states"]), set(STEPS))

    def test_every_state_has_the_top_level_keys(self):
        for step, s in self.g["states"].items():
            self.assertEqual(set(s), TOP_KEYS, step)
        self.assertEqual(self.g["states"]["missing_load"], EMPTY)
        self.assertEqual(self.g["malformed_load"], EMPTY)

    def test_block_is_epoch_seconds_with_minutes(self):
        b = self.g["states"]["after_start_block"]["block"]
        self.assertEqual(set(b), BLOCK_KEYS)
        self.assertEqual((b["start"], b["end"] - b["start"], b["minutes"]), (ANCHOR, 50 * M, 50))
        self.assertIsInstance(b["start"], float)

    def test_held_ask_keys(self):
        (q,) = self.g["states"]["after_route_held"]["queue"]
        self.assertEqual(set(q), QUEUE_KEYS)
        self.assertEqual(q["at"], ANCHOR + 10 * M)

    def test_wind_down_writes_resume_and_nudged(self):
        s = self.g["states"]["after_wind_down"]
        self.assertEqual(set(s["resume"]), RESUME_KEYS)
        self.assertLessEqual(RESUME_SESSION_KEYS - {"session_id"}, set(s["resume"]))
        self.assertEqual(s["resume"]["saved"], ANCHOR)
        self.assertEqual(s["nudged"], s["resume"]["night"])
        self.assertIsNone(s["block"])

    def test_glide_has_no_explicit_wind_down_key(self):
        for step, s in self.g["states"].items():
            self.assertNotIn("wind_down", s, step)


class Provider(Tmp):
    """GlideProvider over each state Glide's writer produced."""

    def test_focus_block_is_peak_with_asks_held(self):
        for now in (ANCHOR, ANCHOR + 10 * M, ANCHOR + 50 * M - 1):
            st = self.state("after_route_held", now)
            self.assertEqual((st.cls, st.since, st.source, st.hold_asks), ("peak", "focus_start", "glide", True))

    def test_no_block_is_unknown(self):
        for step in ("missing_load", "after_route_post_expiry", "after_stop_block"):
            self.assertEqual(self.state(step, ANCHOR + 10 * M).cls, "unknown", step)

    def test_expired_block_left_in_the_file_is_unknown(self):
        # Glide keeps the block until the next route(); its own _active_block needs end > now.
        for now in (ANCHOR + 50 * M, ANCHOR + 51 * M, ANCHOR + 600 * M):
            st = self.state("expired_before_next_event", now)
            self.assertEqual((st.cls, st.hold_asks), ("unknown", False), now)

    def test_wind_down_nudge_is_wind_down(self):
        st = self.state("after_wind_down", ANCHOR + 20 * M)
        self.assertEqual((st.cls, st.since, st.source, st.hold_asks), ("wind_down", "wind_down", "glide", False))
        self.assertEqual(self.state("after_wind_down", ANCHOR + gp.WIND_DOWN_MAX_S + 1).cls, "unknown")

    def test_resume_taken_next_morning_is_unknown_but_nudged_stays(self):
        s = self.g["states"]["after_take_resume"]
        self.assertEqual(self.state("after_take_resume", ANCHOR + 20 * M).cls, "unknown")
        self.assertTrue(wind_down.glide_nudged(s, s["nudged"]))

    def test_missing_file_is_unknown(self):
        self.assertEqual(gp.GlideProvider(str(self.dir / "absent.json"), now=ANCHOR).current().cls, "unknown")

    def test_malformed_file_is_unknown(self):
        p = self.write('{"block": {"start": ')
        self.assertEqual(gp.GlideProvider(p, now=ANCHOR).current().cls, "unknown")
        self.assertIsNone(gp.attention(env={gp.ENV_KEY: p}, home=self.dir))

    def test_flow_week_sees_the_writer_block(self):
        p = self.write(self.g["states"]["after_route_held"])
        self.assertEqual(flow_week.glide_blocks(env={gp.ENV_KEY: p}, home=self.dir),
                         [{"start": ANCHOR, "end": ANCHOR + 50 * M}])


class Envelope(Tmp):
    """limitless_window over a writer-made focus block keeps its envelope and passes tier_audit."""

    def test_window_tool_keeps_envelope_and_passes_tier_audit(self):
        from test_plugin import FakeCtx
        ctx = FakeCtx()
        plugin.register(ctx)
        now = 1894708800.0  # the state fixtures' clock
        glide = self.write(shifted(self.g["states"]["after_route_held"], now - 10 * M - ANCHOR))
        log = self.dir / "audit.jsonl"
        env = {"LIMITLESS_STATE": str(ROOT / "tests" / "fixtures" / "state"),
               "LIMITLESS_ASKS": str(ROOT / "tests" / "fixtures" / "asks" / "asks.jsonl"),
               "LIMITLESS_CONFIG": str(self.dir / "none.json"), gp.ENV_KEY: glide, tier_audit.ENV_KEY: str(log)}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(time, "time", return_value=now):
            res = json.loads(ctx.tools["limitless_window"]["handler"]({}, task_id="t", session_id="s"))
        for key in ("value", "modality", "age_h", "evidence_tier"):
            self.assertIn(key, res)
        self.assertEqual(res["asks"]["deliver"], 0)
        self.assertGreater(res["asks"]["hold"], 0)
        rows = [json.loads(ln) for ln in log.read_text().splitlines()]
        self.assertTrue(rows)
        self.assertFalse(any(r["blocked"] for r in rows), rows)


@unittest.skipUnless(os.environ.get("LIMITLESS_GLIDE_SRC"), "set LIMITLESS_GLIDE_SRC to a Glide checkout")
class LiveWriter(Tmp):
    """Re-run Glide's real writer: drift in its keys, units or nesting fails here first."""

    def setUp(self):
        super().setUp()
        self.live = writer_states(Path(os.environ["LIMITLESS_GLIDE_SRC"]))

    def test_writer_output_matches_golden(self):
        self.assertEqual({k: self.live[k] for k in STEPS}, self.g["states"])
        self.assertEqual(self.live["malformed_load"], self.g["malformed_load"])

    def test_provider_peak_matches_glide_active_block_at_every_minute(self):
        sys.path.insert(0, os.environ["LIMITLESS_GLIDE_SRC"])
        try:
            from glide import attention as a
        finally:
            sys.path.pop(0)
        s = self.live["after_route_held"]
        p = self.write(s)
        for minute in range(-5, 60):
            now = ANCHOR + minute * M
            glide_active = a._active_block(s, datetime.fromtimestamp(now, timezone.utc)) is not None
            ours = gp.GlideProvider(p, now=now).current().hold_asks
            if minute >= 0:  # Glide's writer never puts start after now; before start the provider says unknown
                self.assertEqual(ours, glide_active, minute)


def regen(glide_src):
    states = writer_states(Path(glide_src))
    doc = {"glide": {"repo": "https://github.com/kvnloo/glide", "file": "glide/attention.py", "sha": GLIDE_SHA},
           "anchor": ANCHOR, "states": {k: states[k] for k in STEPS}, "malformed_load": states["malformed_load"]}
    GOLDEN.write_text(json.dumps(doc, indent=1) + "\n")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--regen"]:
        regen(sys.argv[2])
    else:
        unittest.main()
