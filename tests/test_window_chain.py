"""window_chain: first_known(*providers) and the Sleep-mode/unlock classifier as a WindowProvider."""
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import decision_window as dw  # noqa: E402
from limitless import window_chain as wc  # noqa: E402
from limitless.glide_provider import GlideProvider  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"
NOW = 1894708800.0
H = 3600.0


def iso(t):
    return datetime.fromtimestamp(t, tz=timezone.utc).isoformat()


def events(now=NOW, woke_h_ago=3.0, asleep=False, poll=True):
    rows = [{"at": iso(now - 30 * H), "on": True}, {"at": iso(now - woke_h_ago * H), "on": False}]
    if asleep:
        rows.append({"at": iso(now - 0.5 * H), "on": True})
    p = {"at": iso(now - 60), "ok": True} if poll else None
    return wc.EventProvider(rows, p, None, now=now)


class Boom:
    def current(self):
        raise RuntimeError("provider broke")


class FirstKnown(unittest.TestCase):
    def test_first_known_state_wins(self):
        st = wc.first_known(dw.StaticProvider("wind_down", since="wind_down"), dw.StaticProvider("peak"))
        self.assertEqual(st.cls, "wind_down")

    def test_unknown_falls_through_to_the_next(self):
        st = wc.first_known(dw.StaticProvider("unknown"), dw.StaticProvider("trough", since="wake"))
        self.assertEqual((st.cls, st.since), ("trough", "wake"))

    def test_low_confidence_and_bad_classes_count_as_unknown(self):
        st = wc.first_known(dw.StaticProvider("peak", confidence=0.1), dw.StaticProvider("afternoon"),
                            dw.StaticProvider("anytime"))
        self.assertEqual(st.cls, "anytime")

    def test_none_and_broken_providers_are_skipped(self):
        self.assertEqual(wc.first_known(None, Boom(), dw.StaticProvider("peak")).cls, "peak")

    def test_all_unknown_is_unknown(self):
        st = wc.first_known(dw.StaticProvider("unknown"), None)
        self.assertEqual((st.cls, st.confidence), ("unknown", 0.0))
        self.assertEqual(dw.decide("wind_down", st, budget_left=1, asleep=False).action, "hold")

    def test_no_providers_is_unknown(self):
        self.assertEqual(wc.first_known().cls, "unknown")

    def test_glide_first_then_events(self):
        glide = GlideProvider(str(FIX / "glide" / "idle.json"), now=NOW)
        self.assertEqual(wc.first_known(glide, events(woke_h_ago=3)).cls, "peak")
        glide = GlideProvider(str(FIX / "glide" / "wind-down.json"), now=NOW + 60)
        self.assertEqual(wc.first_known(glide, events(woke_h_ago=3)).cls, "wind_down")

    def test_hold_asks_survives_the_chain(self):
        glide = GlideProvider(str(FIX / "glide" / "focus-block.json"), now=NOW + 60)
        self.assertTrue(wc.first_known(glide, events()).hold_asks)


class Events(unittest.TestCase):
    def test_awake_bands_become_window_states_since_wake(self):
        for woke, cls in ((3, "peak"), (7, "trough"), (10, "anytime"), (0.5, "anytime")):
            st = events(woke_h_ago=woke).current()
            self.assertEqual((st.cls, st.since, st.source), (cls, "wake", "events"), woke)

    def test_asleep_is_a_flag_not_a_class(self):
        p = events(asleep=True)
        self.assertTrue(p.asleep)
        self.assertEqual(p.current().cls, "unknown")
        self.assertNotIn("asleep", dw.WINDOW_CLASSES)

    def test_awake_is_not_asleep(self):
        self.assertFalse(events().asleep)

    def test_no_live_evidence_is_unknown_and_not_asleep(self):
        p = events(poll=False)
        self.assertEqual((p.current().cls, p.asleep), ("unknown", False))

    def test_is_a_window_provider(self):
        self.assertIsInstance(events(), dw.WindowProvider)

    def test_from_reader_uses_the_state_dir(self):
        p = wc.EventProvider.from_reader(StateReader(FIX / "state"), now=NOW)
        self.assertIn(p.current().cls, dw.WINDOW_CLASSES + (dw.UNKNOWN,))
        self.assertIsInstance(p.asleep, bool)


if __name__ == "__main__":
    unittest.main()
