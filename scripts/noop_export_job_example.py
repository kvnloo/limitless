"""The synthetic example of the NOOP export job in docs/noop-export.md: python3 -I scripts/noop_export_job_example.py

Builds a made-up NOOP DB (tests/noop_fixture.py) and made-up runs.jsonl rows in a temporary state dir, then runs one
limitless-jobs pass (jobs_runner.run_once, not a dry run, no push) per step and prints the NOOP export's line the way
bin/limitless-jobs does, the mark file, the doctor row and the schedule card. Reads no real state, writes nothing
outside the temp dir, sends nothing, starts no process. UTC stands in for the local zone.
"""
import json
import os
import sys
import tempfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "tests"))
from limitless import doctor, jobs, jobs_runner, schedule_cards  # noqa: E402
from limitless.state_reader import StateReader, config  # noqa: E402
from noop_fixture import RING, hr_before, make_db, stages  # noqa: E402

UTC = timezone.utc
H = 3600
FIRST = date(2030, 1, 1)
NOW = datetime.combine(date(2030, 1, 6), time(9), UTC).timestamp()


def at(d, hh):
    return int(datetime.combine(d, time(hh), UTC).timestamp())


def iso(t):
    return datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        st = root / "state"
        st.mkdir()
        cfg_path = root / "config.json"
        env = {"LIMITLESS_CONFIG": str(cfg_path), "LIMITLESS_STATE": str(st)}
        sessions, hr = [], []
        for i in range(5):
            on = at(FIRST + timedelta(days=i), 23)
            sessions.append((RING, on, on + 8 * H, 0.9, stages(on, 7 * H, H)))
            hr += hr_before(RING, on, 58 + i % 3)
        make_db(st / "noop-copy.db", sessions=sessions, hr=hr)
        runs = []

        def configure(mode):
            cfg = {"noop_db": "noop-copy.db", "sleep_file": "sleep.jsonl", "presleep_hr_file": "presleep-hr.jsonl"}
            if mode is not None:
                cfg["noop_export"] = mode
            cfg_path.write_text(json.dumps(cfg))

        def sync(t, copied):
            row = {"at": iso(t), "job": "sync", "ok": True}
            if copied:
                row["noop"] = {"copied": True}
            runs.append(row)
            (st / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in runs))
            print(f"runs.jsonl += {json.dumps(row)}")

        def step(now):
            rows = jobs_runner.run_once(st, now, push=None, dry_run=False, env=env, home=root, tz=UTC)
            got = [r for r in rows if r["job"] == jobs.NOOP_EXPORT.send_title]
            print("$ limitless-jobs --send   (the NOOP export's line)")
            print("\n".join(f"{r['job']}: {r['action']}: {r['reason']}" for r in got) or "(no NOOP export line)")
            print()

        print("# config noop_export unset (off)")
        configure(None)
        sync(NOW - 6 * H, True)
        step(NOW - 6 * H + 60)
        print("# config noop_export \"dry_run\"")
        configure("dry_run")
        step(NOW - 6 * H + 120)
        print("# config noop_export \"write\"; the next sync copied the NOOP database again")
        configure("write")
        sync(NOW - 3 * H, True)
        step(NOW - 3 * H + 60)
        print("# the same sync row, polled again")
        step(NOW - 3 * H + 120)
        sleep_before = (st / "sleep.jsonl").read_bytes()
        print("# a sync that did not copy the NOOP database, then one that did")
        sync(NOW - 2 * H, False)
        step(NOW - 2 * H + 60)
        sync(NOW - H, True)
        step(NOW - H + 60)
        print(f"sleep.jsonl byte-identical after the rerun: {(st / 'sleep.jsonl').read_bytes() == sleep_before}")
        mode = oct(os.stat(st / jobs_runner.NOOP_MARK).st_mode & 0o777)
        print(f"{jobs_runner.NOOP_MARK} (mode {mode}):")
        print((st / jobs_runner.NOOP_MARK).read_text().rstrip())
        print()
        r = doctor.noop_export_row(StateReader(st), config(env, root), NOW)
        print("$ limitless-doctor   (the job row)")
        print(f"{r['name']}: {r['status']}: {doctor.words(r['reason'])}")
        print()
        print("schedule card:")
        print(schedule_cards.noop_export_card()["description"])
        print(f"files in the state dir: {', '.join(sorted(p.name for p in st.iterdir()))}")


if __name__ == "__main__":
    main()
