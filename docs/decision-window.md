# Decision windows (design note, draft)

## Problem

A proactive job that is correct about *what* to say can still be wrong about *when*. A
question that needs a decision lands while the person is tired; a weekly review lands in the
middle of focused work; an evening question lands at a fixed hour that happens to be the
middle of dinner on that day. Fixed clock times cannot follow a person whose day moves.

Hermes's proactivity roadmap ([#158538](https://github.com/NousResearch/hermes-agent/issues/158538),
STEP 2) asks every recurring job to state when it speaks, and for pacing that sends one
message "at the moment it matters". This note proposes a small, host-neutral way to say
"the moment it matters" without clock times.

## API

A job declares one `window_class`:

| class | meant for | example |
| --- | --- | --- |
| `peak` | a decision | "Pick one of these two plans for the week" |
| `trough` | a review or low-effort read | "Here is last week's summary" |
| `wind_down` | an end-of-day question | "Anything to capture before tomorrow?" |
| `anytime` | capture, short notes | "Saved your note" |

A `WindowProvider` reports the window open now:

```python
class WindowProvider(Protocol):
    def current(self) -> WindowState: ...

WindowState(cls="peak", since="wake", source="state_file", confidence=0.9)
```

`since` names the *event* that opened the window (woke up, focus block ended, screen off),
not a time. Providers own the event logic; the gate never reads a clock.

```python
decide(job_window_class, state, *, budget_left, asleep, critical=False)
    -> Decision(action="deliver" | "hold" | "drop", reason="<one line>")
```

Rules, in order:

1. `critical` delivers.
2. asleep holds.
3. `anytime` delivers.
4. an unknown window (no provider, unrecognised class, confidence < 0.5) holds.
5. a class mismatch holds.
6. a `peak` job with no budget left in this peak window drops: one decision per peak window;
   the job's next run may ask again. The host counts the budget and passes it in.

An invalid `window_class` is a config error (`ValueError`), so a typo fails loudly rather
than holding forever.

Two providers ship for tests and simple hosts: `StaticProvider("peak", since="wake")`, and
`StateFileProvider(path)`, which re-reads `{"cls": "peak", "since": "wake"}` on every call so
any phone automation or wearable adapter can write it. Missing or malformed files read as
unknown.

## How it maps onto Hermes

- **Schedule cards ([#158289](https://github.com/NousResearch/hermes-agent/pull/158289)).**
  `window_class` is one more field on the job record, so the "Schedule this job?" card can show
  it in words ("speaks: in a peak window, at most one decision per window"). The job keeps its
  schedule; the window decides whether a given run speaks.
- **STEP 2, "states when it speaks".** The window class *is* the "when it speaks" half; the
  existing run limit or expiry stays the "when it ends" half.
- **`[SILENT]`.** `hold` and `drop` map onto the existing silent outcome: the run produces no
  message, and the reason line belongs in the run log so a held job stays visible.
- **Pacing.** The peak budget is the "one at the moment it matters" rule, enforced per window
  rather than per day.

## Asks

A chief-of-staff agent keeps a queue of asks that need the person: approvals, decisions,
FYIs. `limitless/asks.py` is the adapter between such a queue and the window; it never
rebuilds or edits the queue. Each ask gets a class from its own fields, never from the clock:

| ask | class |
| --- | --- |
| `kind: decision`, or `kind: approval` with `effort: deep` | `peak` |
| `kind: approval` with `effort: light` (or none) | `anytime` |
| `kind: fyi` | `trough` |
| any other kind | `anytime` (never dropped) |

`plan(asks, window, sent_this_window)` returns `(ask_id, deliver | hold | fold, reason)` per ask:

1. `urgent: true` delivers whatever the window and does not count against the limit.
2. a focus block (a provider with `hold_asks`, e.g. Glide) holds everything else.
3. a `trough` ask folds into the next brief line.
4. asleep holds the rest.
5. an `anytime` ask delivers, meaning it passes to the send gate (dedupe, daily cap).
6. in a peak window, ONE `peak` ask delivers, oldest first, and only if no decision was
   delivered in that window yet; every other `peak` ask holds for the next peak window.

Reasons are plain words: the ask's title with internal card ids removed by the send gate's
`scrub`. The queue is JSONL at `LIMITLESS_ASKS` or config `asks_path`; a missing or broken
file is an empty plan. A row with `delivered_at` is done; a peak one delivered since the wake
event counts as this window's decision. `limitless_window` adds
`asks: {deliver, hold, fold, label}`, where the label is one of "one decision ready",
"decisions waiting" or "nothing waiting". Nothing here sends: the host delivers, after
which it sets `delivered_at`.

The instructions an agent follows when it wants something from the person (append one ask,
one-tap reply, let the window decide, one status board) are the plugin's `limitless:chief`
skill ([chief-skill.md](chief-skill.md)).

## Hermes cron window provider

A Hermes host whose plugin API has `ctx.register_window_provider(provider)` holds a due cron job
that declares a `window_class` until the provider says that window is open. `register(ctx)` offers
it one `limitless.window_provider.WindowProvider`; a host without that method gets nothing and one
content-free log line, so nothing changes there.

`current(now)` reads the same window `limitless_window` plans asks against (Sleep mode, the wake
event, the last unlock, a Glide focus block or wind-down, focused mode) and maps the plugin's word
to the host's class through one table:

| plugin window | host `window_class` open |
| --- | --- |
| `peak` | `peak` |
| `trough` | `trough` |
| `anytime` | `anytime` (every class opens) |
| `wind_down` | `wind_down` |
| `asleep` | none: every windowed job holds |
| `focus_block` (Glide block or focused mode) | none: every windowed job holds |
| `unknown` | none: every windowed job holds |

"None" is the host's unknown window: a job with no `window_class`, or `anytime`, still fires.
`current` reads events, never a clock time, and never raises (an error is none). Config
`window_provider` is on by default; `false` or `"off"` registers nothing.

`bin/limitless-doctor`'s `cron window provider` row tells the three cases apart: off in config, a Hermes whose
plugin API has no `register_window_provider` (config `hermes_agent_dir` names the Hermes source checkout; one
file is searched as text, Hermes is never imported), or registered, with the window the cron gate reads now
([doctor.md](doctor.md)).

## Open questions

- Should `hold` queue the message for the next matching window, or leave it to the job's
  next run? The reference gate only returns the verdict; it does not queue.
- Where should the provider live in Hermes: a config key (`cron.window_provider`), or a plugin
  hook?

Reference implementation: `limitless/decision_window.py` (stdlib only, Python 3.9+), with
`limitless/send_gate.py` taking it as an optional `window` input.
