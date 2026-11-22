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

## Open questions

- Should `hold` queue the message for the next matching window, or leave it to the job's
  next run? The reference gate only returns the verdict; it does not queue.
- Where should the provider live in Hermes: a config key (`cron.window_provider`), or a plugin
  hook?

Reference implementation: `limitless/decision_window.py` (stdlib only, Python 3.9+), with
`limitless/send_gate.py` taking it as an optional `window` input.
