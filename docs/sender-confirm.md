# Sender confirmation

When the owner's whole `push via <profile>` reply sets kevin-push's sender ([push-sender-reply.md](push-sender-reply.md):
`limitless/sender_reply.py` writes `push-sender.json`, `push_sender.profile` reads it), nothing proves the new
sender reaches the owner until some later push happens, maybe hours later. The sender confirmation closes that gap:
one short plain message right after the change, through the normal send gate, so a broken new sender shows up at
once.

## The event

`sender_changed` (`jobs.sender_changed_verdict`): `push-sender.json`'s `at` (the epoch of the owner's reply, read
by `push_sender.reply_at`, only when the file also names a profile kevin-push would use) is newer than the last
reply the mark `sender-confirm.json` settled. It is an event, never a clock time.

- No reply file, or one kevin-push would not use: nothing ("no reply has set the sender").
- A reply timestamped after now: nothing.
- The same reply again, once settled: a drop ("this sender change was already confirmed").
- A change older than `jobs.SENDER_CONFIRM_STALE_S` (twelve hours) never confirmed: a drop, "too late": a late
  confirmation is noise.
- While `KEVIN_PUSH_PROFILE` is set it beats the reply (`push_sender.profile`'s order), so the confirmation would
  not travel the new route: nothing is sent and the row says "KEVIN_PUSH_PROFILE is set and still wins".

## The message

```
Pushes
This is the new route for your phone pushes. If you see this, it works.
Why now: your reply changed the sender for your phone pushes
```

Title `Pushes`, one body line, and the one "Why now" line kevin-push adds. Never the profile name, a path, a card id
or a digit: no digit anywhere in the text.

## The job

`limitless/sender_confirm_job.py`, called once per `limitless-jobs` pass (`jobs_runner.run_once`), right after the
sender ingest's row, so a reply the ingest applies in a pass is confirmed in that same pass. Config
`sender_confirm`:

- `off` (the default): no row, nothing read.
- `dry_run`: nothing is pushed or written; the row says what it would send, title and body.
- `write`: the confirmation goes through `limitless-jobs`' kevin-push call (`KEVIN_PUSH_STRICT=1`,
  `CIRCADIAN_CLASS=decision`): the normal send gate, its Sleep-mode hold, quiet and the daily cap included.

