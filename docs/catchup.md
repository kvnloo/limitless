# Catch-up after an absence

After time away you want a roadmap of what happened, not a wall of text, and at most one thing to do.
`limitless/catchup.py` builds it; the `pre_llm_call` hook adds it to the first turn after the absence.

- **When**: the gap between this turn and your previous message to any agent (the owner session DBs,
  `LIMITLESS_OWNER_DBS` or config `owner_dbs`) is over `catchup_after_h` hours in config.json
  (default 24). This turn's own message (the last two minutes) does not count as "last seen". With no
  owner DB configured the gap is unknown and nothing is added.
- **What**: at most 5 lines, every digit masked (T1), through `tier_audit.gate` (hook `catchup`):

```
[limitless] catch-up: away for a day or two; next: look at the asks waiting
inputs not recording: bike, scale
habit week: running, today Done
while away: messages sent: a few; captures saved: one
asks waiting: one
```

  Messages sent counts the deliveries in `jobs-sent.jsonl` after you were last seen; captures counts
  `captures.jsonl` rows; asks waiting counts the pending rows of the asks queue. Counts are words:
  none, one, a few (two to four), many.
- **Unknown is not zero**: a source that is missing (no file, no queue configured, no `habit.json`)
  reads `unknown`, never `none`.
- **Once**: the hook keeps the last-seen time it answered for in memory and stays quiet while it is
  unchanged. Hermes loads a plugin once per CLI or gateway process, so no marker file is needed; the next
  turn also sees a short gap, because your first message after the absence is then the newest one.
  `on_session_start` cannot carry it: Hermes ignores its return value (hermes-agent
  `website/docs/user-guide/features/hooks.md`, `on_session_start`: "Return value: Ignored").
- **On demand**: `limitless_catchup` returns the same lines whatever the gap, with `label` away or not away
  in its value. Nothing here writes, sends or scores.
