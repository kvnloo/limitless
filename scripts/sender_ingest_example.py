"""The synthetic example of the sender ingest in docs/push-sender-reply.md: python3 -I scripts/sender_ingest_example.py

Builds a made-up Hermes home (two made-up profiles), a made-up Hermes session DB (tests/hermes_db_fixture.py) and
made-up runs.jsonl rows in a temporary dir, then runs one limitless-jobs pass (jobs_runner.run_once, not a dry run,
no push) per step and prints the sender ingest's line the way bin/limitless-jobs does, the profile kevin-push would
send through (push_sender.profile), push-sender.json, the mark, the doctor row and the schedule card. Made-up names
only. Reads no real state, writes nothing outside the temp dir, sends nothing, starts no process, never runs hermes.
"""
import json
import sqlite3
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "tests"))
from limitless import doctor, jobs, jobs_runner, push_sender, schedule_cards, sender_reply  # noqa: E402
from limitless.state_reader import StateReader, config  # noqa: E402
from hermes_db_fixture import make_db  # noqa: E402

UTC = timezone.utc
H = 3600
NOW = datetime(2030, 1, 6, 9, 0, tzinfo=UTC).timestamp()


def iso(t):
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        st = root / "state"
        st.mkdir()
        hermes = root / "hermes"
        for name in ("sender-old", "sender-new"):
            (hermes / "profiles" / name).mkdir(parents=True)
        cfg_path = root / "config.json"
        env = {"LIMITLESS_CONFIG": str(cfg_path), "LIMITLESS_STATE": str(st), "HERMES_HOME": str(hermes)}
        db = st / "hermes.db"
        make_db(db, [("user", "a made-up private note", NOW - 5 * H),
                     ("user", "can you push via sender-new from now on?", NOW - 4 * H - 60),
                     ("user", "push via sender-new", NOW - 4 * H),
                     ("assistant", "push via sender-old", NOW - 4 * H + 10)],
                started=NOW - 6 * H)
        runs = []

        def configure(mode):
            cfg = {"hermes_db": db.name, "push_profile": "sender-old"}
            if mode is not None:
                cfg["sender_ingest"] = mode
            cfg_path.write_text(json.dumps(cfg))
            print(f"# config {json.dumps(cfg)}")

        def say(text, t):
            con = sqlite3.connect(str(db))
            try:
                con.execute("INSERT INTO messages (session_id, role, content, timestamp) VALUES ('s1', 'user', ?, ?)",
                            (text, t))
                con.commit()
            finally:
                con.close()
            print(f"owner says: {text}")

        def sync(t):
            row = {"at": iso(t), "job": "sync", "ok": True}
            runs.append(row)
            (st / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in runs))
            print(f"runs.jsonl += {json.dumps(row)}")

        def step(now, run_env=None):
            rows = jobs_runner.run_once(st, now, push=None, dry_run=False, env=run_env or env, home=root, tz=UTC)
            got = [r for r in rows if r["job"] == jobs.SENDER_INGEST.send_title]
            print("$ limitless-jobs --send   (the sender ingest's line)")
            print("\n".join(f"{r['job']}: {r['action']}: {r['reason']}" for r in got) or "(no sender ingest line)")

        def sender(run_env=None):
            print(f"kevin-push sends through: {push_sender.profile(config(env, root), run_env or env)}\n")

        def doc_row(now):
            r = doctor.sender_ingest_row(StateReader(st), config(env, root), now, env=env)
            print(f"$ limitless-doctor   (the job row)\n{r['name']}: {r['status']}: {r['reason']}\n")

        configure(None)
        sync(NOW - 3 * H)
        step(NOW - 3 * H + 60)
        sender()

        configure("dry_run")
        step(NOW - 3 * H + 120)
        print(f"{sender_reply.SENDER_FILE} exists: {(st / sender_reply.SENDER_FILE).exists()}")
        sender()

        configure("write")
        sync(NOW - 2 * H)
        step(NOW - 2 * H + 60)
        print(f"{sender_reply.SENDER_FILE}: {(st / sender_reply.SENDER_FILE).read_text().strip()}")
        sender()

        print("# the same sync row, polled again")
        step(NOW - 2 * H + 120)
        print()

        print("# the owner names a profile that does not exist")
        say("push via sender-gone", NOW - H - 60)
        sync(NOW - H)
        step(NOW - H + 60)
        sender()

        print("# KEVIN_PUSH_PROFILE still wins over the reply")
        wins = dict(env, KEVIN_PUSH_PROFILE="sender-old")
        say("Push via Sender-New", NOW - 30 * 60 - 60)
        sync(NOW - 30 * 60)
        step(NOW - 30 * 60 + 60, wins)
        sender(wins)

        mark = st / sender_reply.MARK
        reply = st / sender_reply.SENDER_FILE
        print(f"{sender_reply.MARK} (mode {oct(stat.S_IMODE(mark.stat().st_mode))}):\n{mark.read_text().strip()}")
        print(f"{sender_reply.SENDER_FILE} mode: {oct(stat.S_IMODE(reply.stat().st_mode))}\n")
        doc_row(NOW - 30 * 60 + 60)
        print(f"schedule card:\n{schedule_cards.sender_ingest_card()['description']}")
        print(f"files in the state dir: {', '.join(sorted(p.name for p in st.iterdir()))}")


if __name__ == "__main__":
    main()