A `limitless-jobs` pass without `--send` is a dry run too, except `--ingest --confirm` (the timer's pass): it sends
this confirmation in write mode and, on a later pass, the outage recap, and nothing else
([limitless-jobs-systemd.md](limitless-jobs-systemd.md)).

- At most one confirmation per change: the push carries `--once sender_confirm:<sender reply time>`, so a replay
  never sends twice, whatever polls it.
- The mark `sender-confirm.json` in the state dir (atomic, 0600; the reply epoch, an outcome word and the pass
  epoch, never a profile name or any message text) records each attempt: `told` on a real delivery (kevin-push
  reports `telegram`, rc 0), `failed` when the send failed (`log (telegram rc=N)`, or `log (no sender profile)`),
  `held` when Sleep mode held it, `dropped` when kevin-push dropped it (quiet, the once key already claimed, or a
  duplicate: the same text within the send gate's twelve-hour dedupe, which happens only when the sender changes
  twice in half a day).
- `told` and `dropped` settle the change. A failed send, a Sleep-mode hold or the daily cap holds, and the next pass
  tries again, so a sender the owner fixes is confirmed on the next pass.

It never restarts, kills or starts any service, never runs hermes itself and never sends outside kevin-push.

## The proof: the doctor row

The confirmation's own delivery result is the proof. `limitless-doctor` has a `job sender confirm` row right after
the `job sender ingest` row ([doctor.md](doctor.md)). It reads kevin-push's log (config `push_log`): the newest
confirmation row logged after the reply (title `Pushes`, its first words). With no push log set, or no such row
yet, it falls back to the mark's outcome for this reply.

- A failed send: status missing, "the new sender did not reach you: its confirmation failed to send ...; reply push
  via another profile, or fix this one and the next pass tries again".
- A held row (Sleep mode): live, "waits: Sleep mode held the confirmation; it goes out once Sleep mode is off".
- A delivery: live, "the new sender reached you: its confirmation was delivered" with when, in words.
- Else "waiting" (the next pass sends it), "not proven" (it was dropped), "no sender change to confirm", or "the
  sender changed a while ago and was never confirmed"; then the mode. Status off with config `sender_confirm` off.

## With the outage recap

When the old sender broke, its pushes failed, and the first delivery through the new sender also ends that
outage, so the outage recap ([outage-recap.md](outage-recap.md)) can fire on the same delivery. The two never both
go out in one pass: the confirmation runs first, and when it pushed in a pass (delivered, held or failed) the
outage recap holds, unsent and unmarked, with "waits for the next pass: the sender confirmation went out in this
pass". The next pass sends the recap as usual.

## Schedule card

With config `sender_confirm` on, `limitless_schedule` and host registration add one card,
`schedule_cards.sender_confirm_card()`: id `sender_confirm`, trigger and end `sender_changed`, sender `plugin`,
budget the send gate's daily cap, once-key `sender_confirm:<sender reply time>`, after the sender ingest's card and
before the outage recap's ([schedule-cards.md](schedule-cards.md)).

## Example (synthetic)

`python3 -I scripts/sender_confirm_example.py`: a made-up sender reply and kevin-push log in a temporary dir at the
fixture clock, a fake push that only prints what it was handed and logs it the way kevin-push would (a failed send,
a Sleep-mode hold, then a delivery), then one `limitless-jobs` pass with an outage recap due on the same delivery.
Real output:

```text
# pass 1: the reply set the sender; the new sender is broken
$ kevin-push limitless "Pushes" <body> --once sender_confirm:1894708200 --why "your reply changed the sender for your phone pushes"
This is the new route for your phone pushes. If you see this, it works.
kevin-push: log (telegram rc=1)
Sender confirm: hold: your reply changed the sender for your phone pushes; the new sender did not reach you: the send failed; the next pass tries again
job sender confirm: missing: sender confirm: the new sender did not reach you: its confirmation failed to send under an hour ago; reply push via another profile, or fix this one and the next pass tries again; write mode

# pass 2: the owner fixed it; the phone is in Sleep mode
$ kevin-push limitless "Pushes" <body> --once sender_confirm:1894708200 --why "your reply changed the sender for your phone pushes"
This is the new route for your phone pushes. If you see this, it works.
kevin-push: held (sleep mode)
Sender confirm: hold: your reply changed the sender for your phone pushes; not delivered: Sleep mode holds it; the next pass tries again
job sender confirm: live: sender confirm: waits: Sleep mode held the confirmation; it goes out once Sleep mode is off; write mode

# pass 3: Sleep mode is off
$ kevin-push limitless "Pushes" <body> --once sender_confirm:1894708200 --why "your reply changed the sender for your phone pushes"
This is the new route for your phone pushes. If you see this, it works.
kevin-push: telegram
Sender confirm: deliver: your reply changed the sender for your phone pushes; sent
job sender confirm: live: sender confirm: the new sender reached you: its confirmation was delivered under an hour ago; write mode

# pass 4: the next poll
Sender confirm: drop: this sender change was already confirmed
job sender confirm: live: sender confirm: the new sender reached you: its confirmation was delivered under an hour ago; write mode

# limitless-jobs pass 1: the sender changed and an outage just ended
$ kevin-push limitless "Pushes" <body> --once sender_confirm:1894708200 --why "your reply changed the sender for your phone pushes"
This is the new route for your phone pushes. If you see this, it works.
kevin-push: telegram
Sender confirm: deliver: your reply changed the sender for your phone pushes; sent
Outage recap: hold: pushes came back after an outage; waits for the next pass: the sender confirmation went out in this pass

# limitless-jobs pass 2: the next limitless-jobs pass
$ kevin-push limitless "Pushes are back" <body> --once outage_recap:1894690800 --why "pushes are reaching you again after an outage"
Phone pushes are reaching you again.
Missed since earlier today: a few messages (wake brief, back from nap).
They were not sent again: by now they are out of date.
Reply: OK / More
kevin-push: telegram
Sender confirm: drop: this sender change was already confirmed
Outage recap: deliver: pushes came back after an outage; sent
```
