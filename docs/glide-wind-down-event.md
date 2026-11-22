# Glide wind-down event (proposal for a Glide PR; not a Glide change)

## What Glide persists today

Read from https://github.com/kvnloo/glide, `glide/attention.py`, at commit
`daa232a55966c256b1f350b11961d4e507af33fa` (file last changed in `299bc1d`).

`<profile>/glide/attention.json` holds `block`, `queue`, `resume` and `nudged`.

- Focus block: `block = {"start", "end", "minutes"}` (epoch seconds), written by `start_block()`,
  cleared by `stop_block()` or released by `route()` after `end`. Start and end are both
  persisted, so a reader can tell "block running" from the file alone.
- Wind-down: `wind_down()` writes `resume = {"saved", "night", "session_id", "title",
  "last_asks", "queued"}` and `nudged = "<night>"`. That is the only trace of the nudge.
  - It has no end. The window closes only when `take_resume()` clears `resume` on the next
    day's first turn.
  - `resume` is also written by the manual `/glide focus wind-down`, and it means "where you left
    off", not "the evening has started". A reader can't tell a nudge from a manual save.
  - `nudged` is a date string with no time, so it can't be used for staleness.

So Glide has no explicit wind-down event. limitless's `GlideProvider` uses `resume.saved` as the
start and treats it as stale after `WIND_DOWN_MAX_S` (4 h). That cap is a duration from the
event, not a clock time.

## Smallest event file Glide could write

One more key in the same `attention.json`, set by `wind_down()` next to `nudged`:

```json
"wind_down": {"started": 1894708800.0, "by": "nudge", "ended": null}
```

- `started`: epoch seconds when the nudge fired (or when the user ran `/glide focus wind-down`).
- `by`: `"nudge"` (phase-driven) or `"manual"` (the command).
- `ended`: epoch seconds, set by the first of `take_resume()` (next day's first turn) or
  `start_block()` (the person went back to deep work); `null` while wind-down is open.

It adds no new file, no new dependency and no clock rule, and older readers ignore it. With it,
`GlideProvider` would read `wind_down.started`/`ended` first and fall back to `resume.saved`.
