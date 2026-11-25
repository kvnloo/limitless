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


def units(text):
    """{"<name>.service": {"Section": {"Key": "value"}}, ...} from the printed text: each unit starts with a
    `# <name>.service` or `# <name>.timer` line."""
    out, unit, section = {}, None, None
    for line in text.splitlines():
        if line.startswith("# ") and line.endswith((".service", ".timer")):
            unit = out.setdefault(line[2:], {})
        elif line.startswith("[") and line.endswith("]"):
            section = unit.setdefault(line[1:-1], {})
        elif "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            section[k] = v
    return out


def systemd_words(value):
    """Split an ExecStart= value the way systemd does for the forms the printer uses: bare words and one
    double-quoted word with C escapes; then %% -> % and $$ -> $."""
    words, i = [], 0
    while i < len(value):
        if value[i] == " ":
            i += 1
            continue
        if value[i] == '"':
            i, w = i + 1, ""
            while value[i] != '"':
                if value[i] == "\\":
                    w += {"\\": "\\", '"': '"', "'": "'"}[value[i + 1]]
                    i += 2
                else:
                    w += value[i]
                    i += 1
            i += 1
        else:
            j = value.find(" ", i)
            j = len(value) if j < 0 else j
            w, i = value[i:j], j
        words.append(unescape_specifiers(w))
    return words


def unescape_specifiers(word):
    """%% -> % and $$ -> $. A lone % or $ is refused: systemd would expand it as a specifier or a variable,
    so the shell line would no longer be the one printed."""
    out, i = "", 0
    while i < len(word):
        c = word[i]
        if c in "%$":
            if word[i + 1:i + 2] != c:
                raise AssertionError(f"systemd would expand the lone {c!r} at {i} in {word!r}")
            i += 2
        else:
            i += 1
        out += c
    return out


class Systemd(Base):
    def units(self, *args):
        return units(self.schedule("--kind", "systemd", "--label", LABEL, *args))

    def test_a_oneshot_service_and_a_timer(self):
        got = self.units("--out", OUT, "--every", "60")
        self.assertEqual(sorted(got), [LABEL + ".service", LABEL + ".timer"])
        self.assertEqual(got[LABEL + ".service"]["Service"]["Type"], "oneshot")
        timer = got[LABEL + ".timer"]
        self.assertEqual(timer["Timer"]["OnUnitActiveSec"], "60min")
        self.assertIn("OnBootSec", timer["Timer"])
        self.assertEqual(timer["Timer"]["Unit"], LABEL + ".service")
        self.assertEqual(timer["Install"]["WantedBy"], "timers.target")

    def test_the_interval_is_the_minutes_given(self):
        for every in (5, 90, 1440):
            got = self.units("--out", OUT, "--every", str(every))
            self.assertEqual(got[LABEL + ".timer"]["Timer"]["OnUnitActiveSec"], f"{every}min")

    def test_exec_start_runs_the_writer_then_scp(self):
        got = self.units("--out", OUT, "--every", "60", "--copy-to", DEST, "--db", "/tmp/example/a.db")
        words = systemd_words(got[LABEL + ".service"]["Service"]["ExecStart"])
        self.assertEqual(self.sh_steps(words), [writer(OUT, ["/tmp/example/a.db"]), ["scp", "-q", "-p", OUT, DEST]])

    def test_a_space_a_quote_a_dollar_and_a_percent_survive_quoting(self):
        odd_db = '/tmp/example/50% "of" $HOME/a b\\c.db'
        got = self.units("--out", ODD, "--every", "60", "--copy-to", DEST, "--db", odd_db)
        words = systemd_words(got[LABEL + ".service"]["Service"]["ExecStart"])
        self.assertEqual(self.sh_steps(words), [writer(ODD, [odd_db]), ["scp", "-q", "-p", ODD, DEST]])


