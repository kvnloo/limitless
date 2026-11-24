"""StateReader.work_queue_dir / work_items: the overnight work queue, by file name and mtime only.

Synthetic lane names only. The reader never opens an item file and never raises.
"""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import builtins
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless.state_reader import WORK_QUEUE_CONFIG, StateReader  # noqa: E402

NOW = 2_000_000_000.0
H = 3600.0


def touch(path: Path, mtime: float, text: str = "synthetic body\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.utime(path, (mtime, mtime))
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.st = self.root / "state"
        self.st.mkdir()
        self.cfg = self.root / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg)}
        self.reader = StateReader(self.st)

    def configure(self, value):
        self.cfg.write_text(json.dumps({WORK_QUEUE_CONFIG: value}))

    def items(self, since=None):
        return self.reader.work_items(since, env=self.env, home=self.root)


class WorkQueueDir(Base):
    def test_none_by_default(self):
        self.assertIsNone(self.reader.work_queue_dir(self.env, self.root))

    def test_relative_is_in_the_state_dir(self):
        self.configure("lanes")
        self.assertEqual(self.reader.work_queue_dir(self.env, self.root), self.st / "lanes")

    def test_absolute_is_kept(self):
        self.configure(str(self.root / "elsewhere"))
        self.assertEqual(self.reader.work_queue_dir(self.env, self.root), self.root / "elsewhere")

    def test_blank_or_not_a_string_is_none(self):
        for v in ("", "  ", 3, ["lanes"], None):
            self.configure(v)
            self.assertIsNone(self.reader.work_queue_dir(self.env, self.root), v)


class WorkItems(Base):
    def setUp(self):
        super().setUp()
        self.configure("lanes")
        self.q = self.st / "lanes"

    def test_one_row_per_md_file_with_its_status_and_mtime(self):
        touch(self.q / "queue" / "alpha-lane.md", NOW - 3 * H)
        touch(self.q / "running" / "beta-lane.md", NOW - 2 * H)
        touch(self.q / "done" / "gamma-lane.md", NOW - 1 * H)
        touch(self.q / "failed" / "delta-lane.md", NOW - 0.5 * H)
        got = sorted(self.items(), key=lambda r: r["name"])
        self.assertEqual(got, [
            {"name": "alpha-lane", "status": "queued", "mtime": NOW - 3 * H},
            {"name": "beta-lane", "status": "running", "mtime": NOW - 2 * H},
            {"name": "delta-lane", "status": "failed", "mtime": NOW - 0.5 * H},
            {"name": "gamma-lane", "status": "done", "mtime": NOW - 1 * H},
        ])

    def test_ignores_non_md_files_ids_hidden_files_and_subdirs(self):
        touch(self.q / "queue" / "notes.txt", NOW)
        touch(self.q / "queue" / "t_0123abcd.md", NOW)
        touch(self.q / "queue" / "t_deadbeef99.md", NOW)
        touch(self.q / "queue" / ".hidden.md", NOW)
        (self.q / "queue" / "nested.md").mkdir(parents=True)
        touch(self.q / "queue" / "kept-lane.md", NOW)
        touch(self.q / "other" / "stray.md", NOW)       # not one of the four status dirs
        self.assertEqual([r["name"] for r in self.items()], ["kept-lane"])

    def test_a_name_that_only_starts_like_an_id_is_kept(self):
        touch(self.q / "done" / "t_shirt-lane.md", NOW)
        self.assertEqual([r["name"] for r in self.items()], ["t_shirt-lane"])

    def test_never_opens_an_item_file(self):
        touch(self.q / "done" / "gamma-lane.md", NOW)
        real_open, opened = builtins.open, []

        def spy(p, *a, **k):
            if str(p).endswith(".md"):
                opened.append(str(p))
            return real_open(p, *a, **k)

        with mock.patch("builtins.open", spy), mock.patch("io.open", spy):
            got = self.items()
        self.assertEqual([r["name"] for r in got], ["gamma-lane"])
        self.assertEqual(opened, [])

    def test_since_drops_done_and_failed_items_older_than_it_only(self):
        touch(self.q / "queue" / "old-queued.md", NOW - 9 * H)
        touch(self.q / "running" / "old-running.md", NOW - 9 * H)
        touch(self.q / "done" / "old-done.md", NOW - 9 * H)
        touch(self.q / "done" / "new-done.md", NOW - 1 * H)
        touch(self.q / "failed" / "old-failed.md", NOW - 9 * H)
        touch(self.q / "failed" / "new-failed.md", NOW - 1 * H)
        names = sorted(r["name"] for r in self.items(since=NOW - 5 * H))
        self.assertEqual(names, ["new-done", "new-failed", "old-queued", "old-running"])

    def test_no_dir_configured_missing_dir_or_a_file_in_its_place_is_empty(self):
        self.assertEqual(self.items(), [])                 # configured but not there
        self.q.write_text("not a dir")
        self.assertEqual(self.items(), [])
        self.cfg.write_text("{}")
        self.assertEqual(self.items(), [])

    def test_never_raises(self):
        touch(self.q / "done" / "gamma-lane.md", NOW)
        with mock.patch.object(Path, "iterdir", side_effect=PermissionError("denied")):
            self.assertEqual(self.items(), [])
        for bad in ("yesterday", object(), float("nan"), True):
            self.assertIsInstance(self.items(since=bad), list)


if __name__ == "__main__":
    unittest.main()
