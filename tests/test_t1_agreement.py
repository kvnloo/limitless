"""limitless-t1-check: a fixed set of synthetic labeler prompts, run once each through LocalModelLabeler's own
call path, compared with the rule label. Fake model executables written into temp dirs stand in for a model:
no download, no network, no GPU. Words only in the text; the counts are for --json."""
import hermetic_env  # noqa: F401  (first import: isolates HOME, see tests/hermetic_env.py)
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from limitless import labeler, t1_agreement as ta  # noqa: E402

# One fake model: reads the labeler's prompt on stdin and answers by its mode (argv[1]).
FAKE = """#!{python} -I
import os, re, sys, time
sys.path.insert(0, {root!r})
from limitless import labeler
mode = sys.argv[1]
prompt = sys.stdin.read()
kind = re.search(r"Label one (\\S+) value", prompt).group(1)
allowed = re.search(r"from this set: ([^\\n]*?)\\.\\n", prompt).group(1).split(", ")
value = float(re.search(r"Value: (\\S+)", prompt).group(1))
rule = labeler.rule_label(kind, value)
log = os.environ.get("FAKE_LOG")
if log:
    with open(log, "a") as f:
        f.write(str(os.getpid()) + "\\n")
if mode == "agree":
    print(rule)
elif mode == "wrong":
    print([w for w in allowed if w != rule][0])
elif mode == "digits":
    print("7 hours")
elif mode == "hang":
    time.sleep(60)
    print(rule)
elif mode == "fail":
    print(rule)
    sys.exit(3)
elif mode == "sleep only":
    print(rule if kind == "sleep_h" else "about 4")
"""


class Base(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.log = self.dir / "calls.log"

    def model(self, mode):
        """A fake model executable for one mode, as the command line an operator would set."""
        path = self.dir / ("fake-model-" + mode.replace(" ", "-"))
        path.write_text(FAKE.format(python=sys.executable, root=str(ROOT)))
        path.chmod(0o755)
        return f'"{path}" "{mode}"'

    def calls(self):
        return self.log.read_text().split() if self.log.exists() else []

    def check(self, mode, **kw):
        with mock.patch.dict(os.environ, {"FAKE_LOG": str(self.log)}):
            return ta.check(self.model(mode), **kw)

    def assert_words_only(self, result):
        self.assertNotRegex(ta.text(result), r"\d")


class FixedSyntheticSet(Base):
    def test_every_kind_with_a_rule_and_every_answerable_word_is_covered(self):
        kinds = {k for k, _ in ta.CASES}
        self.assertEqual(kinds, set(labeler.RULES))
        for kind, words in labeler.ALLOWED.items():
            want = {w for w in words if w not in ("missing", "no data")}
            got = {labeler.rule_label(k, v) for k, v in ta.CASES if k == kind}
            self.assertEqual(got, want, kind)

    def test_the_prompts_are_the_labelers_own(self):
        p = ta.prompts()
        self.assertEqual(len(p), len(ta.CASES))
        self.assertEqual(p[0], labeler.PROMPT.format(kind=ta.CASES[0][0], value=ta.CASES[0][1],
                                                     allowed=", ".join(ta.answerable(ta.CASES[0][0]))))


class Verdicts(Base):
    def test_a_model_that_always_agrees_agrees_on_all_checks(self):
        r = self.check("agree")
        self.assertEqual(r["verdict"], "all")
        self.assertEqual(r["words"], "agrees on all checks")
        self.assertEqual((r["agrees"], r["disagrees"], r["no_answer"]), (len(ta.CASES), 0, 0))
        self.assertEqual(set(r["kinds"].values()), {"agrees"})
        self.assertEqual(len(self.calls()), len(ta.CASES), "one call per prompt")
        self.assert_words_only(r)
        self.assertIn("agrees on all checks", ta.text(r))

    def test_a_model_that_says_the_wrong_allowed_word_agrees_on_few(self):
        r = self.check("wrong")
        self.assertEqual((r["verdict"], r["words"]), ("few", "agrees on few checks"))
        self.assertEqual((r["agrees"], r["disagrees"]), (0, len(ta.CASES)))
        self.assertEqual(set(r["kinds"].values()), {"disagrees"})
        self.assert_words_only(r)

    def test_digit_output_counts_as_no_answer(self):
        r = self.check("digits")
        self.assertEqual(r["no_answer"], len(ta.CASES))
        self.assertEqual(set(r["kinds"].values()), {"no answer"})
        self.assertEqual(r["words"], "unknown: every call failed")
        self.assert_words_only(r)

    def test_digits_on_some_kinds_give_few_with_per_kind_words(self):
        r = self.check("sleep only")
        self.assertEqual(r["verdict"], "few")
        self.assertEqual(r["kinds"]["sleep_h"], "agrees")
        self.assertEqual(r["kinds"]["readiness"], "no answer")
        self.assertIn("sleep_h: agrees", ta.text(r))

    def test_a_hanging_model_is_killed_and_counted_as_no_answer(self):
        t = time.monotonic()
        r = self.check("hang", timeout_s=0.5)
        self.assertLess(time.monotonic() - t, 30)
        self.assertEqual(r["no_answer"], len(ta.CASES))
        self.assertEqual(r["words"], "unknown: every call failed")
        pids = [int(p) for p in self.calls()]
        self.assertEqual(len(pids), len(ta.CASES))
        for pid in pids:
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    def test_a_non_zero_exit_is_no_answer(self):
        r = self.check("fail")
        self.assertEqual((r["no_answer"], r["words"]), (len(ta.CASES), "unknown: every call failed"))

    def test_the_labelers_default_timeout_is_used(self):
        seen = []
        real = labeler.LocalModelLabeler.__init__

        def spy(self_, cmd, timeout_s=labeler.TIMEOUT_S):
            seen.append(timeout_s)
            real(self_, cmd, timeout_s)
        with mock.patch.object(labeler.LocalModelLabeler, "__init__", spy):
            self.check("agree")
        self.assertEqual(seen, [labeler.TIMEOUT_S])

    def test_most_is_more_than_half(self):
        n = len(ta.CASES)
        self.assertEqual(ta.verdict(n, n), "all")
        self.assertEqual(ta.verdict(n // 2 + 1, n), "most")
        self.assertEqual(ta.verdict(n // 2, n), "few")
        self.assertEqual(ta.verdict(0, n), "few")


class Unknown(Base):
    def boom(self):
        b = mock.Mock(side_effect=AssertionError("a process was started"))
        return mock.patch("subprocess.Popen", b), mock.patch("subprocess.run", b)

    def test_no_command_set_is_unknown_and_nothing_runs(self):
        p1, p2 = self.boom()
        with p1, p2:
            for cmd in (None, "", "   "):
                r = ta.check(cmd)
                self.assertEqual(r["words"], "unknown: no local model command set")
                self.assert_words_only(r)

    def test_a_broken_command_is_unknown_and_nothing_runs(self):
        p1, p2 = self.boom()
        with p1, p2:
            self.assertEqual(ta.check('"unclosed')["words"], "unknown: the command line cannot be read")
            self.assertEqual(ta.check(str(self.dir / "no-such-model-7"))["words"],
                             "unknown: the command's program does not exist")


if __name__ == "__main__":
    unittest.main()