class Refusals(Base):
    """Exit 2, one line on stderr naming the flag, nothing on stdout, no traceback, for both kinds."""

    def assert_refused(self, flag, *args):
        for kind in ("launchd", "systemd"):
            r = self.run_cli("schedule", "--print", "--kind", kind, *args)
            self.assertEqual(r.returncode, 2, (kind, args, r.stdout))
            self.assertEqual(r.stdout, "")
            self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
            self.assertNotIn("Traceback", r.stderr)
            self.assertIn("limitless-owner-beacon: refused:", r.stderr)
            self.assertIn(flag, r.stderr)
            self.assertEqual(sorted(self.home.iterdir()), [])

    def test_every_under_5_or_over_1440_or_not_a_number(self):
        for every in ("4", "0", "1441", "100000", "-5", "1.5", "an hour", "６０"):
            self.assert_refused("--every", "--out", OUT, "--every", every)

    def test_the_bounds_themselves_are_fine(self):
        for every in ("5", "1440"):
            self.schedule("--kind", "systemd", "--out", OUT, "--every", every)

    def test_copy_to_without_a_colon(self):
        for dest in ("user@example-host", "/tmp/example/beacons/b.json"):
            self.assert_refused("--copy-to", "--out", OUT, "--every", "60", "--copy-to", dest)

    def test_copy_to_that_scp_would_read_as_an_option(self):
        self.assert_refused("--copy-to", "--out", OUT, "--every", "60", "--copy-to", "-oProxyCommand=x:y")

    def test_a_relative_out(self):
        for out in ("owner-beacon.json", "cache/owner-beacon.json", "~/owner-beacon.json", "./b.json"):
            self.assert_refused("--out", "--out", out, "--every", "60")

    def test_a_relative_db_or_one_with_the_path_separator(self):
        for db in ("a.db", "/tmp/example/a.db" + os.pathsep + "/tmp/example/b.db"):
            self.assert_refused("--db", "--out", OUT, "--every", "60", "--db", db)

    def test_a_label_that_is_not_a_plain_name(self):
        for label in ("org/example", "has space", "-leading", "a;b"):
            self.assert_refused("--label", "--out", OUT, "--every", "60", "--label", label)

    def test_a_value_with_a_newline(self):
        self.assert_refused("newline", "--out", "/tmp/example/a\nb.json", "--every", "60")
        self.assert_refused("newline", "--out", OUT, "--every", "60", "--copy-to", "user@example-host:/tmp/a\nb")
        self.assert_refused("newline", "--out", OUT, "--every", "60", "--db", "/tmp/example/a\rb.db")
        self.assert_refused("newline", "--out", OUT, "--every", "60", "--label", "org.example\nx")
        self.assert_refused("newline", "--out", OUT, "--every", "60\n")

    def test_bad_arguments_are_one_usage_line(self):
        for args in (("schedule",), ("schedule", "--kind", "launchd", "--out", OUT, "--every", "60"),
                     ("schedule", "--print", "--kind", "cron", "--out", OUT, "--every", "60"),
                     ("schedule", "--print", "--kind", "launchd", "--every", "60"),
                     ("schedule", "--print", "--kind", "launchd", "--out", OUT),
                     ("schedule", "--print", "--kind", "launchd", "--out", OUT, "--every", "60", "--bogus", "x"),
                     ("schedule", "--print", "--kind", "launchd", "--out", OUT, "--out", OUT, "--every", "60")):
            r = self.run_cli(*args)
            self.assertEqual((r.returncode, r.stdout), (2, ""), args)
            self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
            self.assertTrue(r.stderr.startswith("usage: limitless-owner-beacon schedule --print"), r.stderr)


class Help(Base):
    def test_help_says_it_only_prints(self):
        for args in (("--help",), ("schedule", "--help")):
            r = self.run_cli(*args)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("schedule --print --kind launchd|systemd", r.stdout)
            self.assertIn("never writes, loads, enables or runs anything", r.stdout)


if __name__ == "__main__":
    unittest.main()
