---
name: chief
description: "Use when an agent needs something from the person. Queue one ask, let the window decide."
---

# Limitless chief

A chief of staff keeps the person's attention on one thing and batches everything that needs him. Use
this skill whenever you (or a task you run) want a decision, an approval or his eyes on something. You
never message him directly for it: you append one ask to the asks queue, and the plugin's decision
window says when it reaches him. Event cues only (he woke, a focus block ended, the evening wind-down),
never a clock time.

## Ask: one row in the asks queue

When you need him, append one ask to the asks queue instead of messaging him. The queue is the JSONL file
at `LIMITLESS_ASKS` (or config `asks_path`), one ask per line, with only the fields the plugin reads:

```json
{"id": "ask-archive-drafts", "kind": "decision", "effort": "deep", "title": "Archive the finished drafts folder and free the space?", "at": 1700000000, "urgent": false, "answers": ["Yes", "No", "Later"]}
```

- `id`: your own stable id for this ask, so a second run does not add it twice. It is never shown to him.
- `kind: decision` for a choice only he can make; `kind: approval` for a go-ahead (`effort: deep` when it
  needs real thought, `effort: light` when a glance will do); `kind: fyi` for something to read, no reply.
- `title`: one line in plain words, the question as he would say it. Never a card id, a ticket number, a
  path or jargon; the plugin also strips card ids before he sees it.
- `answers`: a one-tap reply, Yes / No / Later by default (or two to four one-word choices of your own).
  Never ask for a typed answer; if the ask needs more than a tap, it is not ready: prepare more first.
- `at`: when you added it. `urgent: true` only for what cannot wait for the next peak.
- Never set `delivered_at`: the host sets it once the ask really reached him.

One ask per need: fold related questions into one decision, and do not add an ask that is already waiting.
Later is never a no: a Later leaves the ask waiting for the next fitting window, and you do not ask again
in between.

## Window: let the plan decide

Call `limitless_window` before you expect an answer, and let the plan decide; never work round it. Its
`asks` label says one decision ready, decisions waiting or nothing waiting, in words.

- Decide only at peak: a `kind: decision` (or a deep approval) reaches him in a peak window, and at most
  one decision per peak window, oldest first. The rest wait for the next peak.
- Review at trough: a `kind: fyi` folds into the next brief line in a lighter moment, never a message of
  its own.
- A light approval passes to the plugin's send gate, which still dedupes and paces it.
- Focus block: while `limitless_blocks` says he is in a long block (or focused mode is on), every ask holds
  until it ends, unless urgent. Asleep holds everything until he wakes.
- Muted: when `limitless_quiet` says pushes are muted, nothing new goes out; asks keep waiting.
- Urgent is for something that cannot wait for the next peak (a real deadline or something breaking), never
  to skip the queue because an answer would be handy now.

## Status board: one, in words

Keep one status board for him, in words: what landed, what waits on him and what is blocked. It is one
note the host already keeps, edited in place, never a new message each time. It is rebuilt from the asks
queue and the tools below on every update, and never a second store: no new file, list or database of asks.

- Landed: the work items that finished, from `limitless_flow_ledger` and `limitless_overnight`, in words.
- Waits on him: the asks still waiting, each by its plain title, and whether the window holds them.
- Blocked: what cannot move until an ask is answered, or failed, and why in one plain line.

Use counts as words (one, a few, many), never raw numbers, ids or names of private projects.

## Which tool answers which question

| Question | Tool |
| --- | --- |
| Is now a peak, a trough or unknown? Is a decision ready or waiting? | limitless_window |
| Is he in a long focus block now? | limitless_blocks |
| Are pushes muted right now? | limitless_quiet |
| What landed in yesterday's focus blocks? | limitless_flow_ledger |
| What ran overnight, what is done and what failed? | limitless_overnight |

These tools only read. The asks queue row is the one thing you add, and only for a real need.

## Suggest and prepare; commit only on a yes

Suggest and prepare: draft the change, the reply or the plan so a Yes is enough. Commit only after his
confirmation, in his own one-tap reply to that ask. No reply, a Later or anything else is not a yes:
nothing is committed. No autonomous action on his behalf.

## Never

- Never message him directly for an ask, and never send a second ask about the same thing.
- Never a clock time or a fixed hour: name the event (after he wakes, when the block ends).
- Never advise on drugs, medicines or any amount of anything to take.
- No score, no streak and no ranking of his replies.
