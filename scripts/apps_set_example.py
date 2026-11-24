"""The synthetic example of the apps-set line in docs/apps-ingest.md: python3 -I scripts/apps_set_example.py

Builds a made-up Hermes session DB (tests/hermes_db_fixture.py) and made-up runs.jsonl rows in a temporary state dir,
runs one limitless-jobs pass (jobs_runner.run_once, not a dry run, no push) per sync, then shows what the wake brief
would carry (jobs_runner.brief_apps_set), what a delivered brief marks (brief_apps_set_told: apps-set.json) and the
doctor's job apps ingest row. A failed delivery is shown as the sender sees it: it never calls the told step. Reads
no real state, writes nothing outside the temp dir, sends nothing, starts no process.
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
from limitless import doctor, jobs_runner  # noqa: E402
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
        env = {"LIMITLESS_CONFIG": str(cfg_path), "LIMITLESS_STATE": str(st),
               "LIMITLESS_AUDIT": str(root / "audit.jsonl")}
        runs = []

        def configure(mode):
            cfg = {"hermes_db": "hermes.db", "apps_ingest": mode}
            cfg_path.write_text(json.dumps(cfg))
            print(f"# config {json.dumps(cfg)}")

        def reply(text, at):
            db = st / "hermes.db"
            if db.exists():
                db.unlink()
            make_db(db, [("user", "a made-up private note", at - H), ("user", text, at)], started=at - 2 * H)
            print("# the person replied (a made-up reply in the session DB)")

        def sync(t):
            runs.append({"at": iso(t), "job": "sync", "ok": True})
            (st / "runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in runs))
            rows = jobs_runner.run_once(st, t + 60, push=None, dry_run=False, env=env, home=root, tz=UTC)
            got = [r for r in rows if r["job"] == "Apps ingest"]
            print("$ limitless-jobs --send   (after a sync)")
            print("\n".join(f"{r['job']}: {r['action']}: {r['reason']}" for r in got))

        def brief(now):
            line = jobs_runner.brief_apps_set(st, now, env, root)
            print(f"brief line: {line or '(no apps-set line)'}")
            return line

        def doc_row(now):
            r = doctor.apps_ingest_row(StateReader(st), config(env, root), now, env=env)
            print(f"{r['name']}: {r['status']}: {r['reason']}")

        def delivered(now):
            print("# the brief went out (a real delivery): the sender marks it told")
            jobs_runner.brief_apps_set_told(st, now, env, root)
            m = st / jobs_runner.APPS_SET_MARK
            print(f"apps-set.json (mode {oct(stat.S_IMODE(m.stat().st_mode))}): {m.read_text().strip()}")

        configure("write")
        reply("work apps: editorapp, termapp\nfeed apps: scrollapp", NOW - 4 * H)
        sync(NOW - 3 * H)
        brief(NOW - 2 * H)
        doc_row(NOW - 2 * H)
        print("# the delivery failed: nothing is marked, the next brief says it")
        brief(NOW - H)
        delivered(NOW - H)
        brief(NOW)
        doc_row(NOW)
        print("# the next sync, with no new reply")
        sync(NOW + H)
        brief(NOW + 2 * H)
        print("# a later reply sets the feed list again")
        reply("feed apps: otherfeedapp", NOW + 3 * H)
        sync(NOW + 4 * H)
        brief(NOW + 5 * H)
        doc_row(NOW + 5 * H)
        delivered(NOW + 5 * H)
        brief(NOW + 6 * H)
        print("# a dry run never tells")
        configure("dry_run")
        reply("work apps: editorapp", NOW + 7 * H)
        sync(NOW + 8 * H)
        brief(NOW + 9 * H)
        audit = [json.loads(ln) for ln in (root / "audit.jsonl").read_text().splitlines()]
        print("the tier audit rows: " + "; ".join(f"hook={a['hook']} digits={a['digits']} blocked={a['blocked']}"
                                                   for a in audit[-1:]) + f" ({len(audit)} rows, counts and a hash)")


if __name__ == "__main__":
    main()
