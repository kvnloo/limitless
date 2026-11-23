"""limitless/doctor.py: the read-only live-state report. Synthetic state dirs only."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import doctor  # noqa: E402

NOW = 1894708800.0  # 2030-01-15T12:00:00Z, the fixture clock


def clean_env(**extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("LIMITLESS_")}
    env.update(extra)
    return env


class DoctorCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.st = self.home / "state"
        self.st.mkdir()
        self.cfg_path = self.home / "config.json"
        self.cfg = {"state": str(self.st)}

    def write(self, name, data):
        p = self.st / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, (dict, list)):
            data = json.dumps(data)
        p.write_text(data if data.endswith("\n") else data + "\n")
        return p

    def rows(self, cfg=None):
        cfg = self.cfg if cfg is None else cfg
        self.cfg_path.write_text(json.dumps(cfg))
        with mock.patch.dict(os.environ, clean_env(HOME=str(self.home), LIMITLESS_CONFIG=str(self.cfg_path)),
                             clear=True):
            return doctor.report(cfg, NOW)

    def row(self, name, cfg=None):
        rows = self.rows(cfg)
        got = [r for r in rows if r["name"] == name]
        self.assertEqual(len(got), 1, [r["name"] for r in rows])
        return got[0]


class StateDirRow(DoctorCase):
    def test_rows_have_the_three_fields_and_a_known_status(self):
        for r in self.rows():
            self.assertTrue({"name", "status", "reason"} <= set(r), r)
            self.assertIn(r["status"], doctor.STATUSES)

    def test_an_existing_readable_state_dir_is_live(self):
        r = self.row("state dir")
        self.assertEqual(r["status"], "live")
        self.assertEqual(r["reason"], "the state dir exists and is readable")

    def test_a_missing_state_dir_is_missing(self):
        r = self.row("state dir", {"state": str(self.home / "nowhere")})
        self.assertEqual((r["status"], r["reason"]), ("missing", "the state dir does not exist"))

    def test_the_reason_never_names_the_path(self):
        for r in self.rows({"state": str(self.home / "nowhere")}):
            self.assertNotIn(str(self.home), r["reason"])


class InputRows(DoctorCase):
    def setUp(self):
        super().setUp()
        # inputs.json snapshot taken half an hour before NOW: ages grow by that much
        self.write("inputs.json", {"at": "2030-01-15T11:30:00Z",
                                   "ageHours": {"wearable": 3.7, "scale": 51.3, "bike": "down", "anki": None,
                                                "phone": 23.6}})

    def test_a_fresh_input_is_live(self):
        r = self.row("input wearable")
        self.assertEqual((r["kind"], r["status"]), ("input", "live"))
        self.assertEqual(r["reason"], "recording: updated within the last day")

    def test_an_input_over_the_stale_threshold_is_stale(self):
        # under the threshold in the snapshot, over it once the snapshot's own age is added (limitless_status)
        for name in ("input scale", "input phone"):
            r = self.row(name)
            self.assertEqual((r["status"], r["reason"]), ("stale", "not recording: no update for over a day"))

    def test_a_down_input_is_stale(self):
        r = self.row("input bike")
        self.assertEqual((r["status"], r["reason"]), ("stale", "not recording: the sync reports it down"))

    def test_an_input_with_no_age_is_missing(self):
        r = self.row("input anki")
        self.assertEqual((r["status"], r["reason"]), ("missing", "no age for this input in inputs.json"))

    def test_inputs_come_in_name_order_after_the_state_dir(self):
        names = [r["name"] for r in self.rows() if r["kind"] in ("state", "input")]
        self.assertEqual(names, ["state dir", "input anki", "input bike", "input phone", "input scale",
                                 "input wearable"])

    def test_no_inputs_file_is_one_missing_row_with_the_status_tools_reason(self):
        (self.st / "inputs.json").unlink()
        r = self.row("inputs")
        self.assertEqual((r["kind"], r["status"]), ("input", "missing"))
        self.assertEqual(r["reason"], "no inputs.json (with ageHours) in the state dir")


def run(at, ok=True):
    return json.dumps({"at": at, "job": "sync", "ok": ok, "took_s": 12.5})


class SyncRunRow(DoctorCase):
    def test_a_recent_ok_run_is_live_with_its_age_in_words(self):
        self.write("runs.jsonl", "\n".join([run("2030-01-15T06:00:00Z", ok=False), "torn line",
                                            run("2030-01-15T10:47:00Z")]))
        r = self.row("last sync run")
        self.assertEqual((r["kind"], r["status"]), ("run", "live"))
        self.assertEqual(r["reason"], "the last sync run was about an hour ago and finished ok")

    def test_hours_and_days_in_words(self):
        cases = [("2030-01-15T11:40:00Z", "live", "under an hour ago"),
                 ("2030-01-15T06:59:00Z", "live", "about five hours ago"),
                 ("2030-01-14T13:00:00Z", "live", "about twenty-three hours ago"),
                 ("2030-01-14T10:00:00Z", "stale", "about a day ago"),
                 ("2030-01-12T09:00:00Z", "stale", "about three days ago"),
                 ("2030-01-01T09:00:00Z", "stale", "over a week ago")]
        for at, status, words in cases:
            self.write("runs.jsonl", run(at))
            r = self.row("last sync run")
            self.assertEqual((r["status"], r["reason"]),
                             (status, f"the last sync run was {words} and finished ok"), at)

    def test_a_failed_last_run_is_stale_even_when_recent(self):
        self.write("runs.jsonl", run("2030-01-15T11:00:00Z", ok=False))
        r = self.row("last sync run")
        self.assertEqual((r["status"], r["reason"]), ("stale", "the last sync run was about an hour ago and failed"))

    def test_no_run_is_missing(self):
        r = self.row("last sync run")
        self.assertEqual((r["status"], r["reason"]), ("missing", "no timestamped row in runs.jsonl"))

    def test_the_run_row_follows_the_inputs(self):
        self.write("runs.jsonl", run("2030-01-15T11:00:00Z"))
        self.assertEqual([r["kind"] for r in self.rows()][:3], ["state", "input", "run"])


ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "state"


def manifest_tools():
    lines = (ROOT / "plugin.yaml").read_text().splitlines()
    start = lines.index("provides_tools:") + 1
    out = []
    for ln in lines[start:]:
        if not ln.startswith("  - "):
            break
        out.append(ln[4:].strip())
    return out


def tree(d):
    """Every file under d with its mtime and bytes: the read-only proof."""
    return sorted((str(p.relative_to(d)), p.stat().st_mtime_ns, p.read_bytes()) for p in Path(d).rglob("*")
                  if p.is_file())


class ToolRows(DoctorCase):
    def tool(self, name, cfg=None):
        return self.row(f"tool {name}", cfg)

    def test_one_row_per_manifest_tool_in_order_after_the_run_row(self):
        rows = self.rows()
        tools_ = [r for r in rows if r["kind"] == "tool"]
        self.assertEqual([r["name"] for r in tools_], [f"tool {n}" for n in manifest_tools()])
        self.assertEqual(rows.index(tools_[0]), [r["kind"] for r in rows].index("run") + 1)

    def test_a_null_value_is_missing_with_the_envelopes_own_reason(self):
        r = self.tool("limitless_habit")
        self.assertEqual((r["status"], r["reason"]), ("missing", "no habit.json with a habit: no habit set this week"))

    def test_an_unknown_value_is_missing_with_the_envelopes_reason(self):
        r = self.tool("limitless_window")
        self.assertEqual((r["status"], r["reason"]), ("missing", "no Sleep-mode events in the state dir"))
        r = self.tool("limitless_phase")
        self.assertEqual((r["status"], r["reason"]), ("missing", "no wake event yet"))

    def test_a_tool_whose_input_is_not_configured_is_off(self):
        for name, reason in [("limitless_body", 'no body file: set "body_file" in config.json'),
                             ("limitless_anki", "no Anki collection set"),
                             ("limitless_ideas", "no idea ledger set"),
                             ("limitless_flow_ledger", "flow ledger unknown: no work apps set (flow_work_apps)")]:
            r = self.tool(name)
            self.assertEqual((r["status"], r["reason"]), ("off", reason), name)

    def test_a_tool_whose_feature_is_off_by_config_is_off(self):
        self.assertEqual(self.tool("limitless_focus_safe")["status"], "off")
        self.assertEqual(self.tool("limitless_breathing")["status"], "off")
        r = self.tool("limitless_card_view")
        self.assertEqual(r["status"], "off")
        self.assertIn("no card dir", r["reason"])

    def test_the_memory_palace_offer_without_a_link_is_off(self):
        r = self.tool("limitless_palace")
        self.assertEqual((r["status"], r["reason"]), ("off", "no memory palace link set (config palace_link)"))

    def test_the_memory_palace_offer_with_a_link_is_not_off(self):
        r = self.tool("limitless_palace", dict(self.cfg, palace_link="palace-app://walk"))
        self.assertNotEqual(r["status"], "off")

    def test_the_state_dir_row_leaves_no_open_iterator(self):
        import warnings
        with warnings.catch_warnings(record=True) as got:
            warnings.simplefilter("always")
            doctor.state_row(self.home)
            import gc
            gc.collect()
        self.assertEqual([w for w in got if issubclass(w.category, ResourceWarning)], [])

    def test_turning_a_feature_on_makes_it_live(self):
        cfg = dict(self.cfg, focus_safe="warn", card_dir=str(self.home / "cards"),
                   wind_down_breathing_link="breath-app://open")
        for name in ("limitless_focus_safe", "limitless_card_view", "limitless_breathing"):
            self.assertIn(self.tool(name, cfg)["status"], ("live", "stale"), name)
        self.assertFalse((self.home / "cards").exists(), "the doctor rendered the card but must not write it")

    def test_a_value_is_live_with_its_evidence_in_words(self):
        r = self.tool("limitless_schedule")
        self.assertEqual((r["status"], r["reason"]), ("live", "answers from direct evidence"))

    def test_a_stale_value_is_stale(self):
        r = self.tool("limitless_quiet")
        self.assertEqual(r["status"], "stale")
        self.assertEqual(r["reason"], "answers, but its evidence is stale or of unknown age")

    def test_a_tool_that_needs_arguments_says_so(self):
        r = self.tool("limitless_capture")
        self.assertEqual((r["status"], r["reason"]), ("missing", "needs its arguments: empty capture: nothing recorded"))

    def test_a_raising_tool_is_missing_and_its_message_is_not_shown(self):
        from limitless import plugin

        def boom(args, now):
            raise RuntimeError("secret detail 42")
        schema = plugin.TOOLS["limitless_body"][0]
        with mock.patch.dict(plugin.TOOLS, {"limitless_body": (schema, boom, "x")}):
            r = self.tool("limitless_body")
        self.assertEqual((r["status"], r["reason"]), ("missing", "the tool failed with RuntimeError"))

    def test_a_manifest_tool_the_plugin_does_not_register_is_missing(self):
        with mock.patch.object(doctor, "manifest_tools", return_value=["limitless_nope"]):
            r = self.tool("limitless_nope")
        self.assertEqual((r["status"], r["reason"]), ("missing", "listed in plugin.yaml but not registered"))

    def test_reasons_never_hold_a_digit(self):
        from limitless import plugin
        from limitless.envelope import missing

        def digits(args, now):
            return missing("capture is over 4000 characters, 12.5 h old")
        schema = plugin.TOOLS["limitless_body"][0]
        with mock.patch.dict(plugin.TOOLS, {"limitless_body": (schema, digits, "x")}):
            r = self.tool("limitless_body")
        self.assertFalse(any(c.isdigit() for c in r["reason"]), r["reason"])
        for r in self.rows():
            self.assertFalse(any(c.isdigit() for c in r["status"] + r["reason"]), r)


class AuditHeld(unittest.TestCase):
    def test_held_records_nothing_and_still_blocks_then_resumes(self):
        from limitless import tier_audit
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "audit.jsonl"
            env = {"LIMITLESS_AUDIT": str(log)}
            with tier_audit.held():
                self.assertIsNone(tier_audit.gate("doctor", "a line with 7", False, env=env))
                self.assertEqual(tier_audit.gate("doctor", "words only", False, env=env), "words only")
            self.assertFalse(log.exists())
            self.assertEqual(tier_audit.gate("doctor", "words only", False, env=env), "words only")
            self.assertEqual(len(log.read_text().splitlines()), 1)


class ReadOnly(DoctorCase):
    def test_the_whole_report_changes_no_file_under_the_state_dir(self):
        for f in FIX.iterdir():
            (self.st / f.name).write_bytes(f.read_bytes())
        self.write("captures.jsonl", {"at": "2030-01-15T09:00:00Z", "text": "synthetic idea", "source": "hermes"})
        self.write("ideas.jsonl", {"kind": "idea", "id": "i1", "at": "2030-01-14T09:00:00Z", "text": "synthetic",
                                   "source": "hermes", "status": "new"})
        self.write("events.jsonl", "\n".join(json.dumps(e) for e in [
            {"event": "wind_down", "at": "2030-01-14T21:00:00Z"}, {"event": "habit_cue", "at": "2030-01-15T08:00:00Z"}]))
        (self.st / "queue" / "queue").mkdir(parents=True)
        (self.st / "queue" / "queue" / "task.md").write_text("synthetic task\n")
        (self.st / "cards").mkdir()
        cfg = dict(self.cfg, card_dir=str(self.st / "cards"), audit_path=str(self.st / "audit.jsonl"),
                   idea_ledger="ideas.jsonl", work_queue_dir="queue", focus_safe="warn",
                   wind_down_breathing_link="breath-app://open")
        before = tree(self.st)
        rows = self.rows(cfg)
        self.assertGreater(len(rows), len(manifest_tools()))
        self.assertEqual(tree(self.st), before)


if __name__ == "__main__":
    unittest.main()
