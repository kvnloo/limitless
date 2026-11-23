# Ephemeral card: the state card and the week review at a glance

`limitless_card_view` shows today's state card (kind `state`, the default) or the week review (kind `week`) as
one small HTML card instead of a block of text: one row per line, each with a chip that says whether the line
is known, unknown or held. Code builds the card (`limitless/ui_card.py`, `limitless/card_view.py`) from the
lines the plugin already makes; the model never writes or adds a row.

## Where the rows come from

- `state`: the same lines the `pre_llm_call` hook injects (`card.build`, with the hook's Anki offer and
  post-wake peak), then the attention mode's line (`modes.line`). The model-facing header line
  (`[limitless] state card ...`) is left out; the card's title is "Today".
- `week`: the week review message (`jobs_runner.week_review_body`, the exact text the week review push sends)
  without its `Reply: Keep / Drop` ask: a card takes no tap. The title is "This week".

## The rules

- Every line goes through `tier_audit.gate` (hook `ui_card:state` or `ui_card:week`) with the raw opt-in off.
  A line that holds a digit is dropped and counted in `dropped`, never shown, even when the person set
  `LIMITLESS_RAW_IN_PROMPT=1` for prompts: the raw opt-in never reaches a card. Lines are built unmasked, so a
  number is dropped rather than shown as `#`. The week review's "N of M logged days" line and its flow line
  carry numbers, so on the card they are dropped; the weekly target line says the week in words.
- Blank lines and anything past eight rows are dropped and counted too.
- The chip comes from the line's words only, never from raw data: `unknown` when the line says unknown, not
  recording, no digest, no data, not enough or none set (any unknown word wins); `held` when it says held,
  hold, waiting, muted, snoozed, quiet tonight or paused; else `known`.
- All text is HTML-escaped (a line `<script>...` shows as text).
- Self-contained: inline CSS only. No JavaScript, no link, no image, no web font, nothing fetched.
  No clock time anywhere, no score, no push and no job of its own: the tool only renders (and writes, below).
- Phone first: the viewport is the device width, nothing has a fixed width, long words wrap and nothing
  scrolls sideways. Large type (body text at one and a quarter rem), a muted palette with a dark variant
  (`prefers-color-scheme`). The rows fade in with CSS only; under `prefers-reduced-motion` there is no motion.

## Where the card goes

Config `card_dir` (or `LIMITLESS_CARD_DIR`) names a directory; the card is written there atomically (temp file,
mode 0600, fsync, rename) as `card-<hash>.html`, the hash being of the card's content: no date or clock in the
name, and the same card always lands on the same file. With no card dir set the card is rendered only, nothing
is written, `path` is null and `note` says so. Old cards are not cleaned up by the plugin.

## The result

```text
{"value": {"path": "<card_dir>/card-<hash>.html", "rows": 5, "dropped": 0}, "modality": "derived",
 "age_h": null, "evidence_tier": "indirect",
 "label": {"label": "a state card with five rows", "tier": "T1", "modality": "derived"}}
```

`modality` is `derived` (built from other values, not measured) and `age_h` is null. `evidence_tier` is the
inputs': for `state` the weakest part of the state card (as `limitless_state`), for `week` the habit week's
self-report aged by `habit.json`'s `at`, `none` with no habit week. The label counts rows in words ("a week
card with two rows"); it never holds a digit.

## Synthetic example

`scripts/ui_card_example.py` renders these synthetic lines (no real person's data) into
[examples/ui-card-state.html](examples/ui-card-state.html) and
[examples/ui-card-week.html](examples/ui-card-week.html); `--check` fails when a committed example is out of
date (`tests/test_ui_card_docs.py` runs it).

State card lines (seven rows, none dropped):

```text
window: peak (proxy)
post-wake peak: open
sleep short (proxy); readiness unknown (no digest in the last day)
habit this week: walk after lunch; today Done; target reached this week
not recording: scale
asks waiting on you
focused mode: answer briefly, hold non-urgent asks
```

Chips: known, known, unknown, known, unknown, held, held.

Week review lines (four rows, two dropped: the logged-days line and the flow line hold numbers):

```text
Walk after lunch: 4 of 5 logged days this week.
habit: target reached this week
Flow: deep work 300 min this week (240 min last week).
Rides this week: two, more than last week.
Sleep: wearable on most nights; phone proxy says about the same; wearable says sleep times steady.
Your rule says: keep it
```
