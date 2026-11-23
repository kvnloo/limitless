# Quiet, snooze and off

The person can mute every push to their phone with one reply, and an event, never a clock time, ends it.
`limitless/quiet.py` keeps the setting in `quiet.json` in the state dir; `bin/kevin-push` checks it before
every send; `limitless_quiet` shows it.

| Reply (whole message, any case) | `quiet.json` mode | Ends when |
| --- | --- | --- |
| `quiet` | `off` | the person replies `on`. Nothing else ends it. |
| `quiet tonight` | `quiet_tonight` | the next `wake` event after the reply (Sleep mode off after a long on, a screen-event wake or an `events.jsonl` row) |
| `snooze` or `snooze until I write again` | `snoozed` | the person writes again: any message newer than the reply in the owner session DBs, beacons or the Hermes DB the replies come from |
| `on` | `on` | (it is the end) |

Anything else changes nothing: "quiet please", "snooze 2h" and "quiet until ten" are not commands. There are
no times of day and no durations anywhere in this.

## What quiet does to a push

- While it holds, every message that would reach the phone is dropped, whatever its class: decisions,
  critical messages, the wake-up brief and "Back from nap" alike. There is no urgent override.
- Dropped means dropped: nothing goes to `held.jsonl` for later, and with `--once KEY` the event key is
  claimed, so a later retry for that event (the next `limitless-jobs` poll, `limitless-brief send`) is dropped
  too. `limitless-jobs` shows the job as `drop`, not "the next run tries again".
- A quiet drop is not a send: it never fills the daily cap of six and is never a duplicate.
- Report-only messages stay log-only and the asks digest still folds into the brief.
- Missing or broken `quiet.json` is `on` (the send gate as before). So is a snooze on a host that cannot see
  any message source, and a quiet night whose wake events cannot be read: it fails open, never mutes forever
  by accident. `quiet` (off) is the one setting that lasts until `on`.

## Held by Sleep mode, kept once

Without quiet, Sleep mode holds a non-critical push instead of dropping it: `bin/kevin-push` keeps it in
`held.jsonl` (kevin-push state dir) for the "Back from nap" message. Senders retry every pass (the wake brief
retries every sync until it goes out), so `limitless/held.py` keeps one row per message: the same `--once KEY`,
else the send gate's dedupe key (title and body without the why-now line, card ids removed). The newest copy
replaces the older one, rows stay in order of their newest hold, and the file is replaced whole (temp file,
mode 0600). A different message is never dropped. Each hold still writes its own `"held (sleep mode)"` row to
`log.jsonl`, so the delivery audit sees every attempt. `held.rows()` lists each held message once, also from
a file an older version wrote with repeats; a line it cannot read is skipped there and kept as it is on the
next hold, never a traceback.

## Why now

Every message that goes out ends with exactly one plain line, `Why now: ...`. `limitless-jobs` passes the
job's verdict (trigger event and decision-window reason) as `kevin-push --why`; another sender can pass
`--why` or `KEVIN_PUSH_WHY`. Without one, an always-sent message names its event ("you woke up") and any
other gets the decision window's reason for its class, each said in plain words ([one-tap.md](one-tap.md)).
Digits and card ids are left out of the line. The
dedupe key is the message without it.

## Setting it from a reply

```bash
bin/limitless-quiet-ingest [--db PATH] [--write]
```

Same shape as `bin/limitless-habit-ingest`: the Hermes session DB (`--db`, `LIMITLESS_HERMES_DB` or config
`hermes_db`; no default) is opened read-only, the person's Telegram messages after the current setting are
read (with no `quiet.json`, only the last day, so a first run never acts on an old message), and the latest
command is written to `quiet.json` (atomic, mode 0600) with `since` = its reply time. Dry run unless
`--write`. Rows never echo a message. Run it as often as `limitless-jobs`, e.g. from the same timer.

## Synthetic example

A synthetic Hermes DB with three messages from the person: "thanks", "snooze 2h", "Quiet tonight".
Real output from `bin/limitless-quiet-ingest` and `bin/kevin-push` with a fake `hermes` (reply times
replaced by `<reply time>`):

```text
$ limitless-quiet-ingest
<reply time>: ignore: not quiet, quiet tonight, snooze or on: changes nothing
<reply time>: ignore: not quiet, quiet tonight, snooze or on: changes nothing
<reply time>: would write: quiet tonight: the latest command
dry run: nothing written (--write writes quiet.json)
$ limitless-quiet-ingest --write
<reply time>: ignore: not quiet, quiet tonight, snooze or on: changes nothing
<reply time>: ignore: not quiet, quiet tonight, snooze or on: changes nothing
<reply time>: write: quiet tonight: the latest command
$ kevin-push x "Pick one" "Keep the synthetic loop?"
kevin-push: log (quiet: quiet tonight, until you wake up)
# a wake event arrives in events.jsonl
$ kevin-push --why "wake event; peak window open (since wake)" x "Pick one" "Keep the synthetic loop?"
kevin-push: telegram
# what the phone got:
Keep the synthetic loop?
Why now: you woke up; your focus is high right now
```

`limitless_quiet` during the quiet night, twelve minutes after the reply (real handler output):

```json
{"value": {"mode": "quiet_tonight", "set": "quiet_tonight", "held": true,
           "why": "quiet: quiet tonight, until you wake up"},
 "modality": "self_report", "age_h": 0.2, "evidence_tier": "direct",
 "label": {"label": "quiet tonight", "tier": "T1", "modality": "self_report"}}
```
