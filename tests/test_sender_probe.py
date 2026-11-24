"""bin/limitless-sender-probe: one recorded ``hermes -p <name> send --list telegram`` settles an unknown sender candidate.

    sender_probe.probe(cfg, env, hermes_home=None, timeout=...) -> [(name, verdict words, fingerprint)]
    sender_probe.save(state_dir, results, now)                   # sender-probe.json, atomic, 0600
    push_sender.candidates(...)                                   # a matching probe settles a SECRET_SOURCE candidate

Synthetic Hermes homes in temp dirs, synthetic profile names (alpha, delta, ...), a fake ``hermes`` script whose
output copies the shape of NousResearch/hermes-agent hermes_cli/send_cmd.py ``_list_targets``. Every child gets
env=child_env(...). Nothing is ever sent.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from limitless import doctor, push_reach, push_recovery as pr, push_sender as ps, sender_probe as sp  # noqa: E402
from hermes_profile_fixture import ready_profile  # noqa: E402

NOW = 1894708800.0   # a fixed made-up clock
H = 3600.0
FAIL = ps.NO_SENDER_HOW
SECRET_YAML = "secrets:\n  telegram:\n    source: synthetic-vault\n"
MARK = "synthetic-stdout-marker"   # the fake prints it; it must never reach the file or the words
BIN = ROOT / "bin" / "limitless-sender-probe"

# The fake hermes: FAKE_HERMES_MODE picks the answer; every call is appended to FAKE_HERMES_CALLS.
FAKE = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_HERMES_CALLS"
case "$FAKE_HERMES_MODE" in
  none)
    echo "hermes send: no targets found for platform 'telegram'. Configured: (none) MARK" >&2
    exit 1 ;;
  targets)
    echo "telegram:"
    echo "  telegram:MARK  [placeholder-chat]"
    echo
    exit 0 ;;
  sleep)
    exec sleep 5 ;;
  other)
    echo "hermes send: some other failure MARK" >&2
    exit 1 ;;
  *)
    exit 3 ;;
esac
""".replace("MARK", MARK)


def log_row(at, how):
    return {"at": int(at), "tag": "limitless", "cls": "report", "title": "Wake-up brief", "body": "Synthetic body.",
            "how": how}


