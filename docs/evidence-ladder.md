# The evidence ladder: how strong a claim is, in one word

The person's rule for how much to trust a claim ("this habit helps my sleep") is an order of evidential
strength, weakest first:

measured > derived > association > preregistered > repeated > replicated

The evidence envelope (`limitless/envelope.py`) already says how a VALUE was obtained (its modality, its age
and an evidence tier of direct, indirect, stale or none). It says nothing about how strong a CLAIM is. The
ladder (`limitless/strength.py`) is that second word. It wraps what the experiment pieces already record
(`limitless/prediction.py` locks and receipts, the stop rule's loop rows, all in `predictions.jsonl`) and
rebuilds none of it. The envelope's four fields never change: the ladder is an extra key beside them.

## The rungs

`strength.LADDER = ("measured", "derived", "association", "preregistered", "repeated", "replicated")`.
`strength.strength_of(claim)` returns `{rung, words, why}` for a small claim dict, with `words` starting
with the rung name (for example "preregistered: one locked week supported it").

| Rung | When | Claim key |
|---|---|---|
| measured | a reading as it was taken | `readings` (a whole number, one or more) |
| derived | a value worked out from readings (an average, a receipt's outcome) | `readings` and `computed: true` |
| association | the habit and the outcome were seen together on three or more logged days, with no locked prediction that held | `days` |
| preregistered | a prediction locked before the habit week, and its outcome receipt supports it | `weeks` |
| repeated | the same habit's locked prediction was supported in two or more separate weeks (distinct `week_of`) | `weeks` |
| replicated | an outside source is cited for the claim | `citation` (non-empty text) |

`weeks` is a list of `{week_of, locked, verdict, logged_days}`. The highest rung the claim reaches wins.

## What never climbs

- A receipt that contradicts or is inconclusive never climbs, and neither does a pending one (no receipt
  yet) or an unlocked week. The words still say it: "preregistered: one locked week supported it, one locked
  week did not"; with no supported week at all, "no rung yet: two locked weeks did not bear it out".
- Fewer than three logged days never climb: not to association, and not as a supported week (the same floor
  as the receipts' own `prediction.MIN_DAYS`).
- Replicated comes only from the `citation` key, an outside source. It is never from the person's own data:
  twelve supported weeks are still "repeated". The prediction ledger never carries a citation, so a rung read
  from it never reaches replicated. A `rung` key in the claim is ignored.
- No score and no number: `words` and `why` have no digit (counts are spelled, "more than ten" above ten).
  No clock time, and habits only (the ledger already refuses anything taken).

## Read from the ledger

`strength.habit_claim(state_dir, habit)` builds the claim for one habit from `predictions.jsonl`,
read-only, and `strength.habit_strength(state_dir, habit)` is its rung:

- every first prediction row of a week is a locked week; its receipt (`prediction.receipt_for`) gives the
  verdict, `pending` when there is none yet;
- a week belongs to the habit that `habit-<week_of>.json` or `habit.json` (`prediction.week_habit`) or that
  week's loop row names, compared without case or outer spaces; with no habit name, only the given week counts;
- a logged-days receipt's outcome ("N of M logged days") gives its logged days; a state-metric receipt was
  only judged with three logged days, so its verdict stands for them.

## On the tools

`limitless_experiment` (once anything is locked) and `limitless_loop` (once a week is decided) gain one
optional key, `strength`, beside the envelope, for the newest prediction's or the newest week's habit. The
envelope's four fields never change, `value` is as it was, and nothing is written or sent. The week review
message is unchanged for now.

## Example

Real output of `python3 -I scripts/evidence_ladder_example.py` (synthetic claims and a temporary synthetic
state dir; nothing real is read, nothing is sent):

```text
strength_of, one synthetic claim per rung:
  one reading                    -> measured: read directly
  a weekly average               -> derived: computed from readings
  seen together on logged days   -> association: seen together across days, no locked prediction yet
  one locked week supported      -> preregistered: one locked week supported it
  two locked weeks supported     -> repeated: two locked weeks supported it
  contradicted twice             -> no rung yet: two locked weeks did not bear it out
  an outside source              -> replicated: an outside source is cited for it

the ledger, one habit, a locked prediction per week:
  week 1: receipt supports     -> preregistered: one locked week supported it
  week 2: receipt contradicts  -> preregistered: one locked week supported it, one locked week did not
  week 3: receipt supports     -> repeated: two locked weeks supported it, one locked week did not

limitless_experiment strength: {"rung": "repeated", "words": "repeated: two locked weeks supported it, one locked week did not", "why": "the same habit's locked prediction was supported in separate weeks"}
limitless_loop strength:       {"rung": "repeated", "words": "repeated: two locked weeks supported it, one locked week did not", "why": "the same habit's locked prediction was supported in separate weeks"}
limitless_loop envelope keys:  ['age_h', 'evidence_tier', 'modality', 'value']
```
