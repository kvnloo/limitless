# Propose: one tiny next action, NO_SUGGESTION by default

The coach contract is: explain, suggest with evidence, prepare, and commit only after the person confirms.
`limitless_propose` is the "suggest" step and nothing more. It answers "what is the one small thing that
fits now?" from a rule table the person can read, and says `NO_SUGGESTION` when nothing clearly fits.
Doing nothing is the default: a suggestion only appears when a rule clearly beats it.

It never writes, sends, schedules or starts anything. The agent asks the person before doing anything.

## Inputs

`propose(state)` (`limitless/propose.py`) is pure. It reads a plain dict of labels the other tools have
already computed. `tools.propose_state` builds that dict read-only:

| label | values | from |
|---|---|---|
| `asleep` | true, false | the event window (`window_chain.EventProvider`: Sleep mode, the wake event, unlocks) |
| `window` | peak, trough, anytime, wind_down | `first_known(Glide, events)`, as `limitless_window` reads it |
| `focus_block` | in a block, between blocks | a Glide focus block (`hold_asks`), else `limitless_blocks` |
| `mode` | none, brainstorm, pm, copilot, focused | `mode.json` (`modes.load`) |
| `quiet` | on, off, quiet tonight, snoozed | `limitless_quiet` (held modes only; one no longer holding is on) |
| `post_wake_peak` | open, in use, closed | `limitless_window`'s `post_wake_peak` label |
| `peak_ask` | waiting, spent, none | the asks queue: a pending non-urgent peak ask; spent once one was delivered since the wake |
| `anki` | set, not set | `LIMITLESS_ANKI` or config `anki_collection` (the collection is not opened) |
| `habit_week` | running, not running | `limitless_habit` |
| `habit_today` | Done, No, Skipped, unlogged | `limitless_habit`'s `today` |

Anything else, including a missing label, `None`, "unknown" or a lookalike such as `1` for true, is
unknown. **An unknown label never triggers a rule.** No state dir at all makes every label unknown.

## The rule table

Read in order; the first rule whose conditions all hold wins; no match is `NO_SUGGESTION`.

| # | id | when | action |
|---|---|---|---|
| 1 | `asleep` | asleep is true | NO_SUGGESTION |
| 2 | `quiet` | quiet is off, quiet tonight or snoozed | NO_SUGGESTION |
| 3 | `focus-block` | focus_block is in a block | NO_SUGGESTION |
| 4 | `focused-mode` | mode is focused | NO_SUGGESTION |
| 5 | `peak-ask` | post_wake_peak is open and peak_ask is waiting | decide the one waiting ask |
| 6 | `anki-trough` | window is trough and anki is set | a short Anki review |
| 7 | `habit-checkin` | habit_week is running and habit_today is unlogged | answer today's habit check-in |
| - | `nothing-fits` | nothing above | NO_SUGGESTION |

Every rule is an event or a state, never a clock time. `peak-ask` keeps the decision window's one decision
per peak window: once a peak ask was delivered since the wake, `peak_ask` is spent and the rule does not
fire. `anki-trough` is the same moment as the state card's trough offer (`anki.offer`): rules 1 to 4 already
cover asleep and a focus block.

## Result

`{action, because, rule_id, evidence}`: `evidence` is the label names the rule read, and `because` cites
those labels in words, never a number. All of it is digit-free, has no clock time and never says must,
should, streak, missed or failed (tests/test_propose.py checks every result over a grid of every known value
and unknown for each label, and that every rule can be reached).

The tool returns an evidence envelope with modality `derived`, `age_h` null, a `note` that it is a
suggestion only, and the T1 label (the action words, or "no suggestion"). Its `evidence_tier` is the weakest
tier of the labels the rule used (direct, then indirect, stale, none). The default rule uses no label, so it
takes the weakest tier among the inputs that were known, or none. `limitless_propose` is a tool the agent
calls; it is not on the `pre_llm_call` card.

## Synthetic example

Real output of `propose()` for synthetic states, and the derived envelope for the second one:

```
propose({})
{
  "action": "NO_SUGGESTION",
  "because": "no rule clearly fits the labels right now, so doing nothing is the suggestion",
  "rule_id": "nothing-fits",
  "evidence": []
}

propose({"asleep": false, "window": "peak", "post_wake_peak": "open", "peak_ask": "waiting", "quiet": "on", "focus_block": "between blocks", "mode": "none"})
{
  "action": "decide the one waiting ask",
  "because": "post-wake peak is open and a peak ask is waiting: one decision fits this stretch",
  "rule_id": "peak-ask",
  "evidence": [
    "post_wake_peak",
    "peak_ask"
  ]
}

propose({"asleep": false, "window": "trough", "anki": "set", "quiet": "snoozed"})
{
  "action": "NO_SUGGESTION",
  "because": "quiet is set: nothing is suggested while the person asked for quiet",
  "rule_id": "quiet",
  "evidence": [
    "quiet"
  ]
}

propose({"asleep": false, "window": "trough", "anki": "set", "habit_week": "running", "habit_today": "unlogged"})
{
  "action": "a short Anki review",
  "because": "a trough window is open and an Anki collection is set: a light review fits a lighter moment",
  "rule_id": "anki-trough",
  "evidence": [
    "window",
    "anki"
  ]
}

propose({"habit_week": "running", "habit_today": "Done", "window": "unknown"})
{
  "action": "NO_SUGGESTION",
  "because": "no rule clearly fits the labels right now, so doing nothing is the suggestion",
  "rule_id": "nothing-fits",
  "evidence": []
}

derived envelope for the second state:
{
  "value": {
    "action": "decide the one waiting ask",
    "because": "post-wake peak is open and a peak ask is waiting: one decision fits this stretch",
    "rule_id": "peak-ask",
    "evidence": [
      "post_wake_peak",
      "peak_ask"
    ],
    "note": "a suggestion only: nothing was done; ask the person before doing anything"
  },
  "modality": "derived",
  "age_h": null,
  "evidence_tier": "indirect",
  "label": {
    "label": "decide the one waiting ask",
    "tier": "T1",
    "modality": "derived"
  }
}
```

Not here, on purpose: no autonomous action, no health or dosing advice, no score, no clock-time rule.
