"""The push-outage recovery end to end, pass by pass, the way a host's timer drives it: limitless-jobs.service runs
`bin/limitless-jobs --ingest --confirm` after each sync row. Five merged pieces meet here: kevin-push's preflight
("log (no sender profile)", push_sender), the outage line on the state card and limitless_status (push_reach),
the owner's whole "push via <profile>" reply writing push-sender.json (sender_ingest_job), the one sender
confirmation (sender_confirm_job) and the once-per-outage recap (outage_recap_job).

    outage -> pass 0 (nothing to do yet) -> owner reply -> pass 1 (sender set, confirmation sent, recap waits)
    -> pass 2 (recap sent once) -> pass 3 + a new sync row (nothing more) -> the card no longer says the outage

Plus: a reply naming a profile that does not exist changes nothing and sends nothing; a reply naming a profile
that exists but has no Telegram bot is refused the same way, and a good reply after it still completes the
recovery; a reply naming a profile whose readiness is unknown (a secret source) is applied, its confirmation
fails, the doctor row and the card say the profile may have no Telegram bot, and a good reply still completes the
recovery (held by Sleep mode instead, the row keeps its held words); and Sleep mode on holds the confirmation while
the recap still waits.

Synthetic state dir, config, Hermes session DB (tests/hermes_db_fixture.py) and Hermes profile tree (made-up
profile names, a token placeholder) in a temp dir. kevin-push is a fake on PATH: it appends its argv to a file
and writes kevin-push-style log rows, using push_sender.check as the real preflight does; it never sends.
"""
from hermetic_env import child_env  # first import: isolates HOME, see tests/hermetic_env.py
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from limitless import card, doctor, jobs, outage_recap, push_reach, push_sender, sender_reply, tools  # noqa: E402
from limitless import outage_recap_job as recap_job  # noqa: E402
from limitless import sender_confirm_job as confirm_job  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402
from hermes_db_fixture import make_db  # noqa: E402

CLI = ROOT / "bin" / "limitless-jobs"
H = 3600
GOOD = "sender-synth"          # the profile the owner's reply names; it exists in the fake Hermes home
GONE = "sender-gone"           # config push_profile: removed, so every push fails before it reaches hermes
NOWHERE = "sender-nowhere"     # a reply naming a profile that does not exist
BOTLESS = "sender-botless"     # a reply naming a profile that exists but has no Telegram bot token
VAULT = "sender-vault"         # a profile whose token may sit in a secret source (readiness unknown); it has none
NO_BOT_LINE = (push_reach.PREFIX + "the profile you named was set but could not send, so it may have no Telegram bot; "
               "reply push via another profile")
PUSH_LOG = "push-log.jsonl"
OUTAGE_LINE = push_reach.PREFIX + push_reach.SENDER_MISSING
RECAP_WAITS = f"Outage recap: hold: {recap_job.EVENT}; waits for the next pass: {confirm_job.RECAP_WAITS}"
RECAP_OPEN = f"Outage recap: {jobs.NOT_TRIGGERED}: {recap_job.OPEN_REASON}"
# Mark files and the epoch fields each may hold as numbers; every string in a mark is words (no digit), but the
# outage recap's once key, which is "outage_recap:<epoch>" by design.
MARKS = {sender_reply.MARK: {"row_at", "ran_at", "after", "refused_at"}, push_sender.REPLY_FILE: {"at"},
         confirm_job.MARK: {"reply_at", "ran_at"}, recap_job.MARK: {"at"}}
FLAGS = {sender_reply.MARK: {"applied_unknown"}}   # the only booleans a mark may hold, and only as true

