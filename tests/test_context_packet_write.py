"""The context packet's one write (config context_packet_path, atomic, mode 0600) and bin/limitless-context-packet
(dry run by default). Synthetic fixtures only (tests/fixtures/state)."""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import context_packet as cp  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "state"
CLI = ROOT / "bin" / "limitless-context-packet"
NOW = 1894708800.0
TODAY = date(2030, 1, 15)


def tree(d: Path):
    return sorted((str(p.relative_to(d)), p.stat().st_mtime_ns, p.stat().st_size) for p in d.rglob("*"))


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.st = self.home / "state"
        shutil.copytree(FIX, self.st)
        self.cfg_file = self.home / "config.json"
        self.env = {"LIMITLESS_CONFIG": str(self.cfg_file)}

    def config(self, **cfg):
        self.cfg_file.write_text(json.dumps(dict({"state": str(self.st)}, **cfg)))

    def main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        code = cp.main(list(argv), env=self.env, home=self.home, now=NOW, today=TODAY, out=out, err=err)
        return code, out.getvalue(), err.getvalue()


class PacketPath(Base):
    def test_unset_is_none(self):
        self.config()
        self.assertIsNone(cp.packet_path(self.env, self.home))

    def test_absolute(self):
        target = self.home / "out" / "packet.json"
        self.config(context_packet_path=str(target))
        self.assertEqual(cp.packet_path(self.env, self.home), target)

    def test_relative_is_in_the_state_dir(self):
        self.config(context_packet_path="context.json")
        self.assertEqual(cp.packet_path(self.env, self.home), self.st / "context.json")

    def test_blank_or_not_text_is_none(self):
        for v in ("", "  ", 7, None, ["a"]):
            self.config(context_packet_path=v)
            self.assertIsNone(cp.packet_path(self.env, self.home), v)


class Write(Base):
    def test_mode_0600_and_the_packet_round_trips(self):
        p = cp.packet(self.st, NOW, TODAY, env=self.env)
        target = self.home / "out" / "packet.json"
        self.assertEqual(cp.write(p, target), str(target))
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertEqual(json.loads(target.read_text()), p)
        self.assertEqual([f.name for f in target.parent.iterdir()], ["packet.json"])   # no temp file left

    def test_replaces_in_place_with_a_rename(self):
        target = self.home / "packet.json"
        target.write_text("old")
        os.chmod(target, 0o644)
        with mock.patch.object(cp.os, "replace", wraps=os.replace) as rep:
            cp.write(cp.packet(self.st, NOW, TODAY, env=self.env), target)
        rep.assert_called_once()
        self.assertEqual(Path(rep.call_args[0][1]), target)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertEqual(json.loads(target.read_text())["schema"], cp.SCHEMA)

    def test_a_failed_write_leaves_the_old_file_and_no_temp(self):
        target = self.home / "packet.json"
        target.write_text("old")
        with mock.patch.object(cp.os, "replace", side_effect=OSError(28, "No space left on device")):
            with self.assertRaises(OSError):
                cp.write(cp.packet(self.st, NOW, TODAY, env=self.env), target)
        self.assertEqual(target.read_text(), "old")
        self.assertEqual(sorted(f.name for f in self.home.iterdir() if f.name.startswith(".")), [])

    def test_publish_writes_only_when_configured(self):
        self.config()
        before = tree(self.home)
        p, path = cp.publish(self.st, NOW, TODAY, env=self.env, home=self.home)
        self.assertIsNone(path)
        self.assertEqual(p["schema"], cp.SCHEMA)
        self.assertEqual(tree(self.home), before)
        self.config(context_packet_path="context.json")
        p, path = cp.publish(self.st, NOW, TODAY, env=self.env, home=self.home)
        self.assertEqual(path, str(self.st / "context.json"))
        self.assertEqual(json.loads((self.st / "context.json").read_text()), p)


class Cli(Base):
    def test_dry_run_by_default_writes_nothing(self):
        self.config(context_packet_path="context.json")
        before = tree(self.home)
        code, out, err = self.main()
        self.assertEqual(code, 0)
        self.assertEqual(tree(self.home), before)
        self.assertIn("sleep: short (proxy, indirect, about four hours ago)", out)
        self.assertIn("window: peak", out)
        self.assertIn("asks: asks waiting on you", out)
        self.assertIn("dry run: nothing written", out)
        self.assertEqual(re.findall(r"\d", out + err), [])   # text mode: words only

    def test_json_is_the_packet_alone_on_stdout(self):
        self.config()
        code, out, err = self.main("--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), cp.packet(self.st, NOW, TODAY, env=self.env))
        self.assertIn("dry run: nothing written", err)

    def test_write_creates_0600(self):
        self.config(context_packet_path="out/context.json")
        code, out, err = self.main("--write")
        self.assertEqual(code, 0, err)
        target = self.st / "out" / "context.json"
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertEqual(json.loads(target.read_text()), cp.packet(self.st, NOW, TODAY, env=self.env))
        self.assertIn("written", out)
        self.assertNotIn(str(self.home), out + err)   # never a path

    def test_write_without_a_path_writes_nothing_and_says_why(self):
        self.config()
        before = tree(self.home)
        code, out, err = self.main("--write", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(tree(self.home), before)
        self.assertIn("context_packet_path", err)
        json.loads(out)

    def test_a_failed_write_exits_one(self):
        self.config(context_packet_path="context.json")
        with mock.patch.object(cp.os, "replace", side_effect=OSError(13, "Permission denied")):
            code, out, err = self.main("--write")
        self.assertEqual(code, 1)
        self.assertIn("not written: Permission denied", err)
        self.assertNotIn(str(self.home), out + err)

    def test_bad_arguments_exit_two(self):
        self.config()
        self.assertEqual(self.main("--send")[0], 2)

    def test_raw_opt_in_is_ignored(self):
        self.config()
        self.env["LIMITLESS_RAW_IN_PROMPT"] = "1"
        code, out, err = self.main()
        self.assertEqual(code, 0)
        self.assertEqual(re.findall(r"\d", out + err), [])

    def test_bin_end_to_end(self):
        self.config(context_packet_path="context.json")
        env = {k: v for k, v in os.environ.items() if not k.startswith("LIMITLESS_")}
        env.update(self.env, HOME=str(self.home), LIMITLESS_RAW_IN_PROMPT="1")
        r = subprocess.run([sys.executable, "-I", str(CLI), "--json"], env=child_env(env), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["schema"], cp.SCHEMA)
        self.assertFalse((self.st / "context.json").exists())
        r = subprocess.run([sys.executable, "-I", str(CLI), "--write"], env=child_env(env), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(stat.S_IMODE((self.st / "context.json").stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
