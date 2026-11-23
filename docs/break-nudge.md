# Break nudge: one soft suggestion after a long focus block

Deep work comes in long blocks. After one, a short break keeps the next block good. The break nudge is
one message per long block, sent when the activity data shows it: no timer, no schedule, no clock time.

- `limitless/blocks.py` finds the blocks in the ActivityWatch DB copy (config `aw_db`, read-only).
- The `break_nudge` job in `limitless/jobs.py` speaks once per block, through the same gates as every push.
- `limitless_blocks` shows the current state to the agent: `in a long block`, `between blocks` or `unknown`.

## Blocks

A work row is an app-in-foreground span of one of your work apps: config `flow_work_apps`, the same list
`limitless/flow_week.py` uses (an app or package name, case-folded, or `title:<text>` inside the window
title). When the DB has an afk bucket, the rows are cut to the not-afk time.

A block is a run of work rows. It survives a short gap (a quick look at another app, or a moment with no
row at all) and ends at the last work row before a longer gap. Two durations, both config:

| Config | Default | What it means |
| --- | --- | --- |
| `break_after_min` | `90` | how long a block has to run before it counts as long |
| `block_gap_min` | `10` | a gap shorter than this does not end a block |

These are lengths of a block, never times of day. No `flow_work_apps`, no DB or no activity row is
**unknown**, never "no block": the job says why in its row and never sends.

## When it speaks

`blocks.long_block_events` adds one `long_block` event per block that ran at least `break_after_min`, at
the moment it reached that length. `limitless-jobs` then decides as it does for every job:

- **Still going** past its usual length: deliver, "your focus block has run past its usual length".
- **Just ended** after at least that long (within an hour of its last work row): deliver, "a long focus
  block just ended". Later than that it drops: a late message is noise.
- **Once per block.** The event key is `break:<block start>`, so another poll, or any other sender with the
  same key, cannot send a second one for the same block. The next long block gets its own key.
- **An open Glide focus block does not hold it.** Every other job waits for the block to end; this one is
  about ending it.
- **Sleep mode holds it** (asleep), and a Sleep-mode on after the event expires it. **Quiet drops it** like
  any push (`docs/quiet.md`). The send gate's daily cap still applies (`hold` at the cap).

## The message

Title `Long focus block`, then one line and the gate's Why-now line:

```
Long focus block; a short break now keeps the next one good
Why now: your focus block has run past its usual length; anytime job and awake
```

No duration, no number, no score, and no advice beyond "a short break".

## Shadow first

`limitless-jobs` lists it like the others and is a dry run unless `--send`. A synthetic example: work apps
`["editor"]`, a made-up `editor` app in the foreground for a hundred minutes with a three-minute look at
`scroller` in the middle, the last row a minute ago.

```
$ limitless-jobs
...
Long focus block: deliver: your focus block has run past its usual length; anytime job and awake
$ limitless-jobs --send
...
Long focus block: deliver: your focus block has run past its usual length; anytime job and awake; sent
$ limitless-jobs --send
...
Long focus block: drop: already spoke once since the long focus block event
```

With no `flow_work_apps` set the row reads
`Long focus block: not_triggered: focus blocks unknown: no work apps set (flow_work_apps)`.

`limitless_blocks` on the same data:

```json
{"value": {"in_block": true, "long": true, "blocks": 1, "long_blocks": 1}, "modality": "proxy",
 "age_h": 0.0, "evidence_tier": "indirect",
 "label": {"tier": "T1", "modality": "proxy", "label": "in a long block"}}
```

It is a proxy: app activity, not attention. A short block that is going, or the time after a block, is
`between blocks`; the value's `in_block` says which.
