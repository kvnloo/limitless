# The owner's "push via <profile>" reply sets kevin-push's sender

When kevin-push's sender profile breaks (the `push sender` doctor row says `missing: the sender profile does not
exist`, and kevin-push logs `log (no sender profile)` instead of starting hermes), the owner is asked in plain
words to pick another profile and answers with one whole message:

```
push via default
```

The sender ingest job applies that reply by itself, the way the apps ingest
([apps-ingest.md](apps-ingest.md#as-an-event-job)) and the ranked drop ingest
([ranked-ledger.md](ranked-ledger.md#as-an-event-job)) apply theirs. Nobody has to hand-edit config
`push_profile`.

## What counts as a reply

`sender_reply.parse` takes only a whole message from the owner (role `user` in a Telegram session of the Hermes
session DB, config `hermes_db`; the same read as the apps ingest, `habit_replies.replies_from_hermes_db`). The
message, with surrounding space stripped, must be exactly `push via <name>` on one line: any case, spaces or tabs
between the words, and a name Hermes resolves under `profiles/` (lowercase letters, digits, `-` and `_`, starting
with a letter or digit, at most sixty-four characters; the name is lowercased first, as Hermes stores it).

Anything else changes nothing: the phrase inside a longer message (`can you push via default?`), a quoted ask
(`Reply 'push via default' to choose`), a trailing period, a second line, an assistant message, or a cron
session's prompt (only Telegram sessions are read). Of the messages after the mark, the newest `push via` message
wins; an older one is never used as a fallback.

## When it applies

Only when `push_sender.check` says the named profile exists (`default`, or a dir under the Hermes home's
`profiles/`, the home `hermes -p` resolves; files only, hermes is never run). A profile that does not exist
changes nothing: the job says "that sender profile does not exist: nothing changed", and the owner is asked
again by whatever asked the first time. When the Hermes home is not known or cannot be read, nothing changes and
the job asks again after the next sync. The code never picks a sender by itself, and there is never a fallback.

## Where the reply lands

Write mode writes `push-sender.json` in the state dir (`{"profile": <name>, "at": <the reply's epoch>}`, atomic,
mode 0600, no words), the way the apps ingest writes `apps.json`; the config file is never edited.
`push_sender.profile(cfg, env)`, which `bin/kevin-push`, its preflight check and the doctor's `push sender` row
all use, picks the sender in this order:

1. `KEVIN_PUSH_PROFILE` in the environment (it still wins over everything);
2. the reply in `push-sender.json` (the state dir: `LIMITLESS_STATE`, else config `state`, else
   `~/.local/state/limitless`); a missing or broken file, or one naming no valid profile, is skipped;
3. config `push_profile` (so the reply wins over an old config value);
4. the built-in default.

## As an event job

Config `sender_ingest`: `off` (the default: no row, nothing read), `dry_run` or `write`. `limitless-jobs --send`
runs it once per new sync row in `runs.jsonl` (`jobs.sender_ingest_verdict`, the apps ingest's rule), right after
the ranked ingest, never on a clock time. No Hermes DB set: skipped. Dry run writes only the mark.

The mark `push-sender-ingest.json` (atomic, 0600) holds epochs and words only, never a name or a message:
`row_at` (the sync row it acted on), `ran_at`, `mode`, `action` (`nothing`, `would write`, `write`, `missing`,
`unknown`) and `after` (the newest owner message a write pass read; a first run reads only the last day). A dry run
never moves `after`, so switching to `write` later still applies the reply. The job sends nothing and logs nothing
as sent.

The schedule card (`schedule_cards.sender_ingest_card()`, [schedule-cards.md](schedule-cards.md)) is on the
`sync` event, sender `local`, budget zero. The doctor's `job sender ingest` row ([doctor.md](doctor.md)) sits
right after `job ranked ingest`: off, stale (no Hermes DB, or a sync it has not run after yet) or live with the
mode, when it ran and what it did in words, plus "KEVIN_PUSH_PROFILE is set and still wins" when it is. No row,
card or line ever holds the profile name.

To prove the new sender works right away, turn on the sender confirmation (config `sender_confirm`): one short
plain push right after the change, whose own delivery result the doctor's `job sender confirm` row reports
([sender-confirm.md](sender-confirm.md)).

## Example (synthetic)

The real output of `python3 -I scripts/sender_ingest_example.py` (a made-up Hermes home with two made-up profiles,
a made-up session DB, a fixed clock):

```text
# config {"hermes_db": "hermes.db", "push_profile": "sender-old"}
runs.jsonl += {"at": "2030-01-06T06:00:00Z", "job": "sync", "ok": true}
$ limitless-jobs --send   (the sender ingest's line)
(no sender ingest line)
kevin-push sends through: sender-old

# config {"hermes_db": "hermes.db", "push_profile": "sender-old", "sender_ingest": "dry_run"}
$ limitless-jobs --send   (the sender ingest's line)
Sender ingest: run: a sync ran; would set the sender profile from your reply (config sender_ingest "write" sets it)
push-sender.json exists: False
kevin-push sends through: sender-old

# config {"hermes_db": "hermes.db", "push_profile": "sender-old", "sender_ingest": "write"}
runs.jsonl += {"at": "2030-01-06T07:00:00Z", "job": "sync", "ok": true}
$ limitless-jobs --send   (the sender ingest's line)
Sender ingest: run: a sync ran; set the sender profile from your reply
push-sender.json: {"at": 1893906000.0, "profile": "sender-new"}
kevin-push sends through: sender-new

# the same sync row, polled again
$ limitless-jobs --send   (the sender ingest's line)
Sender ingest: drop: already ran after this sync

# the owner names a profile that does not exist
owner says: push via sender-gone
runs.jsonl += {"at": "2030-01-06T08:00:00Z", "job": "sync", "ok": true}
$ limitless-jobs --send   (the sender ingest's line)
Sender ingest: run: a sync ran; that sender profile does not exist: nothing changed
kevin-push sends through: sender-new

# KEVIN_PUSH_PROFILE still wins over the reply
owner says: Push via Sender-New
runs.jsonl += {"at": "2030-01-06T08:30:00Z", "job": "sync", "ok": true}
$ limitless-jobs --send   (the sender ingest's line)
Sender ingest: run: a sync ran; set the sender profile from your reply; KEVIN_PUSH_PROFILE is set and still wins
kevin-push sends through: sender-old

push-sender-ingest.json (mode 0o600):
{"action": "write", "after": 1893918540.0, "mode": "write", "ran_at": 1893918660.0, "row_at": 1893918600.0}
push-sender.json mode: 0o600

$ limitless-doctor   (the job row)
job sender ingest: live: write mode: ran under an hour ago after a sync: set the sender profile from your reply

schedule card:
Schedule "Sender ingest" (after each sync run, at most once; asleep or awake: it sends nothing, so no window holds it): ends at the next sync run; nothing is sent; it reads your push via reply and, in write mode, sets the sender profile your pushes go through, only when that profile exists
files in the state dir: hermes.db, push-sender-ingest.json, push-sender.json, runs.jsonl
```

## What it never does

- It never sends a message, never runs hermes and never starts, stops or restarts a process.
- It never edits the config file and never picks a sender the owner did not name.
- It never prints the profile name in a job line, the doctor row or the schedule card.
