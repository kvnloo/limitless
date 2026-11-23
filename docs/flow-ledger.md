# Flow ledger: yesterday's work blocks with any feed leak, in words

The person wants an honest ledger of the day's deep work: which focus blocks happened, whether a feed app
leaked into them, and what landed. It is a ledger, not a grade: no score, no productivity measure, no ranking,
no comparison to a target and no advice. It describes observed app activity, not attention or output. It adds
one line to the wake brief and one tool for the agent; there is no new push and no new job.

## What is counted

`limitless/flow_ledger.py`, over one local day (yesterday, from the wake brief and the tool). It wraps what is
already there and re-derives nothing:

- Blocks: `blocks.focus_blocks` over the day's app-in-foreground rows from the ActivityWatch DB
  (`blocks.read_rows`, read-only, cut to not-afk spans; config `aw_db`, `flow_work_apps`, `block_gap_min`), cut at
  the day's edges. A block is long when it lasted at least `break_after_min` (default ninety minutes), the same
  length the break nudge uses. Short blocks stay in the raw ledger; the words count long blocks only.
- Feed leak: a block leaks when a feed app (`feeds_evidence.feed_apps`: `LIMITLESS_FEED_APPS` or config
  `feed_apps`, matched as `flow_week` matches its feed leak) was in the foreground at any moment inside it. With
  no feed apps set the leak is unknown, never "no leak".
- Landed: the work queue's done items (`overnight.items_for`, config `work_queue_dir`, file name and mtime only)
  whose mtime falls inside the day. A failed item did not land. With no queue configured the landed part is
  left out. Item names never leave the module, not even under the raw opt-in.

Unknown, with a plain reason and never a zero: the day is not over yet, no work apps are set, there is no
readable ActivityWatch DB, or it has no app activity row inside the day. A day with activity and no work row is
known: "no long blocks".

## Words

`flow_ledger.label(got)`: digit-free (counts are spelled none to ten, then "several"), no clock time, no app or
file name. For example "two long blocks, one with a feed leak; three items landed", "one long block, no feed
leak", "three long blocks, all with a feed leak", "two long blocks, feed leaks unknown", "no long blocks;
nothing landed" or "unknown: no work apps set (flow_work_apps)".

## Where the words show

- Wake brief (`bin/limitless-brief`, `jobs_runner.brief_flow_ledger` -> `brief_post.finalize`, after the
  overnight line and before the naps line): at most one line, "Yesterday's work: <label>.", through
  `tier_audit.gate` (hook `brief:flow_ledger`); nothing at all when unknown. It rides in the brief that is
  already going out: no new push, no new job.
- Tool `limitless_flow_ledger`: an envelope `{value: {label}, modality: "observed", age_h, evidence_tier}`, aged
  by the newest activity row of the day; `evidence_tier` is `observed-activity`, or `stale` when that row is
  over a day old. The day, the counts, each block's start and end seconds and its app names (T0) appear only
  under `LIMITLESS_RAW_IN_PROMPT=1`. Read-only; the handler records the label through the tier audit.

## Synthetic example

`python3 -I scripts/flow_ledger_example.py` (a synthetic DB and work queue, UTC as the local zone; real output).
Yesterday has three blocks of the made-up work app `editor`: one of a hundred and ten minutes with a two-minute
look at `chat`, one of ninety-five minutes with a two-minute look at `feed` (the feed app), and one of forty
minutes. The queue has three done items, one failed and one running, all touched that day.

```text
## tool, default
{
 "value": {
  "label": "two long blocks, one with a feed leak; three items landed"
 },
 "modality": "observed",
 "age_h": 15.3,
 "evidence_tier": "observed-activity",
 "label": {
  "label": "two long blocks, one with a feed leak; three items landed",
  "tier": "T1",
  "modality": "observed"
 }
}
## tool, LIMITLESS_RAW_IN_PROMPT=1
{
 "value": {
  "label": "two long blocks, one with a feed leak; three items landed",
  "day": "2033-05-17",
  "long_blocks": 2,
  "leaks": 1,
  "landed": 3,
  "blocks": [
   {
    "start": 1999933200.0,
    "end": 1999939800.0,
    "long": true,
    "leak": false,
    "apps": [
     "chat",
     "editor",
     "org.example.chat",
     "org.example.editor"
    ]
   },
   {
    "start": 1999947600.0,
    "end": 1999953300.0,
    "long": true,
    "leak": true,
    "apps": [
     "editor",
     "feed",
     "org.example.editor",
     "org.example.feed"
    ]
   },
   {
    "start": 1999958400.0,
    "end": 1999960800.0,
    "long": false,
    "leak": false,
    "apps": [
     "editor",
     "org.example.editor"
    ]
   }
  ]
 },
 "modality": "observed",
 "age_h": 15.3,
 "evidence_tier": "observed-activity",
 "label": {
  "label": "two long blocks, one with a feed leak; three items landed",
  "tier": "T1",
  "modality": "observed"
 }
}
## wake brief line
Yesterday's work: two long blocks, one with a feed leak; three items landed.
## the same morning with no work apps set
{
 "value": null,
 "modality": "observed",
 "age_h": null,
 "evidence_tier": "none",
 "reason": "flow ledger unknown: no work apps set (flow_work_apps)",
 "label": {
  "label": "unknown: no work apps set (flow_work_apps)",
  "tier": "T1",
  "modality": "observed"
 }
}
''
```
