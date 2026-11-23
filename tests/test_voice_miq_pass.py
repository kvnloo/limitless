"""limitless/voice_miq.py run(): hand a spoken MIQ answer to capture.py, once per MIQ.

Synthetic state and synthetic z0live session files only (the sessions/SESSION_ID.jsonl export shape).
Config ``voice_miq``: off (default) | dry_run | write. Nothing sends.
"""
import json
import os
import re
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from limitless import capture, jobs, jobs_runner, voice_miq  # noqa: E402

NOW = 1894708800.0
SENT = NOW - 1800.0
Q = jobs_runner.MIQ_QUESTION


def rows(*turns, start=SENT + 60):
    kinds = {"a": "assistant_transcript", "u": "user_transcript"}
    return [{"id": i + 1, "session_id": "s-test", "ts": start + i, "type": kinds[w], "text": t, "data": {}}
            for i, (w, t) in enumerate(turns)]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.st, self.sessions, self.cfg = d / "state", d / "z0live" / "sessions", d / "config.json"
        self.st.mkdir()
        self.sessions.mkdir(parents=True)
        self.env = {"LIMITLESS_STATE": str(self.st), "LIMITLESS_CONFIG": str(self.cfg)}
        self.config("write")
        self.sent(SENT)

    def tearDown(self):
        self.tmp.cleanup()

    def config(self, mode, sessions=True):
        cfg = {} if mode is None else {"voice_miq": mode}
        if sessions:
            cfg["voice_miq_sessions"] = str(self.sessions)
        self.cfg.write_text(json.dumps(cfg))

    def sent(self, t, job="miq"):
        with open(self.st / jobs_runner.SENT_LOG, "a") as f:
            f.write(json.dumps({"t": t, "k": "k-test", "job": job}) + "\n")

    def session(self, name, events, mtime=None):
        p = self.sessions / name
        p.write_text("".join(json.dumps(e) + "\n" for e in events))
        if mtime is not None:
            os.utime(p, (mtime, mtime))
        return p

    def answered(self):
        self.session("s-test.jsonl", rows(("u", "hey"), ("a", "One thing: " + Q), ("u", "yes"),
                                          ("u", "the draft review"), ("a", "Saved.")))

    def run_pass(self, **kw):
        return voice_miq.run(self.st, NOW, env=self.env, **kw)

    def captures(self):
        p = self.st / capture.FILE
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def files(self):
        return sorted(p.name for p in self.st.iterdir())


class Modes(Base):
    def test_kind_is_known_to_capture(self):
        self.assertIn("miq_answer", capture.KINDS)

    def test_default_is_off(self):
        self.assertEqual(voice_miq.mode({}), voice_miq.OFF)
        for bad in ("on", "yes", 1, None, True):
            self.assertEqual(voice_miq.mode({"voice_miq": bad}), voice_miq.OFF, bad)
        self.assertEqual(voice_miq.mode({"voice_miq": " Dry_Run "}), voice_miq.DRY_RUN)

    def test_off_writes_nothing_and_has_no_row(self):
        self.answered()
        self.config(None)
        before = self.files()
        self.assertIsNone(self.run_pass())
        self.assertEqual(self.files(), before)

    def test_dry_run_writes_nothing_and_says_so_in_words(self):
        self.answered()
        self.config("dry_run")
        before = self.files()
        row = self.run_pass()
        self.assertEqual(self.files(), before)
        self.assertEqual(row["job"], voice_miq.TITLE)
        self.assertEqual(row["action"], voice_miq.WOULD)
        self.assertIn("dry run", row["reason"])
        self.assertIn("nothing written", row["reason"])
        self.assertNotIn("draft review", row["reason"])

    def test_write_appends_exactly_one_capture_row(self):
        self.answered()
        row = self.run_pass()
        self.assertEqual(row["action"], voice_miq.CAPTURED, row)
        got = self.captures()
        self.assertEqual(len(got), 1)
        self.assertEqual({k: got[0][k] for k in ("text", "source", "kind")},
                         {"text": "yes the draft review", "source": "z0live", "kind": "miq_answer"})
        self.assertNotIn("draft review", row["reason"])

    def test_write_keeps_earlier_captures(self):
        capture.capture(self.st, "an older idea", NOW - 7200)
        self.answered()
        self.run_pass()
        self.assertEqual([c["text"] for c in self.captures()], ["an older idea", "yes the draft review"])

    def test_mark_is_epoch_only_and_private(self):
        self.answered()
        self.run_pass()
        mark = self.st / voice_miq.MARK
        self.assertEqual(stat.S_IMODE(mark.stat().st_mode), 0o600)
        data = json.loads(mark.read_text())
        self.assertEqual(data, {"miq_sent_at": SENT, "captured_at": NOW})
        self.assertNotIn("review", mark.read_text())

    def test_second_pass_does_nothing(self):
        self.answered()
        self.run_pass()
        mark = (self.st / voice_miq.MARK).read_text()
        row = self.run_pass()
        self.assertEqual(row["action"], voice_miq.NOTHING)
        self.assertIn("already", row["reason"])
        self.assertEqual(len(self.captures()), 1)
        self.assertEqual((self.st / voice_miq.MARK).read_text(), mark)

    def test_the_next_miq_is_captured_again(self):
        self.answered()
        self.run_pass()
        later = NOW + 86400
        self.sent(later - 600)
        self.session("s-next.jsonl", rows(("a", Q), ("u", "no"), start=later - 300))
        row = voice_miq.run(self.st, later, env=self.env)
        self.assertEqual(row["action"], voice_miq.CAPTURED, row)
        self.assertEqual([c["text"] for c in self.captures()], ["yes the draft review", "no"])


