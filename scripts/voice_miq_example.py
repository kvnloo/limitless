"""The synthetic example in docs/voice-miq.md: python3 -I scripts/voice_miq_example.py

Builds a temporary state dir with one made-up MIQ push in jobs-sent.jsonl and a temporary z0live-shaped
``sessions`` dir with one made-up call (the ``sessions/SESSION_ID.jsonl`` export rows), then prints the call
brief's last line, one voice MIQ row per mode, the capture row, the mark and the doctor row. Reads no real
state, writes nothing outside the temp dirs, sends nothing, starts no process.
"""
import json
import sys
import tempfile
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from limitless import call_brief, capture, doctor, jobs_runner, voice_miq  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

NOW = 1894708800.0           # 2030-01-15T12:00:00Z, the fixtures' clock
SENT = NOW - 1800.0
CALL = [("user_transcript", "hey, quick one before bed"),
        ("assistant_transcript", "Sure. First: " + jobs_runner.MIQ_QUESTION),
        ("user_transcript", "yes"),
        ("user_transcript", "finish the draft review"),
        ("assistant_transcript", "Got it.")]


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        st, sessions, cfg = root / "state", root / "z0live" / "sessions", root / "config.json"
        st.mkdir()
        sessions.mkdir(parents=True)
        (st / jobs_runner.SENT_LOG).write_text(json.dumps({"t": SENT, "k": "k-example", "job": "miq"}) + "\n")
        rows = [{"id": i + 1, "session_id": "s-example", "ts": SENT + 60 + i, "type": k, "text": t, "data": {}}
                for i, (k, t) in enumerate(CALL)]
        (sessions / "s-example.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        env = {"LIMITLESS_STATE": str(st), "LIMITLESS_CONFIG": str(cfg)}

        def config(mode):
            cfg.write_text(json.dumps({"voice_miq": mode, "voice_miq_sessions": str(sessions)}))

        def say(row):
            print("(no row)" if row is None else f"{row['job']}: {row['action']}: {row['reason']}")

        print("$ answer_from(call, MIQ_QUESTION)")
        print(repr(voice_miq.answer_from(rows, jobs_runner.MIQ_QUESTION)))
        config("off")
        print("$ voice_miq off")
        say(voice_miq.run(st, NOW, env=env))
        config("dry_run")
        print("$ voice_miq dry_run: the call brief's last line, then the pass")
        print(call_brief.render(StateReader(st), NOW, date(2030, 1, 15), env=env)["lines"][-1])
        say(voice_miq.run(st, NOW, env=env))
        config("write")
        print("$ voice_miq write: the pass, the capture row, the mark")
        say(voice_miq.run(st, NOW, env=env))
        print((st / capture.FILE).read_text().strip())
        print((st / voice_miq.MARK).read_text().strip())
        print("$ the second pass")
        say(voice_miq.run(st, NOW + 600, env=env))
        print("$ the doctor row")
        r = doctor.voice_miq_row(StateReader(st), json.loads(cfg.read_text()), NOW + 600)
        print(f"{r['name']}: {r['status']}: {r['reason']}")
        print("$ the call brief now (MIQ captured): last line")
        print(call_brief.render(StateReader(st), NOW + 600, date(2030, 1, 15), env=env)["lines"][-1])


if __name__ == "__main__":
    main()
