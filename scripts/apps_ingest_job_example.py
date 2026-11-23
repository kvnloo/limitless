"""The synthetic example of the apps ingest job in docs/apps-ingest.md: python3 -I scripts/apps_ingest_job_example.py

Builds a made-up Hermes session DB (tests/hermes_db_fixture.py) and made-up runs.jsonl rows in a temporary state dir,
then runs one limitless-jobs pass (jobs_runner.run_once, not a dry run, no push) per step and prints the apps
ingest's line the way bin/limitless-jobs does, the mark file, the doctor row, the T1 line and the schedule card.
Reads no real state, writes nothing outside the temp dir, sends nothing, starts no process.
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
from limitless import apps_reply, doctor, jobs, jobs_runner, schedule_cards  # noqa: E402
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
        make_db(st / "hermes.db", [("user", "a made-up private note", NOW - 5 * H),
                                   ("user", "work apps: editorapp, termapp\nfeed apps: scrollapp", NOW - 4 * H)],
                started=NOW - 6 * H)
        runs = []

        def configure(mode, db="hermes.db"):
            cfg = {}
            if db is not None:
                cfg["hermes_db"] = db
            if mode is not None:
                cfg["apps_ingest"] = mode
            cfg_path.write_text(json.dumps(cfg))
            print(f"# config {json.dumps(cfg)}")

        def sync(t):
            row = {"at": iso(t), "job": "sync", "ok": True}
            runs.append(row)
            (st / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in runs))
            print(f"runs.jsonl += {json.dumps(row)}")

        def step(now):
            rows = jobs_runner.run_once(st, now, push=None, dry_run=False, env=env, home=root, tz=UTC)
            got = [r for r in rows if r["job"] == jobs.APPS_INGEST.send_title]
            print("$ limitless-jobs --send   (the apps ingest's line)")
            print("\n".join(f"{r['job']}: {r['action']}: {r['reason']}" for r in got) or "(no apps ingest line)")
            for r in got:
                if "line" in r:
                    print(f"T1 line for a later brief: {r['line']}")
            print()

        def doc_row(now):
            r = doctor.apps_ingest_row(StateReader(st), config(env, root), now, env=env)
            print(f"$ limitless-doctor   (the job row)\n{r['name']}: {r['status']}: {r['reason']}\n")

        configure(None)
        sync(NOW - 3 * H)
        step(NOW - 3 * H + 60)

        configure("write", db=None)
        step(NOW - 3 * H + 120)
        doc_row(NOW - 3 * H + 120)

        configure("dry_run")
        step(NOW - 3 * H + 180)
        print(f"apps.json exists after the dry run: {(st / apps_reply.APPS_FILE).exists()}\n")

        configure("write")
        sync(NOW - 2 * H)
        step(NOW - 2 * H + 60)

        print("# the same sync row, polled again")
        step(NOW - 2 * H + 120)

        print("# the next sync, with no new reply")
        sync(NOW - H)
        step(NOW - H + 60)

        mark = st / jobs_runner.APPS_MARK
        print(f"apps-ingest.json (mode {oct(stat.S_IMODE(mark.stat().st_mode))}):\n{mark.read_text().strip()}")
        apps = st / apps_reply.APPS_FILE
        print(f"apps.json mode {oct(stat.S_IMODE(apps.stat().st_mode))}, lists: "
              f"{', '.join(k for k in (apps_reply.WORK, apps_reply.FEED) if apps_reply.stored(apps_reply.load(st), k))}"
              "\n")
        doc_row(NOW - H + 60)
        print(f"schedule card:\n{schedule_cards.apps_ingest_card()['description']}")
        print(f"files in the state dir: {', '.join(sorted(p.name for p in st.iterdir()))}")


if __name__ == "__main__":
    main()
