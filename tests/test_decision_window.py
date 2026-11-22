"""Decision-window gate tests. Synthetic fixtures only."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import decision_window as dw  # noqa: E402


def state(cls="peak", since="wake", source="test", confidence=1.0):
    return dw.WindowState(cls=cls, since=since, source=source, confidence=confidence)


def decide(job="peak", st=None, budget_left=1, asleep=False, critical=False):
    return dw.decide(job, state() if st is None else st, budget_left=budget_left, asleep=asleep, critical=critical)


class Decide(unittest.TestCase):
    def test_matching_peak_with_budget_delivers(self):
        self.assertEqual(decide().action, "deliver")

    def test_every_decision_has_a_one_line_reason(self):
        cases = [decide(), decide(job="trough"), decide(asleep=True), decide(budget_left=0),
                 decide(st=state(cls="unknown")), decide(critical=True, asleep=True), decide(job="anytime")]
        for d in cases:
            self.assertTrue(d.reason, d)
            self.assertNotIn("\n", d.reason)

    def test_anytime_delivers_in_any_open_window(self):
        for cls in ("peak", "trough", "wind_down", "unknown"):
            self.assertEqual(decide(job="anytime", st=state(cls=cls)).action, "deliver", cls)

    def test_anytime_delivers_without_any_state(self):
        self.assertEqual(dw.decide("anytime", None, budget_left=0, asleep=False).action, "deliver")

    def test_anytime_holds_while_asleep(self):
        self.assertEqual(decide(job="anytime", asleep=True).action, "hold")

    def test_class_mismatch_holds(self):
        d = decide(job="trough", st=state(cls="peak"))
        self.assertEqual(d.action, "hold")
        self.assertIn("trough", d.reason)

    def test_wind_down_job_delivers_in_wind_down(self):
        self.assertEqual(decide(job="wind_down", st=state(cls="wind_down")).action, "deliver")

    def test_unknown_state_holds_non_critical(self):
        self.assertEqual(decide(st=state(cls="unknown")).action, "hold")

    def test_missing_state_holds_non_critical(self):
        self.assertEqual(dw.decide("peak", None, budget_left=1, asleep=False).action, "hold")

    def test_unrecognised_state_class_counts_as_unknown(self):
        self.assertEqual(decide(st=state(cls="afternoon")).action, "hold")

    def test_low_confidence_state_counts_as_unknown(self):
        d = decide(st=state(confidence=0.2))
        self.assertEqual(d.action, "hold")
        self.assertIn("unknown", d.reason)

    def test_critical_always_delivers(self):
        for st in (None, state(cls="unknown"), state(cls="trough")):
            d = dw.decide("peak", st, budget_left=0, asleep=True, critical=True)
            self.assertEqual(d.action, "deliver")

    def test_one_decision_per_peak_window(self):
        d = decide(budget_left=0)
        self.assertEqual(d.action, "drop")
        self.assertIn("budget", d.reason)

    def test_budget_only_limits_peak_jobs(self):
        self.assertEqual(decide(job="trough", st=state(cls="trough"), budget_left=0).action, "deliver")

    def test_asleep_holds_before_budget_is_checked(self):
        self.assertEqual(decide(budget_left=0, asleep=True).action, "hold")

    def test_invalid_job_class_is_a_config_error(self):
        with self.assertRaises(ValueError):
            decide(job="morning")

    def test_reason_names_the_event_that_opened_the_window(self):
        self.assertIn("deep_work_end", decide(st=state(since="deep_work_end")).reason)


class Providers(unittest.TestCase):
    def test_static_provider_returns_its_state(self):
        p = dw.StaticProvider("trough", since="lunch")
        s = p.current()
        self.assertEqual((s.cls, s.since, s.source, s.confidence), ("trough", "lunch", "static", 1.0))

    def test_providers_satisfy_protocol(self):
        self.assertIsInstance(dw.StaticProvider("peak"), dw.WindowProvider)
        self.assertIsInstance(dw.StateFileProvider("x.json"), dw.WindowProvider)

    def _file(self, payload):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "window.json")
        with open(path, "w") as f:
            f.write(payload if isinstance(payload, str) else json.dumps(payload))
        return path

    def test_state_file_provider_reads_json(self):
        path = self._file({"cls": "peak", "since": "wake", "confidence": 0.9})
        s = dw.StateFileProvider(path).current()
        self.assertEqual((s.cls, s.since, s.source, s.confidence), ("peak", "wake", "state_file", 0.9))

    def test_state_file_defaults_confidence_to_one(self):
        s = dw.StateFileProvider(self._file({"cls": "wind_down", "since": "screen_off"})).current()
        self.assertEqual(s.confidence, 1.0)

    def test_state_file_rereads_on_every_call(self):
        path = self._file({"cls": "peak"})
        p = dw.StateFileProvider(path)
        self.assertEqual(p.current().cls, "peak")
        with open(path, "w") as f:
            json.dump({"cls": "trough"}, f)
        self.assertEqual(p.current().cls, "trough")

    def test_missing_file_is_unknown(self):
        s = dw.StateFileProvider(os.path.join(tempfile.mkdtemp(), "none.json")).current()
        self.assertEqual(s.cls, "unknown")
        self.assertEqual(s.confidence, 0.0)

    def test_corrupt_file_is_unknown(self):
        self.assertEqual(dw.StateFileProvider(self._file("{not json")).current().cls, "unknown")

    def test_unrecognised_class_in_file_is_unknown(self):
        self.assertEqual(dw.StateFileProvider(self._file({"cls": "noon"})).current().cls, "unknown")

    def test_non_object_json_is_unknown(self):
        self.assertEqual(dw.StateFileProvider(self._file("[1, 2]")).current().cls, "unknown")

    def test_bad_confidence_in_file_is_unknown(self):
        self.assertEqual(dw.StateFileProvider(self._file({"cls": "peak", "confidence": "high"})).current().cls,
                         "unknown")

    def test_provider_state_feeds_decide(self):
        p = dw.StaticProvider("peak", since="wake")
        self.assertEqual(dw.decide("peak", p.current(), budget_left=1, asleep=False).action, "deliver")


if __name__ == "__main__":
    unittest.main()
