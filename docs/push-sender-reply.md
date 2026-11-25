# The owner's "push via <profile>" reply sets kevin-push's sender

When kevin-push's sender profile breaks (the `push sender` doctor row says `missing: the sender profile does not
exist`, and kevin-push logs `log (no sender profile)` instead of starting hermes), the owner is asked in plain
words to pick another profile and answers with one whole message:

```
push via default
```

Which names qualify: the doctor's `sender candidates` row ([doctor.md](doctor.md#sender-candidates-row),
`push_sender.candidates`) lists every profile `hermes -p` could resolve that the readiness check below calls
ready (`ready: alpha, beta`), then the ones it cannot tell (`maybe: delta (keeps its token in a secret source)`),
or says `none can reach Telegram`. While pushes fail and the owner's reply is awaited or was refused, the
`push recovery` row's words end with the same names, e.g. `pushes are failing; waiting for a sender reply; ready
profiles: alpha, beta` (`; ready profiles: `, else `; profiles that may reach Telegram: `, else `; no profile can
reach Telegram`). Files only and presence only, as below; hermes is never run.

A maybe that already failed to send is not offered again. When the reply in `push-sender.json` was applied on an
`unknown:` answer (the mark's `applied_unknown`, below) and its one confirmation then failed to send, both the
`sender candidates` row and the `push recovery` words leave that profile out of the maybes. With no other maybe
the row says `maybe: none left (one already failed to send)` and the words end `; no profile left that may reach
Telegram (one already failed to send)`; a ready profile is still named. Nothing new is stored for this: the
profile is the one `push-sender.json` already holds and the flag is the mark's; the next applied reply clears it.

### Settling an unknown sender

A maybe can also be settled before anyone replies: the operator runs `bin/limitless-sender-probe --write`, which
asks Hermes itself (`hermes -p <name> send --list telegram`, list only, never a send) for each `unknown:` candidate
and saves the verdict in `sender-probe.json` with the profile's `config.yaml` / `.env` mtimes. While those files
are unchanged, a profile Hermes found no Telegram target for is no longer a maybe (`push_sender.PROBED_NONE`), so
neither the `sender candidates` row nor the `push recovery` words offer it; one that lists a target stays a maybe.
Only the candidate lists read the record: the reply check below (`push_sender.readiness`) is files only as before.
Details: [doctor.md](doctor.md#settling-an-unknown-sender).

When the sender profile was deleted by Hermes (`hermes profile delete` writes the marker file
`<Hermes home>/profiles/.deleted/<name>`, a tombstone; `clear_named_profile_deleted` removes it on restore), even
if the dir is still there beside it (Hermes' `named_profile_is_live` refuses a tombstoned dir), the simplest fix is
to restore it, so every surface says so (`push_sender.tombstoned`: the tombstone exists, as Hermes' own
`named_profile_is_deleted` checks; it is never opened, no secret is read, hermes is never run): the `push sender` row says `missing: the sender profile was
deleted; restoring it should bring pushes back`, the state card's reason is `the sender profile was deleted` and
its hint `Reply restore <name> to bring it back.` (`Restore the deleted sender profile to bring it back.` for a
name with a digit; a ready profile is still offered after it, `... or reply push via <a>.`), and the `push
recovery` words read `pushes are failing; waiting for a sender reply; the sender profile was deleted and can be
restored` before the names. The restore itself happens in Hermes: the sender ingest only records a `restore
<name>` reply ([below](#a-restore-reply)), and limitless never restores, moves or deletes a profile. Without a
tombstone every word above stays as it was.

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


## A restore reply

The card's `Reply restore <name> to bring it back.` is answered the same way: one whole owner message, stripped
of surrounding space, exactly `restore <name>` (any case, spaces or tabs between the words, a name Hermes resolves,
lowercased; `restore_reply.parse`). Read from the same owner messages after the same mark as `push via`, the
newest `restore` message wins, never an older one. It counts only when `<name>` is the current sender and Hermes
has it deleted (`push_sender.tombstoned`); a message naming another profile, a live sender, or one with any other
words in it is ignored and nothing is written.

Restoring a profile recreates a Hermes profile and its gateway: an operator action, so the plugin never does it.
In write mode the sender ingest job only records the request in `restore-request.json` (atomic, 0600:
`{"profile": <name>, "at": <the message's epoch>, "seen_at": <the pass's epoch>}`) and its row adds `recorded
your restore request; the operator restores the profile`; a dry run writes nothing (`would record your restore
request for the operator`); off does nothing. It never touches the Hermes home, never runs hermes and never sends.

While that request is at or after the open push outage's first failed row and the sender is still tombstoned,
the state card's hint is `Restore asked; it will be done by the operator.` ([push-reach.md](push-reach.md#the-reply-hint-card-only))
and the `push recovery` words read `pushes are failing; waiting for a sender reply; a restore was asked`
([doctor.md](doctor.md#push-recovery-row)). A request older than the outage counts for nothing. When the profile
is live again the request is stale (the file stays) and every word is today's, byte for byte; the outage recap
flow is unchanged.

## When it applies

Only when `push_sender.check` says the named profile exists (`default`, or a dir under the Hermes home's
`profiles/`, the home `hermes -p` resolves, that is live by Hermes' own rule; files only, hermes is never run).
Live is `push_sender.is_live`, mirroring hermes_constants.py `named_profile_is_live` (what hermes_cli/profiles.py
`resolve_profile_env` asks for `-p`): the dir holds an identity marker (`named_profile_has_identity`: one of
`_PROFILE_IDENTITY_MARKERS`, `config.yaml`, `.env`, `SOUL.md`, `profile.yaml`, `auth.json`, `state.db`, is a file
or a symlink) and has no tombstone (`named_profile_is_deleted`); it reads stats only, never a file. A dir with no
marker, left by cron or log side effects, does not exist for Hermes either. A profile that does not exist
changes nothing: the job says "that sender profile does not exist: nothing changed", and the owner is asked
again by whatever asked the first time. When the Hermes home is not known or cannot be read, nothing changes and
the job asks again after the next sync. The code never picks a sender by itself, and there is never a fallback.

A profile can exist and still have no Telegram bot at all, so the job then asks `push_sender.readiness` about the
same profile and kevin-push's target (`KEVIN_PUSH_TO`, else config `push_to`, else the default): the same files
the doctor's `push sender` row reads (the profile's `.env`, `config.yaml` and channel directory, plus the job's
environment), and only whether a key is present, never a value. A definite no is not applied, and
`push-sender.json` stays as it was:

- no Telegram bot token: "your reply named a profile with no Telegram bot, so it was not applied";
- no chat for the target: "your reply named a profile with no Telegram chat to send to, so it was not applied".

`ready`, or any `unknown:` answer (the token may sit in a secret source, the target is not Telegram, the files
cannot be read), still applies, as before: an unknown is never a refusal. The mark then keeps
`applied_unknown: true`, and if that profile's one confirmation fails to send while the outage is open, the
doctor's `push recovery` row and the state card say "pushes are failing; the profile you named was set but could
not send, so it may have no Telegram bot; reply push via another profile" instead of only "failed to send". A refused reply, like a missing
profile, is not asked about again; the owner sends a new `push via <name>`. While the push outage is open, the
doctor's `job sender ingest` and `push recovery` rows say "pushes are failing; your last reply named a profile
that cannot reach Telegram" until a later reply is applied.

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
`unknown`, `no bot`, `no chat`), `after` (the newest owner message a write pass read; a first run reads only the
last day) and `refused_at` (when the newest refused reply was sent: `missing`, `no bot` or `no chat`; kept across
passes until a later reply is applied) and `applied_unknown` (`true` only, no other value: the reply in
`push-sender.json` was applied on an `unknown:` readiness answer; dropped by the next applied reply that is
`ready`, kept by a dry run, a refusal or a pass with nothing new). A dry run
never moves `after`, so switching to `write` later still applies the reply. The job sends nothing and logs nothing
as sent.

The schedule card (`schedule_cards.sender_ingest_card()`, [schedule-cards.md](schedule-cards.md)) is on the
`sync` event, sender `local`, budget zero. The doctor's `job sender ingest` row ([doctor.md](doctor.md)) sits
right after `job ranked ingest`: off, stale (no Hermes DB, or a sync it has not run after yet) or live with the
mode, when it ran and what it did in words, plus "KEVIN_PUSH_PROFILE is set and still wins" when it is. No row,
card or line ever holds the profile name.

To prove the new sender works right away, turn on the sender confirmation (config `sender_confirm`): one short
plain push right after the change, whose own delivery result the doctor's `job sender confirmation` row reports
([sender-confirm.md](sender-confirm.md)). The timer's `limitless-jobs --ingest --confirm` pass applies the reply and
sends that confirmation in the same pass, and nothing else ([limitless-jobs-systemd.md](limitless-jobs-systemd.md)).

## Example (synthetic)

The real output of `python3 -I scripts/sender_ingest_example.py` (a made-up Hermes home with two made-up ready
profiles, placeholder tokens only, and one with no Telegram bot; a made-up session DB, a fixed clock):

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

# the owner names a profile that exists but has no Telegram bot
owner says: push via sender-botless
runs.jsonl += {"at": "2030-01-06T08:15:00Z", "job": "sync", "ok": true}
$ limitless-jobs --send   (the sender ingest's line)
Sender ingest: run: a sync ran; your reply named a profile with no Telegram bot, so it was not applied
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
Schedule "Sender ingest" (after each sync run, at most once; asleep or awake: it sends nothing, so no window holds it): ends at the next sync run; nothing is sent; it reads your push via reply and, in write mode, sets the sender profile your pushes go through, only when that profile exists and is not known to lack a Telegram bot or chat
files in the state dir: hermes.db, push-sender-ingest.json, push-sender.json, runs.jsonl
```

## What it never does

- It never sends a message, never runs hermes and never starts, stops or restarts a process.
- It never reads a secret value: the readiness gate asks only whether a key is present.
- It never edits the config file and never picks a sender the owner did not name.
- It never prints the profile name in a job line, the doctor row or the schedule card. (Only the doctor's
  `sender candidates` row and the `push recovery` row's reply stages name the profiles the owner may pick.)
