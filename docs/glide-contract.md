# Glide contract: `attention.json`

`limitless/glide_provider.py` (and `flow_week.glide_blocks`, `wind_down.glide_nudged`) read Glide's
`<profile>/glide/attention.json`. This page pins that format to Glide's own writer.

## Pinned source

- Repo: https://github.com/kvnloo/glide (read-only for limitless)
- File: `glide/attention.py`
- Glide main head checked: `051b98ca74985194b8afde99b9dc0db81667be5e` (the file last changed in `299bc1d`)
- Writer: `save()`, called by `start_block()`, `stop_block()`, `route()`, `wind_down()`, `take_resume()`.
  Reader default: `load()`.

## Keys (names only)

| Where | Keys | Written by |
| --- | --- | --- |
| top level | `block`, `queue`, `resume`, `nudged` | `save()`; `load()` default on a missing or bad file |
| `block` | `start`, `end`, `minutes` | `start_block()`; set to null by `stop_block()` |
| `queue[]` | `title`, `body`, `cls`, `at` | `route()` while a block or guarded phase holds |
| `resume` | `saved`, `night`, `title`, `last_asks`, `queued` (+ `session_id` when a session exists) | `wind_down()`; set to null by `take_resume()` |
| `nudged` | night date string, `""` when never | `wind_down()` |

Units: `start`, `end`, `at`, `saved` are epoch seconds (floats); `minutes` is an int; `night` and
`nudged` are `YYYY-MM-DD`. Glide's own "block running" test is `end > now`; a block that ran out stays in
the file until the next `route()` releases it. There is no `wind_down` key: the nudge leaves only
`resume` and `nudged` (proposal: [glide-wind-down-event.md](glide-wind-down-event.md)).

## How it is checked

`tests/fixtures/glide/contract.json` is the file Glide's real writer left after each step (start a
block, hold an ask, let it run out, stop, wind down, take the resume next morning), on a synthetic
anchor with no session database. `tests/test_glide_contract.py` holds the key names above as constants
with the sha, checks the fixture against them, and runs `GlideProvider` over every state: focus block
(peak, asks held), no block, expired block, wind-down nudge, missing file, malformed file. It also checks
that `limitless_window` over a writer-made block keeps its envelope and passes tier_audit.

Re-check against a newer Glide:

    LIMITLESS_GLIDE_SRC=<glide checkout> python3 -I -m unittest discover -s tests -p test_glide_contract.py
    python3 -I tests/test_glide_contract.py --regen <glide checkout>   # after a deliberate format change

The `LiveWriter` tests re-run the writer and fail on any drift in keys, units or nesting; they skip when
`LIMITLESS_GLIDE_SRC` is unset.
