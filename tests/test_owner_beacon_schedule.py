"""bin/limitless-owner-beacon schedule --print: the operator's scheduled write + copy as text (a launchd plist or
systemd user units). It only prints; every host-specific value comes from the arguments.

Synthetic paths only (/tmp/example/..., user@example-host:...). Nothing is written, loaded or run; no network.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import os
import plistlib
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "limitless-owner-beacon"
OUT = "/tmp/example/cache/owner-beacon.json"
DEST = "user@example-host:/tmp/example/state/beacons/this-machine.json"
ODD = "/tmp/example/it's a dir/owner beacon.json"   # a space and a single quote
LABEL = "org.example.owner-beacon"


def writer(out, dbs=()):
    """The writer's argv the printed job runs: this interpreter, this checkout's script, write --out."""
    argv = [sys.executable, str(CLI.resolve()), "write", "--out", out]
    return argv + (["--dbs", os.pathsep.join(dbs)] if dbs else [])


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.env = {"PATH": os.environ.get("PATH", ""), "HOME": str(self.home),
                    "LIMITLESS_STATE": str(self.home / "state"), "LIMITLESS_CONFIG": str(self.home / "none.json")}

    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-I", str(CLI), *args], capture_output=True, text=True,
                              env=child_env(self.env), cwd=str(self.home), timeout=30)

    def schedule(self, *args):
        r = self.run_cli("schedule", "--print", *args)
        self.assertEqual((r.returncode, r.stderr), (0, ""), r.stdout)
        self.assertEqual(sorted(self.home.iterdir()), [], "printing must write nothing")
        return r.stdout

    def plist(self, *args):
        return plistlib.loads(self.schedule("--kind", "launchd", *args).encode())

    def sh_steps(self, program_arguments):
        """The /bin/sh -c line split back into its argvs, one per step joined by &&."""
        self.assertEqual(program_arguments[:2], ["/bin/sh", "-c"])
        self.assertEqual(len(program_arguments), 3)
        words = shlex.split(program_arguments[2])
        steps, cur = [], []
        for w in words:
            if w == "&&":
                steps.append(cur)
                cur = []
            else:
                cur.append(w)
        return steps + [cur]


class Launchd(Base):
    def test_plist_round_trip_gives_the_interval_in_seconds(self):
        for every in (5, 60, 1440):
            got = self.plist("--out", OUT, "--every", str(every))
            self.assertEqual(got["StartInterval"], every * 60)

    def test_writer_only_without_copy_to(self):
        got = self.plist("--out", OUT, "--every", "60", "--label", LABEL)
        self.assertEqual(got["Label"], LABEL)
        self.assertEqual(self.sh_steps(got["ProgramArguments"]), [writer(OUT)])

    def test_writer_then_scp_with_copy_to(self):
        got = self.plist("--out", OUT, "--every", "60", "--copy-to", DEST,
                         "--db", "/tmp/example/a.db", "--db", "/tmp/example/b.db")
        self.assertEqual(self.sh_steps(got["ProgramArguments"]),
                         [writer(OUT, ["/tmp/example/a.db", "/tmp/example/b.db"]),
                          ["scp", "-q", "-p", OUT, DEST]])

    def test_a_space_and_a_quote_survive_shell_quoting(self):
        dest = "user@example-host:/tmp/example/it's here/b.json"
        got = self.plist("--out", ODD, "--every", "60", "--copy-to", dest, "--db", "/tmp/example/a b's.db")
        self.assertEqual(self.sh_steps(got["ProgramArguments"]),
                         [writer(ODD, ["/tmp/example/a b's.db"]), ["scp", "-q", "-p", ODD, dest]])

    def test_label_has_a_neutral_default(self):
        label = self.plist("--out", OUT, "--every", "60")["Label"]
        self.assertTrue(label)
        for word in ("example", "user", "host", str(self.home)):
            self.assertNotIn(word, label)


class Help(Base):
    def test_help_says_it_only_prints(self):
        for args in (("--help",), ("schedule", "--help")):
            r = self.run_cli(*args)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("schedule --print --kind launchd|systemd", r.stdout)
            self.assertIn("never writes, loads, enables or runs anything", r.stdout)


if __name__ == "__main__":
    unittest.main()
