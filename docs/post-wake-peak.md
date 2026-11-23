# Post-wake peak: name the stretch right after waking, cued by the wake event

Right after waking is when the person's hardest pre-planned task fits best. While that stretch is open
the state card says so in one digit-free line, so the agent can offer the pre-planned task first. That is
all it says: no advice beyond "the pre-planned task fits now", and nothing is sent. It only changes what
the agent sees (the card and `limitless_window`); no job, no push.

- `limitless/peak.py`: `post_wake_peak(wake_at, now, peak_h=2, blocks=None, long_s=..., gap_s=...)` (pure)
  and `read_for(reader, now, env)` (every input from the state dir and config, read-only).
- The state card (`pre_llm_call` and `limitless_state`): `post-wake peak: open` or `post-wake peak: in use`
  while it applies; nothing when it is closed or unknown.
- `limitless_window`: a `post_wake_peak` field next to `asks`; the envelope is unchanged.

## The cue is the wake event

The wake is the latest wake event at or before now, the same one the wake brief uses (`jobs.wake_times`
over `jobs_runner.events`): a long Sleep-mode on then off, else a screen-event wake on a day without Sleep
mode (`wake_proxy.py`). Nothing reads a time of day.

| State | When | Card | Tool word |
| --- | --- | --- | --- |
| open | from the wake event until `post_wake_peak_h` hours after it | `post-wake peak: open` | `post-wake peak: open` |
| in use | open, and a focus block started inside it (see below) | `post-wake peak: in use` | `post-wake peak: in use` |
| closed | `post_wake_peak_h` hours have passed, or Sleep mode is on again after the wake | nothing | `post-wake peak: closed` |
| unknown | no wake seen; a wake older than `MAX_AWAKE_H` (missing data, not a long day); a wake after now | nothing | `unknown` |

An unknown wake is never guessed: the reason is `unknown: no wake seen`.

## Config

| Config | Default | Reads |
| --- | --- | --- |
| `post_wake_peak_h` | `2` | how long after the wake event the card says the words. Wording only, not a target |

A bad value (not a number, zero or less) keeps the default. The focus-block settings are the ones in
`blocks.py`: `break_after_min` (default 90) and `block_gap_min` (default 10).

## In use

A focus block (`blocks.focus_blocks`: runs of your `flow_work_apps` in the ActivityWatch DB) that started
inside the open peak counts it as used when it is still going now (its last work row less than
`block_gap_min` ago) or it lasted `break_after_min`. A short block that already ended does not. A block
that started before the wake does not count. No DB or no work apps leaves the peak open (blocks unknown).

## Where the line goes

The card keeps at most six lines. The peak line goes right under the window line; when the card is already
full it is added to the end of the window line instead (`window: peak (proxy); post-wake peak: open`). The
card stays digit-free and passes `tier_audit.gate`. The card cache keys on the peak words, so the line
goes away when the peak closes even when no state file changed.

## Synthetic example

A made-up state dir: Sleep mode on in the evening and off at the wake event, no poll or digest; an
ActivityWatch DB with one editor run from 50 to 79 minutes after the wake; `flow_work_apps: ["editor"]`.
Real output of `tools.window(...)["post_wake_peak"]` and `card.build(...)["text"]`:

```
# 40 min after the wake
{"open": true, "in_use": false, "why": "open since the wake event: the pre-planned task fits now", "label": {"label": "post-wake peak: open", "tier": "T1", "modality": "proxy"}}
[limitless] state card (coarse labels; limitless_state has detail)
window: unknown
post-wake peak: open
sleep unknown (no digest in the last day); readiness unknown (no digest in the last day)
habit: none set this week; flow: deep work recorded, nothing last week to compare (measured)

# 80 min, editor block since 50 min
{"open": true, "in_use": true, "why": "in use: a focus block started inside the peak", "label": {"label": "post-wake peak: in use", "tier": "T1", "modality": "proxy"}}
[limitless] state card (coarse labels; limitless_state has detail)
window: unknown
post-wake peak: in use
sleep unknown (no digest in the last day); readiness unknown (no digest in the last day)
habit: none set this week; flow: deep work recorded, nothing last week to compare (measured)

# 3 h after the wake
{"open": false, "in_use": false, "why": "closed: the peak after the wake event has passed", "label": {"label": "post-wake peak: closed", "tier": "T1", "modality": "proxy"}}
[limitless] state card (coarse labels; limitless_state has detail)
window: unknown
sleep unknown (no digest in the last day); readiness unknown (no digest in the last day)
habit: none set this week; flow: deep work recorded, nothing last week to compare (measured)

# back to sleep: Sleep mode on again at 30 min, read at 40 min
{"open": false, "in_use": false, "why": "closed: Sleep mode is on again after the wake event", "label": {"label": "post-wake peak: closed", "tier": "T1", "modality": "proxy"}}

# no wake seen
{"open": false, "in_use": false, "why": "unknown: no wake seen", "label": {"label": "unknown", "tier": "T1", "modality": "proxy"}}
```

The window class (`window: unknown` here, as there is no live Sleep-mode poll) is a separate answer: the
decision window's `peak` band is hours since wake for asks, and the post-wake peak is the stretch right
after the wake event for the pre-planned task.