class Home(unittest.TestCase):
    """A synthetic Hermes home (``default`` keeps its token in a secret source) and a fake hermes on PATH."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.hermes = self.dir / "hermes"
        (self.hermes / "profiles").mkdir(parents=True)
        (self.hermes / "config.yaml").write_text(SECRET_YAML)
        self.st = self.dir / "state"
        self.st.mkdir()
        fakebin = self.dir / "fakebin"
        fakebin.mkdir()
        self.calls = self.dir / "hermes-calls"
        fake = fakebin / "hermes"
        fake.write_text(FAKE)
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        self.path = f"{fakebin}{os.pathsep}{os.environ.get('PATH', '')}"
        self.cfg = {"push_profile": "default", "push_to": "telegram"}
        self.mode("none")

    def mode(self, mode):
        self.env = child_env(HERMES_HOME=str(self.hermes), HOME=str(self.dir), PATH=self.path,
                             LIMITLESS_STATE=str(self.st), FAKE_HERMES_MODE=mode,
                             FAKE_HERMES_CALLS=str(self.calls))

    def called(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def vault(self, name):
        home = self.hermes / "profiles" / name
        home.mkdir(parents=True)
        (home / "config.yaml").write_text(SECRET_YAML)
        return home

    def botless(self, name):
        home = self.hermes / "profiles" / name
        home.mkdir(parents=True)
        (home / ".env").write_text("TELEGRAM_HOME_CHANNEL=placeholder-chat\n")
        return home

    def probe(self, timeout=sp.TIMEOUT_S):
        return sp.probe(self.cfg, self.env, timeout=timeout)

    def probe_and_save(self, timeout=sp.TIMEOUT_S):
        got = self.probe(timeout)
        sp.save(self.st, got, NOW)
        return got

    def candidates(self):
        return ps.candidates(self.cfg, self.env)

    def verdicts(self, got):
        return {name: words for name, words, _ in got}


class Verdicts(Home):
    def test_no_targets_output_is_no_targets(self):
        self.assertEqual(self.verdicts(self.probe()), {"default": sp.NO_TARGETS})
        self.assertEqual(self.called(), ["-p default send --list telegram"])

    def test_a_listed_telegram_platform_is_targets_found(self):
        self.mode("targets")
        self.assertEqual(self.verdicts(self.probe()), {"default": sp.TARGETS_FOUND})

    def test_a_timeout_is_the_check_failed(self):
        self.mode("sleep")
        self.assertEqual(self.verdicts(self.probe(timeout=0.5)), {"default": sp.CHECK_FAILED})

    def test_another_non_zero_exit_is_the_check_failed(self):
        self.mode("other")
        self.assertEqual(self.verdicts(self.probe()), {"default": sp.CHECK_FAILED})
        self.mode("unknown-mode")
        self.assertEqual(self.verdicts(self.probe()), {"default": sp.CHECK_FAILED})

    def test_a_missing_binary_is_the_check_failed(self):
        self.cfg = dict(self.cfg, hermes_bin=str(self.dir / "no-such-hermes"))
        self.assertEqual(self.verdicts(self.probe()), {"default": sp.CHECK_FAILED})
        self.assertEqual(self.called(), [])

    def test_config_hermes_bin_is_used(self):
        self.cfg = dict(self.cfg, hermes_bin=str(self.dir / "fakebin" / "hermes"))
        self.env = dict(self.env, PATH="/nonexistent-dir")
        self.assertEqual(self.verdicts(self.probe()), {"default": sp.NO_TARGETS})

    def test_only_unknown_candidates_are_probed(self):
        ready_profile(self.hermes / "profiles" / "alpha")   # READY
        self.botless("gamma")                               # NO_TOKEN
        self.vault("delta")                                 # SECRET_SOURCE
        self.assertEqual(sorted(self.verdicts(self.probe())), ["default", "delta"])
        self.assertEqual(sorted(self.called()), ["-p default send --list telegram", "-p delta send --list telegram"])

    def test_a_ready_root_is_never_probed(self):
        (self.hermes / "config.yaml").unlink()
        ready_profile(self.hermes)
        self.assertEqual(self.probe(), [])
        self.assertEqual(self.called(), [])


class Saved(Home):
    def read(self):
        return json.loads((self.st / sp.PROBE_FILE).read_text())

    def test_the_file_holds_words_a_time_and_the_fingerprint_only(self):
        self.vault("delta")
        self.probe_and_save()
        data = self.read()
        self.assertEqual(sorted(data), ["default", "delta"])
        self.assertEqual(data["delta"]["verdict"], sp.NO_TARGETS)
        self.assertEqual(data["delta"]["at"], NOW)
        cfg_ns = (self.hermes / "profiles" / "delta" / "config.yaml").stat().st_mtime_ns
        self.assertEqual(data["delta"]["files"], {"config.yaml": cfg_ns, ".env": None})
        mode = stat.S_IMODE((self.st / sp.PROBE_FILE).stat().st_mode)
        self.assertEqual(mode, 0o600)
        self.assertEqual([p.name for p in self.st.iterdir()], [sp.PROBE_FILE])   # no temp file left

    def test_nothing_from_stdout_or_stderr_reaches_the_file(self):
        for mode in ("none", "targets", "other"):
            self.mode(mode)
            self.probe_and_save()
            text = (self.st / sp.PROBE_FILE).read_text()
            self.assertNotIn(MARK, text)
            self.assertNotIn("placeholder-chat", text)
            self.assertNotIn("Configured", text)

    def test_a_failed_check_changes_no_verdict(self):
        self.probe_and_save()
        before = (self.st / sp.PROBE_FILE).read_bytes()
        self.mode("sleep")
        got = self.probe(timeout=0.5)
        self.assertEqual(self.verdicts(got), {"default": sp.CHECK_FAILED})
        sp.save(self.st, got, NOW + H)
        self.assertEqual((self.st / sp.PROBE_FILE).read_bytes(), before)

    def test_a_failed_check_alone_writes_no_verdict(self):
        self.mode("other")
        sp.save(self.st, self.probe(), NOW)
        self.assertNotIn("default", json.loads((self.st / sp.PROBE_FILE).read_text()))


class Applied(Home):
    def test_no_targets_with_matching_files_is_probed_none(self):
        self.assertEqual(self.candidates(), [("default", ps.SECRET_SOURCE)])
        self.probe_and_save()
        self.assertEqual(self.candidates(), [("default", ps.PROBED_NONE)])
        self.assertEqual(ps.PROBED_NONE, "no Telegram target: hermes send found none")
        self.assertEqual(ps.maybe_names(self.candidates()), [])
        self.assertEqual(ps.ready_names(self.candidates()), [])

    def test_targets_found_stays_unknown_with_new_words(self):
        self.mode("targets")
        self.probe_and_save()
        self.assertEqual(self.candidates(), [("default", ps.UNKNOWN_PREFIX + "hermes send lists a Telegram target")])
        self.assertEqual(ps.maybe_names(self.candidates()), ["default"])

    def test_a_touched_config_is_the_old_behaviour(self):
        self.probe_and_save()
        before = (self.hermes / "config.yaml").stat().st_mtime_ns
        os.utime(self.hermes / "config.yaml", ns=(before + 10**9, before + 10**9))
        self.assertEqual(self.candidates(), [("default", ps.SECRET_SOURCE)])

    def test_a_new_env_file_is_the_old_behaviour(self):
        self.probe_and_save()
        (self.hermes / ".env").write_text("SOMETHING_ELSE=1\n")
        self.assertEqual(self.candidates(), [("default", ps.SECRET_SOURCE)])

    def test_a_missing_or_malformed_file_is_the_old_behaviour(self):
        base = self.candidates()
        for text in ("", "not json", "[]", '{"default": "no targets"}', '{"default": {"verdict": "no targets"}}',
                     '{"default": {"verdict": "maybe", "at": 1, "files": {"config.yaml": null, ".env": null}}}',
                     '{"default": {"verdict": "no targets", "at": 1, "files": {"config.yaml": true, ".env": null}}}'):
            (self.st / sp.PROBE_FILE).write_text(text)
            self.assertEqual(self.candidates(), base, text)

    def test_only_a_secret_source_answer_is_settled(self):
        self.vault("delta")
        self.probe_and_save()
        (self.hermes / "config.yaml").unlink()    # default now has no token: NO_TOKEN, the record is stale anyway
        ready_profile(self.hermes)                 # and now READY: a stored no-targets never overrides it
        os.utime(self.hermes / ".env", ns=(1, 1))
        got = dict(self.candidates())
        self.assertEqual(got["default"], ps.READY)
        self.assertEqual(got["delta"], ps.PROBED_NONE)

    def test_probed_false_skips_the_file(self):
        self.probe_and_save()
        self.assertEqual(ps.candidates(self.cfg, self.env, probed=False), [("default", ps.SECRET_SOURCE)])

    def test_a_probed_none_is_probed_again(self):
        self.probe_and_save()
        self.mode("targets")
        self.assertEqual(self.verdicts(self.probe()), {"default": sp.TARGETS_FOUND})


class Words(Home):
    """The doctor's rows, the push recovery words and the card hint once a probe applied."""

    def setUp(self):
        super().setUp()
        self.cfg = dict(self.cfg, push_log="push-log.jsonl")
        rows = [log_row(NOW - 5 * H, "telegram"), log_row(NOW - 3 * H, FAIL), log_row(NOW - 2 * H, FAIL)]
        (self.st / "push-log.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def row(self):
        return doctor.sender_candidates_row(self.cfg, self.env, state_dir=self.st)

    def recovery(self):
        return pr.from_state(self.st, self.cfg, NOW, env=self.env)

    def test_the_candidates_row_is_unchanged_until_a_probe_applies(self):
        r = self.row()
        self.assertEqual((r["status"], r["reason"]), (doctor.MISSING, "maybe: default (keeps its token in a secret source)"))
        self.probe_and_save()
        r = self.row()
        self.assertEqual((r["status"], r["reason"]), (doctor.MISSING, "none ready; default: no Telegram target (checked)"))

    def test_the_candidates_row_with_a_ready_profile_and_a_probe(self):
        ready_profile(self.hermes / "profiles" / "alpha")
        self.probe_and_save()
        r = self.row()
        self.assertEqual((r["status"], r["reason"]), (doctor.LIVE, "ready: alpha; default: no Telegram target (checked)"))

    def test_the_candidates_row_for_targets_found(self):
        self.mode("targets")
        self.probe_and_save()
        self.assertEqual(self.row()["reason"], "maybe: default (hermes send lists a Telegram target)")

    def test_no_digit_path_or_target_in_any_row(self):
        self.vault("bot2")
        self.probe_and_save()
        got = self.row()["reason"]
        self.assertEqual(got, "none ready; default, one more whose name holds a digit: no Telegram target (checked)")
        for words in (got, self.recovery()[1], doctor.push_sender_row(self.cfg, self.env)["reason"]):
            self.assertIsNone(re.search(r"\d|/|placeholder|" + MARK, words), words)

    def test_recovery_words_drop_the_probed_name(self):
        self.assertEqual(self.recovery(), (pr.MISSING, pr.WAITING_REPLY + "; profiles that may reach Telegram: default"))
        self.probe_and_save()
        self.assertEqual(self.recovery(), (pr.MISSING, pr.WAITING_REPLY + pr.NO_PROFILE))

    def test_the_card_hint_never_offers_the_probed_name(self):
        self.probe_and_save()
        hint = push_reach.hint(self.cfg, self.st, self.env)
        self.assertEqual(hint, push_reach.REPLY_ANY)
        self.assertNotIn("default", hint)

    def test_a_stale_probe_restores_the_old_recovery_words(self):
        self.probe_and_save()
        before = (self.hermes / "config.yaml").stat().st_mtime_ns
        os.utime(self.hermes / "config.yaml", ns=(before + 10**9, before + 10**9))
        self.assertEqual(self.recovery(), (pr.MISSING, pr.WAITING_REPLY + "; profiles that may reach Telegram: default"))


class Cli(Home):
    def run_bin(self, *args, env=None):
        return subprocess.run([sys.executable, "-I", str(BIN), *args], capture_output=True, text=True, timeout=60,
                              env=child_env(self.env if env is None else env))

    def test_dry_run_prints_words_and_writes_nothing(self):
        before = sorted(p.name for p in self.st.iterdir())
        r = self.run_bin()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "default: no targets\ndry run: nothing saved (pass --write to save)\n")
        self.assertNotIn(MARK, r.stdout + r.stderr)
        self.assertEqual(sorted(p.name for p in self.st.iterdir()), before)
        self.assertEqual(self.called(), ["-p default send --list telegram"])

    def test_write_saves_the_file(self):
        self.mode("targets")
        r = self.run_bin("--write")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "default: targets found\nsaved\n")
        self.assertNotIn(MARK, r.stdout + r.stderr)
        data = json.loads((self.st / sp.PROBE_FILE).read_text())
        self.assertEqual(data["default"]["verdict"], sp.TARGETS_FOUND)

    def test_nothing_unknown_runs_nothing(self):
        (self.hermes / "config.yaml").unlink()
        ready_profile(self.hermes)
        r = self.run_bin("--write")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "no sender candidate is unknown; nothing to check\n")
        self.assertEqual(self.called(), [])
        self.assertFalse((self.st / sp.PROBE_FILE).exists())

    def test_no_hermes_home(self):
        env = {k: v for k, v in self.env.items() if k != "HERMES_HOME"}
        env["HOME"] = str(self.dir / "nohome")
        env["LIMITLESS_STATE"] = str(self.st)
        r = self.run_bin(env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "no Hermes home is known; nothing to check\n")

    def test_a_bad_argument_is_usage(self):
        r = self.run_bin("--send")
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage: limitless-sender-probe [--write]", r.stderr)
        self.assertEqual(self.called(), [])


class NeverScheduled(unittest.TestCase):
    def test_no_job_or_timer_runs_it(self):
        """Only the operator runs it: the jobs runner, its bin, the plugin and the timer docs never name it."""
        hits = []
        for rel in ("limitless/jobs.py", "limitless/jobs_runner.py", "limitless/plugin.py", "bin/limitless-jobs",
                    "plugin.yaml", "docs/limitless-jobs-systemd.md"):
            text = (ROOT / rel).read_text(errors="ignore")
            if re.search(r"import\s+sender_probe|sender_probe\.|limitless-sender-probe", text):
                hits.append(rel)
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
