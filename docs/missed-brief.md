# Missed wake brief

When phone pushes fail (the sender profile is missing, Sleep mode was left on, the daily cap), the day's wake
brief is built and logged but never delivered. The person may still write to the agent in any Hermes chat; the
plugin then offers today's missed brief instead of losing it (`limitless/missed_brief.py`).

## Where the brief comes from

kevin-push appends one row per call to its own log (config `push_log`, the file the delivery audit reads). The
wake brief is the row titled with the wake job's send title, and its `body` is the text kevin-push was handed
(for a failed transport attempt, the text as it was shaped to go out). That row is what is offered.
`brief-latest.md` is written by the private loader outside this repo; its shape is not defined here, so it is
not read.

## When a brief is missed

All of:

- today is a wake day (the wake events the plugin already merges: Sleep mode, screen-event wakes, events.jsonl),
  or no wake is known today but today's log holds a wake-brief row with text (see below);
- the delivery audit's own rule (`delivery_audit.brief_misses`) says today had no delivered wake brief, and
  today has a brief row with text;
- the newest such row is no older than the wake job's `stale_after_s`.

A brief from an earlier day is never offered, nor a stale one. Unknown (no push log set, an unreadable log, no
wake and no brief row today) is not missed.

### No wake detected, but a brief was logged

The older brief sender also logs its brief on a morning when no wake proxy fired (the brief then says the sleep
proxy is unavailable). That row is itself evidence that the morning ran. So when no wake is known today but
today's log holds a wake-brief row with text, today counts as a wake day for this offer only, and the same rules
apply: a delivered brief today means nothing is missed, and the offer goes stale `stale_after_s` after the newest
undelivered brief row. "Today" is the local date: a row from yesterday is never taken as today's, even just after
midnight. With no brief row and no wake the reason stays "no wake today is known". The delivery audit is not
changed: its wake-day counts come only from wake events, never from brief rows.

## State card

While a brief is missed the `pre_llm_call` card adds, on a line of its own right after the push-reach line
("Phone pushes are not reaching you: ...") and outside the card's line cap like it:

    Today's wake brief did not reach your phone; ask me for it.

The line is digit-free. It is cached with the card: per turn only stats are taken (the push log, the wake event
files), and the card is rebuilt when one changes or when the offer goes stale.

## Tool

`limitless_missed_brief`, read-only: `{value: {brief, why}, modality: "measured", age_h, evidence_tier}` with a
T1 label beside it. `brief` is the logged text with every digit masked as `#` unless the raw opt-in
(`LIMITLESS_RAW_IN_PROMPT=1`) is set; `why` is the delivery audit's miss reason in words; `note` says when the
log may have cut a long brief. The text goes through `tier_audit.gate` (hook `tool:limitless_missed_brief`), whose
content-free audit row is the only write. When nothing is missed, `value` is null with the reason in words, e.g.
"today's wake brief reached your phone" or "today's wake brief is too old to offer".

It never marks the brief sent (the phone still did not get it), never runs hermes and never sends.
