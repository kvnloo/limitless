# Flow, weekly (deep work and feed leak, no score)

The scorecard's flow criterion asks for two numbers a week: deep-work minutes and feed leak per
block-hour. `limitless/flow_week.py` reads them from the ActivityWatch DB copy (`LIMITLESS_AW_DB` or
config `aw_db`, opened read-only). It gives numbers and a direction on last week, never a score, a
target or a grade: the person reads the trend.

- **Deep work**: active app-in-foreground time in the apps you name as work: `LIMITLESS_FLOW_WORK_APPS`
  (comma list) or config `flow_work_apps` (`app` or `package` names; `title:<text>` matches inside a
  window title). None is set by default, so deep work starts as unknown, never guessed.
- **Feed leak**: active time in your feed apps (`feed_apps`, as for the habit hint) inside a focus
  block, over the block-hours. Blocks come from Glide (`glide_attention`); Glide keeps only its
  current block, so most weeks the leak is unknown until Glide records more. No block: unknown.
- **Missing is unknown, not zero**: a day with no ActivityWatch events is left out (`days_with_data`);
  no DB or an unreadable DB makes every field unknown. Time after the newest event is not counted.
  When the DB has an `afkstatus` bucket, away time is cut out.

Where it shows:

| Place | Words | Example |
| --- | --- | --- |
| Week review (Telegram) | one line with numbers | `Flow (measured, 5 of 7 days): deep work 640 min (last week 580); feed leak unknown (no focus blocks).` |
| `pre_llm_call` card | a digit-free T1 label on the habit line | `flow: deep work up on last week (measured)` or `flow: not recording` |

The week review covers the habit week (`week_of` plus six days) and the week before it; the card covers
the seven days to today and the seven before. "Up" and "down" compare minutes per day with data, so a
short week is not a drop; within a tenth either way reads "about the same" (wording only, not a target).
Nothing here sends, writes a file or keeps a store: with no DB configured, the review and the card are
as they were.
