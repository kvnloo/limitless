"""Replay a kevin-push log.jsonl through the send gate (read-only). Prints counts only, no message text.

usage: python3 -I replay_log.py <repo_dir> <log.jsonl> [since_epoch]
Sleep holds are taken from the logged outcome (the gate cannot re-poll the past phone state).
"""
import collections
import json
import sys

sys.path.insert(0, sys.argv[1])
from limitless import send_gate as g  # noqa: E402

since = float(sys.argv[3]) if len(sys.argv) > 3 else 0
sent, old, new, card_ids = [], collections.Counter(), collections.Counter(), 0
for line in open(sys.argv[2]):
    r = json.loads(line)
    if r["at"] < since:
        continue
    old[r["how"].split(" (")[0] if not r["how"].startswith("log (") else r["how"]] += 1
    how = g.decide(r["tag"], r["title"], r["body"], r.get("cls", "report"), r["at"], sent,
                   r["how"].startswith("held"))
    new[how] += 1
    if how == "send":
        sent.append({"t": r["at"], "k": g.key(r["title"], r["body"])})
        if g.scrub(r["body"]) != r["body"]:
            card_ids += 1
print(json.dumps({"rows": sum(old.values()), "old": old, "new": new, "sends_with_card_ids_scrubbed": card_ids}))
