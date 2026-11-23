"""The synthetic example in docs/open-wearables.md: python3 -I scripts/ow_export_example.py

Serves the made-up Open Wearables pages in tests/fixtures/open_wearables through an injected http callable (no
network, no server), in a temporary state dir whose sleep file already holds one NOOP night. Runs
limitless-ow-export off, as a dry run, with --write, with --write again and against a server that refuses the
key, then shows the doctor row and asks limitless_sleep. Reads no real state, writes nothing outside the temp dir,
sends nothing. UTC stands in for the local zone.
"""
import io
import json
import sys
import tempfile
from datetime import date, datetime, time, timezone
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from limitless import doctor, open_wearables as ow, tools  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

FIX = HERE.parent / "tests" / "fixtures" / "open_wearables"
UTC = timezone.utc
TODAY = date(2030, 1, 8)
NOW = datetime.combine(TODAY, time(9), UTC).timestamp()
KEY = "ow-SYNTHETIC-key-7f3a9c"                       # a made-up key, never printed
USER = "00000000-0000-4000-8000-0000000000aa"
NOOP_NIGHT = {"night": "2030-01-01", "asleep_s": 24600, "source": "noop", "start": "2030-01-01T23:05:00Z",
              "end": "2030-01-02T06:55:00Z"}


def server(status=200):
    pages = [(FIX / n).read_bytes() for n in ("sleep_page1.json", "sleep_page2.json")]

    def http(url, headers, timeout):
        u = urlsplit(url)
        print(f"  GET {u.path} ({'cursor, ' if 'cursor=' in u.query else ''}header {ow.HEADER})")
        if status == 200 and not u.path.endswith("/events/sleep"):   # the user record: a real, not a seed, user
            return 200, json.dumps({"id": USER, "first_name": "Synthetic"}).encode()
        return (status, pages.pop(0)) if status == 200 else (status, b"")
    return http


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    st = root / "state"
    st.mkdir()
    (st / "sleep.jsonl").write_text(json.dumps(NOOP_NIGHT) + "\n")
    cfg_path = root / "config.json"
    base = {"sleep_file": "sleep.jsonl", "open_wearables_url": "http://ow.example.invalid:8000",
            "open_wearables_user": USER}
    env = {"LIMITLESS_CONFIG": str(cfg_path), "LIMITLESS_STATE": str(st), ow.KEY_ENV: KEY}

    for mode, args, status in ((None, [], 200), ("write", [], 200), ("write", ["--write"], 200),
                               ("write", ["--write"], 200), ("write", ["--write"], 401)):
        cfg = dict(base, open_wearables_export=mode) if mode else base
        cfg_path.write_text(json.dumps(cfg))
        out = io.StringIO()
        label = f"open_wearables_export={mode or 'unset'}" + (", server refuses the key" if status != 200 else "")
        print(f"$ limitless-ow-export {' '.join(args)}".rstrip() + f"   ({label})")
        code = ow.main(args, env=env, home=root, tz=UTC, out=out, err=out, http=server(status), today=TODAY,
                       now=NOW - 3600)
        print(out.getvalue().rstrip())
        print(f"  (exit {code})")
        print()

    lines = (st / "sleep.jsonl").read_text().splitlines()
    print(f"sleep.jsonl ({len(lines)} rows, mode {oct((st / 'sleep.jsonl').stat().st_mode & 0o777)}):")
    print("\n".join(lines))
    print()

    reader = StateReader(st)
    cfg = json.loads(cfg_path.read_text())
    r = doctor.open_wearables_row(reader, cfg, NOW)
    print(f"$ limitless-doctor | grep Open\n{r['name']}: {r['status']}: {doctor.words(r['reason'])}")
    s = tools.sleep(reader, NOW, TODAY, env=env, home=root, tz=UTC)
    print(f"limitless_sleep: modality {s['modality']}; {s['value']['label']}")
    print("files in the state dir:", ", ".join(sorted(x.name for x in st.iterdir())))
