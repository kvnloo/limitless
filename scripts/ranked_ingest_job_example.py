"""The synthetic example of the ranked ingest job in docs/ranked-ledger.md: python3 -I scripts/ranked_ingest_job_example.py

Builds a made-up ranked ledger, a made-up Hermes session DB (tests/hermes_db_fixture.py) and made-up runs.jsonl rows in
a temporary state dir, then runs one limitless-jobs pass (jobs_runner.run_once, not a dry run, no push) per step and
prints the ranked ingest's line the way bin/limitless-jobs does, row ten's counts (limitless-ranked list), the status
file, the doctor row and the schedule card. Invented ids only. Reads no real state, writes nothing outside the temp
dir, sends nothing, starts no process.
"""
import json
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "tests"))
from limitless import doctor, jobs, jobs_runner, ranked_ledger, schedule_cards  # noqa: E402
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
        cfg_path = root / "config.json"
        env = {"LIMITLESS_CONFIG": str(cfg_path), "LIMITLESS_STATE": str(st)}
        ledger = st / "ranked-ledger.jsonl"
        ledger.write_text("".join(json.dumps({"id": i, "status": "open", "by": "agent", "evidence": ""}) + "\n"
                                  for i in ("synthetic-item-a", "synthetic-item-b")))
        make_db(st / "hermes.db", [("user", "a made-up private note", NOW - 5 * H),
                                   ("user", "drop: synthetic-item-a", NOW - 4 * H),
                                   ("assistant", "drop: synthetic-item-b", NOW - 4 * H + 10)],
                started=NOW - 6 * H)
        runs = []

        def configure(mode, db="hermes.db"):
            cfg = {"ranked_ledger": ledger.name}
            if db is not None:
                cfg["hermes_db"] = db
            if mode is not None:
                cfg["ranked_ingest"] = mode
            cfg_path.write_text(json.dumps(cfg))
            print(f"# config {json.dumps(cfg)}")

        def sync(t):
            row = {"at": iso(t), "job": "sync", "ok": True}
            runs.append(row)
            (st / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in runs))
            print(f"runs.jsonl += {json.dumps(row)}")

        def step(now):
            rows = jobs_runner.run_once(st, now, push=None, dry_run=False, env=env, home=root, tz=UTC)
            got = [r for r in rows if r["job"] == jobs.RANKED_INGEST.send_title]
            print("$ limitless-jobs --send   (the ranked ingest's line)")
            print("\n".join(f"{r['job']}: {r['action']}: {r['reason']}" for r in got) or "(no ranked ingest line)")
            print()

        def row_ten():
            label, counts = ranked_ledger.summary(st, config(env, root), env)
            print("$ limitless-ranked list")
            print("\n".join(ranked_ledger.list_lines(label, counts)) + "\n")

        def doc_row(now):
            r = doctor.ranked_ingest_row(StateReader(st), config(env, root), now, env=env)
            print(f"$ limitless-doctor   (the job row)\n{r['name']}: {r['status']}: {r['reason']}\n")

        configure(None)
        sync(NOW - 3 * H)
        step(NOW - 3 * H + 60)

        configure("write", db=None)
        step(NOW - 3 * H + 120)
        doc_row(NOW - 3 * H + 120)

        configure("dry_run")
        before = ledger.read_bytes()
        step(NOW - 3 * H + 180)
        print(f"ledger unchanged after the dry run: {ledger.read_bytes() == before}; "
              f"{ranked_ledger.MARK} exists: {(st / ranked_ledger.MARK).exists()}\n")
        row_ten()

        configure("write")
        sync(NOW - 2 * H)
        step(NOW - 2 * H + 60)
        row_ten()

        print("# the same sync row, polled again")
        step(NOW - 2 * H + 120)

        print("# the next sync, with no new owner message")
        sync(NOW - H)
        step(NOW - H + 60)

        status = st / jobs_runner.RANKED_MARK
        print(f"{jobs_runner.RANKED_MARK} (mode {oct(stat.S_IMODE(status.stat().st_mode))}):\n"
              f"{status.read_text().strip()}")
        newest = ranked_ledger.newest(ledger)
        print("newest rows by: " + ", ".join(f"{r['status']} by {r['by']}" for r in newest.values()) + "\n")
        doc_row(NOW - H + 60)
        print(f"schedule card:\n{schedule_cards.ranked_ingest_card()['description']}")
        print(f"files in the state dir: {', '.join(sorted(p.name for p in st.iterdir()))}")


if __name__ == "__main__":
    main()
