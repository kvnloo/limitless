"""The synthetic "push recovery" rows in docs/doctor.md: python3 -I scripts/push_recovery_example.py

A made-up state dir in a temp dir, walked through one push outage's recovery stage by stage: synthetic
kevin-push log rows (made-up titles), a refused reply in the sender ingest's mark, a made-up sender reply in
push-sender.json, a made-up sender confirmation
mark and outage recap mark, at a fixed made-up clock. Each stage prints the doctor's real row
(doctor.push_recovery_row). Reads no real state, writes nothing outside the temp dir, sends nothing, runs no
process.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from limitless import doctor, push_sender, sender_reply  # noqa: E402
from limitless import outage_recap_job as recap_job  # noqa: E402
from limitless import sender_confirm_job as confirm_job  # noqa: E402
from limitless.state_reader import StateReader  # noqa: E402

NOW = 1894708800.0   # 2030-01-15T12:00:00Z, a made-up clock
H = 3600.0
FAIL = push_sender.NO_SENDER_HOW

for k in [k for k in os.environ if k.startswith(("LIMITLESS_", "KEVIN_PUSH_", "HERMES_"))]:
    del os.environ[k]


def row(at, how, title="Wake-up brief", body="Synthetic body."):
    return {"at": int(at), "tag": "limitless", "cls": "report", "title": title, "body": body, "how": how}


def confirmation(how):
    return row(NOW - 100, how, confirm_job.TITLE_SENT, confirm_job.BODY)


with tempfile.TemporaryDirectory() as tmp:
    st = Path(tmp)
    cfg = {"push_log": "push-log.jsonl", "sender_confirm": "write", "outage_recap": "write"}
    outage = [row(NOW - 5 * H, "telegram"), row(NOW - 3 * H, FAIL), row(NOW - 2 * H, FAIL, "MIQ for tonight?")]

    def show(note, rows, c=cfg):
        print(f"# {note}")
        if rows is not None:
            (st / "push-log.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        r = doctor.push_recovery_row(StateReader(st), c, NOW)
        print(f"{r['name']}: {r['status']}: {r['reason']}")

    show("pushes reach the owner", outage[:1])
    show("two pushes failed in a row; no reply yet", outage)
    sender_reply.write_mark(st, {"action": sender_reply.NO_BOT, "refused_at": NOW - H})
    show("the reply named a profile with no Telegram bot, so the sender ingest did not apply it", outage)
    (st / push_sender.REPLY_FILE).write_text(json.dumps({"profile": "sender-synth", "at": NOW - 150}))
    show("the reply set the sender; the next pass sends the confirmation", outage)
    show("Sleep mode held the confirmation", outage + [confirmation("held (sleep mode)")])
    show("the confirmation failed to send", outage + [confirmation("log (telegram rc=1)")])
    back = outage + [confirmation("telegram")]
    show("the confirmation was delivered; the recap waits a pass", back)
    show("the same, config outage_recap off", back, dict(cfg, outage_recap="off"))
    (st / recap_job.MARK).write_text(json.dumps({"key": f"outage_recap:{int(NOW - 3 * H)}", "outcome": "told",
                                                 "at": NOW - 60}))
    show("the recap was sent", back)
    show("no push_log set", None, {})