# kevin-push stand-in: records argv (and KEVIN_PUSH_STRICT), then decides in kevin-push's own order: Sleep mode
# holds; else push_sender.check BROKEN logs "log (no sender profile)" and starts nothing; else a profile whose
# files readiness does not call ready fails the way hermes would ("log (telegram rc=1)"); else a delivery
# ("telegram"). It logs one kevin-push-style row and exits 3 under STRICT for anything but a delivery. It never
# sends and keeps no once keys, so a repeated call is never hidden. $FAKE_PUSH_AT dates a seeded row.
FAKE_KEVIN_PUSH = """#!{py}
import json, os, sys, time
sys.path.insert(0, {root!r})
from limitless import push_sender
from limitless.state_reader import config
args = sys.argv[1:]
with open(os.environ["FAKE_CALLS"], "a") as f:
    f.write(json.dumps({{"argv": args, "strict": os.environ.get("KEVIN_PUSH_STRICT")}}) + "\\n")
rest, opts, i = [], {{}}, 0
while i < len(args):
    if args[i] in ("--once", "--why"):
        opts[args[i]], i = args[i + 1], i + 2
    else:
        rest, i = rest + [args[i]], i + 1
tag, title, body = rest[:3]
st = os.environ["LIMITLESS_STATE"]
try:
    with open(os.path.join(st, "sleepmode.jsonl")) as f:
        asleep = bool(json.loads(f.read().strip().splitlines()[-1]).get("on"))
except (OSError, ValueError, IndexError):
    asleep = False
shown = body + "\\nWhy now: " + opts.get("--why", "a reason")
if asleep:
    how, shown = "held (sleep mode)", body
elif push_sender.check(config()) == push_sender.BROKEN:
    how = push_sender.NO_SENDER_HOW
elif push_sender.readiness(config()) != push_sender.READY:
    how = "log (telegram rc=1)"
else:
    how = "telegram"
at = int(float(os.environ.get("FAKE_PUSH_AT") or time.time()))
with open(os.path.join(st, "push-log.jsonl"), "a") as f:
    f.write(json.dumps({{"at": at, "tag": tag, "cls": os.environ.get("CIRCADIAN_CLASS", "report"), "title": title,
                        "body": shown, "how": how}}) + "\\n")
print("kevin-push: " + how)
sys.exit(3 if os.environ.get("KEVIN_PUSH_STRICT") == "1" and how != "telegram" else 0)
"""


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Recovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.st = self.dir / "state"
        self.st.mkdir()
        self.t0 = float(int(time.time()))      # the CLI reads its own clock; every seeded time is before it
        self.hermes = self.dir / "hermes"
        prof = self.hermes / "profiles" / GOOD
        prof.mkdir(parents=True)
        (prof / ".env").write_text("TELEGRAM_BOT_TOKEN=placeholder-token-not-real\n"
                                   "TELEGRAM_HOME_CHANNEL=placeholder-chat\n")
        (self.hermes / "profiles" / BOTLESS).mkdir()
        (self.hermes / "profiles" / BOTLESS / "config.yaml").write_text("")   # a Hermes identity marker, no bot
        (self.hermes / "profiles" / VAULT).mkdir()
        (self.hermes / "profiles" / VAULT / "config.yaml").write_text("secrets:\n  vault:\n    kind: placeholder\n")
        self.db = self.st / "hermes.db"
        make_db(self.db, [], started=self.t0 - 6 * H)
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        kp = self.bin / "kevin-push"
        kp.write_text(FAKE_KEVIN_PUSH.format(py=sys.executable, root=str(ROOT)))
        kp.chmod(0o755)
        self.calls = self.dir / "calls.jsonl"
        self.cfg_path = self.dir / "config.json"
        self.cfg = {"hermes_db": "hermes.db", "push_profile": GONE, "push_to": "telegram", "push_log": PUSH_LOG,
                    "sender_ingest": "write", "sender_confirm": "write", "outage_recap": "write"}
        self.cfg_path.write_text(json.dumps(self.cfg))
        self.env = {"HOME": str(self.dir), "LIMITLESS_CONFIG": str(self.cfg_path), "LIMITLESS_STATE": str(self.st),
                    "HERMES_HOME": str(self.hermes), "FAKE_CALLS": str(self.calls),
                    "KEVIN_PUSH_BIN": str(kp), "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}"}
        # the outage: two pushes, each logged by kevin-push as not started (the sender profile is gone)
        for title, ago in (("Wake-up brief", 3 * H), ("MIQ for tonight?", 2 * H)):
            self.kevin_push(title, "Synthetic body.", at=self.t0 - ago)
        self.first_at = int(self.t0 - 3 * H)
        self.calls.unlink()
        self.sync(self.t0 - 600)

    # -- fixtures ------------------------------------------------------------------------------------------------

    def kevin_push(self, title, body, at):
        r = subprocess.run([str(self.bin / "kevin-push"), "limitless", title, body],
                           env=child_env(self.env, FAKE_PUSH_AT=str(at)), capture_output=True, text=True,
                           timeout=60)
        self.assertEqual(r.stdout.strip(), "kevin-push: " + push_sender.NO_SENDER_HOW, r.stderr)

    def sync(self, t):
        with open(self.st / "runs.jsonl", "a") as f:
            f.write(json.dumps({"at": iso(t), "job": "sync", "ok": True, "took_s": 9.5}) + "\n")

    def owner_says(self, text, t):
        with closing(sqlite3.connect(str(self.db))) as con:
            con.execute("INSERT INTO messages (session_id, role, content, timestamp) VALUES ('s1', 'user', ?, ?)",
                        (text, t))
            con.commit()

    def sleep_mode(self, on, t):
        with open(self.st / "sleepmode.jsonl", "a") as f:
            f.write(json.dumps({"at": iso(t), "on": on}) + "\n")

    # -- reading back --------------------------------------------------------------------------------------------

    def files(self):
        """{name: bytes} of the state dir, but the inputs the test itself writes and the push log."""
        return {p.name: p.read_bytes() for p in self.st.iterdir()
                if p.is_file() and p.name not in (PUSH_LOG, self.db.name, "runs.jsonl", "sleepmode.jsonl")}

    def log_rows(self):
        return [json.loads(ln) for ln in (self.st / PUSH_LOG).read_text().splitlines()]

    def calls_made(self):
        return [json.loads(ln) for ln in self.calls.read_text().splitlines()] if self.calls.exists() else []

    def mark(self, name):
        p = self.st / name
        return json.loads(p.read_text()) if p.exists() else None

    def run_pass(self):
        """One timer pass. Returns ({job: line}, the kevin-push calls it made, the marks it wrote or changed,
        the push log rows it added)."""
        before, calls, rows = self.files(), len(self.calls_made()), len(self.log_rows())
        r = subprocess.run([sys.executable, "-I", str(CLI), "--ingest", "--confirm"], env=child_env(self.env),
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = {ln.split(": ")[0]: ln for ln in r.stdout.splitlines()}
        after = self.files()
        changed = sorted(n for n in after if before.get(n) != after[n])
        self.assertEqual(sorted(n for n in before if n not in after), [], "a pass never deletes a mark")
        for name in changed:
            self.assertWordsOnly(name)
        return lines, self.calls_made()[calls:], changed, self.log_rows()[rows:]

    def assertWordsOnly(self, name):
        """Every mark a pass writes: numbers only in its epoch fields, strings without a digit (the outage recap's
        once key excepted), never a message text."""
        self.assertIn(name, MARKS, f"an unexpected file was written: {name}")
        data = self.mark(name)
        for k, v in data.items():
            if isinstance(v, bool):
                self.assertIn(k, FLAGS.get(name, ()), (name, k))
                self.assertIs(v, True, (name, k))
            elif isinstance(v, (int, float)):
                self.assertIn(k, MARKS[name], (name, k))
            elif isinstance(v, str):
                if name == recap_job.MARK and k == "key":
                    self.assertRegex(v, r"^outage_recap:\d+$")
                else:
                    self.assertIsNone(re.search(r"\d", v), (name, k, v))
            else:
                self.assertIsNone(v, (name, k, v))
        text = (self.st / name).read_text()
        for words in ("Pushes", "route", "reaching", "Missed", "push via"):
            self.assertNotIn(words, text, name)

    def assertCall(self, call, title, once):
        argv = call["argv"]
        self.assertEqual(argv[:2], ["limitless", title], argv)
        self.assertEqual(argv[argv.index("--once") + 1], once, argv)
        self.assertEqual(call["strict"], "1")

    def card_text(self):
        now = time.time()
        return card.build(StateReader(self.st), now, date.fromtimestamp(now), env=self.env)["text"]

    def delivery(self):
        now = time.time()
        return tools.status_with_delivery(StateReader(self.st), now, self.cfg, self.env)["delivery"]

    def assertOutageShown(self, shown):
        text = self.card_text()
        self.assertEqual(OUTAGE_LINE in text, shown, text)
        self.assertEqual(self.delivery()["value"], OUTAGE_LINE if shown else None, self.delivery())

    # -- the recovery --------------------------------------------------------------------------------------------

    def test_the_outage_recovers_pass_by_pass(self):
        confirm_key = f"sender_confirm:{int(self.t0 - 150)}"
        recap_key = f"outage_recap:{self.first_at}"

        # pass 0: the outage is open and there is no reply yet; the card says so and nothing is pushed
        self.assertOutageShown(True)
        lines, calls, changed, rows = self.run_pass()
        self.assertEqual(calls, [])
        self.assertEqual(changed, [sender_reply.MARK])
        self.assertEqual(rows, [])
        self.assertTrue(lines["Sender ingest"].startswith("Sender ingest: run: a sync ran; "), lines)
        self.assertEqual(lines["Sender confirm"], f"Sender confirm: {jobs.NOT_TRIGGERED}: {jobs.SENDER_NO_REPLY}")
        self.assertEqual(lines["Outage recap"], RECAP_OPEN)
        self.assertOutageShown(True)

        # the owner's reply, then a sync
        self.owner_says(f"push via {GOOD}", self.t0 - 150)
        self.sync(self.t0 - 120)

        # pass 1: the sender is set and the one confirmation goes out through it; the recap waits
        lines, calls, changed, rows = self.run_pass()
        self.assertEqual(len(calls), 1, calls)
        self.assertCall(calls[0], confirm_job.TITLE_SENT, confirm_key)
        self.assertEqual(changed, sorted([sender_reply.MARK, push_sender.REPLY_FILE, confirm_job.MARK]))
        self.assertEqual(self.mark(push_sender.REPLY_FILE), {"profile": GOOD, "at": self.t0 - 150})
        self.assertEqual(self.mark(confirm_job.MARK)["outcome"], confirm_job.TOLD)
        self.assertIsNone(self.mark(recap_job.MARK))
        self.assertEqual([(r["title"], r["how"]) for r in rows], [(confirm_job.TITLE_SENT, "telegram")])
        self.assertEqual(lines["Sender ingest"],
                         "Sender ingest: run: a sync ran; set the sender profile from your reply")
        self.assertTrue(lines["Sender confirm"].startswith("Sender confirm: deliver: "), lines)
        self.assertTrue(lines["Sender confirm"].endswith("; sent"), lines)
        self.assertEqual(lines["Outage recap"], RECAP_WAITS)
        self.assertOutageShown(False)   # the confirmation was delivered: the card stops saying the outage

        # pass 2 (no new sync row): the recap goes out once, nothing else
        lines, calls, changed, rows = self.run_pass()
        self.assertEqual(len(calls), 1, calls)
        self.assertCall(calls[0], outage_recap.TITLE, recap_key)
        self.assertEqual(changed, [recap_job.MARK])
        self.assertEqual(self.mark(recap_job.MARK)["key"], recap_key)
        self.assertEqual(self.mark(recap_job.MARK)["outcome"], recap_job.TOLD)
        self.assertEqual([(r["title"], r["how"]) for r in rows], [(outage_recap.TITLE, "telegram")])
        body = calls[0]["argv"][2]
        self.assertTrue(body.startswith(outage_recap.FIRST_LINE), body)
        self.assertIn("(wake brief, MIQ prompt)", body)
        self.assertNotIn(GOOD, body)
        self.assertEqual(lines["Outage recap"], f"Outage recap: deliver: {recap_job.EVENT}; sent")
        self.assertEqual(lines["Sender confirm"], "Sender confirm: drop: " + jobs.SENDER_SETTLED)
        self.assertOutageShown(False)

        # pass 3, after a new sync row: nothing more is sent and only the ingest's own mark moves
        self.sync(self.t0 - 60)
        lines, calls, changed, rows = self.run_pass()
        self.assertEqual(calls, [])
        self.assertEqual(changed, [sender_reply.MARK])
        self.assertEqual(rows, [])
        self.assertEqual(lines["Sender confirm"], "Sender confirm: drop: " + jobs.SENDER_SETTLED)
        self.assertEqual(lines["Outage recap"], "Outage recap: drop: already told about this outage")
        self.assertOutageShown(False)

        # one confirmation and one recap in all, in that order
        self.assertEqual([c["argv"][1] for c in self.calls_made()], [confirm_job.TITLE_SENT, outage_recap.TITLE])

    def test_a_reply_naming_a_missing_profile_changes_nothing_and_sends_nothing(self):
        self.run_pass()
        self.owner_says(f"push via {NOWHERE}", self.t0 - 150)
        self.sync(self.t0 - 120)
        lines, calls, changed, rows = self.run_pass()
        self.assertEqual(calls, [])
        self.assertEqual(changed, [sender_reply.MARK])
        self.assertEqual(rows, [])
        self.assertEqual(self.mark(sender_reply.MARK)["action"], sender_reply.MISSING)
        self.assertIsNone(self.mark(push_sender.REPLY_FILE))
        self.assertNotIn(NOWHERE, lines["Sender ingest"])
        self.assertEqual(lines["Sender confirm"], f"Sender confirm: {jobs.NOT_TRIGGERED}: {jobs.SENDER_NO_REPLY}")
        self.assertEqual(lines["Outage recap"], RECAP_OPEN)
        self.assertOutageShown(True)
        lines, calls, changed, rows = self.run_pass()   # and the next pass does not pick it up again
        self.assertEqual((calls, changed, rows), ([], [], []))
        self.assertOutageShown(True)

    def test_a_reply_naming_a_botless_profile_is_refused_then_a_good_reply_recovers(self):
        refused = "pushes are failing; your last reply named a profile that cannot reach Telegram"
        self.run_pass()
        self.owner_says(f"push via {BOTLESS}", self.t0 - 300)
        self.sync(self.t0 - 280)

        # the refused pass: nothing applied, nothing sent, the outage goes on and both doctor rows say why
        lines, calls, changed, rows = self.run_pass()
        self.assertEqual((calls, changed, rows), ([], [sender_reply.MARK], []))
        self.assertEqual(self.mark(sender_reply.MARK)["action"], sender_reply.NO_BOT)
        self.assertIsNone(self.mark(push_sender.REPLY_FILE))
        self.assertEqual(lines["Sender ingest"], "Sender ingest: run: a sync ran; your reply named a profile with "
                                                 "no Telegram bot, so it was not applied")
        self.assertEqual(lines["Sender confirm"], f"Sender confirm: {jobs.NOT_TRIGGERED}: {jobs.SENDER_NO_REPLY}")
        self.assertEqual(lines["Outage recap"], RECAP_OPEN)
        self.assertOutageShown(True)
        self.assertEqual(self.recovery(), (doctor.MISSING, refused))
        ingest_row = doctor.sender_ingest_row(StateReader(self.st), self.cfg, time.time(), env=self.env)
        self.assertTrue(ingest_row["reason"].endswith("; " + refused), ingest_row)
        self.assertNotIn(BOTLESS, ingest_row["reason"])

        # a good reply: the sender is set, the confirmation goes out, then the recap, and the outage is over
        self.owner_says(f"push via {GOOD}", self.t0 - 150)
        self.sync(self.t0 - 120)
        lines, calls, changed, rows = self.run_pass()
        self.assertEqual([c["argv"][1] for c in calls], [confirm_job.TITLE_SENT])
        self.assertEqual(self.mark(push_sender.REPLY_FILE), {"profile": GOOD, "at": self.t0 - 150})
        self.assertNotIn("refused_at", self.mark(sender_reply.MARK))
        self.assertEqual(lines["Sender ingest"],
                         "Sender ingest: run: a sync ran; set the sender profile from your reply")
        self.assertEqual(self.recovery(), (doctor.STALE, "pushes are back; the recap waits for the next pass"))
        self.assertOutageShown(False)
        lines, calls, changed, rows = self.run_pass()
        self.assertEqual([c["argv"][1] for c in calls], [outage_recap.TITLE])
        self.assertEqual(self.recovery(), (doctor.LIVE, "pushes are back; recap sent"))
        self.assertEqual([c["argv"][1] for c in self.calls_made()], [confirm_job.TITLE_SENT, outage_recap.TITLE])

    def test_an_unknown_profile_that_cannot_send_says_it_may_have_no_bot_then_a_good_reply_recovers(self):
        no_bot = ("pushes are failing; the profile you named was set but could not send, so it may have no "
                  "Telegram bot; reply push via another profile")
        self.run_pass()
        self.owner_says(f"push via {VAULT}", self.t0 - 300)
        self.sync(self.t0 - 280)

        # applied (readiness was unknown, not a no); the one confirmation goes out through it and fails
        lines, calls, changed, rows = self.run_pass()
        self.assertEqual(len(calls), 1, calls)
        self.assertCall(calls[0], confirm_job.TITLE_SENT, f"sender_confirm:{int(self.t0 - 300)}")
        self.assertEqual(changed, sorted([sender_reply.MARK, push_sender.REPLY_FILE, confirm_job.MARK]))
        self.assertEqual(self.mark(push_sender.REPLY_FILE), {"profile": VAULT, "at": self.t0 - 300})
        self.assertIs(self.mark(sender_reply.MARK)["applied_unknown"], True)
        self.assertEqual(self.mark(confirm_job.MARK)["outcome"], confirm_job.FAILED)
        self.assertEqual([(r["title"], r["how"]) for r in rows], [(confirm_job.TITLE_SENT, "log (telegram rc=1)")])
        self.assertEqual(lines["Sender ingest"],
                         "Sender ingest: run: a sync ran; set the sender profile from your reply")
        self.assertIn(confirm_job.NOT_REACHED, lines["Sender confirm"])
        self.assertEqual(lines["Outage recap"], RECAP_OPEN)
        # the doctor row and the card both say the named profile may have no bot, never its name
        self.assertEqual(self.recovery(), (doctor.MISSING, no_bot))
        text = self.card_text()
        self.assertIn(NO_BOT_LINE, text)
        self.assertNotIn(VAULT, text)
        self.assertEqual(self.delivery()["value"], NO_BOT_LINE)

        # the next pass tries the confirmation again and it fails again: the words stay
        lines, calls, changed, rows = self.run_pass()
        self.assertEqual([c["argv"][1] for c in calls], [confirm_job.TITLE_SENT])
        self.assertEqual(self.recovery(), (doctor.MISSING, no_bot))

        # a good reply: the flag is dropped, the confirmation is delivered, then the recap, and the outage is over
        self.owner_says(f"push via {GOOD}", self.t0 - 150)
        self.sync(self.t0 - 120)
        lines, calls, changed, rows = self.run_pass()
        self.assertEqual([c["argv"][1] for c in calls], [confirm_job.TITLE_SENT])
        self.assertEqual(self.mark(push_sender.REPLY_FILE), {"profile": GOOD, "at": self.t0 - 150})
        self.assertNotIn("applied_unknown", self.mark(sender_reply.MARK))
        self.assertEqual([r["how"] for r in rows], ["telegram"])
        self.assertEqual(self.recovery(), (doctor.STALE, "pushes are back; the recap waits for the next pass"))
        self.assertOutageShown(False)
        self.assertNotIn(NO_BOT_LINE, self.card_text())
        lines, calls, changed, rows = self.run_pass()
        self.assertEqual([c["argv"][1] for c in calls], [outage_recap.TITLE])
        self.assertEqual(self.recovery(), (doctor.LIVE, "pushes are back; recap sent"))

    def test_an_unknown_profile_held_by_sleep_mode_keeps_the_held_words(self):
        self.sleep_mode(True, self.t0 - 4 * H)
        self.owner_says(f"push via {VAULT}", self.t0 - 150)
        self.sync(self.t0 - 120)
        lines, calls, changed, rows = self.run_pass()
        self.assertEqual([r["how"] for r in rows], ["held (sleep mode)"])
        self.assertIs(self.mark(sender_reply.MARK)["applied_unknown"], True)
        self.assertEqual(self.recovery(), (doctor.STALE, "sender set from your reply; the confirmation has not been "
                                                         "delivered yet (held while Sleep mode was on)"))
        self.assertNotIn(NO_BOT_LINE, self.card_text())

    def test_sleep_mode_holds_the_confirmation_and_the_recap_still_waits(self):
        confirm_key = f"sender_confirm:{int(self.t0 - 150)}"
        self.sleep_mode(True, self.t0 - 4 * H)
        self.owner_says(f"push via {GOOD}", self.t0 - 150)
        self.sync(self.t0 - 120)

        lines, calls, changed, rows = self.run_pass()   # held: kevin-push was asked once and held it
        self.assertEqual(len(calls), 1, calls)
        self.assertCall(calls[0], confirm_job.TITLE_SENT, confirm_key)
        self.assertEqual(changed, sorted([sender_reply.MARK, push_sender.REPLY_FILE, confirm_job.MARK]))
        self.assertEqual(self.mark(confirm_job.MARK)["outcome"], confirm_job.HELD)
        self.assertEqual([r["how"] for r in rows], ["held (sleep mode)"])
        self.assertIn("Sleep mode holds it", lines["Sender confirm"])
        self.assertEqual(lines["Outage recap"], RECAP_OPEN)
        self.assertIsNone(self.mark(recap_job.MARK))

        lines, calls, changed, rows = self.run_pass()   # still asleep: asked again, held again, no recap
        self.assertEqual([c["argv"][1] for c in calls], [confirm_job.TITLE_SENT])
        self.assertEqual([r["how"] for r in rows], ["held (sleep mode)"])
        self.assertEqual(lines["Outage recap"], RECAP_OPEN)
        self.assertIsNone(self.mark(recap_job.MARK))

        self.sleep_mode(False, self.t0 - 30)            # awake: the confirmation goes out, the recap waits a pass
        lines, calls, changed, rows = self.run_pass()
        self.assertEqual(len(calls), 1, calls)
        self.assertCall(calls[0], confirm_job.TITLE_SENT, confirm_key)
        self.assertEqual(self.mark(confirm_job.MARK)["outcome"], confirm_job.TOLD)
        self.assertEqual(lines["Outage recap"], RECAP_WAITS)
        self.assertIsNone(self.mark(recap_job.MARK))

        lines, calls, changed, rows = self.run_pass()   # the next pass sends the recap, once
        self.assertEqual(len(calls), 1, calls)
        self.assertCall(calls[0], outage_recap.TITLE, f"outage_recap:{self.first_at}")
        self.assertEqual(self.mark(recap_job.MARK)["outcome"], recap_job.TOLD)
        lines, calls, changed, rows = self.run_pass()
        self.assertEqual((calls, changed, rows), ([], [], []))
        self.assertOutageShown(False)

    # -- limitless-doctor's "push recovery" row at each pass -----------------------------------------------------

    def recovery(self):
        """The doctor's push recovery row as (status, reason), read-only: the state dir is unchanged by it."""
        before = {p.name: p.read_bytes() for p in self.st.iterdir() if p.is_file()}
        r = doctor.push_recovery_row(StateReader(self.st), self.cfg, time.time())
        self.assertEqual({p.name: p.read_bytes() for p in self.st.iterdir() if p.is_file()}, before)
        self.assertEqual((r["name"], r["kind"]), (doctor.PUSH_RECOVERY_ROW, "source"))
        self.assertIsNone(re.search(r"\d", r["reason"]), r)
        self.assertNotIn(GOOD, r["reason"])
        return r["status"], r["reason"]

    def test_the_doctor_row_names_the_stage_at_each_pass(self):
        waiting = (doctor.MISSING, "pushes are failing; waiting for a sender reply")
        self.assertEqual(self.recovery(), waiting)
        self.run_pass()                                  # pass 0: no reply yet
        self.assertEqual(self.recovery(), waiting)
        self.owner_says(f"push via {GOOD}", self.t0 - 150)
        self.sync(self.t0 - 120)
        self.assertEqual(self.recovery(), waiting)       # the reply is in, not applied yet
        self.run_pass()                                  # pass 1: sender set, confirmation delivered, recap waits
        self.assertEqual(self.recovery(), (doctor.STALE, "pushes are back; the recap waits for the next pass"))
        self.run_pass()                                  # pass 2: the recap goes out
        self.assertEqual(self.recovery(), (doctor.LIVE, "pushes are back; recap sent"))
        self.sync(self.t0 - 60)
        self.run_pass()                                  # pass 3: nothing more
        self.assertEqual(self.recovery(), (doctor.LIVE, "pushes are back; recap sent"))

    def test_the_doctor_row_says_sleep_mode_held_the_confirmation(self):
        self.sleep_mode(True, self.t0 - 4 * H)
        self.owner_says(f"push via {GOOD}", self.t0 - 150)
        self.sync(self.t0 - 120)
        self.run_pass()                                  # held
        self.assertEqual(self.recovery(), (doctor.STALE, "sender set from your reply; the confirmation has not been "
                                                         "delivered yet (held while Sleep mode was on)"))
        self.sleep_mode(False, self.t0 - 30)
        self.run_pass()                                  # delivered; the recap waits a pass
        self.assertEqual(self.recovery(), (doctor.STALE, "pushes are back; the recap waits for the next pass"))
        self.run_pass()
        self.assertEqual(self.recovery(), (doctor.LIVE, "pushes are back; recap sent"))


if __name__ == "__main__":
    unittest.main()
