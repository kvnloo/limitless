# Anki reviews in trough windows

The person keeps an Anki deck. Reviews belong in a trough window (decision windows: peak = decide,
trough = review, anytime = capture), never in a peak and never at a clock time. The plugin reads how many
reviews happened this week from Anki's own review log, and in a trough it offers one small step on the
agent's state card (`limitless/anki.py`).

- **Where**: `LIMITLESS_ANKI`, else config.json key `anki_collection` (a path to a `collection.anki2`). None
  by default: then every answer is unknown, "no Anki collection set". Set `anki_copy: true` when the file is
  a copy no Anki process has open (it is then read with `immutable=1`).
- **Read-only, always**: opened through a `file:...?mode=ro` URI (plus `immutable=1` for a copy, or for a
  closed WAL-mode file, where a plain read-only open would leave `-wal`/`-shm` files beside it). Nothing
  writes, creates or locks the collection. A missing file, a locked DB (Anki syncing) or a file that is not
  a collection is unknown with a reason that never names the path: never zero, never a traceback.
- **What counts**: one `revlog` row per answer (`id` is epoch ms) in the week. Rows with `ease` 0 are manual
  reschedules ("set due date"), not answers, and are left out.
- **This week**: the running habit week (`habit.json` `week_of`) when today is one of its seven days, else
  the seven days ending today. The days so far are the days from its first day to today.
- **Words** (wording, not targets): `no reviews this week` (none so far), `reviewed most days this week`
  (more than half of the days so far had a review), else `some reviews this week`. No streak, no penalty: a
  day with no review is unlogged, not failed.
- **Tool** `limitless_anki`: an envelope whose value is the words, modality `measured`, `age_h` from the
  newest review (stale after a day, or with none). The raw count and the day counts appear only with
  `LIMITLESS_RAW_IN_PROMPT=1`. tier_audit logs the label.
- **Trough offer**: `anki.offer(window_state, week)` gives the one line `trough: a short Anki review fits
  now` only when a trough job would deliver now (`decision_window.decide`: a trough window, awake, no focus
  block holding asks) and a collection is set. Never in a peak, asleep, an unknown window, a Glide focus
  block or focused mode. The `pre_llm_call` card adds it like its other optional lines (its own line, or
  after the last line's words when the card is full; at most 6 lines), through `tier_audit.gate`.
- **Week review**: one words-only line before `Reply: Keep / Drop`, e.g.
  `Anki: some reviews this week (measured)`. Unknown adds no line.
- **No pushes**: this changes only what the agent sees and the week review's line. Nothing here sends.

Synthetic example (a made-up collection, today 2030-01-27 15:00 UTC; real output of the code):

```
revlog rows (synthetic):
  2030-01-22 ease 3
  2030-01-22 ease 3
  2030-01-24 ease 2
  2030-01-24 ease 0
  2030-01-26 ease 3

limitless_anki: {"value": {"label": "some reviews this week"}, "modality": "measured", "age_h": 19.0, "evidence_tier": "direct", "label": {"label": "some reviews this week", "tier": "T1", "modality": "measured"}}
limitless_anki (raw opt-in): {"label": "some reviews this week", "count": 4, "days_with_review": 3, "days_so_far": 7}
no collection set: {"value": null, "modality": null, "age_h": null, "evidence_tier": "none", "reason": "no Anki collection set"}

week review line: 'Anki: some reviews this week (measured)'
offer in trough: 'trough: a short Anki review fits now'
offer in peak: ''
offer in peak (focus block): ''
offer in asleep: ''
offer in unknown: ''
```

Three of seven days had a review, so `some reviews this week`; the `ease 0` row is not counted.

No clock-time rule, no streak, no target, no drug or supplement content. The collection is never written.
