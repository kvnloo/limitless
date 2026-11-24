# Outage recap

When kevin-push's sender breaks, every push in that span is only logged (`log (telegram rc=N)`, or
`log (no sender profile)` when the sender profile is missing). While it lasts, the state card says "Phone pushes
are not reaching you" ([push-reach.md](push-reach.md)). By the time delivery works again those messages are out of
date, so they are never re-sent: re-sending them would be noise. The person still learns once, in words, what
they missed: one plain message, "Pushes are back", right after pushes start reaching them again.

## What counts as an outage

`limitless/outage_recap.py` (pure: no clock, no file, no send) reads kevin-push's log rows, the file config
`push_log` names (the same log `delivery_audit` and `push_reach` read).

- A transport failure is a row `delivery_audit.send_failed` says failed: `log (telegram rc=N)` or
  `log (no sender profile)`. A delivery is `how == "telegram"`.
- Rows that never reached the transport (held for Sleep mode, folded, a repeat, the daily cap, quiet) are skipped,
  exactly as `delivery_audit`'s `send_failures` skips them: they neither break a run nor close it.
- An outage is a run of `SEND_FAIL_RUN` (`delivery_audit.SEND_FAIL_RUN`) or more transport failures in a row,
  closed by the first later delivered row.
- Only the most recent outage counts. An outage still open gives nothing (the card already says so); no outage
  gives nothing.

## The message

```
Phone pushes are reaching you again.
Missed since yesterday: a few messages (wake brief, MIQ prompt, back from nap).
They were not sent again: by now they are out of date.
Reply: OK / More
```

- The missed kinds are worded from the failed rows' titles, deduped, in order of first miss: a job's own name
  (wake brief, MIQ prompt, back from nap, habit check-in, week review, break nudge), else the title itself when it
  is a few plain words, else "another push". At most four, then "and others".
- How many is the number of distinct messages (title plus body without its "Why now" line, so the runner's
  retries of one message count once), as a word: one, a few (two to four) or many.
- Since when is the local date of the first failed row against today's: since earlier today, since yesterday,
  since two days ago ... since over a week ago. Dates only, never a clock time.
- The text has no digit, no body text, no profile name, no target and no path.
- The reply line is `one_tap.choices_line(("OK", "More"))`, like every other ask. "Show more" would be two words;
  one-tap options are one word each, so it is said as `More`. `More` is a placeholder: nothing reads the reply
  yet, and an answer changes nothing.

## The job

`limitless/outage_recap_job.py`, called once per `limitless-jobs` pass (`jobs_runner.run_once`, last row). Config
`outage_recap`:

- `off` (the default): no row, nothing read.
- `dry_run`: the row says it would send the recap; nothing is pushed or written.
- `write`: the recap is sent through `limitless-jobs`' kevin-push call (`KEVIN_PUSH_STRICT=1`).

`limitless-jobs --send` sends it, and so does the timer's `limitless-jobs --ingest --confirm` pass
([limitless-jobs-systemd.md](limitless-jobs-systemd.md)); a plain `--ingest` pass or a dry run never does.

Its event is `push_back` (`jobs.OUTAGE_RECAP`): a push delivered after an outage, never a clock time. It is not a
`jobs.SPECS` job, so no decision window holds it (the delivery that woke it shows the person can be reached), but it
goes through kevin-push's send gate like every push: quiet, Sleep mode and the daily cap still apply.

- At most one recap per outage: the push carries `--once outage_recap:<first failed push time>`, a key derived
  from the outage's first failed row, the same on every poll.
- The mark `outage-recap.json` in the state dir (atomic, 0600; the once key, an outcome word and an epoch, never
  a title, a kind or any message text) is written `told` only on a real delivery (kevin-push reports `telegram`,
  rc 0). A repeat poll then drops with "already told about this outage".
- kevin-push dropping it because the key was already claimed, or quiet holding it, settles the outage as
  `dropped`: never told, never retried.
- Any other result (a failed send, the daily cap, a Sleep-mode hold) holds; the next pass tries again.
- When the sender confirmation pushed in the same pass (the owner's reply just changed the sender), the recap holds
  unsent with "waits for the next pass", so the two never go out in one pass ([sender-confirm.md](sender-confirm.md)).
- An outage that closed more than `jobs.OUTAGE_RECAP_STALE_S` (twelve hours) ago is dropped: a late recap is
  noise.

It never restarts, kills or starts any service, never runs hermes itself and never sends outside kevin-push.

## Schedule card and doctor

With config `outage_recap` on, `limitless_schedule` and host registration add one card,
`schedule_cards.outage_recap_card()`: id `outage_recap`, trigger and end `push_back`, sender `plugin`, budget the
send gate's daily cap, once-key `outage_recap:<first failed push time>` ([schedule-cards.md](schedule-cards.md)).

`limitless-doctor` has a `job outage recap` row right after the voice MIQ row ([doctor.md](doctor.md)):
"outage recap: off" (status off), "on, but no push log set" (missing), else live with "waiting" (pushes are still
failing, or they came back and the next pass sends the recap), "told" (with when, in words) or "nothing to
recap", then the mode.

## Example (synthetic)

`python3 -I scripts/outage_recap_example.py`: a made-up kevin-push log in a temporary dir at the fixture clock, a
fake push that only prints what it was handed. Real output:

```text
# pass 1: pushes are still failing
Outage recap: not_triggered: pushes are still failing; the state card already says so
job outage recap: live: outage recap: waiting: pushes are still failing; write mode

# pass 2: a push was delivered: the outage is over
$ kevin-push limitless "Pushes are back" <body> --once outage_recap:1894604400 --why "pushes are reaching you again after an outage"
Phone pushes are reaching you again.
Missed since yesterday: a few messages (wake brief, MIQ prompt, back from nap).
They were not sent again: by now they are out of date.
Reply: OK / More
Outage recap: deliver: pushes came back after an outage; sent
job outage recap: live: outage recap: told: the last outage was recapped under an hour ago; write mode

# pass 3: the next poll
Outage recap: drop: already told about this outage
job outage recap: live: outage recap: told: the last outage was recapped under an hour ago; write mode
```
