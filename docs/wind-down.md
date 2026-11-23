# Wind-down line: one gentle nudge inside the MIQ push

The person wants one quiet wind-down nudge per night (screens down, lights low), not more notifications. The
MIQ ("MIQ for tonight?") already goes out once per night when the wind-down event fires, so the nudge rides
inside that same message as one extra line. No new job, no second push, no extra send-gate call.

## The line

`limitless/wind_down.py`, pure: `line(cfg, glide_state, night)`.

- Config `wind_down_line` picks one line from a fixed list (any case, surrounding spaces ignored):
  - `Screens down and lights low when you're ready.` (the default)
  - `Screens down when you're ready.`
  - `Lights low when you're ready.`
- `"off"` adds no line. A missing or unknown value is the default: free text from config is never sent, so no
  digit, clock time or advice can reach the message that way.
- Glide's own wind-down nudge writes `nudged = "<night date>"` in its `attention.json`
  (`glide_provider.attention`, the same path as `GlideProvider`). When that is tonight's night date
  (`jobs_runner.night_date` of the wind-down event), Glide already nudged and the line is left out: one nudge per
  night across both systems. A nudge from another night, or no/broken Glide file, keeps the line.

Every line is a suggestion ("when you're ready"): no digit, no clock time, no "must" or "should", no health,
supplement, drug or dosing word. Nothing here dims a screen, switches a mode or sends anything.

## Where it shows

`jobs_runner.body` for the MIQ: the question, then the overnight line (when a work queue is set), then the
wind-down line, then `Reply: Yes / No / Later`, so `one_tap.is_one_tap` still holds. The line goes through
`tier_audit.gate` (hook `miq:wind_down`): it has no digit, so it is T1; a digit would be blocked without the raw
opt-in, and the question still goes out without it. A failure building the line leaves it out; it never stops
the question.

Nothing new bypasses the gate. The line is part of the one MIQ body, so quiet (`off`, `quiet tonight`,
`snoozed`) still drops the whole push, and Sleep mode already on still holds it, exactly as before. The MIQ
keeps its one-per-night key (`miq:<night date>`).

## Synthetic MIQ bodies (real output)

From `run_once` over a synthetic state dir (a wind-down event, Glide's `resume` just saved), with a fake push
that records what it gets. `kevin-push` adds its one "Why now" line after these.

```
--- default config, overnight queue set: MIQ pushes = 1
Your wind-down has started. Do you know the one thing that matters most tomorrow?
Overnight: a few tasks running, one queued
Screens down and lights low when you're ready.
Reply: Yes / No / Later
--- default config: MIQ pushes = 1
Your wind-down has started. Do you know the one thing that matters most tomorrow?
Screens down and lights low when you're ready.
Reply: Yes / No / Later
--- wind_down_line: "Lights low when you're ready.": MIQ pushes = 1
Your wind-down has started. Do you know the one thing that matters most tomorrow?
Lights low when you're ready.
Reply: Yes / No / Later
--- wind_down_line: "off": MIQ pushes = 1
Your wind-down has started. Do you know the one thing that matters most tomorrow?
Reply: Yes / No / Later
--- Glide already nudged tonight: MIQ pushes = 1
Your wind-down has started. Do you know the one thing that matters most tomorrow?
Reply: Yes / No / Later
```

Optional breathing choice: config `wind_down_breathing_link` (off by default) adds one more choice to this
same line, "or slow breathing in your app (with live heart data | without heart data): <link>", still one line
and no new push ([breathing-link.md](breathing-link.md)).

Tests: `tests/test_wind_down.py` (choice, off, Glide nudged, wording) and `tests/test_wind_down_miq.py` (body
order, one send-gate call per wind-down, the same gate calls with and without the line, quiet and Sleep mode
hold the whole push, the tier audit row).
