"""jobs.to_cron_fields: each job spec as the two fields Hermes' cron decision-window gate stores.

The host side is the public fork kvnloo/hermes-agent, branch up/cron-decision-window-gate-r2 (a9106628). The
constants and acceptance rules below are copied from it, so this test needs no Hermes install and no network.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import ast
import math
import os
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import jobs  # noqa: E402

JOBS_PY = Path(jobs.__file__)

# The host's WindowClass values, copied from the fork: cron/decision_window.py lines 30-34
# (class WindowClass(str, Enum): PEAK = "peak", TROUGH = "trough", ANYTIME = "anytime", WIND_DOWN = "wind_down").
HERMES_WINDOW_CLASSES = frozenset({"peak", "trough", "anytime", "wind_down"})


def fork_normalize_window_class(value):
    """Copy of the fork's acceptance rule, cron/decision_window.py lines 58-69 (normalize_window_class):
    None or a blank string is no window; a WindowClass value (any case, surrounding spaces) is stored
    lower-cased; anything else raises ValueError."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, str):
        clean = value.strip().lower()
        if clean in HERMES_WINDOW_CLASSES:
            return clean
    raise ValueError(f"window_class must be one of {sorted(HERMES_WINDOW_CLASSES)}, not {value!r}.")


def fork_normalize_stale_after_s(value):
    """Copy of the fork's acceptance rule, cron/decision_window.py lines 72-84 (normalize_stale_after_s):
    None or a blank string is never stale; a boolean raises; anything float() rejects raises; a value that
    is not finite or not above zero raises; else positive seconds as a float."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise ValueError("stale_after_s must be a number of seconds, not a boolean.")
    try:
        seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"stale_after_s must be a number of seconds, not {value!r}.") from exc
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError(f"stale_after_s must be a positive number of seconds, not {value!r}.")
    return seconds


def fork_validate_window_knobs(schedule, window_class, stale_after_s):
    """Copy of cron/decision_window.py lines 87-95 (validate_window_knobs): either field needs a recurring
    schedule, kind cron or interval (cron/jobs.py line 1852 calls it on create, lines 2142-2144 on update)."""
    kind = (schedule or {}).get("kind")
    for name, value in (("window_class", window_class), ("stale_after_s", stale_after_s)):
        if value is not None and kind not in {"cron", "interval"}:
            raise ValueError(f"{name} needs a recurring schedule (cron or interval); kind is {kind!r}.")


def module_specs():
    """Every JobSpec jobs.py defines at module level, plus the variants its factories build."""
    found = [v for v in vars(jobs).values() if isinstance(v, jobs.JobSpec)]
    found += list(jobs.SPECS.values())
    found += [jobs.wake_brief(decision=True), jobs.wake_brief(decision=False)]
    found += [jobs.habit_checkin({"cue": cue}) for cue in jobs.EVENTS]
    found += [jobs.week_review({"cue": cue}) for cue in jobs.EVENTS]
    return found


def source_windows():
    """The window word of every JobSpec(...) call written in jobs.py (third positional or window_class=)."""
    out = []
    for node in ast.walk(ast.parse(JOBS_PY.read_text(encoding="utf-8"))):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "JobSpec"):
            continue
        arg = next((k.value for k in node.keywords if k.arg == "window_class"), None)
        if arg is None and len(node.args) >= 3:
            arg = node.args[2]
        out.append((node.lineno, arg.value if isinstance(arg, ast.Constant) else None))
    return out


class CronFields(unittest.TestCase):
    def test_every_spec_maps_into_the_host_window_classes(self):
        specs = module_specs()
        self.assertGreater(len(specs), 10)
        for spec in specs:
            with self.subTest(job=spec.name, window=spec.window_class):
                f = jobs.to_cron_fields(spec)
                self.assertIn(f["window_class"], HERMES_WINDOW_CLASSES)
                self.assertLessEqual(set(f), {"window_class", "stale_after_s"})

    def test_named_jobs(self):
        f = jobs.to_cron_fields
        self.assertEqual(f(jobs.WAKE_BRIEF), {"window_class": "anytime", "stale_after_s": jobs.WAKE_STALE_S})
        self.assertEqual(f(jobs.wake_brief(decision=True)),
                         {"window_class": "peak", "stale_after_s": jobs.WAKE_STALE_S})
        self.assertEqual(f(jobs.NAP), {"window_class": "anytime", "stale_after_s": jobs.NAP_STALE_S})
        self.assertEqual(f(jobs.MIQ), {"window_class": "wind_down", "stale_after_s": jobs.MIQ_STALE_S})
        self.assertEqual(f(jobs.HABIT_CHECKIN), {"window_class": "anytime", "stale_after_s": jobs.HABIT_STALE_S})
        self.assertEqual(f(jobs.NOOP_EXPORT), {"window_class": "anytime"})   # no expiry: no stale_after_s

    def test_static_every_window_written_in_jobs_py_is_mapped(self):
        """A new JobSpec(...) in jobs.py whose window word is not in the table fails here, before any run."""
        seen = source_windows()
        self.assertGreater(len(seen), 10)
        for lineno, word in seen:
            with self.subTest(line=lineno):
                self.assertIsNotNone(word, "JobSpec window_class must be a literal word")
                self.assertIn(word, jobs.CRON_WINDOW)
        for spec in module_specs():
            self.assertIn(spec.window_class, jobs.CRON_WINDOW)

    def test_table_targets_are_host_values_and_match_the_window_provider(self):
        self.assertLessEqual(set(jobs.CRON_WINDOW.values()), HERMES_WINDOW_CLASSES)
        from limitless import window_provider
        for word, host in jobs.CRON_WINDOW.items():
            self.assertEqual(window_provider.TO_CRON[word], host)

    def test_stale_after_s_is_a_positive_int_when_present(self):
        for spec in module_specs():
            f = jobs.to_cron_fields(spec)
            with self.subTest(job=spec.name):
                if spec.stale_after_s is None:
                    self.assertNotIn("stale_after_s", f)
                    continue
                s = f["stale_after_s"]
                self.assertIs(type(s), int)
                self.assertGreater(s, 0)
                self.assertGreaterEqual(s, spec.stale_after_s)   # never shorter than the spec's own expiry
        odd = SimpleNamespace(name="synthetic", window_class="trough", stale_after_s=0.25)
        self.assertEqual(jobs.to_cron_fields(odd), {"window_class": "trough", "stale_after_s": 1})

    def test_the_fork_accepts_every_output(self):
        for spec in module_specs():
            f = jobs.to_cron_fields(spec)
            with self.subTest(job=spec.name):
                self.assertEqual(fork_normalize_window_class(f["window_class"]), f["window_class"])
                stale = fork_normalize_stale_after_s(f.get("stale_after_s"))
                self.assertEqual(stale, None if spec.stale_after_s is None else float(f["stale_after_s"]))
                for kind in ("cron", "interval"):
                    fork_validate_window_knobs({"kind": kind}, f["window_class"], f.get("stale_after_s"))

    def test_the_copied_rules_reject_what_the_fork_rejects(self):
        for bad in ("evening", "focus_block", 3, True):
            with self.assertRaises(ValueError):
                fork_normalize_window_class(bad)
        for bad in (True, 0, -1, float("inf"), float("nan"), "soon"):
            with self.assertRaises(ValueError):
                fork_normalize_stale_after_s(bad)
        with self.assertRaises(ValueError):
            fork_validate_window_knobs({"kind": "once"}, "peak", None)

    def test_no_window_is_no_fields(self):
        for spec in (SimpleNamespace(name="synthetic"), SimpleNamespace(name="synthetic", window_class=None),
                     SimpleNamespace(name="synthetic", window_class="", stale_after_s=60)):
            self.assertEqual(jobs.to_cron_fields(spec), {})

    def test_an_unmapped_window_word_fails_loudly(self):
        with self.assertRaises(ValueError):
            jobs.to_cron_fields(SimpleNamespace(name="synthetic", window_class="evening"))

    def test_returns_a_new_dict(self):
        a = jobs.to_cron_fields(jobs.MIQ)
        a["window_class"] = "peak"
        self.assertEqual(jobs.to_cron_fields(jobs.MIQ)["window_class"], "wind_down")

    def test_schedule_card_gains_no_digit_and_keeps_when_it_speaks(self):
        for spec in module_specs():
            card = jobs.to_schedule_card(spec)
            with self.subTest(job=spec.name):
                self.assertNotIn("window_class", card)
                self.assertNotIn("stale_after_s", card)
                self.assertTrue(card["speaks"])
                for k, v in card.items():
                    self.assertFalse(re.search(r"\d", v), f"{k}: {v}")


if __name__ == "__main__":
    unittest.main()
