"""idea_ledger.append and the configured ledger path: dry run by default, one atomic append, no default path."""
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import idea_ledger  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

A = {"at": "2030-01-07T21:00:00+00:00", "text": "Synthetic idea about a reading lamp", "source": "hermes"}
B = {"at": "2030-01-07T22:30:00+00:00", "text": "Another synthetic idea", "source": "bedtime"}


class Append(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = Path(self.tmp.name)
        self.path = self.d / "ideas.jsonl"
        self.rows = idea_ledger.new_rows([A, B], [], None)

    def test_dry_run_by_default_writes_nothing(self):
        out = idea_ledger.append(self.path, self.rows)
        self.assertEqual((out["count"], out["written"]), (2, False))
        self.assertFalse(self.path.exists())

    def test_write_appends_whole_newline_terminated_lines_mode_0600(self):
        out = idea_ledger.append(self.path, self.rows, write=True)
        self.assertEqual((out["count"], out["written"]), (2, True))
        raw = self.path.read_bytes()
        self.assertTrue(raw.endswith(b"\n"))
        self.assertEqual([json.loads(x) for x in raw.decode().splitlines()], self.rows)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)

    def test_existing_bytes_are_kept_and_a_missing_newline_is_added_first(self):
        self.path.write_bytes(b'{"kind": "idea", "id": "idea_x", "text": "kept"}')
        os.chmod(self.path, 0o640)
        before = self.path.read_bytes()
        idea_ledger.append(self.path, self.rows[:1], write=True)
        raw = self.path.read_bytes()
        self.assertTrue(raw.startswith(before + b"\n"))
        self.assertEqual(json.loads(raw.decode().splitlines()[1]), self.rows[0])
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o640)   # an existing file keeps its mode

    def test_one_write_call(self):
        calls = []
        real = os.write

        def spy(fd, data):
            calls.append(data)
            return real(fd, data)

        with mock.patch.object(idea_ledger.os, "write", side_effect=spy):
            idea_ledger.append(self.path, self.rows, write=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].count(b"\n"), 2)

    def test_no_path_does_nothing_and_says_why(self):
        out = idea_ledger.append(None, self.rows, write=True)
        self.assertEqual((out["count"], out["written"], out["why"]), (0, False, "no idea ledger set"))

    def test_nothing_new_writes_nothing(self):
        out = idea_ledger.append(self.path, [], write=True)
        self.assertEqual((out["count"], out["written"]), (0, False))
        self.assertFalse(self.path.exists())

    def test_a_missing_folder_is_not_created(self):
        p = self.d / "no-such-dir" / "ideas.jsonl"
        out = idea_ledger.append(p, self.rows, write=True)
        self.assertEqual((out["written"], out["why"]), (False, idea_ledger.NO_DIR))
        self.assertFalse(p.parent.exists())

    def test_non_idea_rows_are_not_written(self):
        out = idea_ledger.append(self.path, [{"kind": "note"}, "x", None] + self.rows[:1], write=True)
        self.assertEqual(out["count"], 1)
        self.assertEqual(len(self.path.read_text().splitlines()), 1)


class Path_(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.state = self.home / "state"
        self.state.mkdir()
        self.reader = StateReader(self.state)

    def cfg(self, obj):
        p = self.home / "config.json"
        p.write_text(json.dumps(obj))
        return {"LIMITLESS_CONFIG": str(p)}

    def test_not_set_is_none(self):
        self.assertIsNone(self.reader.idea_ledger_path({}, self.home))
        self.assertIsNone(self.reader.idea_ledger_path(self.cfg({"idea_ledger": "  "}), self.home))

    def test_env_wins_over_config_and_relative_is_in_the_state_dir(self):
        env = self.cfg({"idea_ledger": "from-config.jsonl"})
        self.assertEqual(self.reader.idea_ledger_path(env, self.home), self.state / "from-config.jsonl")
        env["LIMITLESS_IDEA_LEDGER"] = str(self.home / "notes" / "ideas.jsonl")
        self.assertEqual(self.reader.idea_ledger_path(env, self.home), self.home / "notes" / "ideas.jsonl")

    def test_rows_read_only_the_object_lines(self):
        p = self.state / "ideas.jsonl"
        p.write_text('{"kind": "idea", "id": "idea_a"}\nnot json\n[1]\n{"kind": "idea", "id": "idea_b"}\n')
        env = self.cfg({"idea_ledger": "ideas.jsonl"})
        self.assertEqual([r["id"] for r in self.reader.idea_ledger_rows(env, self.home)], ["idea_a", "idea_b"])
        self.assertEqual(self.reader.idea_ledger_rows({}, self.home), [])


class Plan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.state = self.home / "state"
        self.state.mkdir()
        (self.state / "captures.jsonl").write_text("".join(json.dumps(c) + "\n" for c in (A, B)))

    def env(self, ledger):
        return {"LIMITLESS_STATE": str(self.state), "LIMITLESS_CONFIG": str(self.home / "none.json"),
                **({"LIMITLESS_IDEA_LEDGER": ledger} if ledger else {})}

    def test_unset_ledger_plans_nothing(self):
        out = idea_ledger.run(self.state, self.env(None), self.home, write=True)
        self.assertEqual((out["count"], out["written"], out["why"]), (0, False, idea_ledger.NO_LEDGER))
        self.assertEqual(sorted(p.name for p in self.state.iterdir()), ["captures.jsonl"])

    def test_run_twice_appends_once(self):
        env = self.env(str(self.state / "ideas.jsonl"))
        self.assertEqual(idea_ledger.run(self.state, env, self.home)["count"], 2)       # dry run
        self.assertFalse((self.state / "ideas.jsonl").exists())
        self.assertEqual(idea_ledger.run(self.state, env, self.home, write=True)["count"], 2)
        again = idea_ledger.run(self.state, env, self.home, write=True)
        self.assertEqual((again["count"], again["written"]), (0, False))
        self.assertEqual(len((self.state / "ideas.jsonl").read_text().splitlines()), 2)

    def test_the_captures_file_is_never_the_ledger(self):
        env = self.env(str(self.state / "captures.jsonl"))
        before = (self.state / "captures.jsonl").read_bytes()
        out = idea_ledger.run(self.state, env, self.home, write=True)
        self.assertEqual((out["written"], out["why"]), (False, idea_ledger.SAME_AS_CAPTURES))
        self.assertEqual((self.state / "captures.jsonl").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