class Nothing(Base):
    def assert_nothing(self, row, words):
        self.assertEqual(row["action"], voice_miq.NOTHING, row)
        self.assertIn(words, row["reason"])
        self.assertEqual(self.captures(), [])
        self.assertFalse((self.st / voice_miq.MARK).exists())

    def test_no_miq_sent(self):
        (self.st / jobs_runner.SENT_LOG).write_text(json.dumps({"t": SENT, "k": "x", "job": "wake_brief"}) + "\n")
        self.answered()
        self.assert_nothing(self.run_pass(), "no MIQ")

    def test_miq_too_old(self):
        (self.st / jobs_runner.SENT_LOG).write_text("")
        self.sent(NOW - jobs.MIQ_STALE_S - 1)
        self.answered()
        self.assert_nothing(self.run_pass(), "no MIQ")

    def test_not_asked_in_a_call(self):
        self.session("s-test.jsonl", rows(("u", "hey"), ("a", "Hi."), ("u", "bye")))
        self.assert_nothing(self.run_pass(), "not answered")

    def test_asked_but_silent(self):
        self.session("s-test.jsonl", rows(("a", Q)))
        self.assert_nothing(self.run_pass(), "not answered")

    def test_a_call_before_the_miq_was_sent_does_not_count(self):
        self.session("s-old.jsonl", rows(("a", Q), ("u", "yes"), start=SENT - 600))
        self.assert_nothing(self.run_pass(), "not answered")

    def test_no_sessions_dir_configured(self):
        self.answered()
        self.config("write", sessions=False)
        self.assert_nothing(self.run_pass(), "not configured")

    def test_sessions_dir_missing(self):
        self.answered()
        for p in self.sessions.iterdir():
            p.unlink()
        self.sessions.rmdir()
        self.assert_nothing(self.run_pass(), "does not exist")

    def test_broken_lines_are_skipped(self):
        p = self.session("s-test.jsonl", rows(("a", Q), ("u", "yes")))
        with open(p, "a") as f:
            f.write('{"id": 9, "type": "user_trans')
        self.assertEqual(self.run_pass()["action"], voice_miq.CAPTURED)

    def test_no_state_dir(self):
        self.answered()
        row = voice_miq.run(self.st / "missing", NOW, env=self.env)
        self.assertEqual(row["action"], voice_miq.NOTHING)


class RunOnce(Base):
    def test_off_adds_no_row(self):
        self.config(None)
        self.answered()
        titles = [r["job"] for r in jobs_runner.run_once(self.st, NOW, env=self.env)]
        self.assertNotIn(voice_miq.TITLE, titles)

    def test_write_mode_in_a_dry_pass_is_a_dry_run(self):
        self.answered()
        out = jobs_runner.run_once(self.st, NOW, env=self.env, dry_run=True)
        self.assertEqual(out[-1]["job"], voice_miq.TITLE)
        self.assertEqual(out[-1]["action"], voice_miq.WOULD)
        self.assertEqual(self.captures(), [])

    def test_write_mode_in_a_send_pass_captures_once(self):
        self.answered()
        jobs_runner.run_once(self.st, NOW, env=self.env, dry_run=False, push=lambda t, b: "telegram")
        jobs_runner.run_once(self.st, NOW, env=self.env, dry_run=False, push=lambda t, b: "telegram")
        self.assertEqual([c["kind"] for c in self.captures()], ["miq_answer"])


class Digits(Base):
    """Digit walk: every label and every reason this pass can say is words only."""

    def reasons(self):
        out = []
        for mode in ("dry_run", "write"):
            for setup in ("answered", "silent", "none", "stale", "nosessions", "twice"):
                self.tearDown()
                self.setUp()
                self.config(mode, sessions=setup != "nosessions")
                if setup == "answered" or setup == "twice":
                    self.answered()
                elif setup == "silent":
                    self.session("s.jsonl", rows(("a", Q)))
                elif setup in ("none", "stale"):
                    (self.st / jobs_runner.SENT_LOG).write_text("")
                    if setup == "stale":
                        self.sent(NOW - jobs.MIQ_STALE_S - 1)
                out.append(self.run_pass())
                if setup == "twice":
                    out.append(self.run_pass())
        self.tearDown()
        self.setUp()
        self.session("s-long.jsonl", rows(("a", Q), ("u", "word " * (capture.MAX_CHARS // 4))))
        out.append(self.run_pass())
        self.assertEqual(out[-1]["action"], voice_miq.NOTHING)
        self.assertFalse((self.st / voice_miq.MARK).exists())
        return out

    def test_every_reason_is_digit_free(self):
        for row in self.reasons():
            for v in row.values():
                self.assertIsNone(re.search(r"\d", v), row)

    def test_every_label_is_digit_free(self):
        # SOURCE is the capture row's source field (the app's name), never said in a reason
        labels = [v for k, v in vars(voice_miq).items()
                  if isinstance(v, str) and not k.startswith("__") and k != "SOURCE"]
        self.assertTrue(labels)
        for v in labels:
            self.assertIsNone(re.search(r"\d", v), v)


if __name__ == "__main__":
    unittest.main()
