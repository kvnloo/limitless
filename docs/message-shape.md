# Message shape: every push is short, TLDR first

Ranked item L17: concise messages, the most important information at the top, no walls of text. F18:
attention is a currency. Many features add one line each to the wake brief, the MIQ and the week review;
`limitless/message_shape.py` holds the whole message to a size.

## The rules

- The first line is the TLDR. It is kept as it is, in first place: never folded, never cut.
- The closing Reply line (`Reply: Keep / Drop`, one_tap.choices_line) and the Why now line
  (send_gate.outgoing) are always kept in their places. The Reply line is never cut, so a tap still parses.
- A message with more than `message_max_lines` non-blank lines (default 6) keeps its first middle lines and
  folds the rest into one plain line, "and eleven more lines in the plugin", the count said in words. The
  week review's full text stays on its card (limitless_card_view).
- Any other line longer than `message_max_line_chars` characters (default 160) is cut at a word boundary
  and ends with an ellipsis. A line that offers a link (`scheme://...`, such as the wind-down breathing link)
  is never cut: a cut link is a broken one.
- Config `message_max_lines` (a whole number, at least four: the TLDR, the folded line, the Reply line and
  the Why now line) and `message_max_line_chars` (a whole number, at least forty). Any other value is the
  default.
- A message that already fits goes out byte for byte as before.

## Where it runs

Exactly one place: `bin/kevin-push`, on the text it hands to the transport, after send_gate.outgoing added
the Why now line. Every job (limitless-jobs), the wake brief (limitless-brief) and every older sender reaches
the phone through kevin-push, so every one of them gets it. The dedupe key is still the message as it was
handed to kevin-push.

When anything was folded or cut, kevin-push writes one tier_audit row (`tier_audit.shape_event`, hook
`message_shape`): counts only, the number of lines folded and cut, no text and no hash. `limitless-tier-audit`
does not count it as an injection. With the audit off (no `LIMITLESS_AUDIT`, no `audit_path`) nothing is
written.

## Never

No new push and no new job; no change to what a message asks; nothing is reworded by a model (lines are only
kept, folded or cut); it never adds a digit (the folded count is in words); no clock time.

## Before and after

A synthetic week review with every optional line, real output of
`python3 -I scripts/message_shape_example.py`:

```text
before:
  Lights down when wind-down starts: 2 of 3 logged days this week.
  habit: on the way
  Phone data (a proxy, not a check-in): the first hour mostly feed-free.
  Flow: not recording this week (no ActivityWatch data).
  Work pattern this week (observed app activity, not attention): work was broken up.
  Body fat trending down (calibrated estimate).
  Rides this week: none, more than last week.
  Sleep: wearable on most nights; phone proxy says shorter.
  Pre-sleep heart rate: lower than usual most nights (wearable).
  Naps this week: a few, some close to the night (phone Sleep mode).
  Anki: some reviews this week (measured)
  Ideas recorded this week: a few, none triaged.
  Experiment: outcome pending (judged later)
  Your rule says: keep it
  Reply: Keep / Drop
  Why now: it is your habit cue
after:
  Lights down when wind-down starts: 2 of 3 logged days this week.
  habit: on the way
  Phone data (a proxy, not a check-in): the first hour mostly feed-free.
  and eleven more lines in the plugin
  Reply: Keep / Drop
  Why now: it is your habit cue
audit row: folded eleven, cut zero
```
