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
`GlideProvider` reads `wind_down.started`/`ended` first and falls back to `resume.saved`.

## Reader

What limitless does with each field (`limitless/glide_provider.py`, `wind_down_event`):

- `started`: the start of the window. Wind-down is open from `started` until `ended` or
  `WIND_DOWN_MAX_S` (4 h) after `started`, whichever comes first. The cap is a duration from the
  event, never a clock time. Outside that span the Glide window is unknown, even when an older
  `resume.saved` would still look fresh. A running focus block still wins (`peak`).
- `ended`: closes the window at that instant (take_resume or start_block). `null`, or anything that
  isn't a finite number, means still open, up to the cap.
- `by`: exposed as `"nudge"`, `"manual"` or `"unknown"` (anything else). Both kinds count as
  wind-down. Only a nudge counts as "Glide already nudged tonight", so the MIQ wind-down line
  (`wind_down.glide_nudged`, which keys on `nudged` == tonight) still goes out after a manual
  `/glide focus wind-down`. An unknown `by` keeps the `nudged` answer (fewer messages).
- Malformed key: not an object, `started` not a finite number or after `now`, or `ended` before
  `started`. limitless ignores it and answers exactly as if it were absent.
- No key (older Glide): the `resume.saved` path with the same cap, unchanged.
- Whether this file is wired in at all: `limitless-doctor`'s `glide source` row (`glide_provider.source_status`) says `not configured`, `file missing`, `unreadable`, `older Glide (no wind-down event key)`, or `ok:` with the wind-down or focus block state ([doctor.md](doctor.md)).
