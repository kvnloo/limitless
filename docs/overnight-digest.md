# Overnight digest

Agents can keep working while the person sleeps. At wind-down they hear in one line what is running
overnight; the wake brief says in one line what landed and what failed. Counts only, in words.

- **Where**: config.json key `work_queue_dir` (a relative path is in the state dir). None by default. The
  dir mirrors a simple lane queue: `queue/`, `running/`, `done/`, `failed/`, one `<name>.md` per item.
  `StateReader.work_items(since)` reads only the file names and mtimes, never the content. Files that are
  not `.md`, hidden files and names that are card ids (`t_` + hex) are skipped; it never raises.
- **Wind-down**: the MIQ job (woken by the `wind_down` event) keeps its question first and adds
  `overnight.plan_line`, e.g. `Overnight: a few tasks running, one queued`. An empty queue says
  `Overnight: nothing running or queued`.
- **Wake brief**: `bin/limitless-brief` passes `overnight.landed_for` to `brief_post.finalize`, which adds
  one last line for done and failed items whose mtime is after the latest `wind_down` event (with none in
  the last `MAX_AWAKE_H`, that long back: a duration, not a clock time), e.g. `Overnight: a few done, one
  failed`. Nothing finished is `Overnight: nothing ran`.
- **Unknown is not zero**: no dir configured, or the dir is not there, adds no line, and the tool returns
  `value: null` with a reason.
- **Tool** `limitless_overnight`: an envelope whose value is `{running, queued, done_since, failed_since}`,
  modality `measured`, aged by the newest item's mtime, with a T1 label. Read-only.
- **Privacy**: counts are the labeler's count words (none, one, a few, many), so lines and labels carry no
  digit, and item names never appear: a lane name can carry project words.

Synthetic example (made-up queue, wind-down nine hours ago):

```
lanes/running/synthetic-alpha.md     changed 2 h ago
lanes/queue/synthetic-beta.md        changed 8 h ago
lanes/done/synthetic-gamma.md        changed 3 h ago
lanes/done/synthetic-delta.md        changed 4 h ago
lanes/failed/synthetic-epsilon.md    changed 30 min ago
lanes/done/synthetic-old.md          changed 14 h ago (before the wind-down: not counted)
```

The wake brief ends with `Overnight: a few done, one failed, one still running`; `limitless_overnight`
returns `{"value": {"running": 1, "queued": 1, "done_since": 2, "failed_since": 1}, "modality": "measured",
"age_h": 0.5, "evidence_tier": "direct", "label": {"label": "one task running, one queued; a few done, one
failed, one still running", "tier": "T1", "modality": "measured"}}`.

No score, no clock-time rule. Nothing here sends on its own: the lines ride on messages that already go out.
